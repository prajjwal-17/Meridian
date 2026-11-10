import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from app.database import Base
from import_scifact import document_metadata, parse_corpus_record, run_import
from app.models import ChunkEntityMention, Document, DocumentChunk, Entity, EntityRelationship
from app.text_processor import process_text_document
class SciFactImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)
    def setUp(self):
        self.db = self.Session()
    def tearDown(self):
        self.db.execute(delete(EntityRelationship))
        self.db.execute(delete(ChunkEntityMention))
        self.db.execute(delete(Entity))
        self.db.execute(delete(DocumentChunk))
        self.db.execute(delete(Document))
        self.db.commit()
        self.db.close()
    def record(self, source_id="4983"):
        return {"_id": source_id, "title": "A study", "text": "Evidence about scientific findings.", "metadata": {}}
    def test_record_validation_and_source_metadata(self):
        record = parse_corpus_record('{"_id":"4983","title":"A study","text":"Evidence.","metadata":{}}', 1)
        metadata = document_metadata(record)
        self.assertEqual(metadata["source_name"], "beir-scifact")
        self.assertEqual(metadata["source_document_id"], "4983")
        self.assertEqual(metadata["content_type"], "application/json")
        with self.assertRaises(ValueError):
            parse_corpus_record('{"_id":"x","title":"missing"}', 2)
    def test_dry_run_parses_without_database_or_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            path.write_text('{"_id":"1","title":"Title","text":"Text","metadata":{}}\n', encoding="utf-8")
            counts = run_import(path, dry_run=True)
        self.assertEqual(counts["processed"], 1)
        self.assertEqual(counts["failed"], 0)
    @patch("app.text_processor.generate_embedding", return_value=[0.0] * 384)
    def test_direct_text_ingestion_is_idempotent_and_inherits_acl(self, embedding):
        document = Document(filename="scifact_1.json", object_key="datasets/beir-scifact/1.json", content_type="application/json", file_size=1, checksum="a" * 64, source_name="beir-scifact", source_document_id="1", permission_tier="public")
        self.db.add(document)
        self.db.commit()
        first = process_text_document(self.db, document.id, "A short scientific text.")
        second = process_text_document(self.db, document.id, "A short scientific text.")
        self.assertEqual(first.chunks_created, 1)
        self.assertEqual(second.chunks_created, 0)
        self.assertEqual(self.db.query(DocumentChunk).count(), 1)
        self.assertEqual(self.db.query(DocumentChunk).one().permission_tier, "public")
        self.assertEqual(embedding.call_count, 1)
    @patch("import_scifact.upload_source_object")
    @patch("import_scifact.process_text_document")
    def test_source_identity_prevents_duplicate_documents(self, process_text, upload):
        from import_scifact import import_record
        document = Document(filename="scifact_1.json", object_key="datasets/beir-scifact/1.json", content_type="application/json", file_size=1, checksum="a" * 64, source_name="beir-scifact", source_document_id="1", permission_tier="public")
        self.db.add(document)
        self.db.commit()
        process_text.return_value = None
        self.assertEqual(import_record(self.db, self.record("1")), "processed")
        self.db.refresh(document)
        document.status = "processed"
        self.db.add(DocumentChunk(document_id=document.id, page_number=1, chunk_index=0, text="existing", token_count=1, permission_tier="public"))
        self.db.commit()
        self.assertEqual(import_record(self.db, self.record("1")), "skipped")
        self.assertEqual(self.db.query(Document).count(), 1)
        upload.assert_not_called()
if __name__ == "__main__":
    unittest.main()
