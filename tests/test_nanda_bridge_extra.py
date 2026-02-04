import pytest
from fastapi import HTTPException

from nanda_bridge import (
    DeltaStore,
    NandaBridge,
    NandaAgentFacts,
    SimpleAgent,
    SimpleAgentConverter,
)
from nanda_bridge.models import NandaTool
from nanda_bridge.router import _parse_agent_identifier, create_nanda_router
from nanda_bridge.store import PersistentDeltaStore


def _make_agent_facts(agent_id: str = "agent-1") -> NandaAgentFacts:
    converter = SimpleAgentConverter(
        registry_id="test-registry",
        provider_name="Test Provider",
        provider_url="https://test.com",
        base_url="https://registry.test.com",
    )
    agent = SimpleAgent(
        id=agent_id,
        name=f"Agent {agent_id}",
        description="Test agent",
        labels=["chat"],
    )
    return converter.to_nanda(agent)


def test_converter_skills_and_unregister_and_get():
    converter = SimpleAgentConverter(
        registry_id="test-registry",
        provider_name="Test Provider",
        provider_url="https://test.com",
    )
    agent = SimpleAgent(
        id="agent-skills",
        name="Skillful Agent",
        description="Has skills",
        skills=[
            {"id": "dict-skill", "description": "dict based", "inputModes": ["text"], "outputModes": ["text"]},
            "string-skill",
        ],
        endpoints={"primary": "https://api.test.com/agent-skills"},
    )
    converter.register(agent)
    facts = converter.to_nanda(agent)

    assert [s.id for s in facts.skills] == ["dict-skill", "string-skill"]
    assert facts.endpoints.static == ["https://api.test.com/agent-skills"]

    converter.unregister(agent.id)
    assert converter.get_agent(agent.id) is None


def test_converter_ext_metadata_dynamic_and_proof():
    converter = SimpleAgentConverter(
        registry_id="test-registry",
        provider_name="Test Provider",
        provider_url="https://test.com",
    )
    agent = SimpleAgent(
        id="agent-meta",
        name="Meta Agent",
        description="Has metadata",
        public=False,
        classification="internal",
        card_template="card-v1",
        metadata={
            "certification": {"fedramp": "pending"},
            "telemetry": {"latency_ms": 50},
        },
        endpoints={"primary": "https://api.test.com/meta"},
        dynamic_endpoints=["https://edge.test.com/meta"],
    )

    facts = converter.to_nanda(agent)

    assert facts.endpoints.dynamic == ["https://edge.test.com/meta"]
    meta = facts.metadata["x_test_registry"]
    assert meta["public"] is False
    assert meta["classification"] == "internal"
    assert meta["card_template"] == "card-v1"
    assert meta["certification"]["fedramp"] == "pending"
    assert meta["telemetry"]["latency_ms"] == 50
    assert any(entry["key"] == "primary" for entry in meta["endpoints_extended"])
    assert any(entry["key"] == "dynamic_0" for entry in meta["endpoints_extended"])
    assert facts.proof["method"] == "sha256"


def test_delta_store_pruning_get_and_clear():
    store = DeltaStore(max_deltas=2)
    facts = _make_agent_facts("prune-me")

    first = store.add("upsert", facts)
    store.add("upsert", facts)
    third = store.add("upsert", facts)

    assert len(store) == 2
    assert store.get(first.seq) is None
    assert store.get(third.seq).seq == third.seq
    assert store.current_seq == third.seq
    assert store.next_seq == third.seq + 1

    store.clear()
    assert len(store) == 0
    assert store.current_seq == 0
    assert store.next_seq == 1


class DummyPersistentStore(PersistentDeltaStore):
    def __init__(self):
        super().__init__(max_deltas=10)
        self.persisted: list = []
        self.loaded: list = []
        self._load_returns: list[list] = []

    def _persist(self, delta):
        self.persisted.append(delta)
        return super()._persist(delta)

    def _load_since(self, seq: int):
        self.loaded.append(seq)
        if self._load_returns:
            return self._load_returns.pop(0)
        return super()._load_since(seq)


def test_persistent_delta_store_paths():
    store = DummyPersistentStore()
    facts = _make_agent_facts("persistent")

    delta = store.add("upsert", facts)
    assert store.persisted == [delta]

    store._load_returns.append([delta])
    assert store.since(0) == [delta]

    assert store.since(delta.seq) == []


def _build_router(converter=None, delta_store=None, tools=None):
    converter = converter or SimpleAgentConverter(
        registry_id="test-registry",
        provider_name="Test Provider",
        provider_url="https://provider.test",
        base_url="https://registry.test",
    )
    delta_store = delta_store or DeltaStore()
    router = create_nanda_router(
        converter=converter,
        delta_store=delta_store,
        registry_id="test-registry",
        base_url="https://registry.test",
        provider_name="Test Provider",
        provider_url="https://provider.test",
        tools=tools,
        namespaces=["did:web:provider.test:*"],
    )
    return router, converter, delta_store


