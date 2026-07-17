"""Chunking — pure, deterministic (S6). Sizing rationale: all-MiniLM-L6-v2
truncates ~256 wordpieces (~1000 chars), so chunks must stay under MAX_CHUNK_CHARS."""

from auspex.kb.chunking import MAX_CHUNK_CHARS, chunk_doc, chunk_text
from auspex.kb.seed import load_seed_docs
from auspex.kb.types import KBDoc


def doc(content: str) -> KBDoc:
    return KBDoc(
        doc_id="T0000",
        title="Test",
        content=content,
        doc_type="technique",
        source="test",
        source_ref="",
        ids=("T0000",),
    )


def test_short_text_is_one_chunk():
    assert chunk_text("A short paragraph.") == ["A short paragraph."]


def test_small_paragraphs_pack_into_one_chunk():
    text = "First paragraph.\n\nSecond paragraph."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert "First paragraph." in chunks[0] and "Second paragraph." in chunks[0]


def test_paragraphs_split_when_packing_would_overflow():
    p1 = "A" * 600
    p2 = "B" * 600
    chunks = chunk_text(f"{p1}\n\n{p2}")
    assert chunks == [p1, p2]  # 1203 chars > max ⇒ two chunks, intact paragraphs


def test_oversized_paragraph_splits_on_sentence_boundaries():
    sentences = [f"Sentence number {i} carries some analytic content." for i in range(40)]
    chunks = chunk_text(" ".join(sentences))
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHUNK_CHARS for c in chunks)
    # No sentence is lost or torn: rejoining reproduces every sentence
    rejoined = " ".join(chunks)
    assert all(s in rejoined for s in sentences)


def test_monster_sentence_hard_splits():
    chunks = chunk_text("x" * 2500)
    assert all(len(c) <= MAX_CHUNK_CHARS for c in chunks)
    assert sum(len(c) for c in chunks) == 2500


def test_empty_and_whitespace_yield_nothing():
    assert chunk_text("") == []
    assert chunk_text("  \n\n  ") == []


def test_chunk_ids_are_deterministic_and_ordered():
    d = doc("First paragraph.\n\n" + "B" * 999)
    chunks = chunk_doc(d)
    assert [c.chunk_id for c in chunks] == ["T0000#0", "T0000#1"]
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert chunk_doc(d) == chunks  # same input ⇒ same chunks (upsert identity)


def test_all_seed_docs_chunk_within_limits():
    for d in load_seed_docs():
        chunks = chunk_doc(d)
        assert chunks, f"{d.doc_id} produced no chunks"
        assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
