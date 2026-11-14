"""Grounded-answer benchmark over the enterprise evaluation cases.

Runs answer_question() in-process (real database, real Ollama) for every base
case and reports, per case:
  - whether an answer was produced or the system abstained,
  - whether the answer cites an expected source,
  - whether it cites any forbidden source (must never happen),
  - end-to-end latency.

Usage (from backend/):  python scripts/answer_quality_bench.py [out.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "notebooks"))

from app.answer_generation import answer_question  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from meridian_evaluation import BASE_CASES, context_for  # noqa: E402


def source_label(item: dict) -> str | None:
    return item.get("source_document_id") or item.get("filename")


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    db = SessionLocal()
    rows = []
    try:
        for case in BASE_CASES:
            started = time.perf_counter()
            result = answer_question(db, case.question, context_for(case), top_k=5, rerank=True)
            seconds = time.perf_counter() - started
            cited = {source_label(c) for c in result.get("citations", [])}
            expects_answer = bool(case.relevant_sources)
            answered = bool(result.get("sufficient_evidence"))
            row = {
                "case": case.case_id,
                "question": case.question,
                "expects_answer": expects_answer,
                "answered": answered,
                "correct_outcome": answered == expects_answer,
                "cites_expected": bool(cited & set(case.relevant_sources)),
                "cites_forbidden": sorted(cited & set(case.forbidden_sources)),
                "seconds": round(seconds, 2),
                "answer": result.get("answer", "")[:400],
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False)[:500], flush=True)
    finally:
        db.close()

    answerable = [r for r in rows if r["expects_answer"]]
    summary = {
        "cases": len(rows),
        "correct_outcome_rate": round(sum(r["correct_outcome"] for r in rows) / len(rows), 3),
        "answered_with_expected_source": f"{sum(r['answered'] and r['cites_expected'] for r in answerable)}/{len(answerable)}",
        "forbidden_citations": sum(bool(r["cites_forbidden"]) for r in rows),
        "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
        "max_seconds": max(r["seconds"] for r in rows),
    }
    print("SUMMARY", json.dumps(summary))
    if out_path:
        out_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if summary["forbidden_citations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
