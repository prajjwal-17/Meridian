"""Live validation of hybrid + cross-encoder reranking.

1. Through the API, for each demo account: reranked results are sorted by
   cross_encoder_score, keep their RRF score, and never include a document the
   account cannot read.
2. In-process: the real cross-encoder only ever receives text from chunks in
   the caller's authorized set (checked before inference).
"""

from __future__ import annotations

import sys

import requests

from live_support import BASE_URL, authorized_document_ids, demo_accounts, login, run_live, user_id_for

QUERIES = (
    "employee leave and attendance policy",
    "how should backend services communicate",
    "expense reimbursement requirements",
)


def validate_api() -> list[str]:
    failures = []
    for account in demo_accounts()[:6]:
        session = login(account)
        allowed = authorized_document_ids(user_id_for(session))
        for query in QUERIES:
            response = session.get(
                f"{BASE_URL}/search",
                params={"q": query, "mode": "hybrid", "top_k": 5, "rerank": "true"},
                timeout=120,
            )
            if response.status_code != 200:
                failures.append(f"{account['name']} {query!r}: HTTP {response.status_code}")
                continue
            results = response.json()["results"]
            scores = [r["cross_encoder_score"] for r in results]
            if scores != sorted(scores, reverse=True):
                failures.append(f"{account['name']} {query!r}: results not sorted by cross-encoder score")
            if any("rrf_score" not in r for r in results):
                failures.append(f"{account['name']} {query!r}: RRF score was dropped")
            leaked = {r["document_id"] for r in results} - allowed
            if leaked:
                failures.append(f"{account['name']} {query!r}: unauthorized documents {sorted(leaked)}")
    missing = requests.get(f"{BASE_URL}/search", params={"q": "leave", "mode": "hybrid", "rerank": "true"}, timeout=30)
    if missing.status_code != 401:
        failures.append(f"unauthenticated rerank returned HTTP {missing.status_code}")
    print(f"API rerank checks done ({len(failures)} failures)")
    return failures


def validate_pre_inference_acl() -> list[str]:
    from app import reranker as reranker_module
    from app.database import SessionLocal
    from app.dependencies import get_authenticated_permission_context
    from app.hybrid_retrieval import hybrid_search
    from app.models import DocumentChunk, User
    from app.permissions import authorized_chunk_ids

    account = demo_accounts()[0]
    session = login(account)
    user_id = user_id_for(session)
    db = SessionLocal()
    original_loader = reranker_module.load_cross_encoder
    real_model = original_loader()
    captured: list[tuple[str, str]] = []

    class RecordingModel:
        def predict(self, pairs):
            captured.extend(pairs)
            return real_model.predict(pairs)

    reranker_module.load_cross_encoder = lambda: RecordingModel()
    try:
        context = get_authenticated_permission_context(db, db.get(User, user_id))
        allowed_ids = authorized_chunk_ids(db, context)
        results = hybrid_search(db, "employee leave attendance payroll", top_k=5, permission_context=context, rerank=True)
        allowed_texts = {t for (t,) in db.query(DocumentChunk.text).filter(DocumentChunk.id.in_(allowed_ids)).all()}
        failures = []
        if not results or not captured:
            failures.append("cross-encoder received no candidate pairs")
        if any(text not in allowed_texts for _, text in captured):
            failures.append("cross-encoder received text outside the authorized chunk set")
        print(f"pre-inference ACL: {len(captured)} pairs checked for {account['name']}")
        return failures
    finally:
        reranker_module.load_cross_encoder = original_loader
        db.close()


def main() -> int:
    failures = validate_api() + validate_pre_inference_acl()
    for failure in failures:
        print("FAIL", failure)
    print("PASS" if not failures else f"{len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run_live(main))
