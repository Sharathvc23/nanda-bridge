# A Reference Implementation for NANDA-Compatible Agent Registry Endpoints

**Authors:** StellarMinds ([stellarminds.ai](https://stellarminds.ai))
**Date:** February 2026
**Version:** 1.0

## Abstract

The NANDA (Network of AI Agents in Decentralized Architecture) ecosystem requires registry operators to expose standardized HTTP endpoints for agent discovery, resolution, and change synchronization. Implementing these endpoints from scratch requires understanding the AgentFacts schema, the Quilt delta-sync protocol, DID-based identity, and registry discovery conventions — a significant adoption barrier for new registry operators. This paper presents `nanda-bridge`, a Python library that provides Pydantic models implementing the NANDA AgentFacts specification (16 model types covering identity, capabilities, trust, telemetry, and messaging), a FastAPI router exposing five standard endpoints (`/nanda/index`, `/nanda/resolve`, `/nanda/deltas`, `/nanda/tools`, `/.well-known/nanda.json`), a thread-safe delta store for Quilt-compatible change tracking with configurable pruning, and an `AgentConverter` protocol enabling integration with arbitrary internal registry data models. The library supports three levels of adoption: drop-in usage via `NandaBridge` with `SimpleAgent`, protocol-based integration via the `AgentConverter` interface, and full customization via `AbstractAgentConverter` with inheritance. The implementation includes DID construction (`did:web:`), NANDA handle generation (`@registry:namespace/agent`), multi-format agent identifier parsing, SHA-256 proof generation, MCP tool advertisement, and A2A message envelopes. The library ships with 23 tests and depends on FastAPI and Pydantic as its only runtime dependencies.

## 1. Introduction

### 1.1 Problem Statement

Federated AI agent discovery requires that participating registries expose their agent inventories through standardized HTTP APIs. The NANDA protocol defines the schemas and endpoint conventions for this interoperability, but implementing them involves several non-trivial concerns:

- **Schema compliance** — The AgentFacts specification includes nested structures for provider identity, endpoints (static, dynamic, and adaptive), capabilities, skills, certification, evaluations, telemetry, and extensible metadata with vendor-prefixed keys.
- **Identity construction** — Agents must be addressable via DIDs (`did:web:`), NANDA handles (`@registry:namespace/agent`), and plain identifiers, with the registry responsible for constructing and parsing all three formats.
- **Change synchronization** — Registries must expose a delta feed with monotonically increasing sequence numbers, enabling peer registries to perform incremental sync without full re-indexing.
- **Discovery** — Registries must serve a well-known document (`/.well-known/nanda.json`) advertising their endpoints, provider identity, and supported capabilities.

Building these from scratch for each registry creates duplicated effort and risks schema divergence across implementations.

### 1.2 Motivation

The NANDA ecosystem needs a reference implementation that:

1. **Lowers the adoption barrier** — a new registry should be able to expose NANDA-compatible endpoints with minimal code.
2. **Ensures schema compliance** — Pydantic models provide runtime validation that serialized output matches the AgentFacts specification.
3. **Supports progressive adoption** — registries with simple needs should be able to use a high-level facade, while complex registries should be able to inject custom conversion logic without forking the library.
4. **Provides sync primitives** — a delta store with sequence-number-based change tracking, suitable as a foundation for Quilt-style federation.

### 1.3 Contributions

This paper makes the following contributions:

- **16 Pydantic model types** implementing the NANDA AgentFacts specification, including trust verification (certification, evaluations, telemetry), MCP tool descriptors, A2A message envelopes, and the well-known registry discovery document.
- **A FastAPI router factory** (`create_nanda_router()`) that produces five standard NANDA endpoints with query parameter validation, pagination, and multi-format agent identifier parsing.
- **A thread-safe delta store** with monotonic sequence numbering, configurable retention pruning, and a `PersistentDeltaStore` base class for database-backed implementations.
- **An `AgentConverter` protocol** (`@runtime_checkable`) enabling integration with arbitrary internal registry data models without inheritance, plus `AbstractAgentConverter` for inheritance-based integration.
- **A `NandaBridge` high-level facade** that composes converter, delta store, and router into a single object for rapid adoption.
- **Three-tier identity construction** — `did:web:` DIDs, `@registry:namespace/agent` handles, and SHA-256 proof digests — with a multi-format identifier parser supporting all three formats plus namespaced identifiers.

## 2. Related Work

### 2.1 NANDA Official Adapter

The official NANDA Adapter SDK (`projnanda/adapter`) provides the canonical client-side SDK for interacting with NANDA registries. It focuses on consuming registry APIs rather than serving them. This work complements the official adapter by providing the server-side implementation that the adapter connects to — the registry endpoints themselves.

### 2.2 NANDA Quilt (Federated Registry Specification)

The NANDA Quilt specification defines how registries federate through delta-based synchronization, gossip protocols, and peer discovery. Quilt prescribes the delta feed format (sequence numbers, action types, timestamps) but does not provide a reference implementation of the delta store or the HTTP endpoints. This work implements the delta store and endpoint layer that Quilt federation builds upon.

### 2.3 Google Agent-to-Agent (A2A) Protocol

Google's A2A protocol defines a communication framework for AI agents, including agent cards, task management, and message exchange. While A2A focuses on inter-agent communication semantics, NANDA focuses on agent discovery and registry federation. The `NandaA2AMessage` model in this library provides a bridge between the two protocols, enabling NANDA-registered agents to exchange A2A-compatible messages.

### 2.4 OpenAPI / FastAPI Ecosystem

FastAPI provides automatic OpenAPI schema generation, Pydantic-based request/response validation, and async support. By building on FastAPI, the NANDA endpoints automatically gain OpenAPI documentation, JSON Schema validation, and ASGI deployment compatibility. However, FastAPI alone does not provide NANDA-specific concerns like delta stores, DID construction, or handle generation — these are the domain-specific additions this library provides.

### 2.5 Gaps Addressed

This work addresses three gaps in the existing landscape:

1. **Server-side reference implementation** — a ready-to-deploy library for registry operators, complementing the client-side official adapter.
2. **Progressive adoption path** — three integration levels (facade, protocol, abstract class) accommodating registries of varying complexity.
3. **Schema-validated models** — Pydantic models ensuring that serialized output matches the AgentFacts specification at runtime, rather than relying on documentation-level compliance.

## 3. Design / Architecture

### 3.1 Component Architecture

The library is organized into four modules:

```
┌─────────────────────────────────────────────────┐
│            NandaBridge (router.py)               │  High-level facade
├─────────────────────────────────────────────────┤
│       FastAPI Router (router.py)                 │  5 NANDA endpoints
├──────────────────┬──────────────────────────────┤
│ DeltaStore        │  AgentConverter              │  Change tracking │ Registry integration
│ (store.py)        │  (converter.py)              │
├──────────────────┴──────────────────────────────┤
│         Pydantic Models (models.py)              │  16 NANDA types
└─────────────────────────────────────────────────┘
```

Each module has a single responsibility: models define the schema, the converter translates internal types to NANDA types, the store tracks changes, and the router exposes HTTP endpoints.

### 3.2 Model Taxonomy

The 16 Pydantic models are organized into five groups:

| Group | Models | Purpose |
|-------|--------|---------|
| Core | `NandaAgentFacts`, `NandaProvider`, `NandaEndpoints`, `NandaAdaptiveResolver`, `NandaAuthentication`, `NandaCapabilities`, `NandaSkill` | Agent identity, connectivity, and capabilities |
| Trust | `NandaCertification`, `NandaEvaluations`, `NandaTelemetry` | Trust verification, performance metrics, observability |
| Response | `NandaAgentFactsIndexResponse`, `NandaAgentFactsDelta`, `NandaAgentFactsDeltaResponse` | API response envelopes |
| Discovery | `NandaWellKnown` | Registry discovery document |
| Tools & Messaging | `NandaTool`, `NandaToolsResponse`, `NandaA2AMessage` | MCP tools and agent-to-agent messaging |

### 3.3 Three-Tier Adoption Model

The library supports three levels of integration complexity:

**Tier 1: Drop-in (NandaBridge + SimpleAgent)**

```python
bridge = NandaBridge(registry_id="my-registry", ...)
bridge.register_agent(SimpleAgent(id="my-agent", name="My Agent", ...))
app.include_router(bridge.router)
```

Suitable for new registries without existing data models. `NandaBridge` composes a `SimpleAgentConverter`, `DeltaStore`, and `APIRouter` internally.

**Tier 2: Protocol-based (AgentConverter)**

```python
class MyConverter:
    def to_nanda(self, agent) -> NandaAgentFacts: ...
    def list_agents(self, limit, offset) -> Iterator: ...
    def get_agent(self, agent_id) -> Any | None: ...
    def is_public(self, agent) -> bool: ...
```

Suitable for registries with existing internal models. Any class implementing the four required methods satisfies the `@runtime_checkable` `AgentConverter` protocol — no inheritance needed.

**Tier 3: Inheritance-based (AbstractAgentConverter)**

```python
class MyConverter(AbstractAgentConverter):
    def __init__(self, db):
        super().__init__(registry_id="my-registry", ...)
```

Suitable for registries that want built-in helper methods (`build_provider()`, `build_handle()`) alongside their custom conversion logic.

### 3.4 Identity System

The library constructs three forms of agent identity:

| Format | Example | Construction |
|--------|---------|-------------|
| DID | `did:web:example.com:agents:prod:my-agent` | `did:{method}:{domain}:agents:{namespace}:{id}` |
| Handle | `@my-registry:prod/my-agent` | `@{registry_id}:{namespace}/{agent_id}` |
| Proof digest | `sha256:a1b2c3...` | `SHA-256("{id}:{namespace}:{version}:{registry_id}")` |

The `_parse_agent_identifier()` function reverses all three formats plus plain IDs and namespaced identifiers, enabling the `/nanda/resolve` endpoint to accept any identifier format.

### 3.5 Endpoint Design

The router exposes five endpoints:

| Endpoint | Method | Response Model | Purpose |
|----------|--------|---------------|---------|
| `/nanda/index` | GET | `NandaAgentFactsIndexResponse` | List all public agents (paginated) |
| `/nanda/resolve` | GET | `NandaAgentFacts` | Resolve a single agent by ID/DID/handle |
| `/nanda/deltas` | GET | `NandaAgentFactsDeltaResponse` | Get changes since a sequence number |
| `/nanda/tools` | GET | `NandaToolsResponse` | List available MCP tools |
| `/.well-known/nanda.json` | GET | `NandaWellKnown` | Registry discovery document |

The index endpoint filters agents through `converter.is_public()` and supports `limit`/`offset` pagination (validated: `limit` 1–500, `offset` >= 0). The resolve endpoint returns 404 for unknown agents and 403 for non-public agents.

## 4. Implementation

### 4.1 NandaAgentFacts Model

The core model captures 15 fields organized by the NANDA specification:

```python
class NandaAgentFacts(BaseModel):
    id: str                                    # DID or UUID
    handle: str | None = None                  # @registry:namespace/agent
    agent_name: str                            # Human-readable name
    label: str | None = None                   # Short category
    description: str                           # Agent description
    version: str                               # Semver recommended
    provider: NandaProvider                     # Organization running the agent
    endpoints: NandaEndpoints                   # How to reach the agent
    capabilities: NandaCapabilities             # What the agent can do
    skills: list[NandaSkill] = []              # Detailed skill definitions
    certification: NandaCertification | None    # Trust verification
    evaluations: NandaEvaluations | None        # Performance metrics
    telemetry: NandaTelemetry | None            # Observability config
    metadata: dict[str, Any] = {}              # Vendor extensions (x_ prefix)
    proof: dict[str, Any] | None = None        # Attestation payload
```

The `metadata` field supports the NANDA `x_` prefix convention for vendor extensions. The `SimpleAgentConverter` populates this with `x_{registry_id}` containing the agent's namespace, original ID, visibility, classification, and extended endpoint metadata.

### 4.2 SimpleAgentConverter

The `SimpleAgentConverter` translates `SimpleAgent` dataclass instances into `NandaAgentFacts`. The conversion process:

1. **DID construction** — Derives `did:web:{domain}:agents:{namespace}:{id}` from the provider URL and agent identity.
2. **Handle generation** — Calls `NandaAgentFacts.create_handle()` with registry ID, namespace, and agent ID.
3. **Endpoint assembly** — Merges static endpoints from the agent's `endpoints` dict, dynamic endpoints, and optional adaptive resolver configuration.
4. **Skill processing** — Accepts skills as either dictionaries (with `id`, `description`, `inputModes`, `outputModes`) or plain strings, normalizing both into `NandaSkill` instances. Agents with no skills receive a default skill URN.
5. **Trust metadata** — Populates `NandaCertification` (level, issuer, attestations), optional `NandaEvaluations` (performance score, availability, audit trail), and optional `NandaTelemetry`.
6. **Vendor extension** — Builds the `x_{registry_id}` metadata block with extended endpoint descriptors including protocol detection and human-readable descriptions.
7. **Proof generation** — Computes a SHA-256 digest of `"{id}:{namespace}:{version}:{registry_id}"` as a lightweight, non-secret integrity placeholder.

### 4.3 Delta Store

The `DeltaStore` provides thread-safe change tracking with three operations:

```python
class DeltaStore:
    def add(self, action: str, agent: NandaAgentFacts) -> NandaAgentFactsDelta
    def since(self, seq: int) -> list[NandaAgentFactsDelta]
    def get(self, seq: int) -> NandaAgentFactsDelta | None
```

**Thread safety** — All operations acquire a `threading.Lock()` before accessing the internal delta list and sequence counter.

**Monotonic sequencing** — Each `add()` call increments the sequence counter atomically before creating the delta record. Sequence numbers start at 1 and never decrease.

**Retention pruning** — The store accepts a `max_deltas` parameter (default 10,000). After each `add()`, if the delta count exceeds the maximum, the oldest deltas are pruned via list slicing (`self._deltas[-self._max_deltas:]`). This bounds memory usage while preserving the most recent history for sync consumers.

**Persistence extension** — The `PersistentDeltaStore` subclass adds `_persist()` and `_load_since()` hooks. The `add()` method calls `super().add()` for in-memory tracking, then `_persist()` for database storage. The `since()` method tries `_load_since()` first, falling back to in-memory if the persistent store returns empty.

### 4.4 Agent Identifier Parser

The `/nanda/resolve` endpoint must accept multiple identifier formats. The `_parse_agent_identifier()` function handles four patterns:

| Input Format | Example | Extraction |
|-------------|---------|-----------|
| Handle | `@myregistry:ns/my-agent` | Split on `/`, take last segment |
| DID | `did:web:example.com:agents:ns:my-agent` | Split on `:`, take last segment |
| Namespaced | `ns:my-agent` | Split on `:`, take last segment |
| Plain ID | `my-agent` | Return as-is |

The parser processes formats in priority order (handle → DID → namespaced → plain) and always extracts the terminal agent identifier, normalizing all formats to a simple string for lookup via `converter.get_agent()`.

### 4.5 Well-Known Discovery Document

The `NandaWellKnown` model serves at `/.well-known/nanda.json` and advertises:

- **Identity** — `registry_id` and `registry_did` (derived as `did:web:{domain}`)
- **Namespaces** — DID namespaces the registry manages (e.g., `did:web:example.com:*`)
- **Endpoint URLs** — Full URLs for index, resolve, deltas, and optionally tools
- **Provider** — Organization identity
- **Capabilities** — Supported NANDA features (`agentfacts`, `deltas`, optionally `mcp-tools`)
- **Peers** — Optional list of peer registry URLs for Quilt federation

### 4.6 Public API

The package exports 21 symbols:

| Category | Exports |
|----------|---------|
| Core Models | `NandaAgentFacts`, `NandaProvider`, `NandaEndpoints`, `NandaAdaptiveResolver`, `NandaAuthentication`, `NandaCapabilities`, `NandaSkill` |
| Trust Models | `NandaCertification`, `NandaEvaluations`, `NandaTelemetry` |
| Response Models | `NandaAgentFactsIndexResponse`, `NandaAgentFactsDelta`, `NandaAgentFactsDeltaResponse`, `NandaWellKnown` |
| Tools & Messaging | `NandaTool`, `NandaToolsResponse`, `NandaA2AMessage` |
| Infrastructure | `DeltaStore`, `AgentConverter`, `SimpleAgent`, `SimpleAgentConverter`, `create_nanda_router`, `NandaBridge` |

## 5. Integration

### 5.1 NANDA Ecosystem Context

The `nanda-bridge` package occupies the **transport layer** in the NANDA ecosystem, answering the question: *"How do I expose agents to the NANDA network?"* It serves as the HTTP interface through which all model metadata reaches federated peers.

| Package | Role | Question Answered |
|---------|------|-------------------|
| `nanda-model-provenance` | Identity metadata | Where did this model come from? |
| `nanda-model-card` | Metadata schema | What is this model? |
| `nanda-model-integrity-layer` | Integrity verification | Does this model's metadata meet policy? |
| `nanda-model-governance` | Cryptographic governance | Has this model been approved? |
| `nanda-bridge` | Transport layer | How do I expose this to the NANDA network? |

### 5.2 Integration with Model Provenance

Model provenance metadata flows into the bridge through the `NandaAgentFacts.metadata` field. The `nanda-model-provenance` package's `to_agentfacts_extension()` method produces a dict under the `x_model_provenance` key that can be merged into the agent's metadata:

```python
from nanda_model_provenance import ModelProvenance

provenance = ModelProvenance(model_id="llama-3.1-8b", provider_id="ollama")
agent_metadata = provenance.to_agentfacts_extension()
# {"x_model_provenance": {"model_id": "llama-3.1-8b", "provider_id": "ollama"}}
```

This dict is included in the `metadata` field of `NandaAgentFacts`, which the bridge serializes and serves through the `/nanda/index` and `/nanda/resolve` endpoints.

### 5.3 Integration with the Integrity Layer

The `nanda-model-integrity-layer` package's `attach_to_agent_facts()` function injects both `x_model_integrity` and `x_model_provenance` keys into agent metadata. When this enriched metadata is set on a `NandaAgentFacts` instance, the bridge serves it with full integrity information — provenance, lineage, attestation, and governance report — to discovering peers.

### 5.4 Integration with the Governance Layer

The `nanda-model-governance` package's `approval_to_integrity_facts()` function converts a `ModelApproval` into metadata suitable for embedding in agent facts. The governance status (approved, revoked, expiration) becomes discoverable through the bridge's endpoints, enabling consuming registries to filter agents by governance status.

### 5.5 Federation Workflow

A complete NANDA federation workflow spans the bridge and its peers:

1. **Registration** — A registry operator creates a `NandaBridge`, registers agents, and deploys the FastAPI application.
2. **Discovery** — A peer registry fetches `/.well-known/nanda.json` to discover endpoint URLs.
3. **Initial sync** — The peer calls `/nanda/index` to retrieve all public agents.
4. **Incremental sync** — The peer polls `/nanda/deltas?since={last_seq}` to receive only changes since the last sync.
5. **Resolution** — End users or agents call `/nanda/resolve?agent={id}` to retrieve a specific agent's full metadata.

## 6. Evaluation

### 6.1 Test Coverage

The test suite contains **23 test methods** across 2 test modules:

| Test Module | Tests | Coverage Area |
|-------------|:-----:|---------------|
| `test_nanda_bridge.py` | 11 | Models, delta store, converter, bridge facade, well-known |
| `test_nanda_bridge_extra.py` | 12 | Skills, metadata, pruning, persistence, routing, parsing, unregister |

Test types include model construction tests, converter integration tests (skills as dicts and strings, endpoint assembly, metadata extension), delta store behavior tests (pruning, persistence hooks, thread safety), router endpoint tests (index filtering, resolve with 404/403, deltas, tools, well-known), identifier parser tests (all five formats), and bridge lifecycle tests (register, unregister, tool management).

### 6.2 Example: Minimal Registry

```python
from fastapi import FastAPI
from nanda_bridge import NandaBridge, SimpleAgent

bridge = NandaBridge(
    registry_id="my-registry",
    provider_name="My Company",
    provider_url="https://example.com",
    base_url="https://registry.example.com",
)

bridge.register_agent(SimpleAgent(
    id="my-agent",
    name="My Agent",
    description="An AI assistant",
    namespace="production",
    labels=["chat", "tool-use"],
    skills=[
        {"id": "summarize", "description": "Summarizes text"},
        {"id": "translate", "description": "Translates between languages"},
    ],
))

app = FastAPI()
app.include_router(bridge.router)
# Serves: /nanda/index, /nanda/resolve, /nanda/deltas, /nanda/tools, /.well-known/nanda.json
```

### 6.3 Example: Custom Registry Integration

```python
from nanda_bridge import AgentConverter, NandaAgentFacts, NandaProvider, NandaEndpoints, NandaCapabilities, DeltaStore, create_nanda_router

class MyRegistryConverter:
    def __init__(self, db):
        self.db = db
        self.registry_id = "my-registry"

    def to_nanda(self, agent) -> NandaAgentFacts:
        return NandaAgentFacts(
            id=f"did:web:example.com:agents:{agent.id}",
            agent_name=agent.display_name,
            description=agent.description,
            version=agent.version,
            provider=NandaProvider(name="My Co", url="https://example.com"),
            endpoints=NandaEndpoints(static=[agent.endpoint_url]),
            capabilities=NandaCapabilities(modalities=agent.capabilities),
        )

    def list_agents(self, limit, offset):
        return self.db.query_agents(limit=limit, offset=offset)

    def get_agent(self, agent_id):
        return self.db.get_agent(agent_id)

    def is_public(self, agent):
        return agent.visibility == "public"

router = create_nanda_router(
    converter=MyRegistryConverter(db),
    delta_store=DeltaStore(),
    registry_id="my-registry",
    base_url="https://registry.example.com",
    provider_name="My Company",
    provider_url="https://example.com",
)
```

## 7. Conclusion

### 7.1 Summary

This paper presented `nanda-bridge`, a reference implementation for NANDA-compatible agent registry endpoints. By providing 16 Pydantic models, a FastAPI router factory, a thread-safe delta store, and a protocol-based converter interface, the library lowers the barrier for new registries to join the NANDA federation. The three-tier adoption model (facade, protocol, abstract class) accommodates registries of varying complexity, from simple in-memory stores to production databases with custom data models. The delta store's monotonic sequencing and retention pruning provide the foundation for Quilt-compatible incremental sync.

### 7.2 Future Work

Several directions merit further investigation:

- **WebSocket delta streaming** — Adding a `/nanda/deltas/stream` WebSocket endpoint for real-time push-based sync, complementing the current poll-based delta feed.
- **Registry attestation** — Signing index and delta responses with Ed25519 signatures (integrating with `nanda-model-governance`) to provide cryptographic proof of registry integrity.
- **Quilt gossip protocol** — Implementing peer-to-peer delta propagation using the `peers` field in the well-known document, enabling transitive federation without a central coordinator.
- **Rate limiting and caching** — Adding configurable rate limits per endpoint and ETag-based caching for the index and resolve endpoints.
- **Async delta store** — Providing an async variant of the `DeltaStore` protocol for registries using async database drivers (asyncpg, motor).

## References

1. NANDA Protocol. "Network of AI Agents in Decentralized Architecture." https://projectnanda.org

2. NANDA Quilt. "Quilt of Registries and Verified AgentFacts." https://github.com/aidecentralized/NANDA-Quilt-of-Registries-and-Verified-AgentFacts

3. Google. "Agent-to-Agent (A2A) Protocol." https://github.com/google/A2A

4. Ramírez, S. "FastAPI: Modern, Fast, Web Framework for Building APIs." https://fastapi.tiangolo.com

5. Pydantic. "Data Validation Using Python Type Annotations." https://docs.pydantic.dev

6. W3C. "Decentralized Identifiers (DIDs) v1.0." W3C Recommendation, July 2022. https://www.w3.org/TR/did-core/

7. Mitchell, M., Wu, S., Zaldivar, A., Barnes, P., Vasserman, L., Hutchinson, B., Spitzer, E., Raji, I.D., and Gebru, T. (2019). "Model Cards for Model Reporting." *Proceedings of the Conference on Fairness, Accountability, and Transparency (FAT\*)*, pp. 220–229.
