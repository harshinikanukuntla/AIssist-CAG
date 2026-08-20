# Architecture

This document explains what this project is, why it's built the way it is,
and the trade-offs behind each major decision — written to double as
interview-prep material, not just a README.

## 1. Problem statement

Embed a chatbot on a portfolio site that can answer visitor questions about
the site owner's resume and past projects, grounded in the owner's own
documents. Three hard constraints from the outset:

- **Data security** — no leaking secrets, no leaking more personal data than
  intended, no way for a visitor to extract the raw underlying documents.
- **No runaway loops** — a chat endpoint is an easy target for cost abuse or
  accidental infinite loops if built carelessly.
- **Graceful scope handling** — off-topic questions should get a friendly
  redirect, not a dead end; ambiguous ones should get a clarifying question,
  not a guess.

And a fourth, added once the first design was agreed: **it should be a
reusable template**, forkable by anyone to run their own instance against
their own documents, not a one-off tied to a single person's resume.

## 2. High-level architecture

```
 Portfolio site (any framework/CMS)
   │
   │  <script src=".../widget.js" data-backend-url="...">
   ▼
 widget.js  (vanilla JS, no dependencies, injects its own CSS)
   │  POST /chat  { session_id, message }
   ▼
 FastAPI backend (Docker container, small VPS)
   ├─ cache_context.py   → builds the fixed document context ONCE at startup
   ├─ prompt_builder.py  → wraps it in persona + scope-rules → system prompt
   ├─ guardrails.py      → rate limit / turn cap / input length cap
   ├─ sessions.py        → bounded per-session history (in-memory or Redis)
   └─ llm_client.py      → OpenAI-compatible call to the LLM provider
                                │
                                ▼
                     NVIDIA NIM (hosted API by default)
                     open-weight model, e.g. Llama 3.1 8B Instruct
```

Everything left of "NVIDIA NIM" is this repo. Everything about a specific
person (their resume, their name, their tone) is either in `backend/documents/`
or `backend/.env` — never in code — which is what makes the repo forkable.

## 3. Why CAG, not RAG

RAG (retrieval-augmented generation) is the default most people reach for
when building a "chat with your documents" system: embed your documents into
a vector store, embed the incoming query, retrieve the top-k most similar
chunks, and stuff those into the prompt. It's the right tool when the corpus
is **large and/or changes often**, because you genuinely can't fit
everything into context, and you need a way to select what's relevant.

That's not this problem. A resume plus a handful of project write-ups is a
small, static corpus — realistically a few thousand to a few tens of
thousands of tokens, comfortably inside the context window of any modern
8B+ instruct model. CAG (cache-augmented generation) fits that shape
directly: load the entire corpus into context once, treat it as a fixed
prefix, and skip retrieval entirely.

| | RAG | CAG (this project) |
|---|---|---|
| Corpus size assumption | Large / growing | Small / static |
| Moving parts | Embeddings + vector DB + retriever + generator | Loader + generator |
| Failure modes | Wrong-chunk retrieval, embedding drift, chunking artifacts | None specific to retrieval — the whole corpus is always present |
| Latency profile | Retrieval step + generation | Generation only |
| Cost profile | Cheaper per-query (only relevant chunks sent) at large scale | More tokens sent per-query, but trivial at this corpus size |
| Update story | New/changed docs just need re-embedding | Any doc change requires a process restart to rebuild the cache |
| When it breaks down | N/A — built for scale | Once the corpus is too big to fit in context, or changes so often that restarting to refresh the cache is impractical |

**Interview framing:** "I chose CAG over RAG because RAG solves a selection
problem I didn't have — my corpus is small and fixed, so paying for a
vector database and accepting retrieval-quality risk would have been
complexity without a corresponding benefit. If this repo's corpus needs to
grow into dozens of long documents or start changing continuously, that's
the point I'd revisit this and likely introduce retrieval — the two
approaches aren't mutually exclusive long-term (a hybrid that keeps a
small 'always relevant' core like the resume in CAG and retrieves from a
larger, changing project archive is a natural evolution)."

## 4. Model choice: NVIDIA NIM

