import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.bm25_retrieval import bm25_search
from app.dependencies import get_permission_context
from app.entity_graph import index_chunk_entities
from app.graph_retrieval import graph_search
from app.models import ChunkEntityMention, Document, DocumentChunk, Entity, EntityRelationship
from app.permissions import (
    PermissionContext,
    authorized_chunk_ids,
    can_access_document,
    validate_acl_metadata,
)


class ACLPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        self.db = self.Session()
        self.docs = {}
        for name, tier, team, department, users in (
            ("public.pdf", "public", None, None, None),
            ("hr-handbook.pdf", "department", None, "HR", None),
            ("engineering-design.pdf", "department", None, "Engineering", None),
            ("finance-close.pdf", "department", None, "Finance", None),
            ("platform-runbook.pdf", "team", "platform", None, None),
            ("finance-ops.pdf", "team", "finance-ops", None, None),
            ("restricted.pdf", "restricted", None, None, ["alice"]),
        ):
            document = Document(
                filename=name, object_key=name, content_type="application/pdf",
                file_size=1, checksum=name.ljust(64, "x")[:64],
                permission_tier=tier, permission_team=team,
                permission_department=department, restricted_user_ids=users,
            )
            self.db.add(document)
            self.db.flush()
            chunk = DocumentChunk(
                document_id=document.id, page_number=1, chunk_index=0,
                text=f"semaphore guidance from {name}", token_count=4,
                permission_tier=tier,
            )
            self.db.add(chunk)
            self.db.flush()
            self.docs[name] = (document, chunk)
            index_chunk_entities(self.db, chunk.id, chunk.text)
        self.db.commit()

    def tearDown(self):
        self.db.execute(delete(EntityRelationship))
        self.db.execute(delete(ChunkEntityMention))
        self.db.execute(delete(Entity))
        self.db.execute(delete(DocumentChunk))
        self.db.execute(delete(Document))
        self.db.commit()
        self.db.close()

    def test_permission_tiers(self):
        self.assertTrue(can_access_document(
            self.docs["public.pdf"][0], PermissionContext(user_id="alice")
        ))
        self.assertTrue(can_access_document(
            self.docs["platform-runbook.pdf"][0],
            PermissionContext(user_id="alice", team="platform"),
        ))
        self.assertFalse(can_access_document(
            self.docs["platform-runbook.pdf"][0],
            PermissionContext(user_id="alice", team="Platform"),
        ))
        self.assertTrue(can_access_document(
            self.docs["engineering-design.pdf"][0],
            PermissionContext(user_id="alice", department="Engineering"),
        ))
        self.assertFalse(can_access_document(
            self.docs["engineering-design.pdf"][0],
            PermissionContext(user_id="alice", department="engineering"),
        ))
        self.assertTrue(can_access_document(
            self.docs["restricted.pdf"][0], PermissionContext(user_id="alice")
        ))
        self.assertFalse(can_access_document(
            self.docs["restricted.pdf"][0], PermissionContext(user_id="bob")
        ))
        self.assertFalse(can_access_document(
            self.docs["public.pdf"][0], PermissionContext()
        ))

    def test_upload_acl_metadata_is_required_and_validated(self):
        with self.assertRaises(ValueError):
            validate_acl_metadata(None)
        with self.assertRaises(ValueError):
            validate_acl_metadata("team")
        with self.assertRaises(ValueError):
            validate_acl_metadata("restricted")
        self.assertEqual(
            validate_acl_metadata("public")["permission_tier"], "public"
        )
        self.assertEqual(
            validate_acl_metadata("restricted", restricted_user_ids=["alice"])[
                "restricted_user_ids"
            ],
            ["alice"],
        )

    def test_missing_identity_fails_closed_at_api_context_boundary(self):
        with self.assertRaises(Exception) as raised:
            get_permission_context(None, None, None)
        self.assertEqual(raised.exception.status_code, 401)

    def test_missing_permission_metadata_fails_closed(self):
        document, chunk = self.docs["public.pdf"]
        document.permission_tier = None
        chunk.permission_tier = None
        self.db.commit()
        self.assertNotIn(chunk.id, authorized_chunk_ids(self.db, PermissionContext()))

    def test_bm25_and_graph_remove_unauthorized_chunks(self):
        context = PermissionContext(user_id="alice", team="platform")
        allowed = authorized_chunk_ids(self.db, context)
        self.assertEqual(len(allowed), 3)  # public + platform team + restricted alice

        bm25_results = bm25_search(
            self.db, "semaphore guidance", top_k=20, permission_context=context
        )
        self.assertEqual({item["document_id"] for item in bm25_results}, {
            self.docs["public.pdf"][0].id,
            self.docs["platform-runbook.pdf"][0].id,
            self.docs["restricted.pdf"][0].id,
        })

        graph_results = graph_search(
            self.db, "What is a semaphore?", top_k=20,
            permission_context=context,
        )
        result_ids = {item["document_id"] for item in graph_results}
        self.assertTrue(result_ids)
        self.assertTrue(result_ids.issubset({
            self.docs["public.pdf"][0].id,
            self.docs["platform-runbook.pdf"][0].id,
            self.docs["restricted.pdf"][0].id,
        }))

    def test_realistic_hr_engineering_finance_access_matrix(self):
        cases = (
            (
                PermissionContext(user_id="hr-user", department="HR"),
                {"public.pdf", "hr-handbook.pdf"},
            ),
            (
                PermissionContext(
                    user_id="eng-user",
                    department="Engineering",
                    team="platform",
                ),
                {"public.pdf", "engineering-design.pdf", "platform-runbook.pdf"},
            ),
            (
                PermissionContext(
                    user_id="finance-user",
                    department="Finance",
                    team="finance-ops",
                ),
                {"public.pdf", "finance-close.pdf", "finance-ops.pdf"},
            ),
        )
        document_by_chunk = {
            chunk.id: name for name, (_, chunk) in self.docs.items()
        }
        for context, expected_names in cases:
            visible_names = {
                document_by_chunk[chunk_id]
                for chunk_id in authorized_chunk_ids(self.db, context)
            }
            self.assertEqual(visible_names, expected_names)

            results = bm25_search(
                self.db, "semaphore guidance", top_k=20,
                permission_context=context,
            )
            self.assertEqual(
                {result["filename"] for result in results},
                expected_names,
            )

    def test_dense_filter_is_applied_before_database_results(self):
        from app import retrieval

        class FakeQuery:
            def __init__(self):
                self.filters = []

            def join(self, *_args):
                return self

            def filter(self, *expressions):
                self.filters.extend(expressions)
                return self

            def order_by(self, *_args):
                return self

            def limit(self, *_args):
                return self

            def all(self):
                return []

        class FakeDB:
            def __init__(self):
                self.query_result = FakeQuery()

            def query(self, *_args):
                return self.query_result

        fake_db = FakeDB()
        context = PermissionContext(user_id="eng-user", department="Engineering")
        with patch.object(
            retrieval, "generate_embedding", return_value=[0.0] * 384
        ), patch.object(
            retrieval, "authorized_chunk_ids", return_value={42}
        ):
            self.assertEqual(
                retrieval.semantic_search(
                    fake_db, "engineering", permission_context=context
                ),
                [],
            )
        self.assertTrue(any("document_chunks.id IN" in str(expr)
                            for expr in fake_db.query_result.filters))

    def test_hybrid_forwards_same_acl_context_to_both_retrievers(self):
        from app.hybrid_retrieval import hybrid_search

        context = PermissionContext(
            user_id="finance-user",
            department="Finance",
            team="finance-ops",
        )
        with patch(
            "app.hybrid_retrieval.bm25_search", return_value=[]
        ) as bm25, patch(
            "app.hybrid_retrieval.semantic_search", return_value=[]
        ) as dense:
            self.assertEqual(
                hybrid_search(self.db, "finance", permission_context=context),
                [],
            )
        self.assertIs(bm25.call_args.kwargs["permission_context"], context)
        self.assertIs(dense.call_args.kwargs["permission_context"], context)

if __name__ == "__main__":
    unittest.main()
