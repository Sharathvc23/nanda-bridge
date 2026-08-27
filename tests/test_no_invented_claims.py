"""The bridge must not emit claims the source never made.

Three places asserted things nothing had established, and each produced output a
consumer cannot distinguish from a real assertion by the source.
"""

from __future__ import annotations

from sm_bridge import SimpleAgent, SimpleAgentConverter
from sm_bridge.onboarding import ANSEntryConverter

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


# ── certification ────────────────────────────────────────────


def test_no_certification_block_when_the_source_declared_none() -> None:
    # Previously every agent got {"level": "self-declared", "issuer": <us>},
    # including agents that never certified anything and never asked us to.
    facts = _converter().to_sm(_agent())
    assert facts.certification is None


def test_a_declared_certification_is_kept() -> None:
    facts = _converter().to_sm(_agent(certification_level="audited", certification_issuer="NANDA"))
    assert facts.certification is not None
    assert facts.certification.level == "audited"
    assert facts.certification.issuer == "NANDA"


# ── skills ───────────────────────────────────────────────────


def test_a_placeholder_skill_is_marked_as_synthesized() -> None:
    # NANDA requires minItems:1, so a source with no skills cannot be represented
    # without one. The placeholder stays, but it must be distinguishable from a
    # skill the source actually declared.
    facts = _converter().to_sm(_agent())
    assert len(facts.skills) == 1
    assert facts.metadata[EXT]["synthesized"] == ["skills"]


def test_declared_skills_are_not_marked_synthesized() -> None:
    facts = _converter().to_sm(_agent(skills=[{"id": "summarize", "description": "Summarize"}]))
    assert facts.skills[0].id == "summarize"
    assert facts.metadata[EXT]["synthesized"] == []


def test_a_source_cannot_shadow_the_synthesized_marker() -> None:
    # The marker is this bridge's statement about its own output. A source that
    # supplies its own `synthesized` key must not be able to hide the fact.
    facts = _converter().to_sm(_agent(metadata={"synthesized": []}))
    assert facts.metadata[EXT]["synthesized"] == ["skills"]


# ── conformance level ────────────────────────────────────────


def _entry_converter(**kw) -> ANSEntryConverter:
    kw.setdefault("registry_name", "peer")
    kw.setdefault("display_name", "Peer")
    kw.setdefault("resolver_endpoint", "https://peer.example/resolve")
    return ANSEntryConverter(**kw)


def test_conformance_is_basic_when_the_checkpoint_was_not_verified() -> None:
    # `auditable` was asserted from two non-empty strings. The field's own
    # docstring says "Computed, not asserted", and conformance.conformance_level
    # is the real predicate — it was never called.
    entry = _entry_converter(tl_checkpoint="ckpt", root_keys=["k1"]).to_entry()
    assert entry.conformance_level == "basic"


def test_conformance_is_auditable_only_when_the_checkpoint_verifies() -> None:
    entry = _entry_converter(tl_checkpoint="ckpt", root_keys=["k1"]).to_entry(
        checkpoint_verifies=True
    )
    assert entry.conformance_level == "auditable"


def test_a_verified_claim_still_needs_a_checkpoint_to_verify() -> None:
    entry = _entry_converter().to_entry(checkpoint_verifies=True)
    assert entry.conformance_level == "basic"
