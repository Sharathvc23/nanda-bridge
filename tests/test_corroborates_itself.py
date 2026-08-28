"""Sweep this bridge with the Quilt and require agreement.

sm-bridge is a registry: a thing the corroboration stack audits, not a consumer
of it. Every bug found in this package during the 0.7.0 cycle was this registry
committing a behaviour that stack exists to detect —

  - answering for an identifier scoped to another registry
  - dropping fields from a peer's record while re-serving it
  - emitting skills and certifications the source never declared
  - losing agents from the catalog when their delta was pruned

Three of those are omissions and one is a fabrication, which is exactly the
vocabulary of `sm_divergence`. So point it at ourselves: two instances of this
bridge, serving the same agents, must corroborate to AGREE. A divergence here
means this registry is misrepresenting its own data.

**What this cannot do.** Corroboration compares sources against each other, so
two instances of the same code misbehaving identically agree with each other.
This catches divergence-shaped faults — a scoping bug that makes one answer
differ, an agent lost from one catalog — and is blind to uniform ones. Both
bridges inventing the same endpoint, or both truncating a peer record the same
way, is an `AGREE`. `test_identical_invention_is_invisible_to_self_corroboration`
pins that boundary so this file is not read as stronger than it is.

Verified against real regressions by reverting each fix and re-running:

===============================  ============================================
Reverted fix                     Result
===============================  ============================================
registry scope check (#11)       CAUGHT — foreign identifier resolves locally
400 rejection becomes 404        CAUGHT — a scoping refusal read as absence
extra="allow" (#13)              not caught — both bridges truncate identically
===============================  ============================================

Test-only. `sm-divergence` is a dev dependency and nothing in `sm_bridge`
imports it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sm_divergence import DivergenceDetector
from sm_divergence.discovery.views import RecordView
from sm_resolver import Status

from sm_bridge import DeltaStore, SimpleAgent, SimpleAgentConverter
from sm_bridge.router import create_sm_router

from .conftest import TEST_BASE_URL, TEST_PROVIDER_NAME, TEST_PROVIDER_URL, TEST_REGISTRY_ID


class BridgeResolver:
    """A Resolver over this bridge's own `/nanda/resolve`.

    This is the shape a real sweeper would use: perform the source's query,
    classify, and reduce to a comparable view. A 404 is a positive claim of
    absence; a 400 is not a claim at all and MUST be an error, or a scoping
    rejection would be recorded as this registry asserting the agent does not
    exist.
    """

    def __init__(self, label: str, client: TestClient, vantage: str | None = None) -> None:
        self.label = label
        self.vantage = vantage
        self._client = client

    async def resolve(self, agent_id: str) -> tuple[Status, RecordView | None]:
        try:
            r = self._client.get("/nanda/resolve", params={"agent": agent_id})
        except Exception:
            return "error", None
        if r.status_code == 404:
            return "absent", None
        if r.status_code != 200:
            return "error", None
        body = r.json()
        static = (body.get("endpoints") or {}).get("static") or []
        return "present", RecordView(endpoint=static[0] if static else None, did=None)


def _bridge(agents: list[SimpleAgent], *, provider_url: str = TEST_PROVIDER_URL) -> TestClient:
    converter = SimpleAgentConverter(
        registry_id=TEST_REGISTRY_ID,
        provider_name=TEST_PROVIDER_NAME,
        provider_url=provider_url,
        base_url=TEST_BASE_URL,
    )
    for a in agents:
        converter.register(a)
    router, wellknown = create_sm_router(
        converter=converter,
        delta_store=DeltaStore(),
        registry_id=TEST_REGISTRY_ID,
        base_url=TEST_BASE_URL,
        provider_name=TEST_PROVIDER_NAME,
        provider_url=provider_url,
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(wellknown)
    return TestClient(app)


def _agent(agent_id: str, endpoint: str) -> SimpleAgent:
    return SimpleAgent(
        id=agent_id,
        name=f"Agent {agent_id}",
        description="An agent.",
        endpoints={"api": endpoint},
    )


@pytest.mark.asyncio
async def test_two_bridges_serving_the_same_agents_corroborate() -> None:
    agents = [_agent("a1", "https://one.example"), _agent("a2", "https://two.example")]
    detector = DivergenceDetector(
        [
            BridgeResolver("bridge-a", _bridge(agents)),
            BridgeResolver("bridge-b", _bridge(agents)),
        ]
    )
    results = await detector.check(["a1", "a2"])
    assert [r.verdict for r in results] == ["AGREE", "AGREE"]
    assert all(r.findings == [] for r in results)


@pytest.mark.asyncio
async def test_an_agent_held_by_one_bridge_only_is_an_omission() -> None:
    # The control. If this does not produce a finding, the sweep is not actually
    # comparing anything and the AGREE above is worthless.
    detector = DivergenceDetector(
        [
            BridgeResolver("bridge-a", _bridge([_agent("a1", "https://one.example")])),
            BridgeResolver("bridge-b", _bridge([])),
        ]
    )
    (result,) = await detector.check(["a1"])
    assert result.verdict == "DIVERGENT"
    assert [f.kind for f in result.findings] == ["omission"]


@pytest.mark.asyncio
async def test_bridges_disagreeing_on_an_endpoint_diverge() -> None:
    detector = DivergenceDetector(
        [
            BridgeResolver("bridge-a", _bridge([_agent("a1", "https://one.example")])),
            BridgeResolver("bridge-b", _bridge([_agent("a1", "https://other.example")])),
        ]
    )
    (result,) = await detector.check(["a1"])
    assert result.verdict == "DIVERGENT"
    assert [f.kind for f in result.findings] == ["endpoint"]


@pytest.mark.asyncio
async def test_a_foreign_scoped_identifier_is_an_error_not_an_absence() -> None:
    # The 400-not-404 decision from the 0.7.0 security fix, checked from the
    # auditor's side. If /resolve returned 404 here, both bridges would be
    # recorded as positively asserting absence — a claim neither made.
    agents = [_agent("a1", "https://one.example")]
    detector = DivergenceDetector(
        [
            BridgeResolver("bridge-a", _bridge(agents)),
            BridgeResolver("bridge-b", _bridge(agents)),
        ]
    )
    (result,) = await detector.check(["@other-registry:ns/a1"])
    assert result.verdict == "INSUFFICIENT"
    assert all(c.status == "error" for c in result.claims)
    assert result.findings == []


@pytest.mark.asyncio
async def test_identical_invention_is_invisible_to_self_corroboration() -> None:
    # The boundary of the technique, pinned rather than described.
    #
    # An agent with no declared endpoint gets one invented for it
    # (`converter.py`: `{base_url}/agents/{id}`). Both bridges invent the same
    # value, so the sweep corroborates a value neither source ever asserted and
    # reports AGREE.
    #
    # This is not a defect in the sweep. It is what corroboration is: evidence
    # that independent sources concur, which is worth exactly as much as their
    # independence. Two copies of one implementation are not independent.
    # Catching invention needs comparison against the source data, not against a
    # second instance of the same converter.
    agents = [SimpleAgent(id="a1", name="Agent a1", description="An agent.")]
    detector = DivergenceDetector(
        [
            BridgeResolver("bridge-a", _bridge(agents)),
            BridgeResolver("bridge-b", _bridge(agents)),
        ]
    )
    (result,) = await detector.check(["a1"])
    assert result.verdict == "AGREE"
    invented = result.claims[0].view
    assert invented is not None and invented.endpoint is not None
    assert "/agents/a1" in invented.endpoint
