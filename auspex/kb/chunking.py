"""Deterministic paragraph-first chunking — S6.

The chunk is the retrieval unit: embedded as one vector, matched by BM25 as one
body of text. Sizing constraint: all-MiniLM-L6-v2 truncates at 256 wordpieces
(~1000 chars of English) — anything past that is invisible to the neural leg,
so chunks aim under it. BM25 still sees the full chunk text either way.

Strategy (no tokenizer dependency, pure function):
paragraphs pack greedily into chunks up to `max_chars`; a paragraph that alone
exceeds `max_chars` splits on sentence boundaries; a sentence that alone
exceeds `max_chars` hard-splits. No overlap — the seed corpus is summaries and
short records; overlap buys nothing there and complicates re-ingest identity.
Revisit when S7 feeds bring long documents (IDEAS.md).
"""

import re

from auspex.kb.types import KBChunk, KBDoc

MAX_CHUNK_CHARS = 1000

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_oversized(text: str, max_chars: int) -> list[str]:
    """Sentence-pack one oversized paragraph; hard-split monster sentences."""
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        while len(sentence) > max_chars:  # degenerate: one huge sentence
            head, sentence = sentence[:max_chars], sentence[max_chars:]
            if current:
                parts.append(current)
                current = ""
            parts.append(head)
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            parts.append(current)
            current = sentence
    if current:
        parts.append(current)
    return parts


def chunk_text(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text into chunk strings ≤ max_chars, paragraph-first."""
    pieces: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT_RE.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            pieces.extend(_split_oversized(paragraph, max_chars))
        else:
            pieces.append(paragraph)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def chunk_doc(doc: KBDoc, *, max_chars: int = MAX_CHUNK_CHARS) -> list[KBChunk]:
    return [
        KBChunk(doc=doc, chunk_index=i, text=text)
        for i, text in enumerate(chunk_text(doc.content, max_chars=max_chars))
    ]
