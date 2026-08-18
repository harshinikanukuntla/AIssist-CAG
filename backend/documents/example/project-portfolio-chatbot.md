# Project: Portfolio CAG Chatbot (Example)

> Placeholder example content — see the note in `resume.md` in this same
> folder. This shows the level of detail worth writing for a project
> write-up: what it does, why it was built, what was hard about it.

## What it is

A chatbot embedded on my portfolio site that answers visitor questions
about my resume and past projects, built on a cache-augmented generation
(CAG) architecture rather than a typical RAG pipeline.

## Why CAG instead of RAG

My document set (resume + project write-ups) is small and static, so
retrieval-per-query wasn't necessary — it just added a vector database and
an extra failure mode (the retriever picking the wrong chunk) without
benefit. Loading the full document set as a fixed context once, and reusing
it as a stable prefix for every request, was simpler and more predictable.

## What was hard

Making sure the assistant stayed on-topic without sounding robotic when
asked something unrelated, and building guardrails (turn caps, rate limits,
input length limits) so a single conversational endpoint couldn't be turned
into a runaway cost sink.

## Stack

FastAPI backend, NVIDIA NIM (hosted, OpenAI-compatible) for inference, a
vanilla JS embeddable widget, deployed via Docker Compose behind Caddy on a
small VPS.
