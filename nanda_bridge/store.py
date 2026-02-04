"""
NANDA Delta Store

Simple in-memory delta store for tracking agent changes.
Provides the foundation for NANDA Quilt sync protocol.

For production use, extend this class to persist deltas to a database.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any, Protocol

from .models import NandaAgentFacts, NandaAgentFactsDelta


class DeltaStoreProtocol(Protocol):
    """Protocol for delta store implementations."""
    
    def add(self, action: str, agent: NandaAgentFacts) -> NandaAgentFactsDelta:
        """Record a new delta."""
        ...
    
    def since(self, seq: int) -> list[NandaAgentFactsDelta]:
        """Get all deltas since a sequence number."""
        ...
    
    @property
    def next_seq(self) -> int:
        """Get the next sequence number."""
        ...


class DeltaStore:
    """In-memory delta store for NANDA agent changes.
    
    Thread-safe implementation suitable for development and testing.
    For production, subclass and override to persist to a database.
    
    Usage:
        store = DeltaStore()
        
        # Record a change
        delta = store.add("upsert", agent_facts)
        
        # Get changes since seq 0
        deltas = store.since(0)
        
        # Get next sequence number for polling
        next_seq = store.next_seq
    """
    
    def __init__(self, max_deltas: int = 10000):
        """Initialize the delta store.
        
        Args:
            max_deltas: Maximum number of deltas to retain (oldest are pruned)
        """
        self._lock = threading.Lock()
        self._seq = 0
        self._deltas: list[NandaAgentFactsDelta] = []
        self._max_deltas = max_deltas
    
    def add(self, action: str, agent: NandaAgentFacts) -> NandaAgentFactsDelta:
        """Record a new delta.
        
        Args:
            action: Delta action type ("upsert", "delete", "revoke")
            agent: Agent facts to record
            
        Returns:
            The created delta with assigned sequence number
        """
        with self._lock:
            self._seq += 1
            delta = NandaAgentFactsDelta(
                seq=self._seq,
                action=action,
                recorded_at=datetime.now(UTC),
                agent=agent,
                signature=None,
            )
            self._deltas.append(delta)
            
            # Prune old deltas if needed
            if len(self._deltas) > self._max_deltas:
                self._deltas = self._deltas[-self._max_deltas:]
            
            return delta
    
    def since(self, seq: int) -> list[NandaAgentFactsDelta]:
        """Get all deltas since a sequence number.
        
        Args:
            seq: Sequence number to start from (exclusive)
            
        Returns:
            List of deltas with seq > the provided value
        """
        with self._lock:
            return [d for d in self._deltas if d.seq > seq]
    
    def get(self, seq: int) -> NandaAgentFactsDelta | None:
        """Get a specific delta by sequence number.
        
        Args:
            seq: Sequence number to retrieve
            
        Returns:
            The delta if found, None otherwise
        """
        with self._lock:
            for d in self._deltas:
                if d.seq == seq:
                    return d
            return None
    
    @property
    def next_seq(self) -> int:
        """Get the next sequence number that will be assigned."""
        with self._lock:
            return self._seq + 1
    
    @property
    def current_seq(self) -> int:
        """Get the current (most recent) sequence number."""
        with self._lock:
            return self._seq
    
    def clear(self) -> None:
        """Clear all deltas (useful for testing)."""
        with self._lock:
            self._seq = 0
            self._deltas = []
    
    def __len__(self) -> int:
        """Return the number of stored deltas."""
        with self._lock:
            return len(self._deltas)


class PersistentDeltaStore(DeltaStore):
    """Base class for persistent delta store implementations.
    
    Subclass this and implement the abstract methods to persist
    deltas to a database.
    
    Example PostgreSQL implementation:
    
        class PostgresDeltaStore(PersistentDeltaStore):
            def __init__(self, dsn: str):
                super().__init__()
                self._dsn = dsn
                self._init_schema()
                self._load_seq()
            
            def _persist(self, delta: NandaAgentFactsDelta) -> None:
                # INSERT INTO nanda_deltas ...
                pass
            
            def _load_since(self, seq: int) -> list[NandaAgentFactsDelta]:
                # SELECT * FROM nanda_deltas WHERE seq > ...
                pass
    """
    
    def add(self, action: str, agent: NandaAgentFacts) -> NandaAgentFactsDelta:
        """Record a delta and persist it."""
        delta = super().add(action, agent)
        self._persist(delta)
        return delta
    
    def since(self, seq: int) -> list[NandaAgentFactsDelta]:
        """Load deltas from persistent storage."""
        # Try persistent storage first
        persisted = self._load_since(seq)
        if persisted:
            return persisted
        # Fall back to in-memory
        return super().since(seq)
    
    def _persist(self, delta: NandaAgentFactsDelta) -> None:
        """Persist a delta to storage. Override in subclass."""
        pass
    
    def _load_since(self, seq: int) -> list[NandaAgentFactsDelta]:
        """Load deltas from storage. Override in subclass."""
        return []
