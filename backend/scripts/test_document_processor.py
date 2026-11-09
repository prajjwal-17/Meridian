import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.document_processor import process_document
from app.models import ChunkEntityMention, Document, DocumentChunk, Entity, EntityRelationship


class DocumentProcessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        self.db = self.Session()
        self.document = Document(
            filename="motorq.pdf",
            object_key="documents/motorq.pdf",
            content_type="application/pdf",
            file_size=100,
            checksum="b" * 64,
            permission_tier="public",
        )
        self.db.add(self.document)
        self.db.commit()
        self.db.refresh(self.document)

    def tearDown(self):
        self.db.execute(delete(EntityRelationship))
        self.db.execute(delete(ChunkEntityMention))
        self.db.execute(delete(Entity))
        self.db.execute(delete(DocumentChunk))
        self.db.execute(delete(Document))
        self.db.commit()
        self.db.close()

    @patch("app.document_processor.download_file_bytes", return_value=b"%PDF-test")
    @patch("app.document_processor.extract_pdf_text", return_value=[
        {"page_number": 1, "text": "FastAPI uses PostgreSQL for deadlock prevention."},
    ])
    @patch("app.document_processor.generate_embedding", return_value=[0.0] * 384)
    def test_processes_new_document(self, _embedding, _extract, _download):
        result = process_document(self.db, self.document.id)
        self.assertEqual(result.status, "processed")
        self.assertEqual(result.chunks_created, 1)
        self.assertEqual(self.db.query(DocumentChunk).count(), 1)
        self.assertEqual(self.db.get(Document, self.document.id).status, "processed")

    @patch("app.document_processor.download_file_bytes", return_value=b"%PDF-test")
    @patch("app.document_processor.extract_pdf_text", return_value=[
        {"page_number": 1, "text": "FastAPI uses PostgreSQL for deadlock prevention."},
    ])
    @patch("app.document_processor.generate_embedding", return_value=[0.0] * 384)
    def test_retry_is_idempotent(self, embedding, _extract, _download):
        first = process_document(self.db, self.document.id)
        second = process_document(self.db, self.document.id)
        self.assertEqual(first.chunks_created, 1)
        self.assertEqual(second.chunks_created, 0)
        self.assertEqual(second.embeddings_created, 0)
        self.assertEqual(self.db.query(DocumentChunk).count(), 1)
        mention_count = self.db.query(ChunkEntityMention).count()
        self.assertGreater(mention_count, 0)
        self.assertEqual(self.db.query(ChunkEntityMention).count(), mention_count)
        self.assertEqual(embedding.call_count, 1)

    @patch("app.document_processor.download_file_bytes", return_value=b"%PDF-test")
    @patch("app.document_processor.extract_pdf_text", return_value=[
        {"page_number": 1, "text": "Restricted semaphore guidance."},
    ])
    @patch("app.document_processor.generate_embedding", return_value=[0.0] * 384)
    def test_chunks_inherit_document_acl_on_retry(self, _embedding, _extract, _download):
        self.document.permission_tier = "restricted"
        self.document.restricted_user_ids = ["alice"]
        self.db.commit()

        process_document(self.db, self.document.id)
        chunk = self.db.query(DocumentChunk).one()
        self.assertEqual(chunk.permission_tier, "restricted")

        # A stale chunk snapshot is repaired from the document authority.
        chunk.permission_tier = "public"
        self.db.commit()
        process_document(self.db, self.document.id)
        self.db.refresh(self.document)
        self.db.refresh(chunk)
        self.assertEqual(self.document.permission_tier, "restricted")
        self.assertEqual(chunk.permission_tier, "restricted")


if __name__ == "__main__":
    unittest.main()
