# NANDA Bridge

A Python library for building NANDA-compatible AI agent registries.

**[NANDA](https://projectnanda.org)** (Networked AI Agents in Decentralized Architecture) is the protocol for federated AI agent discovery and communication. This library provides the primitives needed to make your agent registry interoperable with the NANDA ecosystem.

## Features

- **NANDA AgentFacts Models** - Pydantic models implementing the [projnanda/agentfacts-format](https://github.com/projnanda) specification
- **FastAPI Router** - Drop-in endpoints for `/nanda/index`, `/nanda/resolve`, `/nanda/deltas`
- **Delta Store** - Change tracking for registry synchronization
- **Converter Interface** - Abstract pattern for integrating with your existing registry

## Installation

```bash
pip install nanda-bridge
```

Or install from source:

```bash
git clone https://github.com/lyraspace/nanda-bridge
cd nanda-bridge
pip install -e .
```

## Quick Start

### Basic Usage

```python
from fastapi import FastAPI
from nanda_bridge import NandaBridge, SimpleAgent

# Create the bridge
bridge = NandaBridge(
    registry_id="my-registry",
    provider_name="My Company",
    provider_url="https://example.com",
    base_url="https://registry.example.com"
)

# Register agents
bridge.register_agent(SimpleAgent(
    id="my-agent",
    name="My Agent",
    description="An agent that does things",
    namespace="production",
    labels=["chat", "tool-use"],
    skills=[
        {"id": "summarize", "description": "Summarizes text"},
        {"id": "translate", "description": "Translates between languages"}
    ]
))

# Mount the router
app = FastAPI()
app.include_router(bridge.router)
```

This gives you:

- `GET /nanda/index` - List all public agents
- `GET /nanda/resolve?agent=my-agent` - Resolve a single agent
- `GET /nanda/deltas?since=0` - Get changes for sync
- `GET /nanda/.well-known/nanda.json` - Registry discovery

### Custom Registry Integration

For existing registries with their own data models:

```python
from nanda_bridge import (
    AbstractAgentConverter,
    NandaAgentFacts,
    NandaProvider,
    NandaEndpoints,
    NandaCapabilities,
    NandaSkill,
    DeltaStore,
    create_nanda_router,
)
from typing import Iterator

class MyRegistryConverter(AbstractAgentConverter):
    def __init__(self, db_connection):
        super().__init__(
            registry_id="my-registry",
            provider_name="My Company",
            provider_url="https://example.com"
        )
        self.db = db_connection
    
    def to_nanda(self, agent) -> NandaAgentFacts:
        return NandaAgentFacts(
            id=f"did:web:example.com:agents:{agent.id}",
            handle=self.build_handle(agent.namespace, agent.id),
            agent_name=agent.display_name,
            label=agent.category,
            description=agent.description,
            version=agent.version,
            provider=self.build_provider(),
            endpoints=NandaEndpoints(static=[agent.endpoint_url]),
            capabilities=NandaCapabilities(modalities=agent.capabilities),
            skills=[NandaSkill(id=s.id, description=s.desc) for s in agent.skills],
            metadata={
                "x_my_registry": {
                    "internal_id": agent.internal_id,
                    "created_at": agent.created_at.isoformat(),
                }
            }
        )
    
    def list_agents(self, limit: int, offset: int) -> Iterator:
        return self.db.query_agents(limit=limit, offset=offset)
    
    def get_agent(self, agent_id: str):
        return self.db.get_agent(agent_id)
    
    def is_public(self, agent) -> bool:
        return agent.visibility == "public"

# Create router with custom converter
converter = MyRegistryConverter(db_connection)
delta_store = DeltaStore()

router = create_nanda_router(
    converter=converter,
    delta_store=delta_store,
    registry_id="my-registry",
    base_url="https://registry.example.com",
    provider_name="My Company",
    provider_url="https://example.com"
)

app = FastAPI()
app.include_router(router)
```

## Models

### NandaAgentFacts

The core data structure for agent metadata:

```python
from nanda_bridge import NandaAgentFacts

facts = NandaAgentFacts(
    id="did:web:example.com:agents:my-agent",
    handle="@my-registry:production/my-agent",
    agent_name="My Agent",
    label="assistant",
    description="An AI assistant",
    version="1.0.0",
    provider=NandaProvider(
        name="My Company",
        url="https://example.com"
    ),
    endpoints=NandaEndpoints(
        static=["https://api.example.com/agents/my-agent"]
    ),
    capabilities=NandaCapabilities(
        modalities=["text", "tool-use"],
        authentication=NandaAuthentication(methods=["did-auth"])
    ),
    skills=[
        NandaSkill(
            id="urn:my-registry:cap:summarize:v1",
            description="Summarizes long documents",
            inputModes=["text"],
            outputModes=["text"]
        )
    ],
    metadata={
        "x_my_registry": {
            "custom_field": "custom_value"
        }
    }
)
```

### Handle Format

NANDA handles follow the format `@registry:namespace/agent-id`:

```python
handle = NandaAgentFacts.create_handle(
    registry="my-registry",
    namespace="production", 
    agent_id="my-agent"
)
# Returns: "@my-registry:production/my-agent"
```

## Delta Store

Track changes for registry synchronization:

```python
from nanda_bridge import DeltaStore, NandaAgentFacts

store = DeltaStore()

# Record an agent creation/update
delta = store.add("upsert", agent_facts)
print(f"Recorded delta with seq={delta.seq}")

# Get all changes since seq 0
deltas = store.since(0)

# Get next sequence number for polling
next_seq = store.next_seq
```

For production, extend `PersistentDeltaStore` to persist to a database:

```python
from nanda_bridge import PersistentDeltaStore

class PostgresDeltaStore(PersistentDeltaStore):
    def __init__(self, dsn: str):
        super().__init__()
        self.conn = psycopg2.connect(dsn)
    
    def _persist(self, delta):
        # INSERT INTO nanda_deltas ...
        pass
    
    def _load_since(self, seq):
        # SELECT * FROM nanda_deltas WHERE seq > ...
        pass
```

## MCP Tools

Advertise MCP tools that agents can use:

```python
from nanda_bridge import NandaBridge, NandaTool

bridge = NandaBridge(
    registry_id="my-registry",
    provider_name="My Company",
    provider_url="https://example.com",
    tools=[
        NandaTool(
            tool_id="search",
            description="Search the web",
            endpoint="https://api.example.com/mcp/search",
            params=["query", "limit"]
        ),
        NandaTool(
            tool_id="calculate",
            description="Perform calculations",
            endpoint="https://api.example.com/mcp/calculate",
            params=["expression"]
        )
    ]
)
```

## Registry Discovery

The library automatically serves `/.well-known/nanda.json` for registry discovery:

```json
{
  "registry_id": "my-registry",
  "registry_did": "did:web:registry.example.com",
  "namespaces": ["did:web:example.com:*"],
  "index_url": "https://registry.example.com/nanda/index",
  "resolve_url": "https://registry.example.com/nanda/resolve",
  "deltas_url": "https://registry.example.com/nanda/deltas",
  "tools_url": "https://registry.example.com/nanda/tools",
  "provider": {
    "name": "My Company",
    "url": "https://example.com"
  },
  "capabilities": ["agentfacts", "deltas", "mcp-tools"]
}
```

## Federating with NANDA

To join the NANDA network:

1. Deploy your registry with the NANDA bridge endpoints
2. Ensure `/.well-known/nanda.json` is accessible
3. Contact the MIT NANDA team to register as a federated peer
4. (Optional) Implement Quilt-compatible sync or gossip mechanisms for real-time or near-real-time federation

## Related Projects

- [Project NANDA](https://github.com/projnanda) - ProjectNANDA.org
- [NANDA Adapter](https://github.com/projnanda/adapter) - Official NANDA SDK
- [NANDA Quilt](https://github.com/aidecentralized/NANDA-Quilt-of-Registries-and-Verified-AgentFacts) - Federated registry specification

## License

MIT License - see [LICENSE](LICENSE)

## Contributing

Contributions welcome! Please read our contributing guidelines and submit pull requests.

## Credits

Developed by [stellarminds.ai](https://stellarminds.ai) and open-sourced for [projectnanda.org](https://projectnanda.org).
