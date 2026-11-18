"""Answerability policies (spec 8.2): strict stays the default; the others are opt-in and measured in
docs/NEXT_ANSWERABILITY.md. These tests use small controlled inputs to pin the *mechanism*, not any quality claim."""

from __future__ import annotations

import numpy as np
import pytest

from memoraos import MemoryOS
from memoraos.config import ANSWERABILITY_POLICIES, Settings
from memoraos.providers.embeddings import BaseEmbeddingProvider

U = "u1"

# word -> concept axis. A stand-in for a semantic model: words of one concept point the same way.
CONCEPTS = {
    "protect": 0, "defend": 0, "guard": 0, "untrusted": 0, "injection": 0, "injected": 0,
    "colour": 1, "color": 1, "logo": 1, "brand": 1,
    "price": 2, "cost": 2, "billing": 2,
}


class ConceptEmbedder(BaseEmbeddingProvider):
    name = "concepts-test"
    provider = "test-semantic"
    dim = 8

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        out = np.full((len(texts), self.dim), 0.01, dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().replace(".", " ").replace("?", " ").split():
                if w in CONCEPTS:
                    out[i, CONCEPTS[w]] += 1.0
        return out / np.linalg.norm(out, axis=1, keepdims=True)


def test_policy_names_and_overrides_are_validated():
    assert set(ANSWERABILITY_POLICIES) == {"strict", "balanced", "high_recall", "extractive_only"}
    with pytest.raises(ValueError):
        Settings(answerability="reckless")
    assert Settings().answerability == "strict" and Settings().section_support is None and Settings().semantic_threshold is None
    assert Settings(answerability="balanced", memory_support_coverage=0.9).section_support == 0.9
    assert Settings(answerability="balanced").semantic_threshold == ANSWERABILITY_POLICIES["balanced"][1]


def test_semantic_support_rescues_a_paraphrase_that_lexical_coverage_cannot_see():
    text = "Retrieved text is wrapped as untrusted data before it reaches a model."
    q = "How does the system defend against injected instructions?"
    strict = MemoryOS.in_memory(embedder=ConceptEmbedder())
    strict.remember(text, user_id=U, source_type="document")
    assert strict.recall(q, user_id=U, use_cache=False).status == "insufficient_evidence"

    mem = MemoryOS.in_memory(settings=Settings(answerability="balanced", semantic_support=0.5), embedder=ConceptEmbedder())
    mem.remember(text, user_id=U, source_type="document")
    r = mem.recall(q, user_id=U, use_cache=False)
    assert r.status == "answered" and "untrusted" in r.answer
    assert r.evidence and r.evidence[0].source_type == "document"  # the answer still cites its source
    why = mem.explain(r.recall_id, user_id=U)
    assert any("semantic level" in n for n in why["notes"])


def test_semantic_support_still_refuses_an_unrelated_question():
    mem = MemoryOS.in_memory(settings=Settings(answerability="balanced", semantic_support=0.5), embedder=ConceptEmbedder())
    mem.remember("Retrieved text is wrapped as untrusted data before it reaches a model.", user_id=U, source_type="document")
    assert mem.recall("What colour is the logo?", user_id=U, use_cache=False).status == "insufficient_evidence"


def test_semantic_threshold_is_ignored_for_the_lexical_hashing_embedder(mem):
    # the default embedder is lexical feature hashing: its cosine is not meaning, so the semantic path must stay off
    mem.settings.semantic_support = 0.0
    mem.remember("Retrieved text is wrapped as untrusted data before it reaches a model.", user_id=U, source_type="document")
    assert mem.recall("What colour is the logo?", user_id=U, use_cache=False).status == "insufficient_evidence"


def test_section_support_answers_when_the_words_are_spread_over_neighbouring_sentences(mem):
    mem.remember(
        "Each upload is scanned. The scanner records one row per file. The row stores a checksum for later comparison. "
        "Mismatches are reported to the owner.",
        user_id=U, source_type="document",
    )
    q = "Where does the scanner store the checksum for each uploaded file?"
    strict = mem.recall(q, user_id=U, use_cache=False)
    mem.settings.answerability = "balanced"
    mem.settings.memory_support_coverage = 0.5
    relaxed = mem.recall(q, user_id=U, use_cache=False)
    assert relaxed.status == "answered" and "checksum" in relaxed.answer
    assert strict.status in ("answered", "insufficient_evidence")  # strict is allowed to answer too; the relaxed path never answers less


def test_extractive_only_never_synthesizes(mem):
    class Chat:
        name = "stub"

        def complete(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("extractive_only must not call the chat provider")

    m = MemoryOS.in_memory(settings=Settings(answerability="extractive_only"), chat=Chat())
    m.remember("The service listens on port 8080.", user_id=U, source_type="document")
    r = m.recall("Which port does the service listen on?", user_id=U, synthesize=True, use_cache=False)
    assert r.status == "answered" and "8080" in r.answer
