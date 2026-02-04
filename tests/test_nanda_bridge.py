"""
Tests for nanda-bridge
"""

import pytest
from datetime import datetime, UTC

from nanda_bridge import (
    NandaAgentFacts,
    NandaProvider,
    NandaEndpoints,
    NandaCapabilities,
    NandaAuthentication,
    NandaSkill,
    NandaWellKnown,
    DeltaStore,
    SimpleAgent,
    SimpleAgentConverter,
    NandaBridge,
)


class TestModels:
    """Test NANDA model definitions."""
    
    def test_create_agent_facts(self):
        """Test creating a basic NandaAgentFacts instance."""
        facts = NandaAgentFacts(
            id="did:web:example.com:agents:test",
            handle="@test/agent",
            agent_name="Test Agent",
            label="test",
            description="A test agent",
            version="1.0.0",
            provider=NandaProvider(name="Test", url="https://test.com"),
            endpoints=NandaEndpoints(static=["https://test.com/agent"]),
            capabilities=NandaCapabilities(modalities=["text"]),
            skills=[NandaSkill(id="test-skill", description="A test skill")],
        )
        
        assert facts.id == "did:web:example.com:agents:test"
        assert facts.handle == "@test/agent"
        assert facts.agent_name == "Test Agent"
        assert len(facts.skills) == 1
    
    def test_create_handle(self):
        """Test handle creation helper."""
        handle = NandaAgentFacts.create_handle(
            registry="my-registry",
            namespace="prod",
            agent_id="my-agent"
        )
        assert handle == "@my-registry:prod/my-agent"
    
    def test_well_known(self):
        """Test well-known document creation."""
        doc = NandaWellKnown(
            registry_id="test-registry",
            registry_did="did:web:test.com",
            namespaces=["did:web:test.com:*"],
            index_url="https://test.com/nanda/index",
            resolve_url="https://test.com/nanda/resolve",
            deltas_url="https://test.com/nanda/deltas",
            provider=NandaProvider(name="Test", url="https://test.com"),
        )
        
        assert doc.registry_id == "test-registry"
        assert "agentfacts" in doc.capabilities


class TestDeltaStore:
    """Test delta store functionality."""
    
    def test_add_delta(self):
        """Test adding a delta."""
        store = DeltaStore()
        
        facts = NandaAgentFacts(
            id="did:web:example.com:agents:test",
            handle="@test/agent",
            agent_name="Test Agent",
            label="test",
            description="A test agent",
            version="1.0.0",
            provider=NandaProvider(name="Test", url="https://test.com"),
            endpoints=NandaEndpoints(static=[]),
            capabilities=NandaCapabilities(modalities=[]),
            skills=[],
        )
        
        delta = store.add("upsert", facts)
        
        assert delta.seq == 1
        assert delta.action == "upsert"
        assert delta.agent.id == facts.id
    
    def test_since(self):
        """Test getting deltas since a sequence number."""
        store = DeltaStore()
        
        facts = NandaAgentFacts(
            id="did:web:example.com:agents:test",
            handle="@test/agent",
            agent_name="Test Agent",
            label="test",
            description="A test agent",
            version="1.0.0",
            provider=NandaProvider(name="Test", url="https://test.com"),
            endpoints=NandaEndpoints(static=[]),
            capabilities=NandaCapabilities(modalities=[]),
            skills=[],
        )
        
        store.add("upsert", facts)
        store.add("upsert", facts)
        store.add("upsert", facts)
        
        deltas = store.since(1)
        assert len(deltas) == 2
        
        deltas = store.since(0)
        assert len(deltas) == 3
    
    def test_next_seq(self):
        """Test sequence number tracking."""
        store = DeltaStore()
        
        assert store.next_seq == 1
        
        facts = NandaAgentFacts(
            id="did:web:example.com:agents:test",
            handle="@test/agent",
            agent_name="Test Agent",
            label="test",
            description="Test",
            version="1.0.0",
            provider=NandaProvider(name="Test", url="https://test.com"),
            endpoints=NandaEndpoints(static=[]),
            capabilities=NandaCapabilities(modalities=[]),
            skills=[],
        )
        
        store.add("upsert", facts)
        assert store.next_seq == 2


class TestConverter:
    """Test agent converter."""
    
    def test_simple_agent_converter(self):
        """Test SimpleAgentConverter."""
        converter = SimpleAgentConverter(
            registry_id="test-registry",
            provider_name="Test Provider",
            provider_url="https://test.com",
            base_url="https://registry.test.com",
        )
        
        agent = SimpleAgent(
            id="my-agent",
            name="My Agent",
            description="A test agent",
            namespace="prod",
            labels=["chat", "assistant"],
        )
        
        converter.register(agent)
        
        facts = converter.to_nanda(agent)
        
        assert "did:" in facts.id
        assert facts.handle == "@test-registry:prod/my-agent"
        assert facts.agent_name == "My Agent"
        assert facts.provider.name == "Test Provider"
        assert "chat" in facts.capabilities.modalities
    
    def test_list_agents(self):
        """Test listing agents."""
        converter = SimpleAgentConverter(
            registry_id="test-registry",
            provider_name="Test",
            provider_url="https://test.com",
        )
        
        converter.register(SimpleAgent(id="agent-1", name="Agent 1", description="First"))
        converter.register(SimpleAgent(id="agent-2", name="Agent 2", description="Second"))
        
        agents = list(converter.list_agents(limit=10, offset=0))
        assert len(agents) == 2


class TestNandaBridge:
    """Test high-level NandaBridge."""
    
    def test_bridge_creation(self):
        """Test creating a NandaBridge."""
        bridge = NandaBridge(
            registry_id="test-registry",
            provider_name="Test",
            provider_url="https://test.com",
        )
        
        assert bridge.registry_id == "test-registry"
        assert bridge.router is not None
    
    def test_register_agent(self):
        """Test registering an agent via bridge."""
        bridge = NandaBridge(
            registry_id="test-registry",
            provider_name="Test",
            provider_url="https://test.com",
        )
        
        facts = bridge.register_agent(SimpleAgent(
            id="my-agent",
            name="My Agent",
            description="Test",
        ))
        
        assert facts.handle == "@test-registry:default/my-agent"
        
        # Should have recorded a delta
        deltas = bridge.delta_store.since(0)
        assert len(deltas) == 1
        assert deltas[0].action == "upsert"
    
    def test_wellknown(self):
        """Test well-known document generation."""
        bridge = NandaBridge(
            registry_id="test-registry",
            provider_name="Test",
            provider_url="https://test.com",
            base_url="https://registry.test.com",
        )
        
        wellknown = bridge.wellknown
        
        assert wellknown.registry_id == "test-registry"
        assert "https://registry.test.com/nanda/index" == wellknown.index_url
