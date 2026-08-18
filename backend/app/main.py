"""
FastAPI app: a single POST /chat endpoint (one bounded LLM call per
turn — no agent loop) plus /health.

Everything document-specific and persona-specific is loaded once at
startup from config.py / documents/, so this file has no per-user
content hardcoded in it — that's what keeps the project forkable.
"""

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.cache_context import EmptyDocumentCacheError, build_document_cache
from app.config import get_settings
from app.guardrails import (
    InputTooLongError,
    TurnLimitExceededError,
    check_input_length,
    check_turn_limit,
    limiter,
    looks_like_injection_attempt,
)
from app.llm_client import LLMClient, LLMUnavailableError
from app.prompt_builder import build_system_prompt
from app.sessions import build_session_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aissist_cag")

settings = get_settings()

try:
    document_cache = build_document_cache(settings.documents_dir)
except EmptyDocumentCacheError as exc:
    # Fail fast and loud: a fork with no real documents yet should not
    # silently come up and serve an assistant that knows nothing.
    raise SystemExit(f"Startup failed: {exc}") from exc

SYSTEM_PROMPT = build_system_prompt(settings, document_cache)
llm_client = LLMClient(settings)
session_store = build_session_store(settings)

logger.info(
    "Loaded %d document(s) into the CAG context (%d chars): %s",
    len(document_cache.source_files),
    len(document_cache.context_block),
    ", ".join(document_cache.source_files),
)

app = FastAPI(title="AIssist-CAG", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    turn_count: int
    ended: bool = False


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "documents_loaded": len(document_cache.source_files),
        "model": settings.llm_model,
    }


@app.post("/chat", response_model=ChatResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def chat(request: Request, body: ChatRequest):
    try:
        check_input_length(body.message, settings.max_input_chars)
    except InputTooLongError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if looks_like_injection_attempt(body.message):
        logger.warning("Possible prompt-injection attempt in session %s", body.session_id)

    state = session_store.get(body.session_id)

    try:
        check_turn_limit(state, settings.max_turns_per_session)
    except TurnLimitExceededError:
        return ChatResponse(
            session_id=body.session_id,
            reply=(
                "We've covered a lot of ground in this conversation! "
                f"{settings.contact_redirect_message}"
            ),
            turn_count=state.turn_count,
            ended=True,
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *state.history, {"role": "user", "content": body.message}]

    try:
        reply = await llm_client.complete(messages)
    except LLMUnavailableError as exc:
        logger.error("LLM call failed for session %s: %s", body.session_id, exc)
        return ChatResponse(
            session_id=body.session_id,
            reply="Sorry, I'm having trouble responding right now — please try again in a moment.",
            turn_count=state.turn_count,
        )

    state.append_turn(body.message, reply)
    session_store.save(body.session_id, state)

    return ChatResponse(session_id=body.session_id, reply=reply, turn_count=state.turn_count)
