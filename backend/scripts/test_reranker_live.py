"""Live reranker validation against the running API and PostgreSQL database.

The API checks use the real cross-encoder. The database check wraps the real
model only to record the chunk texts passed to it, proving ACL filtering occurs
before inference without replacing model scoring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.hybrid_retrieval import hybrid_search
from app.models import DocumentChunk
from app.permissions import PermissionContext, authorized_chunk_ids
from app import reranker as reranker_module


BASE_URL = "http://127.0.0.1:8000"
CASES = (
    ("HR", "employee leave attendance payroll", 7, {7}, {"user": "alice", "department": "hr"}),
    ("Engineering", "Docker Kubernetes FastAPI PostgreSQL", 8, {8, 10}, {"user": "bob", "team": "backend", "department": "engineering"}),
    ("Finance", "quarterly budget operating expenses invoices", 9, {9}, {"user": "charlie", "team": "finance-ops", "department": "finance"}),
    ("Backend", "API Gateway Kafka microservice Redis", 10, {8, 10}, {"user": "bob", "team": "backend", "department": "engineering"}),
)


def headers(identity: dict[str, str]) -> dict[str, str]:
    return {
        "X-Meridian-User": identity["user"],
        "X-Meridian-Team": identity.get("team", ""),
        "X-Meridian-Department": identity.get("department", ""),
    }


def api_json(session: requests.Session, query: str, identity: dict[str, str], rerank: bool) -> dict:
    response = session.get(
        f"{BASE_URL}/search",
        params={"q": query, "mode": "hybrid", "top_k": 5, "rerank": str(rerank).lower()},
        headers=headers(identity),
        timeout=120,
    )
    if response.status_code != 200:
        raise AssertionError(f"hybrid rerank={rerank} returned HTTP {response.status_code}: {response.text[:300]}")
    payload = response.json()
    if not isinstance(payload.get("results"), list):
        raise AssertionError("/search response does not contain a results list")
    return payload


def validate_api() -> None:
    session = requests.Session()
    for label, query, expected_document_id, allowed_document_ids, identity in CASES:
        plain = api_json(session, query, identity, rerank=False)["results"]
        assert plain, f"{label}: rerank=false returned no results"
        assert expected_document_id in {item["document_id"] for item in plain}, f"{label}: target missing without reranking"
        assert all("rrf_score" in item for item in plain), f"{label}: RRF score missing without reranking"
        assert all("cross_encoder_score" not in item for item in plain), f"{label}: reranker score leaked into disabled response"

        reranked = api_json(session, query, identity, rerank=True)["results"]
        assert reranked, f"{label}: rerank=true returned no results"
        result_ids = {item["document_id"] for item in reranked}
        assert expected_document_id in result_ids, f"{label}: target missing after reranking: {result_ids}"
        assert result_ids <= allowed_document_ids, f"{label}: unauthorized document IDs returned: {result_ids - allowed_document_ids}"
        assert all("cross_encoder_score" in item for item in reranked), f"{label}: cross-encoder score missing"
        assert all("rrf_score" in item for item in reranked), f"{label}: original RRF score was not preserved"
        scores = [float(item["cross_encoder_score"]) for item in reranked]
        assert scores == sorted(scores, reverse=True), f"{label}: reranked scores are not descending: {scores}"
        print(
            f"PASS live {label}: plain_ids={[item['document_id'] for item in plain]}, "
            f"reranked_ids={[item['document_id'] for item in reranked]}, "
            f"scores={[round(score, 5) for score in scores]}"
        )

    missing = session.get(
        f"{BASE_URL}/search",
        params={"q": "employee leave attendance payroll", "mode": "hybrid", "rerank": "true"},
        timeout=120,
    )
    assert missing.status_code == 401, f"missing identity returned HTTP {missing.status_code}"
    print("PASS live missing identity: HTTP 401")


def validate_pre_inference_acl() -> None:
    db = SessionLocal()
    original_loader = reranker_module.load_cross_encoder
    real_model = original_loader()
    captured_pairs: list[tuple[str, str]] = []

    class RecordingModel:
        def predict(self, pairs):
            captured_pairs.extend(pairs)
            return real_model.predict(pairs)

    reranker_module.load_cross_encoder = lambda: RecordingModel()
    try:
        context = PermissionContext(user_id="alice", department="hr", team="recruitment")
        allowed_ids = authorized_chunk_ids(db, context)
        results = hybrid_search(
            db,
            "employee leave attendance payroll",
            top_k=5,
            permission_context=context,
            rerank=True,
        )
        assert results
        allowed_texts = {
            text
            for (text,) in db.query(DocumentChunk.text).filter(DocumentChunk.id.in_(allowed_ids)).all()
        }
        assert captured_pairs, "real cross-encoder received no pairs"
        assert all(text in allowed_texts for _, text in captured_pairs), (
            "cross-encoder received text from a chunk outside the authorized chunk set"
        )
        print(f"PASS pre-inference ACL: {len(captured_pairs)} real pairs, authorized_chunks={sorted(allowed_ids)}")
    finally:
        reranker_module.load_cross_encoder = original_loader
        db.close()


if __name__ == "__main__":
    validate_api()
    validate_pre_inference_acl()
