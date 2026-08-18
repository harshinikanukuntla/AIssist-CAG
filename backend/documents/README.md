# Documents

This folder is the entire "knowledge base" the assistant can draw on — it's
the CAG cache. At startup, the backend reads every `.md`/`.txt` file placed
**directly in this folder** (not inside `example/`), concatenates them with
clear delimiters, and uses that as a fixed system-prompt prefix for every
request.

## Adding your own content

1. Delete or ignore `example/` — it's a reference template only and is
   never loaded into the cache.
2. Add your own files directly here, e.g.:
   - `resume.md` — your background, skills, experience
   - `project-<name>.md` — one file per project/feature you want it to be
     able to talk about in depth
3. Restart the backend. It reads documents once at startup, not per-request
   (that's the point — see `docs/ARCHITECTURE.md` for why). If you edit a
   document, you need to restart the process to pick up the change.

If this folder has no real files in it (fresh clone, only `example/` and
this README present), the backend will refuse to start with a clear error
telling you to add content first — this is intentional, so a fork can't
accidentally go live with an assistant that knows nothing about you.

## Format tips

- Plain Markdown or plain text, no special frontmatter required.
- Write documents the way you'd want them summarized to a stranger, not as
  raw bullet-point notes — the model quotes/paraphrases what's here, so
  clearer prose makes for clearer answers.
- Don't include anything you don't want an anonymous website visitor able
  to ask about. Personal contact details (phone, home address) are
  filtered by the system prompt's rules, but it's still safest not to put
  sensitive data in here in the first place — see the "Data Security"
  section of `docs/ARCHITECTURE.md`.
- Keep it to a small, curated set of documents. This is a CAG design, not
  RAG — everything here is loaded in full on every request, so this folder
  should stay small (a resume + a handful of project write-ups), not grow
  into a large or frequently-changing corpus.
