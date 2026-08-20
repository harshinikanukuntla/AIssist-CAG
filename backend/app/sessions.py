"""
Bounded, per-session conversation history.

Default backend is an in-memory dict — correct for the common case of a
single backend instance on one small VPS. A fork that scales out to
multiple instances can set SESSION_BACKEND=redis (and REDIS_URL) to
share session state across them without any other code change; the
`redis` package is only imported when that path is actually used.
"""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import Settings

MAX_HISTORY_MESSAGES = 12  # ~6 user/assistant turns kept as context

# Caps the in-memory store's dict size so a stream of unique session_ids
# (many real visitors, or a script that never reuses one) can't grow
# process memory unboundedly between restarts. Not exposed as an env var —
# like MAX_HISTORY_MESSAGES, it's an internal implementation limit a fork
# would never need to tune, not a per-deployment persona/provider setting.
MAX_SESSIONS_IN_MEMORY = 5000


@dataclass
class SessionState:
    turn_count: int = 0
    history: list[dict[str, str]] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)

    def append_turn(self, user_message: str, assistant_message: str) -> None:
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": assistant_message})
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.turn_count += 1
        self.last_seen = time.time()

    def to_json(self) -> str:
        return json.dumps(
            {"turn_count": self.turn_count, "history": self.history, "last_seen": self.last_seen}
        )

    @classmethod
    def from_json(cls, raw: str) -> "SessionState":
        data = json.loads(raw)
        return cls(turn_count=data["turn_count"], history=data["history"], last_seen=data["last_seen"])


class SessionStore(ABC):
    @abstractmethod
    def get(self, session_id: str) -> SessionState: ...

    @abstractmethod
    def save(self, session_id: str, state: SessionState) -> None: ...


class InMemorySessionStore(SessionStore):
    def __init__(self, ttl_seconds: int):
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None or (time.time() - state.last_seen) > self._ttl_seconds:
            return SessionState()
        return state

    def save(self, session_id: str, state: SessionState) -> None:
        self._sessions[session_id] = state
        if len(self._sessions) > MAX_SESSIONS_IN_MEMORY:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        # One eviction per save that pushes over the cap is enough to stay
        # at the limit, since save() is called at most once per turn. A
        # plain O(n) scan is fine at this scale (thousands of sessions) and
        # avoids pulling in a full LRU-cache dependency for what's meant to
        # be a lightweight single-VPS store in the first place. Because it
        # evicts by oldest last_seen, expired-but-not-yet-overwritten
        # sessions are always the first to go.
        oldest_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_seen)
        del self._sessions[oldest_id]


class RedisSessionStore(SessionStore):
    def __init__(self, redis_url: str, ttl_seconds: int):
        import redis  # imported lazily so it's only required when actually used

        self._ttl_seconds = ttl_seconds
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = "aissist-cag:session:"

    def get(self, session_id: str) -> SessionState:
        raw = self._redis.get(self._key_prefix + session_id)
        if raw is None:
            return SessionState()
        return SessionState.from_json(raw)

    def save(self, session_id: str, state: SessionState) -> None:
        self._redis.setex(self._key_prefix + session_id, self._ttl_seconds, state.to_json())


def build_session_store(settings: Settings) -> SessionStore:
    if settings.session_backend == "redis":
        if not settings.redis_url:
            raise ValueError("SESSION_BACKEND=redis requires REDIS_URL to be set.")
        return RedisSessionStore(settings.redis_url, settings.session_ttl_seconds)
    return InMemorySessionStore(settings.session_ttl_seconds)
