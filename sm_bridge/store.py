"""
NANDA Delta Store

Simple in-memory delta store for tracking agent changes.
Provides the foundation for registry-to-registry delta sync.

For production use, extend this class to persist deltas to a database.
"""

from __future__ import annotations

import threading
import warnings
from datetime import datetime, timezone
from typing import Protocol

from .models import SmAgentFacts, SmAgentFactsDelta


class DeltaStoreProtocol(Protocol):
    """Protocol for delta store implementations."""

    def add(self, action: str, agent: SmAgentFacts) -> SmAgentFactsDelta:
        """Record a new delta."""
        ...

    def since(self, seq: int) -> list[SmAgentFactsDelta]:
        """Get all deltas since a sequence number."""
        ...

    def snapshot(self) -> list[SmAgentFactsDelta]:
        """The most recent delta for each agent, in sequence order."""
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

    def __init__(self, max_deltas: int | None = None):
        """Initialize the delta store.

        Args:
            max_deltas: Deprecated and ignored. The log is append-only.
        """
        if max_deltas is not None:
            warnings.warn(
                "max_deltas is ignored: the delta log is append-only. Pruning "
                "dropped the OLDEST deltas while the catalog was rebuilt by "
                "replaying from zero, so an agent whose only upsert had aged out "
                "vanished with no error. An agent's history is evidence, and a "
                "registry that silently forgets what it served cannot be audited "
                "for what it served.",
                DeprecationWarning,
                stacklevel=2,
            )
        self._lock = threading.Lock()
        self._seq = 0
        self._deltas: list[SmAgentFactsDelta] = []
        # The most recent delta per agent id, so rebuilding current state costs
        # one entry per agent rather than a replay of the whole log. A complete
        # log must not make the read path grow without bound.
        self._latest: dict[str, SmAgentFactsDelta] = {}

    def add(self, action: str, agent: SmAgentFacts) -> SmAgentFactsDelta:
        """Record a new delta.

        Args:
            action: Delta action type ("upsert", "delete", "revoke")
            agent: Agent facts to record

        Returns:
            The created delta with assigned sequence number
        """
        with self._lock:
            self._seq += 1
            delta = SmAgentFactsDelta(
                seq=self._seq,
                action=action,
                recorded_at=datetime.now(timezone.utc),
                agent=agent,
                signature=None,
            )
            self._deltas.append(delta)
            self._latest[agent.id] = delta
            return delta

    def since(self, seq: int) -> list[SmAgentFactsDelta]:
        """Get all deltas since a sequence number.

        Args:
            seq: Sequence number to start from (exclusive)

        Returns:
            List of deltas with seq > the provided value
        """
        with self._lock:
            return [d for d in self._deltas if d.seq > seq]

    def snapshot(self) -> list[SmAgentFactsDelta]:
        """The most recent delta for each agent, in sequence order.

        A `delete` or `revoke` is kept: a removal is a fact about the agent, not
        the absence of one, and dropping it would resurrect the agent on the next
        rebuild.

        Equivalent to replaying `since(0)`, and `current_facts` is tested against
        that equivalence — this is an optimisation, not a different answer.

        A subclass that persists deltas MUST override this; the default reads the
        in-memory index and would be wrong for a store whose history lives
        elsewhere.
        """
        with self._lock:
            return sorted(self._latest.values(), key=lambda d: d.seq)

    def get(self, seq: int) -> SmAgentFactsDelta | None:
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
            self._latest = {}

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

            def _persist(self, delta: SmAgentFactsDelta) -> None:
                # INSERT INTO nanda_deltas ...
                pass

            def _load_since(self, seq: int) -> list[SmAgentFactsDelta]:
                # SELECT * FROM nanda_deltas WHERE seq > ...
                pass
    """

    def add(self, action: str, agent: SmAgentFacts) -> SmAgentFactsDelta:
        """Record a delta and persist it."""
        delta = super().add(action, agent)
        self._persist(delta)
        return delta

    def since(self, seq: int) -> list[SmAgentFactsDelta]:
        """Load deltas from persistent storage."""
        # Try persistent storage first
        persisted = self._load_since(seq)
        if persisted:
            return persisted
        # Fall back to in-memory
        return super().since(seq)

    def _persist(self, delta: SmAgentFactsDelta) -> None:
        """Persist a delta to storage. Override in subclass."""
        pass

    def _load_since(self, seq: int) -> list[SmAgentFactsDelta]:
        """Load deltas from storage. Override in subclass."""
        return []
