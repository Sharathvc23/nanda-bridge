"""Nothing an agent does is deleted, and the catalog does not lose agents.

`DeltaStore` pruned to `max_deltas`, dropping the OLDEST deltas, while
`current_facts` rebuilt the catalog by replaying from zero. So an agent whose
only `upsert` had aged out disappeared from the catalog — no error, no gap, no
way to tell it had ever been there.

Two changes. The log is append-only and complete: an agent's history is
evidence, and a registry that silently forgets what it served cannot be audited
for what it served. And the catalog is rebuilt from a per-agent snapshot rather
than a full replay, so a complete log does not make the rebuild grow without
bound.
"""

from __future__ import annotations

import pytest

from sm_bridge import DeltaStore, SimpleAgent, SimpleAgentConverter, current_facts, default_slug

from .conftest import TEST_BASE_URL, TEST_PROVIDER_NAME, TEST_PROVIDER_URL, TEST_REGISTRY_ID


def _converter() -> SimpleAgentConverter:
    return SimpleAgentConverter(
        registry_id=TEST_REGISTRY_ID,
        provider_name=TEST_PROVIDER_NAME,
        provider_url=TEST_PROVIDER_URL,
        base_url=TEST_BASE_URL,
    )


def _facts(conv: SimpleAgentConverter, agent_id: str, endpoint: str = "https://one.example"):
    return conv.to_sm(
        SimpleAgent(id=agent_id, name=f"Agent {agent_id}", description="d", endpoints={"api": endpoint})
    )


# ── nothing is deleted ───────────────────────────────────────


def test_the_log_keeps_every_delta() -> None:
    conv, store = _converter(), DeltaStore()
    facts = _facts(conv, "a1")
    for _ in range(10_050):
        store.add("upsert", facts)
    assert len(store) == 10_050
    assert len(store.since(0)) == 10_050


def test_the_first_delta_survives_far_past_the_old_prune_threshold() -> None:
    conv, store = _converter(), DeltaStore()
    store.add("upsert", _facts(conv, "first"))
    filler = _facts(conv, "filler")
    for _ in range(10_100):
        store.add("upsert", filler)
    first = store.get(1)
    assert first is not None
    assert first.agent.metadata[f"x_{TEST_REGISTRY_ID.replace('-', '_')}"]["original_id"] == "first"


def test_an_agent_whose_upsert_is_old_stays_in_the_catalog() -> None:
    # The bug, stated as a test. `first` is registered once and never touched
    # again; enough traffic follows to have pushed it out of a pruned log.
    conv, store = _converter(), DeltaStore()
    store.add("upsert", _facts(conv, "first"))
    filler = _facts(conv, "filler")
    for _ in range(10_100):
        store.add("upsert", filler)
    assert "first" in current_facts(store, default_slug)


def test_max_deltas_is_deprecated_and_no_longer_prunes() -> None:
    # Accepting the argument and silently ignoring it would be its own lie.
    with pytest.warns(DeprecationWarning, match="append-only"):
        store = DeltaStore(max_deltas=5)
    conv = _converter()
    facts = _facts(conv, "a1")
    for _ in range(20):
        store.add("upsert", facts)
    assert len(store) == 20


# ── the snapshot ─────────────────────────────────────────────


def test_the_snapshot_is_one_delta_per_agent() -> None:
    conv, store = _converter(), DeltaStore()
    for i in range(5):
        store.add("upsert", _facts(conv, "a1", f"https://v{i}.example"))
    store.add("upsert", _facts(conv, "a2"))
    snap = store.snapshot()
    assert len(snap) == 2
    assert {d.seq for d in snap} == {5, 6}


def test_the_snapshot_keeps_a_delete_as_the_latest_state() -> None:
    # A removal is a fact about the agent, not the absence of one. Dropping it
    # from the snapshot would resurrect the agent on the next rebuild.
    conv, store = _converter(), DeltaStore()
    store.add("upsert", _facts(conv, "a1"))
    store.add("delete", _facts(conv, "a1"))
    (latest,) = store.snapshot()
    assert latest.action == "delete"
    assert current_facts(store, default_slug) == {}


def test_the_snapshot_agrees_with_a_full_replay() -> None:
    # The property that makes the snapshot safe: it is an optimisation, not a
    # different answer.
    conv, store = _converter(), DeltaStore()
    for i in range(3):
        store.add("upsert", _facts(conv, f"a{i}"))
    store.add("upsert", _facts(conv, "a1", "https://updated.example"))
    store.add("delete", _facts(conv, "a2"))

    replayed: dict[str, object] = {}
    for delta in store.since(0):
        slug = default_slug(delta.agent)
        if delta.action == "upsert":
            replayed[slug] = delta.agent
        else:
            replayed.pop(slug, None)
    assert current_facts(store, default_slug) == replayed


def test_clear_still_empties_the_store_for_tests() -> None:
    conv, store = _converter(), DeltaStore()
    store.add("upsert", _facts(conv, "a1"))
    store.clear()
    assert len(store) == 0
    assert store.snapshot() == []
    assert current_facts(store, default_slug) == {}


def test_the_latest_delta_wins_when_two_agents_share_a_slug() -> None:
    # `default_slug` takes the handle tail, so agents in different namespaces can
    # collide on it. The snapshot must be applied in sequence order, or which one
    # the catalog shows depends on dict ordering.
    conv, store = _converter(), DeltaStore()
    early = conv.to_sm(
        SimpleAgent(id="x", name="Early", description="d", namespace="one",
                    endpoints={"api": "https://early.example"})
    )
    later = conv.to_sm(
        SimpleAgent(id="x", name="Later", description="d", namespace="two",
                    endpoints={"api": "https://later.example"})
    )
    assert default_slug(early) == default_slug(later)
    assert early.id != later.id

    store.add("upsert", early)
    store.add("upsert", later)
    shown = current_facts(store, default_slug)[default_slug(later)]
    assert shown.agent_name == "Later"


def test_the_catalog_does_not_replay_the_whole_log() -> None:
    # A complete log must not make the read path grow with history. Pinned by a
    # store that refuses a full replay rather than by timing, which would be
    # brittle.
    class NoReplayStore(DeltaStore):
        def since(self, seq: int) -> list:  # type: ignore[override]
            if seq == 0:
                raise AssertionError("current_facts must not replay the whole log")
            return super().since(seq)

    conv, store = _converter(), NoReplayStore()
    for i in range(50):
        store.add("upsert", _facts(conv, "a1", f"https://v{i}.example"))
    store.add("upsert", _facts(conv, "a2"))
    assert set(current_facts(store, default_slug)) == {"a1", "a2"}
