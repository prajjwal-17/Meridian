import math
import re
from collections import Counter
from threading import Lock

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.permissions import PermissionContext, authorized_chunk_ids

_TOKEN_RE = re.compile(r"\b[a-zA-Z0-9]+\b")

# Per-chunk token statistics, keyed by chunk id. The entry is rebuilt when the
# chunk text changes, so re-processing a document can never serve stale terms.
_term_cache: dict[int, tuple[int, Counter, int]] = {}
_term_cache_lock = Lock()


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _chunk_terms(chunk_id: int, text: str) -> tuple[Counter, int]:
    fingerprint = hash(text)
    cached = _term_cache.get(chunk_id)
    if cached is not None and cached[0] == fingerprint:
        return cached[1], cached[2]
    tokens = tokenize(text)
    entry = (fingerprint, Counter(tokens), len(tokens))
    with _term_cache_lock:
        _term_cache[chunk_id] = entry
    return entry[1], entry[2]


def bm25_search(
    db: Session,
    query: str,
    top_k: int = 5,
    k1: float = 1.5,
    b: float = 0.75,
    permission_context: PermissionContext | None = None,
    allowed_ids: set[int] | None = None,
) -> list[dict]:
    """Okapi BM25 over the chunks the caller is authorized to read.

    Corpus statistics (document frequency, average length) are computed over
    the authorized chunks only, so unauthorized text never influences scores.
    """

    if not query.strip():
        raise ValueError("Search query cannot be empty")

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    if allowed_ids is None:
        allowed_ids = authorized_chunk_ids(
            db, permission_context or PermissionContext()
        )
    if not allowed_ids:
        return []

    rows = (
        db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.page_number,
            DocumentChunk.chunk_index,
            DocumentChunk.text,
            Document.filename,
            Document.source_name,
            Document.source_document_id,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(DocumentChunk.id.in_(allowed_ids))
        .all()
    )
    if not rows:
        return []

    stats = [_chunk_terms(row.id, row.text) for row in rows]
    document_count = len(stats)
    average_length = sum(length for _, length in stats) / document_count
    if average_length == 0:
        return []

    query_frequency = Counter(query_tokens)
    idf = {}
    for term in query_frequency:
        df = sum(1 for counts, _ in stats if term in counts)
        idf[term] = math.log(1 + (document_count - df + 0.5) / (df + 0.5))

    results = []
    for row, (counts, document_length) in zip(rows, stats):
        score = 0.0
        norm = k1 * (1 - b + b * document_length / average_length)
        for term, query_count in query_frequency.items():
            frequency = counts.get(term, 0)
            if frequency:
                score += idf[term] * frequency * (k1 + 1) / (frequency + norm) * query_count
        if score > 0:
            results.append({
                "chunk_id": row.id,
                "document_id": row.document_id,
                "filename": row.filename,
                "source_name": row.source_name,
                "source_document_id": row.source_document_id,
                "page_number": row.page_number,
                "chunk_index": row.chunk_index,
                "text": row.text,
                "bm25_score": score,
            })

    results.sort(key=lambda result: result["bm25_score"], reverse=True)
    return results[:top_k]
