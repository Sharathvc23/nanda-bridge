"""
NANDA Bridge - A Python library for building NANDA-compatible agent registries.

NANDA (Network of AI Agents in Decentralized Architecture) is MIT Media Lab's
protocol for federated AI agent discovery and communication.

This library provides:
- Pydantic models matching the NANDA AgentFacts schema (list39.org compatible)
- FastAPI router with standard NANDA endpoints
- Simple delta store for change tracking
- Abstract interfaces for custom registry integration

Usage:
    from nanda_bridge import NandaBridge, NandaAgentFacts
    
    bridge = NandaBridge(
        registry_id="my-registry",
        provider_name="My Company",
        provider_url="https://example.com"
    )
    
    app = FastAPI()
    app.include_router(bridge.router)

See https://github.com/projnanda for the official NANDA specification.
"""

from .models import (
    NandaAdaptiveResolver,
    NandaAgentFacts,
    NandaAgentFactsDelta,
    NandaAgentFactsDeltaResponse,
    NandaAgentFactsIndexResponse,
    NandaAuthentication,
    NandaCapabilities,
    NandaCertification,
    NandaEndpoints,
    NandaEvaluations,
    NandaProvider,
    NandaSkill,
    NandaTelemetry,
    NandaTool,
    NandaToolsResponse,
    NandaWellKnown,
    NandaA2AMessage,
)
from .store import DeltaStore
from .converter import AgentConverter, SimpleAgent, SimpleAgentConverter
from .router import create_nanda_router, NandaBridge

__version__ = "0.2.0"
__all__ = [
    # Core Models
    "NandaAgentFacts",
    "NandaProvider",
    "NandaEndpoints",
    "NandaAdaptiveResolver",
    "NandaAuthentication",
    "NandaCapabilities",
    "NandaSkill",
    # Trust & Verification Models
    "NandaCertification",
    "NandaEvaluations",
    "NandaTelemetry",
    # Response Models
    "NandaAgentFactsIndexResponse",
    "NandaAgentFactsDelta",
    "NandaAgentFactsDeltaResponse",
    "NandaWellKnown",
    # Tool Models
    "NandaTool",
    "NandaToolsResponse",
    # Messaging
    "NandaA2AMessage",
    # Store
    "DeltaStore",
    # Converter
    "AgentConverter",
    "SimpleAgent",
    "SimpleAgentConverter",
    # Router
    "create_nanda_router",
    "NandaBridge",
]
