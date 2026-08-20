# Chatbot API Contract

This documents the HTTP contract exposed by the AIssist-CAG backend, for
whoever is wiring the widget into a portfolio site. It's generated from the
actual implementation in `backend/app/main.py` and `widget/widget.js` — if
those change, update this file to match.

## Base URL

Configurable per deployment. Local dev default: `http://localhost:8000`.
No path prefix — endpoints are mounted at the root (`/chat`, `/health`).

## CORS

The backend only allows origins listed in `ALLOWED_ORIGINS` (comma-separated
env var, see `backend/.env.example`). The portfolio site's origin(s) — e.g.
`https://yourportfolio.com` — must be added there before the widget will be
able to call the API from the browser. Allowed methods: `POST`, `GET`.
Allowed headers: `Content-Type` only.

## POST /chat

Send one user turn, get back one assistant reply. Stateless request/response
— conversation history is kept server-side, keyed by `session_id`.

### Request

```json
{
  "session_id": "uuid-string (optional)",
  "message": "string (required, non-empty)"
}
```

- `session_id`: if omitted, the server generates one — but the widget
  should always send a stable id (see below) so history persists across
  messages in the same conversation. If sent explicitly, it must be
  non-empty (after trimming whitespace) and at most 128 characters —
  it's used directly as a store key server-side, so it's validated like
  any other untrusted input.
- `message`: max length is server-configured (`MAX_INPUT_CHARS`, default
  2000 chars). Empty/whitespace-only messages are rejected.

### Response — 200 OK

```json
{
  "session_id": "uuid-string",
  "reply": "string",
  "turn_count": 3,
  "ended": false
}
```

- `ended: true` means the session hit its turn cap (`MAX_TURNS_PER_SESSION`,
  default 20) — `reply` will contain a redirect-to-contact-form message.
  Treat this as a normal reply, not an error; the caller may keep sending
  messages but should expect the same canned response.

### Error responses

| Status | When | Body |
|---|---|---|
| 400 | Empty message, or message exceeds max length | `{"detail": "..."}` |
| 400 | `session_id` empty/whitespace-only, or exceeds 128 characters | `{"detail": "..."}` |
| 429 | Rate limit exceeded (`RATE_LIMIT_PER_MINUTE`, default 20/min, per client IP) | standard slowapi error body |
| 5xx / network failure | LLM provider unavailable | Backend catches this itself and returns a 200 with a friendly fallback `reply` — the widget only needs to handle true network failures (fetch throwing) and non-2xx statuses |

The widget's job on non-`res.ok` is to show `data.detail` if present, else a
generic fallback message.

## GET /health

```json
{
  "status": "ok",
  "documents_loaded": 2,
  "model": "meta/llama-3.1-8b-instruct"
}
```

Useful for a pre-flight check or status indicator; not required for basic
chat to work.

## Session handling (portfolio-side responsibilities)

- Generate a session id once per browser (e.g. `crypto.randomUUID()`),
  persist it in `localStorage`, and send the same id on every `/chat`
  call so the backend's in-memory/Redis session store can accumulate
  turn history.
- Sessions expire server-side after `SESSION_TTL_SECONDS` (default 3600s)
  — no client action needed, a new id will just start a fresh session.

## What the portfolio side must NOT do

- Don't try to stream tokens — `/chat` is a single blocking call that
  returns the full reply, not SSE/websocket.
- Don't send any field besides `session_id` and `message` — extra fields
  are ignored, not validated against, so typos won't be caught.
- Don't hardcode the backend URL — make it configurable (env var / data
  attribute), since dev/staging/prod will point at different hosts.

## Reference implementation

`widget/widget.js` in this repo is a working, framework-agnostic reference
client against this exact contract (vanilla JS, single `<script>` embed,
handles pending/error states). The portfolio integration can either drop
that script in directly or reimplement the same request/response handling
in the portfolio's own stack (e.g. a React component) — either is fine as
long as the contract above is respected.
