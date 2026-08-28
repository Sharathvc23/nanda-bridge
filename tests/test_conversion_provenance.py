"""What the source said, and what this bridge supplied.

`to_sm` declares a total conversion — `to_sm(agent) -> SmAgentFacts` — but the
conversion is lossy in both directions. A mandatory frame with required fields
the source does not have will fill them, and fields the frame has no slot for are
dropped. Neither was visible in the output.

Self-corroboration cannot catch this: two instances of one converter invent the
same values and agree (see `test_corroborates_itself.py`). The converter has to
declare it, because nothing downstream can infer it.
"""

from __future__ import annotations

from sm_bridge import SimpleAgent, SimpleAgentConverter
from sm_bridge.gateway import to_a2a_card, to_catalog_entry

from .conftest import TEST_BASE_URL, TEST_PROVIDER_NAME, TEST_PROVIDER_URL, TEST_REGISTRY_ID

EXT = f"x_{TEST_REGISTRY_ID.replace('-', '_')}"


def _converter() -> SimpleAgentConverter:
    return SimpleAgentConverter(
        registry_id=TEST_REGISTRY_ID,
        provider_name=TEST_PROVIDER_NAME,
        provider_url=TEST_PROVIDER_URL,
        base_url=TEST_BASE_URL,
    )


def _agent(**kw) -> SimpleAgent:
    kw.setdefault("id", "a1")
    kw.setdefault("name", "Agent")
    kw.setdefault("description", "An agent.")
    return SimpleAgent(**kw)


def _prov(agent: SimpleAgent) -> dict:
    return _converter().to_sm(agent).metadata[EXT]["provenance"]


# ── invented ─────────────────────────────────────────────────


def test_an_endpoint_the_source_never_declared_is_recorded_as_invented() -> None:
    # The endpoint is the field the corroboration stack compares. Synthesising
    # one and serving it unmarked means two registries can agree on an address
    # neither source ever asserted.
    assert "endpoints.static" in _prov(_agent())["invented"]


def test_a_declared_endpoint_is_not_invented() -> None:
    assert "endpoints.static" not in _prov(_agent(endpoints={"api": "https://real.example"}))["invented"]


def test_a_synthesised_agent_did_is_recorded() -> None:
    # `id` is built by string-munging the provider URL; the source supplied a
    # bare id, not a DID.
    assert "id" in _prov(_agent())["invented"]


def test_a_synthesised_provider_did_is_recorded() -> None:
    assert "provider.did" in _prov(_agent())["invented"]


def test_the_placeholder_skill_is_recorded_as_invented() -> None:
    assert "skills" in _prov(_agent())["invented"]


# ── defaulted ────────────────────────────────────────────────


def test_a_label_taken_from_the_namespace_is_recorded_as_defaulted() -> None:
    # NANDA requires `label`. With no labels the namespace is repurposed as one,
    # which is a category claim the source did not make.
    assert "label" in _prov(_agent())["defaulted"]


def test_a_declared_label_is_not_defaulted() -> None:
    assert "label" not in _prov(_agent(labels=["chat"]))["defaulted"]


def test_a_missing_skill_description_is_recorded_as_defaulted() -> None:
    prov = _prov(_agent(skills=[{"id": "summarize"}]))
    assert "skills[0].description" in prov["defaulted"]


# ── dropped ──────────────────────────────────────────────────


def test_skill_keys_the_frame_has_no_slot_for_are_recorded_as_dropped() -> None:
    prov = _prov(_agent(skills=[{"id": "s", "description": "d", "pricing": "$1", "tags": ["x"]}]))
    assert sorted(prov["dropped"]) == ["skills[0].pricing", "skills[0].tags"]


# ── a source cannot rewrite the record of what we did ────────


def test_a_source_cannot_shadow_provenance() -> None:
    prov = _prov(_agent(metadata={"provenance": {"invented": [], "defaulted": [], "dropped": []}}))
    assert "skills" in prov["invented"]


def test_a_clean_conversion_reports_nothing() -> None:
    prov = _prov(
        _agent(
            labels=["chat"],
            endpoints={"api": "https://real.example"},
            skills=[{"id": "s", "description": "d"}],
        )
    )
    assert prov == {"invented": ["id", "provider.did"], "defaulted": [], "dropped": []}


# ── the gateway stops inventing too ──────────────────────────


def test_an_agent_reachable_only_dynamically_gets_a_real_card_url() -> None:
    # `url = static[0] if static else ""` emitted a card with an empty URL for an
    # agent that is reachable, just not statically.
    facts = _converter().to_sm(_agent(dynamic_endpoints=["https://dyn.example"]))
    facts.endpoints.static = []
    card = to_a2a_card(facts, "a1", "acme.example", TEST_BASE_URL)
    assert card.url == "https://dyn.example"


def test_the_card_does_not_claim_a_capability_the_source_never_declared() -> None:
    card = to_a2a_card(_converter().to_sm(_agent()), "a1", "acme.example", TEST_BASE_URL)
    assert "pushNotifications" not in card.capabilities


def test_the_catalog_entry_does_not_invent_a_ttl_or_a_liveness_claim() -> None:
    entry = to_catalog_entry(_converter().to_sm(_agent()), "a1", TEST_BASE_URL)
    assert "ttl_seconds" not in entry.metadata
    assert "status" not in entry.metadata
