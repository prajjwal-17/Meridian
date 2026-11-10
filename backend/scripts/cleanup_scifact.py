"""Safely audit and optionally remove the imported BEIR SciFact corpus.

The default operation is read-only.  Use --execute only after reviewing the
dry-run report and approving the exact deletion set.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ChunkEntityMention,
    Document,
    DocumentChunk,
    Entity,
    EntityRelationship,
)
from app.storage import BUCKET_NAME, s3_client  # noqa: E402


SOURCE_NAME = "beir-scifact"
SOURCE_KEY_PREFIX = "datasets/beir-scifact/"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
ENTERPRISE_DOCUMENT_IDS = set(range(2, 11))


@dataclass
class Snapshot:
    documents: list[Document]
    chunks: list[DocumentChunk]
    chunk_ids: set[int]
    mention_count: int
    embedding_count: int
    entity_ids: set[int]
    exclusive_entity_ids: set[int]
    deletable_relationship_ids: set[int]
    ambiguous_relationship_ids: set[int]
    object_keys: list[str]
    existing_object_keys: set[str]
    orphaned_object_keys: set[str]
    missing_object_keys: set[str]
    ambiguous_document_ids: set[int]
    enterprise_documents: list[Document]
    enterprise_chunk_counts: dict[int, int]


def expected_object_key(source_document_id: str) -> str:
    if not source_document_id or not SAFE_ID.fullmatch(source_document_id):
        raise ValueError(f"Unsafe or missing SciFact source ID: {source_document_id!r}")
    return f"{SOURCE_KEY_PREFIX}{source_document_id}.json"


def list_storage_keys() -> set[str]:
    keys: set[str] = set()
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=SOURCE_KEY_PREFIX):
        keys.update(item["Key"] for item in page.get("Contents", []) if item.get("Key"))
    return keys


def _enterprise_filter():
    return or_(Document.source_name.is_(None), Document.source_name != SOURCE_NAME)


def build_snapshot(db, storage_keys: set[str]) -> Snapshot:
    documents = (
        db.query(Document)
        .filter(Document.source_name == SOURCE_NAME)
        .order_by(Document.id)
        .all()
    )

    object_keys: list[str] = []
    ambiguous_document_ids: set[int] = set()
    for document in documents:
        try:
            expected = expected_object_key(document.source_document_id or "")
        except ValueError:
            ambiguous_document_ids.add(document.id)
            continue
        if document.object_key != expected:
            ambiguous_document_ids.add(document.id)
        object_keys.append(document.object_key)

    document_ids = {document.id for document in documents}
    chunks = []
    if document_ids:
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id.in_(document_ids))
            .order_by(DocumentChunk.id)
            .all()
        )
    chunk_ids = {chunk.id for chunk in chunks}
    mention_rows = []
    if chunk_ids:
        mention_rows = (
            db.query(ChunkEntityMention)
            .filter(ChunkEntityMention.chunk_id.in_(chunk_ids))
            .all()
        )
    entity_ids = {row.entity_id for row in mention_rows}

    exclusive_entity_ids: set[int] = set()
    if entity_ids:
        mention_counts = dict(
            db.query(ChunkEntityMention.entity_id, func.count(ChunkEntityMention.id))
            .filter(ChunkEntityMention.entity_id.in_(entity_ids))
            .group_by(ChunkEntityMention.entity_id)
            .all()
        )
        shared_entity_ids = {
            entity_id
            for entity_id, count in mention_counts.items()
            if count != sum(1 for row in mention_rows if row.entity_id == entity_id)
        }
        # The comparison above is intentionally based on all mentions in the
        # database: an entity is exclusive only when every mention is in a
        # selected SciFact chunk.
        exclusive_entity_ids = entity_ids - shared_entity_ids

    relationship_rows = []
    if entity_ids:
        relationship_rows = (
            db.query(EntityRelationship)
            .filter(
                or_(
                    EntityRelationship.source_entity_id.in_(entity_ids),
                    EntityRelationship.target_entity_id.in_(entity_ids),
                )
            )
            .all()
        )
    deletable_relationship_ids = {
        row.id
        for row in relationship_rows
        if row.source_entity_id in exclusive_entity_ids
        and row.target_entity_id in exclusive_entity_ids
    }
    ambiguous_relationship_ids = {
        row.id
        for row in relationship_rows
        if (row.source_entity_id in exclusive_entity_ids)
        != (row.target_entity_id in exclusive_entity_ids)
    }

    enterprise_documents = db.query(Document).filter(_enterprise_filter()).all()
    enterprise_ids = {document.id for document in enterprise_documents}
    enterprise_chunk_counts = dict(
        db.query(DocumentChunk.document_id, func.count(DocumentChunk.id))
        .filter(DocumentChunk.document_id.in_(enterprise_ids or {-1}))
        .group_by(DocumentChunk.document_id)
        .all()
    )

    expected_keys = set(object_keys)
    return Snapshot(
        documents=documents,
        chunks=chunks,
        chunk_ids=chunk_ids,
        mention_count=len(mention_rows),
        embedding_count=sum(1 for chunk in chunks if chunk.embedding is not None),
        entity_ids=entity_ids,
        exclusive_entity_ids=exclusive_entity_ids,
        deletable_relationship_ids=deletable_relationship_ids,
        ambiguous_relationship_ids=ambiguous_relationship_ids,
        object_keys=object_keys,
        existing_object_keys=storage_keys & expected_keys,
        orphaned_object_keys=storage_keys - expected_keys,
        missing_object_keys=expected_keys - storage_keys,
        ambiguous_document_ids=ambiguous_document_ids,
        enterprise_documents=enterprise_documents,
        enterprise_chunk_counts=enterprise_chunk_counts,
    )


def print_snapshot(snapshot: Snapshot) -> None:
    selected_ids = {document.id for document in snapshot.documents}
    enterprise_ids = {document.id for document in snapshot.enterprise_documents}
    protected_overlap = selected_ids & ENTERPRISE_DOCUMENT_IDS
    print("SciFact cleanup dry-run")
    print(f"  source identity: {SOURCE_NAME!r}")
    print(f"  documents selected: {len(snapshot.documents)}")
    print(f"  chunks selected: {len(snapshot.chunks)}")
    print(f"  embeddings selected: {snapshot.embedding_count}")
    print(f"  chunk entity mentions selected: {snapshot.mention_count}")
    print(f"  referenced entities: {len(snapshot.entity_ids)}")
    print(f"  entities safe to delete: {len(snapshot.exclusive_entity_ids)}")
    print(f"  relationships safe to delete: {len(snapshot.deletable_relationship_ids)}")
    print(f"  ambiguous relationships preserved: {len(snapshot.ambiguous_relationship_ids)}")
    print(f"  storage objects selected: {len(snapshot.object_keys)}")
    print(f"  storage objects found: {len(snapshot.existing_object_keys)}")
    print(f"  missing storage objects: {len(snapshot.missing_object_keys)}")
    print(f"  orphaned objects under SciFact prefix: {len(snapshot.orphaned_object_keys)}")
    print(f"  non-SciFact documents preserved: {len(enterprise_ids)}")
    print(f"  non-SciFact chunks preserved: {sum(snapshot.enterprise_chunk_counts.values())}")
    print(f"  enterprise IDs 2 through 10 selected: {sorted(protected_overlap)}")

    print("\nStorage object keys selected for deletion:")
    for key in sorted(snapshot.object_keys):
        print(f"  {key}")

    if snapshot.missing_object_keys:
        print("\nMissing object keys:")
        for key in sorted(snapshot.missing_object_keys):
            print(f"  {key}")
    if snapshot.orphaned_object_keys:
        print("\nOrphaned object keys (not selected for deletion):")
        for key in sorted(snapshot.orphaned_object_keys):
            print(f"  {key}")
    if snapshot.ambiguous_document_ids:
        print(f"\nAmbiguous document mappings: {sorted(snapshot.ambiguous_document_ids)}")
    if snapshot.ambiguous_relationship_ids:
        print(
            "\nAmbiguous relationships are preserved because relationship rows do not "
            "store chunk provenance."
        )
    if protected_overlap:
        print("\nSAFETY FAILURE: enterprise document IDs overlap the deletion set.")


def validate_snapshot(snapshot: Snapshot) -> None:
    selected_ids = {document.id for document in snapshot.documents}
    overlap = selected_ids & ENTERPRISE_DOCUMENT_IDS
    if overlap:
        raise RuntimeError(f"Deletion set overlaps protected enterprise IDs: {sorted(overlap)}")
    if snapshot.ambiguous_document_ids:
        raise RuntimeError(
            f"Ambiguous SciFact document/object mappings: {sorted(snapshot.ambiguous_document_ids)}"
        )
    if snapshot.missing_object_keys:
        raise RuntimeError("One or more selected SciFact objects are missing from SeaweedFS.")
    if snapshot.orphaned_object_keys:
        raise RuntimeError(
            "Orphaned objects exist under the SciFact prefix; refusing execute until reviewed."
        )
    if snapshot.ambiguous_relationship_ids:
        raise RuntimeError(
            "Relationships touch shared entities without provenance; refusing execute."
        )


def verify_unchanged(before: Snapshot, after: Snapshot) -> None:
    before_by_id = {document.id: document for document in before.enterprise_documents}
    after_by_id = {document.id: document for document in after.enterprise_documents}
    if set(before_by_id) != set(after_by_id):
        raise RuntimeError("Non-SciFact document IDs changed during cleanup.")
    for document_id, original in before_by_id.items():
        current = after_by_id[document_id]
        fields = ("checksum", "permission_tier", "permission_team", "permission_department")
        if any(getattr(original, field) != getattr(current, field) for field in fields):
            raise RuntimeError(f"Protected ACL/checksum changed for document {document_id}.")
        if before.enterprise_chunk_counts.get(document_id, 0) != after.enterprise_chunk_counts.get(document_id, 0):
            raise RuntimeError(f"Protected chunk count changed for document {document_id}.")


def execute_cleanup(db, before: Snapshot) -> None:
    # Rebuild the complete set inside the same database session immediately
    # before mutating anything. Storage is still a separate system.
    storage_keys = list_storage_keys()
    current = build_snapshot(db, storage_keys)
    if (
        {document.id for document in current.documents} != {document.id for document in before.documents}
        or current.chunk_ids != before.chunk_ids
        or set(current.object_keys) != set(before.object_keys)
    ):
        raise RuntimeError("Deletion set changed since the dry-run; refusing execute.")
    validate_snapshot(current)

    document_ids = {document.id for document in current.documents}
    try:
        if current.chunk_ids:
            db.query(ChunkEntityMention).filter(
                ChunkEntityMention.chunk_id.in_(current.chunk_ids)
            ).delete(synchronize_session=False)
        if current.deletable_relationship_ids:
            db.query(EntityRelationship).filter(
                EntityRelationship.id.in_(current.deletable_relationship_ids)
            ).delete(synchronize_session=False)
        if current.exclusive_entity_ids:
            db.query(Entity).filter(Entity.id.in_(current.exclusive_entity_ids)).delete(
                synchronize_session=False
            )
        if document_ids:
            # Database cascades remove chunks and chunk mentions.
            db.query(Document).filter(Document.id.in_(document_ids)).delete(
                synchronize_session=False
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    failed_storage: list[tuple[str, str]] = []
    for key in current.object_keys:
        try:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
        except Exception as exc:  # pragma: no cover - requires live S3 failure
            failed_storage.append((key, str(exc)))
            break
    if failed_storage:
        raise RuntimeError(f"Database committed but storage deletion failed: {failed_storage}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report only; this is the default.")
    mode.add_argument("--execute", action="store_true", help="Delete the verified SciFact set.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        storage_keys = list_storage_keys()
        snapshot = build_snapshot(db, storage_keys)
        print_snapshot(snapshot)
        if not args.execute:
            print("\nNo changes made. Re-run with --execute only after reviewing this report.")
            return 0
        execute_cleanup(db, snapshot)
        remaining = build_snapshot(db, list_storage_keys())
        verify_unchanged(snapshot, remaining)
        if remaining.documents or remaining.chunks or remaining.existing_object_keys:
            raise RuntimeError("Post-execution verification found remaining SciFact data.")
        print("\nCleanup executed and verified.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
