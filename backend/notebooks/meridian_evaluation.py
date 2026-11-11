# %% [markdown]
# # Meridian Enterprise Retrieval Evaluation
#
# This notebook-compatible script evaluates the existing Meridian retrieval
# implementation on enterprise ACL scenarios. It is intentionally read-only:
# it creates no documents, changes no ACLs, and does not modify the database.
#
# Run in Jupyter or VS Code cell mode, or from PowerShell:
#
# ```powershell
# .\.venv\Scripts\python.exe notebooks\meridian_evaluation.py
# ```
#
# Outputs are written to `backend/evaluation_results/`:
# - `enterprise_results.csv`: one row per scenario and retrieval mode
# - `enterprise_summary.json`: aggregate metrics and environment details
# - `metrics_by_mode.png`: metric comparison
# - `latency_by_mode.png`: latency comparison
# - `acl_and_relevance_heatmap.png`: per-case result matrix
#
# The evaluator reports relevance and ACL security separately. A permitted but
# irrelevant result is not an ACL failure.

# %%
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.permissions import PermissionContext
from app.bm25_retrieval import bm25_search
from app.retrieval import semantic_search
from app.hybrid_retrieval import hybrid_search
from app.graph_retrieval import graph_search


OUTPUT_DIR = ROOT / "evaluation_results"


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    user_id: str
    user_label: str
    departments: tuple[str, ...]
    teams: tuple[str, ...]
    question: str
    relevant_sources: tuple[str, ...]
    forbidden_sources: tuple[str, ...]


CASES = (
    EvaluationCase(
        "hr_department",
        "USR-00003",
        "Aisha Khan",
        ("Human Resources",),
        ("People Operations",),
        "What does the employee leave and attendance policy say?",
        ("HR-001",),
        ("HR-003", "ENG-001", "ENG-002", "ENG-003", "ENG-004", "FIN-001", "FIN-002", "FIN-003", "FIN-004", "IT-001", "IT-002", "IT-003", "IT-004", "OPS-001", "OPS-002", "OPS-003"),
    ),
    EvaluationCase(
        "engineering_team",
        "USR-00005",
        "Priya Nair",
        ("Engineering",),
        ("Backend Platform", "Data Engineering"),
        "How should backend services communicate and integrate?",
        ("ENG-003",),
        ("ENG-004", "FIN-001", "FIN-002", "FIN-003", "FIN-004", "IT-001", "IT-002", "IT-003", "IT-004", "OPS-001", "OPS-002", "OPS-003", "HR-001", "HR-003", "HR-004"),
    ),
    EvaluationCase(
        "multi_department_overlap",
        "USR-00009",
        "Grace Wilson",
        ("Finance", "Operations"),
        ("Accounts Payable", "Business Operations"),
        "What are the expense reimbursement and vendor management requirements?",
        ("FIN-002", "FIN-003", "OPS-002"),
        ("FIN-004", "ENG-001", "ENG-002", "ENG-003", "ENG-004", "IT-001", "IT-002", "IT-003", "IT-004", "HR-001", "HR-003", "HR-004"),
    ),
    EvaluationCase(
        "restricted_allowed",
        "USR-00007",
        "Sofia Chen",
        ("Engineering",),
        ("Data Engineering",),
        "Summarize the annual department budget allocation report.",
        ("FIN-004",),
        ("FIN-001", "FIN-002", "FIN-003", "ENG-001", "ENG-002", "ENG-003", "ENG-004", "IT-001", "IT-002", "IT-003", "IT-004", "OPS-001", "OPS-002", "OPS-003", "HR-001", "HR-003", "HR-004"),
    ),
    EvaluationCase(
        "restricted_denied",
        "USR-00003",
        "Aisha Khan",
        ("Human Resources",),
        ("People Operations",),
        "What is in the annual department budget allocation report?",
        (),
        ("FIN-004",),
    ),
    EvaluationCase(
        "team_denied",
        "USR-00008",
        "Omar Haddad",
        ("Finance",),
        ("Financial Planning",),
        "What is the employee expense reimbursement process?",
        (),
        ("FIN-002", "FIN-003", "FIN-004"),
    ),
    EvaluationCase(
        "it_department",
        "USR-00010",
        "Noah Patel",
        ("IT and Security",),
        ("Security Operations", "Infrastructure"),
        "What does the enterprise access control policy require?",
        ("IT-001",),
        ("ENG-001", "ENG-002", "ENG-003", "FIN-001", "FIN-002", "FIN-003", "FIN-004", "HR-001", "HR-003", "HR-004", "OPS-001", "OPS-002", "OPS-003"),
    ),
    EvaluationCase(
        "no_relevant_evidence",
        "USR-00003",
        "Aisha Khan",
        ("Human Resources",),
        ("People Operations",),
        "What was the company's revenue in 2035?",
        (),
        ("FIN-001", "FIN-002", "FIN-003", "FIN-004", "ENG-001", "ENG-002", "ENG-003", "ENG-004", "IT-001", "IT-002", "IT-003", "IT-004", "OPS-001", "OPS-002", "OPS-003"),
    ),
)


