import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.permissions import PermissionContext
from evaluate_scifact import load_qrels, query_metrics, deduplicate_source_ids, write_results
class SciFactEvaluationTests(unittest.TestCase):
    def test_metrics_support_multiple_relevant_documents(self):
        metrics = query_metrics(
            ["doc-b", "doc-a", "doc-c"],
            {"doc-a": 1, "doc-b": 1},
        )
        self.assertEqual(metrics["recall_at_10"], 1.0)
        self.assertEqual(metrics["mrr_at_10"], 1.0)
        self.assertEqual(metrics["top1_accuracy"], 1.0)
        self.assertGreater(metrics["ndcg_at_10"], 0.0)
    def test_duplicate_chunks_are_deduplicated(self):
        results = [
            {"source_document_id": "doc-a"},
            {"source_document_id": "doc-a"},
            {"source_document_id": "doc-b"},
            {"source_document_id": None},
        ]
        self.assertEqual(deduplicate_source_ids(results), ["doc-a", "doc-b"])
    def test_empty_results_have_zero_metrics(self):
        metrics = query_metrics([], {"doc-a": 1})
        self.assertEqual(metrics["recall_at_10"], 0.0)
        self.assertEqual(metrics["mrr_at_10"], 0.0)
        self.assertEqual(metrics["ndcg_at_10"], 0.0)
        self.assertEqual(metrics["top1_accuracy"], 0.0)
    def test_qrels_keep_only_explicit_judgments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.tsv"
            path.write_text(
                "query-id\tcorpus-id\tscore\n1\ta\t1\n1\tb\t2\n",
                encoding="utf-8",
            )
            self.assertEqual(load_qrels(path), {"1": {"a": 1, "b": 2}})
    def test_results_can_be_written_without_database_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_results(
                [{"mode": "bm25", "query_count": 1}],
                [{
                    "mode": "bm25",
                    "query_id": "1",
                    "status": "empty",
                    "returned_ids": [],
                    "relevant_ids": ["a"],
                    "recall_at_10": 0.0,
                    "mrr_at_10": 0.0,
                    "ndcg_at_10": 0.0,
                    "top1_accuracy": 0.0,
                    "error": "",
                }],
                output,
            )
            self.assertTrue((output / "metrics_summary.json").exists())
            self.assertTrue((output / "per_query_results.csv").exists())
if __name__ == "__main__":
    unittest.main()
