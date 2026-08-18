"""
Guardrails that keep this a single, bounded LLM call per turn — no
agent loop, no runaway cost, no unbounded sessions.

Rate limiting is IP-based via slowapi (protects against scripted abuse
driving up LLM API cost). Turn caps and input-length caps are enforced
per session. `looks_like_injection_attempt` is a soft heuristic used
only for logging/telemetry — the actual defense against prompt/context
extraction lives in the system prompt itself (see main.py), since
keyword-matching alone is too brittle to safely block on.
"""

import re

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.sessions import SessionState

limiter = Limiter(key_func=get_remote_address)


class TurnLimitExceededError(Exception):
    pass


class InputTooLongError(Exception):
    pass


_INJECTION_PATTERNS = [
    re.compile(r"ignore (all|any|previous|prior|the above)?\s*instructions", re.I),
    re.compile(r"(reveal|print|repeat|show).{0,20}(system prompt|instructions|prompt)", re.I),
    re.compile(r"you are now", re.I),
    re.compile(r"disregard (your|the) (rules|guidelines|instructions)", re.I),
]


def looks_like_injection_attempt(message: str) -> bool:
    return any(p.search(message) for p in _INJECTION_PATTERNS)


def check_input_length(message: str, max_chars: int) -> None:
    if len(message) > max_chars:
        raise InputTooLongError(f"Message exceeds the {max_chars}-character limit.")


def check_turn_limit(state: SessionState, max_turns: int) -> None:
    if state.turn_count >= max_turns:
        raise TurnLimitExceededError(f"Session exceeded the {max_turns}-turn limit.")
