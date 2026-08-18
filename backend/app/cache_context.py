"""
Builds the CAG "cache": a single fixed context block assembled once at
process startup from every document in documents/, and reused as a
byte-identical prefix on every request.

This is the core of the "cache-augmented" design — instead of retrieving
fragments per-query (RAG), the whole small, static corpus is loaded up
front. There's no embedding step, no vector store, and no retrieval
step to get wrong.
"""

from dataclasses import dataclass
from pathlib import Path

DOC_EXTENSIONS = {".md", ".txt"}
EXCLUDED_NAMES = {"readme.md"}
EXCLUDED_DIRS = {"example"}


class EmptyDocumentCacheError(RuntimeError):
    """Raised when documents_dir has no real content to cache — a fork
    that hasn't added its own documents yet should fail loudly at
    startup rather than silently serving an assistant with no knowledge."""


@dataclass(frozen=True)
class DocumentCache:
    context_block: str
    source_files: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.source_files


def _iter_document_paths(documents_dir: Path):
    for path in sorted(documents_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in DOC_EXTENSIONS:
            continue
        if path.name.lower() in EXCLUDED_NAMES:
            continue
        if EXCLUDED_DIRS & {p.name.lower() for p in path.relative_to(documents_dir).parents}:
            continue
        yield path


def build_document_cache(documents_dir: str) -> DocumentCache:
    root = Path(documents_dir)
    if not root.exists():
        raise EmptyDocumentCacheError(
            f"Documents directory '{documents_dir}' does not exist. "
            "Create it and add your own .md/.txt files — see documents/README.md."
        )

    paths = list(_iter_document_paths(root))
    if not paths:
        raise EmptyDocumentCacheError(
            f"No documents found directly in '{documents_dir}'. "
            "This usually means a fresh fork hasn't added real content yet. "
            "See documents/README.md and documents/example/ for the expected "
            "format, then add your own .md/.txt files directly under "
            f"'{documents_dir}' (not inside the example/ folder)."
        )

    sections = []
    for path in paths:
        title = path.relative_to(root).as_posix()
        body = path.read_text(encoding="utf-8").strip()
        sections.append(f"### Document: {title}\n\n{body}")

    context_block = "\n\n---\n\n".join(sections)
    return DocumentCache(
        context_block=context_block,
        source_files=tuple(p.relative_to(root).as_posix() for p in paths),
    )
