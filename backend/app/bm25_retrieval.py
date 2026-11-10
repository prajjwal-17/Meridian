
import math
import re
from collections import Counter

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.permissions import PermissionContext, authorized_chunk_ids


def tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())


def bm25_search(
    db: Session,
    query: str,
    top_k: int = 5,
    k1: float = 1.5,
    b: float = 0.75,
    permission_context: PermissionContext | None = None,
) -> list[dict]:

    if not query.strip():
        raise ValueError("Search query cannot be empty")

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    allowed_ids = authorized_chunk_ids(
        db, permission_context or PermissionContext()
    )
    if not allowed_ids:
        return []

    rows = (
        db.query(
            DocumentChunk,
            Document.filename,
            Document.source_name,
            Document.source_document_id,
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id
        )
        .filter(DocumentChunk.id.in_(allowed_ids))
        .all()
    )

    if not rows:
        return []

    query_tokens = tokenize(query)

    if not query_tokens:
        return []

    corpus = [
        tokenize(chunk.text)
        for chunk, filename, source_name, source_document_id in rows
    ]

    document_count = len(corpus)

    document_lengths = [
        len(tokens) for tokens in corpus
    ]

    average_length = (
        sum(document_lengths) / document_count
    )

    if average_length == 0:
        return []

    # Count how many documents contain each term
    document_frequency = Counter()

    for tokens in corpus:
        document_frequency.update(set(tokens))

    query_frequency = Counter(query_tokens)

    results = []

    for index, tokens in enumerate(corpus):

        term_frequency = Counter(tokens)
        document_length = document_lengths[index]

        score = 0.0

        for term, query_count in query_frequency.items():

            frequency = term_frequency[term]

            if frequency == 0:
                continue

            df = document_frequency[term]

            idf = math.log(
                1 + (
                    document_count - df + 0.5
                ) / (df + 0.5)
            )

            numerator = frequency * (k1 + 1)

            denominator = frequency + k1 * (
                1 - b + b * document_length / average_length
            )

            score += (
                idf
                * numerator
                / denominator
                * query_count
            )

        if score > 0:
            chunk, filename, source_name, source_document_id = rows[index]

            results.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "filename": filename,
                "source_name": source_name,
                "source_document_id": source_document_id,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "bm25_score": score
            })

    results.sort(
        key=lambda result: result["bm25_score"],
        reverse=True
    )

    return results[:top_k]