def test_index_filters_private_and_lists_public():
    router, converter, _ = _build_router()
    public_agent = SimpleAgent(id="public", name="Public", description="pub", labels=["chat"])
    private_agent = SimpleAgent(id="private", name="Private", description="priv", public=False)
    converter.register(public_agent)
    converter.register(private_agent)

    index_route = next(r for r in router.routes if r.path.endswith("/index"))
    data = index_route.endpoint(limit=100, offset=0).model_dump()

    assert data["total_count"] == 1
    assert data["agents"][0]["id"].endswith("public")


def test_resolve_not_found_and_not_public():
    router, converter, _ = _build_router()
    private_agent = SimpleAgent(id="private", name="Private", description="priv", public=False, namespace="ns")
    converter.register(private_agent)

    resolve_route = next(r for r in router.routes if r.path.endswith("/resolve"))

    with pytest.raises(HTTPException) as missing:
        resolve_route.endpoint(agent="missing")
    assert missing.value.status_code == 404

    handle = "@test-registry:ns/private"
    with pytest.raises(HTTPException) as forbidden:
        resolve_route.endpoint(agent=handle)
    assert forbidden.value.status_code == 403


def test_resolve_success_returns_agentfacts():
    router, converter, _ = _build_router()
    agent = SimpleAgent(id="good", name="Good Agent", description="ok", labels=["chat"])
    converter.register(agent)

    resolve_route = next(r for r in router.routes if r.path.endswith("/resolve"))
    facts = resolve_route.endpoint(agent="good")

    assert facts.agent_name == "Good Agent"
    assert facts.handle.endswith("/good")


def test_deltas_endpoint_returns_changes_and_next_seq():
    router, converter, delta_store = _build_router()
    agent = SimpleAgent(id="delta-agent", name="Delta Agent", description="desc")
    converter.register(agent)
    delta_store.add("upsert", converter.to_nanda(agent))

    deltas_route = next(r for r in router.routes if r.path.endswith("/deltas"))
    body = deltas_route.endpoint(since=0).model_dump()

    assert len(body["deltas"]) == 1
    assert body["next_seq"] == delta_store.next_seq


def test_tools_and_wellknown_routes():
    tools = [
        NandaTool(
            tool_id="t1",
            description="Tool 1",
            endpoint="https://tools.test/t1",
            params=["x"],
            version="v1",
        )
    ]
    router, _, _ = _build_router(tools=tools)

    tools_route = next(r for r in router.routes if r.path.endswith("/tools"))
    tools_resp = tools_route.endpoint().model_dump()
    assert tools_resp["tools"][0]["tool_id"] == "t1"

    wellknown_route = next(r for r in router.routes if "well-known" in r.path)
    wellknown = wellknown_route.endpoint().model_dump()
    assert wellknown["tools_url"] is not None
    assert "mcp-tools" in wellknown["capabilities"]


def test_parse_agent_identifier_variants():
    assert _parse_agent_identifier("@registry/agent", "registry") == "agent"
    assert _parse_agent_identifier("@registry", "registry") == "registry"
    assert _parse_agent_identifier("did:web:example.com:agents:ns:agent", "registry") == "agent"
    assert _parse_agent_identifier("ns:agent", "registry") == "agent"
    assert _parse_agent_identifier("plain-agent", "registry") == "plain-agent"


def test_bridge_unregister_records_delete_and_add_tool():
    bridge = NandaBridge(
        registry_id="bridge-test",
        provider_name="Bridge",
        provider_url="https://bridge.test",
    )
    agent = SimpleAgent(id="bridge-agent", name="Bridge Agent", description="desc")
    bridge.register_agent(agent)
    assert len(bridge.delta_store) == 1

    bridge.unregister_agent(agent.id)
    assert len(bridge.delta_store) == 2
    assert bridge.delta_store.since(1)[0].action == "delete"
    assert bridge.converter.get_agent(agent.id) is None

    tool = NandaTool(tool_id="bridge-tool", description="Tool", endpoint="https://tool.test")
    bridge.add_tool(tool)
    assert len(bridge.tools) == 1
    assert bridge.wellknown.tools_url is not None


def test_bridge_accepts_custom_converter_branch():
    custom_converter = SimpleAgentConverter(
        registry_id="custom-registry",
        provider_name="Custom",
        provider_url="https://custom.test",
    )
    custom_store = DeltaStore()
    bridge = NandaBridge(
        registry_id="custom-registry",
        provider_name="Custom",
        provider_url="https://custom.test",
        converter=custom_converter,
        delta_store=custom_store,
    )
    assert bridge.converter is custom_converter
    assert bridge.delta_store is custom_store
