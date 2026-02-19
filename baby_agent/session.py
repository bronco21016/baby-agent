"""In-memory session store with TTL expiry."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .config import settings

log = logging.getLogger(__name__)


@dataclass
class Session:
    session_id: str
    history: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    last_active: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_active = time.monotonic()

    def is_expired(self) -> bool:
        return (time.monotonic() - self.last_active) > settings.session_ttl_seconds


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> Session:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.is_expired():
                if session is not None:
                    log.info("Session %s expired; starting fresh.", session_id)
                session = Session(session_id=session_id)
                self._sessions[session_id] = session
            return session

    async def save(self, session: Session) -> None:
        async with self._lock:
            session.touch()
            self._sessions[session.session_id] = session

    async def active_count(self) -> int:
        async with self._lock:
            return sum(1 for s in self._sessions.values() if not s.is_expired())

    async def evict_expired(self) -> int:
        async with self._lock:
            expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)


# Module-level singleton
store = SessionStore()


async def session_cleanup_task() -> None:
    """Background coroutine: evict expired sessions every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        evicted = await store.evict_expired()
        if evicted:
            log.info("Evicted %d expired session(s).", evicted)
