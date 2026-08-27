"""A peer's record must survive federation intact.

`pull_deltas` validates a peer's record into `SmAgentFacts` and stores it, and
`gateway.py` re-serves what was stored. Pydantic's default is `extra="ignore"`,
so any field the model does not declare was dropped silently — and we then
re-served a truncated version of another registry's record as though it were
complete. That misrepresents the peer, and there was no record that anything had
been lost.
"""

from __future__ import annotations

from typing import Any

from sm_bridge import DeltaStore, SmAgentFacts, current_facts, default_slug, pull_deltas

from .test_federation import _delta, _facts, _peer_fetch


def _delta_with_extras(seq: int, slug: str) -> dict[str, Any]:
    d = _delta(seq, "upsert", slug)
    d["agent"]["x_peer_native"] = {"keep": "me"}
    d["agent"]["some_future_field"] = "from a newer AgentFacts revision"
    d["agent"]["skills"][0]["pricing"] = "$1"
    return d


def test_an_unknown_top_level_field_survives_validation() -> None:
    agent = SmAgentFacts.model_validate(_delta_with_extras(1, "a")["agent"])
    dumped = agent.model_dump(mode="json")
    assert dumped["x_peer_native"] == {"keep": "me"}
    assert dumped["some_future_field"] == "from a newer AgentFacts revision"


def test_an_unknown_nested_field_survives_validation() -> None:
    agent = SmAgentFacts.model_validate(_delta_with_extras(1, "a")["agent"])
    assert agent.model_dump(mode="json")["skills"][0]["pricing"] == "$1"


def test_federated_records_keep_their_unknown_fields() -> None:
    store = DeltaStore()
    log = [_delta_with_extras(1, "a")]
    result = pull_deltas("https://peer.example", store, 0, fetch=_peer_fetch(log))
    assert result.applied == 1

    facts = next(iter(current_facts(store, default_slug).values()))
    dumped = facts.model_dump(mode="json")
    assert dumped["x_peer_native"] == {"keep": "me"}
    assert dumped["skills"][0]["pricing"] == "$1"


def test_our_own_records_carry_no_extras() -> None:
    # Preserving a peer's fields must not become a way for our own converter to
    # emit fields nothing declared.
    dumped = _facts("a").model_dump(mode="json")
    assert "x_peer_native" not in dumped
    assert "some_future_field" not in dumped


def test_response_wrappers_stay_strict() -> None:
    # The permissive base is for records we relay, not for our own output.
    # Widening a response wrapper would let undeclared fields into our responses
    # with nothing noticing, so the boundary is pinned here rather than only
    # described in a docstring.
    from sm_bridge.models import SmAgentFactsIndexResponse, SmRecord

    wrappers = [
        "SmAgentFactsIndexResponse",
        "SmAgentFactsDelta",
        "SmAgentFactsDeltaResponse",
        "SmWellKnown",
        "SmTool",
        "SmToolsResponse",
        "SmA2AMessage",
    ]
    import sm_bridge.models as m

    for name in wrappers:
        assert not issubclass(getattr(m, name), SmRecord), f"{name} must not accept extra fields"

    parsed = SmAgentFactsIndexResponse.model_validate(
        {
            "generated_at": "2026-06-24T00:00:00+00:00",
            "registry_id": "peer",
            "agents": [],
            "junk": "dropped",
        }
    )
    assert "junk" not in parsed.model_dump(mode="json")