def context_for(case: EvaluationCase) -> PermissionContext:
    return PermissionContext(
        user_id=case.user_id,
        departments=frozenset(case.departments),
        teams=frozenset(case.teams),
    )


def retrieve(db, mode: str, case: EvaluationCase, top_k: int = 10) -> list[dict[str, Any]]:
    context = context_for(case)
    if mode == "bm25":
        return bm25_search(db, case.question, top_k=top_k, permission_context=context)
    if mode == "dense":
        return semantic_search(db, case.question, top_k=top_k, permission_context=context)
    if mode == "hybrid":
        return hybrid_search(db, case.question, top_k=top_k, permission_context=context)
    if mode == "hybrid_rerank":
        return hybrid_search(db, case.question, top_k=top_k, permission_context=context, rerank=True)
    if mode == "graph":
        return graph_search(db, case.question, top_k=top_k, permission_context=context)
    raise ValueError(f"Unknown retrieval mode: {mode}")


def unique_sources(results: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in results:
        source = item.get("source_document_id")
        if source is not None and str(source) not in seen:
            seen.add(str(source))
            values.append(str(source))
    return values


def ndcg_at_10(returned: list[str], relevant: tuple[str, ...]) -> float:
    relevant_set = set(relevant)
    gains = [1 if source in relevant_set else 0 for source in returned[:10]]
    dcg = sum(gain / __import__("math").log2(index + 2) for index, gain in enumerate(gains))
    ideal = sum(1 / __import__("math").log2(index + 2) for index in range(min(10, len(relevant_set))))
    return dcg / ideal if ideal else 0.0


def metrics(case: EvaluationCase, returned: list[str]) -> dict[str, Any]:
    relevant = set(case.relevant_sources)
    first_rank = next((index for index, source in enumerate(returned[:10], start=1) if source in relevant), None)
    return {
        "hit_at_10": bool(relevant.intersection(returned[:10])) if relevant else None,
        "mrr_at_10": 1 / first_rank if first_rank else 0.0,
        "ndcg_at_10": ndcg_at_10(returned, case.relevant_sources),
        "acl_pass": not bool(set(returned).intersection(case.forbidden_sources)),
        "forbidden_returned": sorted(set(returned).intersection(case.forbidden_sources)),
        "expected_returned": sorted(relevant.intersection(returned)),
    }


def run(modes: tuple[str, ...] = ("bm25", "dense", "hybrid", "hybrid_rerank", "graph"), top_k: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    started_all = time.perf_counter()
    with SessionLocal() as db:
        for case in CASES:
            for mode in modes:
                started = time.perf_counter()
                row: dict[str, Any] = {
                    "case_id": case.case_id,
                    "user": case.user_label,
                    "user_id": case.user_id,
                    "mode": mode,
                    "question": case.question,
                    "status": "success",
                    "error": "",
                }
                try:
                    results = retrieve(db, mode, case, top_k=top_k)
                    returned = unique_sources(results)
                    row.update(metrics(case, returned))
                    row["returned_sources"] = returned
                    row["result_count"] = len(results)
                    row["chunk_ids"] = [item.get("chunk_id") for item in results]
                    row["scores"] = [
                        item.get("cross_encoder_score", item.get("rrf_score", item.get("graph_score", item.get("bm25_score", item.get("similarity")))))
                        for item in results
                    ]
                except Exception as exc:
                    row.update({
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "returned_sources": [],
                        "result_count": 0,
                        "chunk_ids": [],
                        "scores": [],
                        "hit_at_10": None,
                        "mrr_at_10": None,
                        "ndcg_at_10": None,
                        "acl_pass": False,
                        "forbidden_returned": [],
                        "expected_returned": [],
                    })
                row["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                rows.append(row)
                print(f"{row['status'].upper():7} {case.case_id:24} {mode:14} {row['latency_ms']:9.2f} ms | returned={row.get('returned_sources', [])} | ACL={row.get('acl_pass')}")

    successful = [row for row in rows if row["status"] == "success"]
    summary: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "case_count": len(CASES),
        "mode_count": len(modes),
        "row_count": len(rows),
        "successful_rows": len(successful),
        "error_rows": len(rows) - len(successful),
        "total_runtime_seconds": round(time.perf_counter() - started_all, 3),
        "modes": list(modes),
        "top_k": top_k,
        "python": sys.version,
        "ollama_model": os.environ.get("OLLAMA_MODEL", "not used by retrieval evaluator"),
        "by_mode": {},
    }
    for mode in modes:
        mode_rows = [row for row in successful if row["mode"] == mode]
        summary["by_mode"][mode] = {
            "rows": len(mode_rows),
            "mean_latency_ms": round(sum(row["latency_ms"] for row in mode_rows) / len(mode_rows), 2) if mode_rows else None,
            "hit_at_10": round(sum(bool(row["hit_at_10"]) for row in mode_rows if row["hit_at_10"] is not None) / max(1, sum(row["hit_at_10"] is not None for row in mode_rows)), 4) if mode_rows else None,
            "mrr_at_10": round(sum(row["mrr_at_10"] for row in mode_rows if row["mrr_at_10"] is not None) / len(mode_rows), 4) if mode_rows else None,
            "ndcg_at_10": round(sum(row["ndcg_at_10"] for row in mode_rows if row["ndcg_at_10"] is not None) / len(mode_rows), 4) if mode_rows else None,
            "acl_pass_rate": round(sum(bool(row["acl_pass"]) for row in mode_rows) / len(mode_rows), 4) if mode_rows else None,
            "forbidden_leakage_rows": sum(bool(row["forbidden_returned"]) for row in mode_rows),
        }
    return rows, summary


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "enterprise_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "enterprise_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    fields = ["case_id", "user", "user_id", "mode", "status", "question", "returned_sources", "expected_returned", "forbidden_returned", "hit_at_10", "mrr_at_10", "ndcg_at_10", "acl_pass", "result_count", "latency_ms", "error"]
    with (output_dir / "enterprise_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row.get(field)) if isinstance(row.get(field), list) else row.get(field, "") for field in fields})
    try:
        import matplotlib.pyplot as plt
        modes = summary["modes"]
        labels = [mode.replace("_", " ").title() for mode in modes]
        values = summary["by_mode"]
        metrics_to_plot = [("hit_at_10", "Hit@10"), ("mrr_at_10", "MRR@10"), ("ndcg_at_10", "nDCG@10"), ("acl_pass_rate", "ACL pass rate")]
        fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
        for axis, (key, title) in zip(axes.flat, metrics_to_plot):
            axis.bar(labels, [values[mode][key] or 0 for mode in modes], color="#138a72")
            axis.set_title(title)
            axis.set_ylim(0, 1.05)
            axis.tick_params(axis="x", rotation=30)
        fig.suptitle("Meridian enterprise retrieval and ACL results")
        fig.savefig(output_dir / "metrics_by_mode.png", dpi=180)
        plt.close(fig)
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.bar(labels, [values[mode]["mean_latency_ms"] or 0 for mode in modes], color="#3867d6")
        axis.set_ylabel("Mean latency (ms)")
        axis.set_title("Mean retrieval latency by mode")
        axis.tick_params(axis="x", rotation=30)
        fig.tight_layout()
        fig.savefig(output_dir / "latency_by_mode.png", dpi=180)
        plt.close(fig)
        case_labels = [case.case_id for case in CASES]
        matrix = []
        for case_id in case_labels:
            matrix.append([1 if next(row for row in rows if row["case_id"] == case_id and row["mode"] == mode).get("hit_at_10") else 0 for mode in modes])
        fig, axis = plt.subplots(figsize=(10, 6))
        image = axis.imshow(matrix, cmap="YlGn", vmin=0, vmax=1, aspect="auto")
        axis.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
        axis.set_yticks(range(len(case_labels)), case_labels)
        axis.set_title("Enterprise relevance Hit@10 by case and mode")
        fig.colorbar(image, ax=axis, label="Hit@10")
        fig.tight_layout()
        fig.savefig(output_dir / "acl_and_relevance_heatmap.png", dpi=180)
        plt.close(fig)
        summary["plots_generated"] = True
    except ImportError:
        summary["plots_generated"] = False
        summary["plot_note"] = "Install matplotlib in the notebook environment to generate PNG figures."
    (output_dir / "enterprise_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only enterprise retrieval and ACL evaluation")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--modes", nargs="+", default=["bm25", "dense", "hybrid", "hybrid_rerank", "graph"])
    args = parser.parse_args()
    rows, summary = run(tuple(args.modes), args.top_k)
    write_outputs(rows, summary, args.output_dir)
    print(json.dumps(summary, indent=2))
    return 1 if summary["error_rows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
