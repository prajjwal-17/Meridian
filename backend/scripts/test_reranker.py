import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.permissions import PermissionContext
from app.reranker import (
    MODEL_NAME,
    RerankerError,
    load_cross_encoder,
    rerank_candidates,
)


def candidate(chunk_id, text, rrf_score):
    return {
        "chunk_id": chunk_id,
        "document_id": chunk_id + 100,
        "filename": f"doc-{chunk_id}.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": text,
        "rrf_score": rrf_score,
        "retrieval_sources": ["bm25", "dense"],
    }


class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = None

    def predict(self, pairs):
        self.pairs = pairs
        return self.scores


class RerankerTests(unittest.TestCase):
    def setUp(self):
        self.context = PermissionContext(user_id="alice", department="HR")
        self.candidates = [
            candidate(1, "weak chunk", 0.42),
            candidate(2, "strong chunk", 0.91),
            candidate(3, "medium chunk", 0.33),
        ]

    def test_scores_pairs_orders_descending_and_preserves_metadata(self):
        model = FakeCrossEncoder([0.2, 0.95, 0.6])
        results = rerank_candidates(
            "employee leave policy",
            self.candidates,
            permission_context=self.context,
            authorized_ids={1, 2, 3},
            model=model,
        )

        self.assertEqual(model.pairs, [
            ("employee leave policy", "weak chunk"),
            ("employee leave policy", "strong chunk"),
            ("employee leave policy", "medium chunk"),
        ])
        self.assertEqual([item["chunk_id"] for item in results], [2, 3, 1])
        self.assertEqual(results[0]["cross_encoder_score"], 0.95)
        self.assertEqual(results[0]["rrf_score"], 0.91)
        self.assertEqual(results[0]["filename"], "doc-2.pdf")
        self.assertEqual(results[0]["retrieval_sources"], ["bm25", "dense"])

    def test_top_k_selection(self):
        model = FakeCrossEncoder([0.2, 0.95, 0.6])
        results = rerank_candidates(
            "employee leave policy",
            self.candidates,
            top_k=2,
            permission_context=self.context,
            authorized_ids={1, 2, 3},
            model=model,
        )
        self.assertEqual([item["chunk_id"] for item in results], [2, 3])

    def test_empty_candidates_do_not_load_or_score_model(self):
        with patch("app.reranker.load_cross_encoder") as load:
            self.assertEqual(
                rerank_candidates(
                    "query",
                    [],
                    permission_context=self.context,
                    authorized_ids=set(),
                ),
                [],
            )
        load.assert_not_called()

    def test_acl_filtering_happens_before_pairs_are_scored(self):
        model = FakeCrossEncoder([0.8])
        results = rerank_candidates(
            "employee leave policy",
            self.candidates,
            permission_context=self.context,
            authorized_ids={2},
            model=model,
        )
        self.assertEqual(model.pairs, [("employee leave policy", "strong chunk")])
        self.assertEqual([item["chunk_id"] for item in results], [2])

    def test_missing_acl_context_fails_closed(self):
        with self.assertRaises(RerankerError):
            rerank_candidates("query", self.candidates)

    def test_model_scoring_failure_is_explicit(self):
        class BrokenModel:
            def predict(self, _pairs):
                raise RuntimeError("model unavailable")

        with self.assertRaisesRegex(RerankerError, "scoring failed"):
            rerank_candidates(
                "query",
                self.candidates,
                permission_context=self.context,
                authorized_ids={1, 2, 3},
                model=BrokenModel(),
            )

    def test_model_loading_failure_is_explicit(self):
        fake_sentence_transformers = types.SimpleNamespace(
            CrossEncoder=lambda _name: (_ for _ in ()).throw(
                RuntimeError("offline")
            )
        )
        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            with self.assertRaisesRegex(RerankerError, MODEL_NAME):
                load_cross_encoder()

    def test_hybrid_filters_acl_before_reranker_receives_candidates(self):
        from app.hybrid_retrieval import hybrid_search

        unauthorized = candidate(2, "secret unauthorized text", 0.9)
        authorized = candidate(1, "authorized text", 0.8)
        with patch(
            "app.hybrid_retrieval.bm25_search",
            return_value=[unauthorized, authorized],
        ), patch(
            "app.hybrid_retrieval.semantic_search",
            return_value=[],
        ), patch(
            "app.hybrid_retrieval.authorized_chunk_ids",
            return_value={1},
        ), patch(
            "app.hybrid_retrieval.rerank_candidates",
            return_value=[],
        ) as rerank:
            hybrid_search(
                None,
                "query",
                permission_context=self.context,
                rerank=True,
            )

        received = rerank.call_args.kwargs["candidates"]
        self.assertEqual([item["chunk_id"] for item in received], [1])
        self.assertNotIn("secret unauthorized text", [
            item["text"] for item in received
        ])


if __name__ == "__main__":
    unittest.main()
