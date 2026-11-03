"""Deterministic entity extraction from document chunks.

The extractor intentionally targets high-signal entities instead of treating
every noun as an entity. Its patterns and vocabulary are isolated so a future
NER model can implement the same ``extract_entities`` contract.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    entity_type: str
    mention_count: int = 1


_TECHNOLOGIES = {
    "bm25", "docker", "fastapi", "kafka", "kubernetes", "langchain",
    "postgresql", "python", "pytorch", "redis", "sqlalchemy", "tensorflow",
    "pgvector", "elasticsearch", "openai", "aws", "s3",
}
_CONCEPT_TERMS = {
    "authentication", "authorization", "embedding", "hybrid search",
    "semantic search", "entity extraction", "knowledge graph", "retrieval",
    "reranking", "chunking", "vector database", "access control",
    "semaphore", "semaphores", "deadlock", "deadlock prevention",
    "operating system", "memory management", "disk scheduling",
    "multithreading", "parallel processing", "database concepts",
    "normalization", "computer network", "system programming",
    "machine learning", "deep learning", "data science",
    "continuous learning", "learning ability",
}

_TECHNICAL_ACRONYMS = {
    "AWS", "BM25", "CISC", "CNN", "CSE", "ER", "J2EE", "J2SE",
    "LSTM", "MEAN", "MIPS", "NLP", "PC", "PGVECTOR", "RISC", "RNN",
    "S3",
}

_GENERIC_HEADINGS = {
    "accountabilities", "area", "behaviors", "key", "role", "requirement",
    "requirements", "title", "what", "pick", "any", "description",
    "objective", "objectives", "instructions", "criteria", "details",
}
_TABLE_ARTIFACTS = {
    "area what", "pick any", "role title", "key accountabilities",
    "role requirement", "what pick", "pick any one",
}

_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9_+-]{1,}\b")
_PROPER_TERM_RE = re.compile(r"\b(?:[A-Z][a-z0-9]+\s+){1,3}[A-Z][a-z0-9]+\b")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*")


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _is_usable_proper_name(name: str) -> bool:
    normalized = _normalise(name)
    if normalized in _TABLE_ARTIFACTS:
        return False
    words = normalized.split()
    return len(words) >= 2 and not any(word in _GENERIC_HEADINGS for word in words)


def extract_entities(text: str) -> list[ExtractedEntity]:
    """Extract high-signal technical, organizational, and concept entities."""

    if not text or not text.strip():
        return []

    counts: Counter[tuple[str, str]] = Counter()

    lowered = text.lower()
    for term in sorted(_CONCEPT_TERMS, key=len, reverse=True):
        count = len(re.findall(rf"(?<!\w){re.escape(term)}(?!\w)", lowered))
        if count:
            counts[(term, "concept")] += count

    for word in _WORD_RE.findall(text):
        normalised = _normalise(word)
        if normalised in _TECHNOLOGIES:
            counts[(word, "technology")] += 1

    # Acronyms are useful technical or organizational signals, unlike ordinary nouns.
    for acronym in _ACRONYM_RE.findall(text):
        if acronym.upper() in _TECHNICAL_ACRONYMS:
            counts[(acronym, "technical_term")] += 1

    # Multi-word capitalized names provide a conservative organization/person signal.
    for proper_name in _PROPER_TERM_RE.findall(text):
        normalized = _normalise(proper_name)
        if (
            normalized not in {_normalise(k) for k in _CONCEPT_TERMS}
            and _is_usable_proper_name(proper_name)
        ):
            counts[(proper_name, "organization")] += 1

    return [
        ExtractedEntity(name=name, entity_type=kind, mention_count=count)
        for (name, kind), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][0]))
    ]