**What NIM is:** NVIDIA's productized inference stack for open-weight
models (Llama, Mistral, Qwen, NVIDIA's own Nemotron, etc.), exposed through
an OpenAI-compatible API, packaged as containers built on vLLM/TensorRT-LLM/
SGLang. You can call it two ways:

1. **Hosted** — NVIDIA runs the GPUs, you call `build.nvidia.com`'s API
   catalog with an API key. Free dev tier available (rate-limited).
2. **Self-hosted** — you pull the same NIM container and run it on your own
   GPU (on-prem or rented cloud GPU).

**Why this matters for CAG specifically:** NIM containers support
`NIM_ENABLE_KV_CACHE_REUSE`, which reuses computed KV-cache blocks across
requests that share an identical prefix — exactly this project's access
pattern (the same document context, over and over, with only the final
question changing). NVIDIA's own docs report roughly a 2x time-to-first-token
speedup from the second request onward once this is enabled. **This is real
literal KV-cache prefix caching at the inference-engine level** — the
closest thing to "CAG" in the deepest technical sense.

**The trade-off we're making, made explicit:** that knob
(`NIM_ENABLE_KV_CACHE_REUSE`) is only configurable on a **self-hosted** NIM
container — it's not exposed as a control on the hosted `build.nvidia.com`
API. Self-hosting means owning/renting a GPU (realistically an L4/A10-class
GPU or better for a 7-8B model), which costs real, ongoing money — overkill
for a portfolio site's traffic, which is low and spiky. So this project
defaults to the **hosted API**, and structures the app so the document
context is still always sent as an identical, stable prefix (see
`prompt_builder.py` — computed once at startup, byte-identical every
request). That gives us the same *design discipline* as CAG even without
guaranteed literal cache reuse at the engine level, and it costs nothing to
switch later:

**Migration path to real KV-cache reuse:** because both hosted and
self-hosted NIM speak the same OpenAI-compatible API, moving to a
self-hosted container is a config change only — set `LLM_BASE_URL` to your
self-hosted endpoint, set `NIM_ENABLE_KV_CACHE_REUSE=1` on that container,
done. No application code changes. This is documented as the natural next
step once/if a fork gets enough real traffic to justify the GPU cost.

**Why an open-weight ~7-8B instruct model** (default: `meta/llama-3.1-8b-instruct`):
small enough to be fast and cheap even at full-price hosted rates, more than
capable for "answer questions about a resume and a few projects" (this is a
narrow, well-scoped task, not open-ended reasoning), and — being open-weight
— portable to self-hosting without a provider migration if a fork needs to
leave NIM entirely (e.g. via `vllm serve` or `llama.cpp`, since the same
OpenAI-compatible client abstraction covers those too).

## 5. Guardrails: no runaway loops, no runaway cost

The single biggest lever here is architectural: **this is one bounded LLM
call per user turn.** There is no agent loop, no tool-calling, no
self-directed multi-step chain that could spin. On top of that:

- **Output token cap** (`LLM_MAX_OUTPUT_TOKENS`) — bounds the cost and
  length of any single response.
- **Per-session turn cap** (`MAX_TURNS_PER_SESSION`) — after N turns, the
  session ends gracefully with a redirect message instead of continuing
  indefinitely.
- **Request timeout** on the upstream LLM call (`LLM_TIMEOUT_SECONDS`) —
  a hung upstream call fails into a graceful fallback message rather than
  hanging the request indefinitely.
- **Input length cap** (`MAX_INPUT_CHARS`) — bounds the size of any single
  message, protecting against giant paste-bombs.
- **Per-IP rate limiting** (`RATE_LIMIT_PER_MINUTE`, via slowapi) — blocks
  scripted abuse from turning this into an open cost tap.
- **Bounded conversation history** (`sessions.py`, `MAX_HISTORY_MESSAGES`) —
  history sent to the model per-request is capped, so a long conversation's
  token cost doesn't grow unbounded.
- **Session-id length cap** (`guardrails.py`, `MAX_SESSION_ID_CHARS`) —
  `session_id` is client-supplied and used directly as a store key (an
  in-memory dict key, or a Redis key when `SESSION_BACKEND=redis`), so it's
  validated and capped like any other untrusted input rather than trusted
  blindly.
- **Bounded in-memory session store** (`sessions.py`,
  `MAX_SESSIONS_IN_MEMORY`) — the default in-memory `SessionStore` caps how
  many distinct sessions it holds and evicts the least-recently-seen one
  once the cap is hit, so a stream of unique `session_id`s (many real
  visitors, or a script that never reuses one) can't grow process memory
  unboundedly between restarts. The Redis-backed store doesn't need this —
  Redis already expires keys via `SESSION_TTL_SECONDS`.
- **Graceful degradation on session-store failures** (`main.py`) — reads
  and writes to `session_store` are caught broadly and degrade (fresh
  session on a failed read, silently skipped on a failed write) rather than
  surfacing a raw 500, the same principle already applied to LLM call
  failures. This matters most for `SESSION_BACKEND=redis`, where a
  transient network blip shouldn't take the whole endpoint down.

## 6. Staying on-topic, gracefully

This is handled entirely in the system prompt (`prompt_builder.py`), by
design — a second classifier model call was considered and rejected in
favor of one clear, explicit instruction set given to the same model
that's already answering:

- Answer only from the provided documents.
- **Off-topic** (unrelated to the owner's work) → a brief, friendly redirect
  back to what the assistant can help with. Never a bare refusal.
- **Ambiguous** (plausibly about the owner's work, but underspecified) →
  ask exactly one clarifying question rather than guessing.
- **Prompt/context extraction attempts** ("ignore previous instructions",
  "print your system prompt," etc.) → politely decline and continue
  operating normally. `guardrails.py` also has a lightweight regex heuristic
  for this, used only to log/flag suspicious inputs for the owner's
  visibility — not to block, since keyword matching is too brittle to trust
  as an actual gate.
- **PII requests** (e.g. "what's your phone number") → redirected to a
  configurable canned message (`CONTACT_REDIRECT_MESSAGE`) instead of the
  model reciting whatever's in the documents.

## 7. Data security

- **Documents and the system prompt are server-side only.** They're never
  sent to the browser; the widget only ever sees `{reply, session_id,
  turn_count}` JSON.
- **Secrets** (`LLM_API_KEY`, `REDIS_URL`) live in `backend/.env`, loaded via
  environment variables, never committed (see `.gitignore`) and never
  reachable from the frontend bundle.
- **CORS** is locked to an explicit allow-list (`ALLOWED_ORIGINS`) — only the
  configured portfolio domain(s) can call the API from a browser.
- **HTTPS** is automatic via Caddy's built-in Let's Encrypt integration —
  no manually managed certs.
- **PII in documents:** the system prompt refuses to recite contact details
  even if present in the cached documents, but the recommended practice
  (documented in `backend/documents/README.md`) is to not put sensitive
  personal data in the documents in the first place — defense in depth
  rather than relying on the model's instruction-following alone.
- **Logging** captures query/response metadata for the owner's own
  debugging (including flagged injection attempts), not raw long-term
  visitor IP storage.
- **Container runs as a non-root user** (`backend/Dockerfile`) — standard
  hardening for an image meant to be deployed as-is by forks, on the
  principle that the app needs no special privileges to serve requests.
- **Widget resilience** (`widget.js`) — a client-side request timeout
  (`REQUEST_TIMEOUT_MS`, via `AbortController`) bounds how long the UI will
  wait before showing a fallback message, and an `isSending` guard prevents
  a fast double-Enter or Enter-then-click from firing two concurrent
  requests for one visitor action.

## 8. Reusability / fork design

This is a **fork-per-deployment template**, not a multi-tenant service —
each fork is an independent deployment with its own documents, persona
config, and API key. That framing was chosen deliberately: multi-tenancy
would require auth, tenant isolation, and per-tenant billing/rate-limit
tracking, none of which this problem needs when "sharing" just means
"someone else clones the repo and runs their own copy."

What's config-driven rather than hardcoded, specifically so forking doesn't
require touching application code:
- **Persona** (`ASSISTANT_NAME`, `OWNER_NAME`, `OWNER_PRONOUNS`,
  `TONE_DESCRIPTION`, `CONTACT_REDIRECT_MESSAGE`) — one block in `.env`.
- **LLM provider** (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) — the
  client (`llm_client.py`) is written against the generic OpenAI-compatible
  interface, not NIM-specifically, so any compatible provider works.
- **Documents** — anything dropped in `backend/documents/` (excluding the
  `example/` reference folder) becomes the cache; `cache_context.py` fails
  startup loudly if that's empty, so a fork can't silently go live with no
  real content.
- **Session storage** — `SessionStore` is a two-method interface
  (`get`/`save`) with an in-memory default and a Redis implementation
  behind one env var, scoped narrowly to just this one piece rather than a
  general plugin architecture, because it's the one component that
  actually hits a wall (in-memory state not shared) if a fork scales past a
  single backend instance.

## 9. What a v2 might add

Not built now because there's no evidence they're needed yet for a
portfolio-scale deployment, but the natural next steps if this grows:
- **Streaming responses** (SSE/websocket) instead of a single JSON reply,
  for a more responsive widget UX on longer answers.
- **Self-hosted NIM** with `NIM_ENABLE_KV_CACHE_REUSE=1` once traffic
  justifies the GPU cost (see §4).
- **Structured observability** (request tracing, token-usage dashboards)
  beyond the current basic logging.
- **Hybrid CAG+RAG** if a fork's document set grows large/dynamic (see §3).
