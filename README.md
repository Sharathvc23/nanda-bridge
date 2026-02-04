# NANDA Bridge

NANDA Bridge is a minimal Python reference implementation for NANDA AgentFacts,
registry endpoints, and Quilt-style deltas. It is designed as a simple on-ramp
for new registries.

## Features

- AgentFacts models (Pydantic v2)
- FastAPI router for NANDA endpoints
- Delta store for change tracking
- Converter interface for custom registries
- Optional MCP tool advertising

## Requirements

- Python 3.10+

## Installation

```bash
pip install nanda-bridge  # once published to PyPI
```

From source:

```bash
git clone https://github.com/Sharathvc23/nanda-bridge
cd nanda-bridge
pip install -e .
```

From GitHub:

```bash
pip install git+https://github.com/Sharathvc23/nanda-bridge.git
```

## Quick Start

```python
from fastapi import FastAPI
from nanda_bridge import NandaBridge, SimpleAgent

bridge = NandaBridge(
    registry_id="my-registry",
    provider_name="My Company",
    provider_url="https://example.com",
    base_url="https://registry.example.com",
)

bridge.register_agent(
    SimpleAgent(
        id="my-agent",
        name="My Agent",
        description="An agent that does things",
        namespace="production",
        labels=["chat", "tool-use"],
        skills=[
            {"id": "summarize", "description": "Summarizes text"},
            {"id": "translate", "description": "Translates between languages"},
        ],
    )
)

app = FastAPI()
app.include_router(bridge.router)
```

### Endpoints

When mounted with the default prefix (`/nanda`), the router exposes:

- `GET /nanda/index` - list public agents
- `GET /nanda/resolve?agent=...` - resolve a single agent
- `GET /nanda/deltas?since=0` - change feed for sync
- `GET /nanda/tools` - MCP tool listing (if configured)
- `GET /nanda/.well-known/nanda.json` - registry discovery

## Custom Registry Integration

For registries with their own internal models, implement a converter:

```python
from typing import Iterator
from nanda_bridge import (
    AbstractAgentConverter,
    NandaAgentFacts,
    NandaCapabilities,
    NandaEndpoints,
    NandaProvider,
    NandaSkill,
    DeltaStore,
    create_nanda_router,
)

class MyRegistryConverter(AbstractAgentConverter):
    def __init__(self, db_connection):
        super().__init__(
            registry_id="my-registry",
            provider_name="My Company",
            provider_url="https://example.com",
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
            },
        )

    def list_agents(self, limit: int, offset: int) -> Iterator:
        return self.db.query_agents(limit=limit, offset=offset)

    def get_agent(self, agent_id: str):
        return self.db.get_agent(agent_id)

    def is_public(self, agent) -> bool:
        return agent.visibility == "public"

converter = MyRegistryConverter(db_connection)
delta_store = DeltaStore()

router = create_nanda_router(
    converter=converter,
    delta_store=delta_store,
    registry_id="my-registry",
    base_url="https://registry.example.com",
    provider_name="My Company",
    provider_url="https://example.com",
)
```

## Models

The core model is `NandaAgentFacts`, with support types for providers,
endpoints, capabilities, skills, tools, and A2A messages. See
`nanda_bridge.models` for the full schema.

## Delta Store

```python
from nanda_bridge import DeltaStore

store = DeltaStore()
delta = store.add("upsert", agent_facts)
deltas = store.since(0)
next_seq = store.next_seq
```

For production, extend the persistent store:

```python
from nanda_bridge.store import PersistentDeltaStore

class PostgresDeltaStore(PersistentDeltaStore):
    def _persist(self, delta):
        pass

    def _load_since(self, seq):
        return []
```

## MCP Tools

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
            params=["query", "limit"],
        ),
    ],
)
```

## Registry Discovery

By default, the well-known document is served at
`/nanda/.well-known/nanda.json` (under the router prefix). If you need it at
the root, create the router manually with `prefix=""` and mount it at `/`.

## Development

```bash
pytest -q
```

## API Stability

This project is pre-1.0. Public APIs may change between minor releases.
For production use, pin exact versions and review changelogs before upgrading.

## License

MIT License. See `LICENSE`.

## Credits

Developed by stellarminds.ai and open-sourced for Project NANDA (https://projectnanda.org).

