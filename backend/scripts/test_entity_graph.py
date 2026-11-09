import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.entity_extractor import extract_entities
from app.entity_graph import index_chunk_entities
from app.graph_retrieval import graph_search
from app.permissions import PermissionContext
from app.models import ChunkEntityMention, Document, DocumentChunk, Entity, EntityRelationship


class EntityGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        self.db = self.Session()
        document = Document(
            filename="architecture.pdf", object_key=f"{self._testMethodName}.pdf", content_type="application/pdf",
            file_size=10, checksum="a" * 64, permission_tier="public",
        )
        self.db.add(document)
        self.db.flush()
        self.chunk = DocumentChunk(
            document_id=document.id, page_number=1, chunk_index=0,
            text="FastAPI uses SQLAlchemy with PostgreSQL and pgvector for hybrid search.",
            token_count=10, permission_tier="public",
        )
        self.db.add(self.chunk)
        self.db.flush()

    def tearDown(self):
        self.db.execute(delete(EntityRelationship))
        self.db.execute(delete(ChunkEntityMention))
        self.db.execute(delete(Entity))
        self.db.execute(delete(DocumentChunk))
        self.db.execute(delete(Document))
        self.db.commit()
        self.db.rollback()
        self.db.close()

    def test_extractor_returns_high_signal_entities(self):
        entities = extract_entities(
            "ROLE TITLE: Area What Pick Any. FastAPI uses SQLAlchemy for semantic search. "
            "Machine Learning and Deep Learning support the system. Semaphores prevent deadlock."
        )
        names = {entity.name.lower() for entity in entities}
        by_name = {entity.name.lower(): entity for entity in entities}
        self.assertIn("fastapi", names)
        self.assertIn("sqlalchemy", names)
        self.assertIn("semantic search", names)
        self.assertIn("semaphores", names)
        self.assertIn("deadlock", names)
        self.assertNotIn("user", names)
        self.assertNotIn("role", names)
        self.assertNotIn("title", names)
        self.assertNotIn("area what", names)
        self.assertNotIn("pick any", names)
        self.assertEqual(by_name["machine learning"].entity_type, "concept")
        self.assertEqual(by_name["deep learning"].entity_type, "concept")

    def test_entities_mentions_and_relationships_persist(self):
        index_chunk_entities(self.db, self.chunk.id, self.chunk.text)
        self.db.commit()
        self.assertGreater(self.db.query(Entity).count(), 2)
        self.assertEqual(self.db.query(ChunkEntityMention).count(), self.db.query(Entity).count())
        self.assertGreater(self.db.query(EntityRelationship).count(), 0)

    def test_duplicate_detector_hits_do_not_duplicate_mentions(self):
        index_chunk_entities(self.db, self.chunk.id, "Python Python CSE CSE")
        self.db.commit()
        self.assertEqual(
            self.db.query(ChunkEntityMention).count(),
            self.db.query(Entity).count(),
        )

    def test_graph_retrieval_returns_related_chunk(self):
        index_chunk_entities(self.db, self.chunk.id, self.chunk.text)
        self.db.commit()
        results = graph_search(
            self.db, "How does PostgreSQL support hybrid search?", top_k=5,
            permission_context=PermissionContext(user_id="tester"),
        )
        self.assertEqual(results[0]["chunk_id"], self.chunk.id)
        self.assertEqual(results[0]["filename"], "architecture.pdf")
        self.assertTrue(results[0]["matched_entities"])
        self.assertIn("relationships", results[0])

    def test_cooccurrence_does_not_propagate_to_unrelated_chunk(self):
        second_document = Document(
            filename="unrelated.pdf", object_key="unrelated.pdf", content_type="application/pdf",
            file_size=10, checksum="c" * 64, permission_tier="public",
        )
        self.db.add(second_document)
        self.db.flush()
        unrelated_chunk = DocumentChunk(
            document_id=second_document.id, page_number=1, chunk_index=0,
            text="Python and PostgreSQL throughput engineering.", token_count=6,
            permission_tier="public",
        )
        self.db.add(unrelated_chunk)
        self.db.flush()

        index_chunk_entities(self.db, self.chunk.id, "Semaphore uses Python for synchronization.")
        index_chunk_entities(self.db, unrelated_chunk.id, unrelated_chunk.text)
        self.db.commit()

        results = graph_search(
            self.db, "What is a semaphore?", top_k=10,
            permission_context=PermissionContext(user_id="tester"),
        )
        result_chunk_ids = {result["chunk_id"] for result in results}
        self.assertIn(self.chunk.id, result_chunk_ids)
        self.assertNotIn(unrelated_chunk.id, result_chunk_ids)


if __name__ == "__main__":
    unittest.main()
