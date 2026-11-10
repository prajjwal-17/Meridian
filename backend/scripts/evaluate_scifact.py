"""Read-only SciFact retrieval evaluation for Meridian."""
from __future__ import annotations
import argparse
import csv
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.bm25_retrieval import bm25_search
from app.database import SessionLocal
from app.graph_retrieval import graph_search
from app.hybrid_retrieval import hybrid_search
from app.permissions import PermissionContext
from app.retrieval import semantic_search
DATASET_DIR = Path(__file__).resolve().parents[1] / "data" / "scifact"
RESULTS_DIR = DATASET_DIR / "results"
MODES = ("bm25", "dense", "hybrid", "hybrid_rerank")
def load_queries(path: Path) -> dict[str, str]:
    queries = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            queries[str(record["_id"])] = record["text"]
    return queries
def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels = defaultdict(dict)
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file, delimiter="	"):
            qrels[str(row["query-id"])][str(row["corpus-id"])] = int(row["score"])
    return dict(qrels)
def deduplicate_source_ids(results: list[dict]) -> list[str]:
    seen = set()
    source_ids = []
    for result in results:
        source_id = result.get("source_document_id")
        if source_id is None or source_id in seen:
            continue
        seen.add(source_id)
        source_ids.append(str(source_id))
    return source_ids
def dcg(relevances: list[int]) -> float:
    return sum(
        (2 ** relevance - 1) / math.log2(rank + 2)
        for rank, relevance in enumerate(relevances)
    )
def query_metrics(returned_ids: list[str], relevant: dict[str, int]) -> dict[str, float]:
    relevant = {
        source_id: score
        for source_id, score in relevant.items()
        if score > 0
    }
    top_ids = returned_ids[:10]
    relevance = [relevant.get(source_id, 0) for source_id in top_ids]
    relevant_count = sum(1 for value in relevance if value > 0)
    first_rank = next(
        (rank for rank, value in enumerate(relevance, start=1) if value > 0),
        None,
    )
    ideal = sorted(relevant.values(), reverse=True)[:10]
    return {
        "recall_at_10": relevant_count / len(relevant) if relevant else 0.0,
        "mrr_at_10": 1.0 / first_rank if first_rank else 0.0,
        "ndcg_at_10": dcg(relevance) / dcg(ideal) if dcg(ideal) else 0.0,
        "top1_accuracy": 1.0 if relevance and relevance[0] > 0 else 0.0,
    }
def retrieve(db, mode: str, query: str, context: PermissionContext) -> list[dict]:
    if mode == "bm25":
        return bm25_search(db, query, top_k=10, permission_context=context)
    if mode == "dense":
        return semantic_search(db, query, top_k=10, permission_context=context)
    if mode == "hybrid":
        return hybrid_search(db, query, top_k=10, permission_context=context)
    return hybrid_search(
        db,
        query,
        top_k=10,
        permission_context=context,
        rerank=True,
    )
def classify_failure(exc: Exception) -> str:
    message = str(exc).lower()
    if any(term in message for term in ("model", "cross-encoder", "sentence-transformers", "huggingface")):
        return "model_unavailable"
    return "error"
def evaluate_mode(db, mode: str, queries: dict[str, str], qrels: dict[str, dict[str, int]], context: PermissionContext) -> tuple[dict, list[dict]]:
    metrics_rows = []
    started = time.perf_counter()
    for query_id, query in queries.items():
        relevant = qrels[query_id]
        row = {"mode": mode, "query_id": query_id, "status": "success", "error": ""}
        try:
            results = retrieve(db, mode, query, context)
            returned_ids = deduplicate_source_ids(results)
            row.update({"returned_ids": returned_ids, "relevant_ids": sorted(relevant)})
            row.update(query_metrics(returned_ids, relevant))
            if not returned_ids:
                row["status"] = "empty"
        except Exception as exc:
            row.update({
                "status": classify_failure(exc),
                "returned_ids": [],
                "relevant_ids": sorted(relevant),
                "error": str(exc),
            })
        metrics_rows.append(row)
    successful = [row for row in metrics_rows if row["status"] in {"success", "empty"}]
    failed = [row for row in metrics_rows if row["status"] not in {"success", "empty"}]
    summary = {
        "mode": mode,
        "query_count": len(queries),
        "successful_queries": len(successful),
        "failed_queries": len(failed),
        "empty_result_queries": sum(row["status"] == "empty" for row in successful),
        "evaluation_duration_seconds": time.perf_counter() - started,
    }
    for metric in ("recall_at_10", "mrr_at_10", "ndcg_at_10", "top1_accuracy"):
        summary[metric] = (
            sum(row[metric] for row in successful) / len(successful)
            if successful else None
        )
    return summary, metrics_rows
def write_results(summaries: list[dict], rows: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics_summary.json").write_text(
        json.dumps(summaries, indent=2),
        encoding="utf-8",
    )
    fields = [
        "mode", "query_id", "status", "returned_ids", "relevant_ids",
        "recall_at_10", "mrr_at_10", "ndcg_at_10", "top1_accuracy", "error",
    ]
    with (output_dir / "per_query_results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: json.dumps(row[field]) if isinstance(row.get(field), list) else row.get(field, "")
                for field in fields
            })
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()
    if args.top_k != 10:
        raise SystemExit("SciFact evaluation is defined at top-k=10")
    queries = load_queries(DATASET_DIR / "queries.jsonl")
    qrels = load_qrels(DATASET_DIR / "qrels" / "test.tsv")
    judged_queries = {query_id: queries[query_id] for query_id in qrels if query_id in queries}
    if args.limit is not None:
        judged_queries = dict(list(judged_queries.items())[:args.limit])
    context = PermissionContext(user_id="scifact-evaluation")
    summaries = []
    rows = []
    with SessionLocal() as db:
        for mode in MODES:
            summary, mode_rows = evaluate_mode(db, mode, judged_queries, qrels, context)
            summaries.append(summary)
            rows.extend(mode_rows)
            print(json.dumps(summary, indent=2))
    write_results(summaries, rows, args.output_dir)
    return 1 if any(summary["failed_queries"] for summary in summaries) else 0
if __name__ == "__main__":
    raise SystemExit(main())
