"""An identifier scoped to another registry must not resolve against this one.

`/resolve` answers about agents THIS registry holds, and attaches this
registry's proof block to the answer. Reducing `@other-registry:ns/foo` to `foo`
and looking it up locally means answering for a subject we were not asked about,
under our own attestation.

Rejection is 400, never 404. A 404 is read by a corroborator as a positive claim
of absence, which would make this registry appear to assert something about
another registry's namespace and could raise a false `omission` finding against
it. 400 carries no claim.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sm_bridge.router import _parse_agent_identifier, create_sm_router

from .conftest import TEST_PROVIDER_URL, TEST_REGISTRY_ID


def _parse(value: str) -> str | None:
    return _parse_agent_identifier(value, TEST_REGISTRY_ID, TEST_PROVIDER_URL)


class TestOwnScopeIsStripped:
    def test_handle_naming_this_registry(self) -> None:
        assert _parse(f"@{TEST_REGISTRY_ID}/agent") == "agent"

    def test_handle_with_namespace_naming_this_registry(self) -> None:
        assert _parse(f"@{TEST_REGISTRY_ID}:ns/agent") == "agent"

    def test_did_web_under_this_provider(self) -> None:
        assert _parse("did:web:test.com:agents:default:agent") == "agent"

    def test_bare_handle_has_no_scope_to_check(self) -> None:
        assert _parse("@agent") == "agent"


class TestForeignScopeIsRejected:
    def test_handle_naming_another_registry(self) -> None:
        assert _parse("@other-registry/agent") is None

    def test_namespaced_handle_naming_another_registry(self) -> None:
        assert _parse("@other-registry:ns/agent") is None

    def test_did_web_under_another_provider(self) -> None:
        assert _parse("did:web:other.example:agents:agent") is None

    def test_urn_names_a_foreign_authority_by_construction(self) -> None:
        assert _parse("urn:ai:domain:acme.example:agent:concierge") is None

    def test_unknown_did_method(self) -> None:
        assert _parse("did:key:z6MkExample") is None

    def test_empty_identifier(self) -> None:
        assert _parse("") is None


class TestUnscopedIdentifiersArePassedThrough:
    def test_plain_id(self) -> None:
        assert _parse("plain-agent") == "plain-agent"

    def test_a_colon_is_not_evidence_of_a_namespace(self) -> None:
        # The old rule split any colon and took the last part, which could not
        # tell a local id from another registry's URN. An unrecognised format is
        # the id, whole.
        assert _parse("ns:agent") == "ns:agent"


@pytest.fixture
def client() -> TestClient:
    from sm_bridge import DeltaStore, SimpleAgent, SimpleAgentConverter

    from .conftest import TEST_BASE_URL, TEST_PROVIDER_NAME

    converter = SimpleAgentConverter(
        registry_id=TEST_REGISTRY_ID,
        provider_name=TEST_PROVIDER_NAME,
        provider_url=TEST_PROVIDER_URL,
        base_url=TEST_BASE_URL,
    )
    converter.register(SimpleAgent(id="agent-1", name="Agent 1", description="Test agent"))
    router, wellknown = create_sm_router(
        converter=converter,
        delta_store=DeltaStore(),
        registry_id=TEST_REGISTRY_ID,
        base_url=TEST_BASE_URL,
        provider_name=TEST_PROVIDER_NAME,
        provider_url=TEST_PROVIDER_URL,
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(wellknown)
    return TestClient(app)


def test_resolve_serves_its_own_agent(client: TestClient) -> None:
    assert client.get("/nanda/resolve", params={"agent": "agent-1"}).status_code == 200


def test_resolve_rejects_a_foreign_identifier_with_400(client: TestClient) -> None:
    # Today this returns 200 with THIS registry's agent-1 and this registry's
    # proof block, for an identifier that names a different registry.
    r = client.get("/nanda/resolve", params={"agent": "@other-registry:ns/agent-1"})
    assert r.status_code == 400
    assert "registry" in r.json()["detail"].lower()
