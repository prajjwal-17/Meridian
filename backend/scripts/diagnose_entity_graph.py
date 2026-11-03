"""Read-only PostgreSQL diagnostics for the persisted entity graph."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.database import SessionLocal
from app.graph_retrieval import graph_search
from app.models import ChunkEntityMention, Document, DocumentChunk, Entity, EntityRelationship


QUERIES = (
    "What is a semaphore?",
    "Explain deadlock prevention.",
    "What operating system concepts are relevant to a CSE scientist?",
)


def print_counts(db):
    print("Entity graph counts")
    documents = db.scalars(select(Document).order_by(Document.id)).all()
    print("  documents: " + ", ".join(f"{doc.id}={doc.status}" for doc in documents))
    print(f"  entities: {db.scalar(select(func.count()).select_from(Entity))}")
    print(f"  chunk mentions: {db.scalar(select(func.count()).select_from(ChunkEntityMention))}")
    print(f"  relationships: {db.scalar(select(func.count()).select_from(EntityRelationship))}")
    print(f"  document chunks: {db.scalar(select(func.count()).select_from(DocumentChunk))}")
    print()


def print_links(db, limit: int = 50):
    rows = db.execute(
        select(
            Entity.name,
            Entity.entity_type,
            ChunkEntityMention.mention_count,
            DocumentChunk.id.label("chunk_id"),
            Document.id.label("document_id"),
            Document.filename,
            DocumentChunk.page_number,
            DocumentChunk.chunk_index,
        )
        .join(ChunkEntityMention, ChunkEntityMention.entity_id == Entity.id)
        .join(DocumentChunk, DocumentChunk.id == ChunkEntityMention.chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .order_by(Entity.name, DocumentChunk.id)
        .limit(limit)
    ).all()
    print(f"Linked entity mentions (showing up to {limit})")
    for row in rows:
        print(
            f"  entity={row.name!r} type={row.entity_type} mentions={row.mention_count} "
            f"chunk_id={row.chunk_id} document_id={row.document_id} filename={row.filename!r} "
            f"page={row.page_number} chunk_index={row.chunk_index}"
        )
    if not rows:
        print("  (none)")
    print()


def print_relationships(db, limit: int = 50):
    source_entity = aliased(Entity)
    target_entity = aliased(Entity)
    rows = db.execute(
        select(
            source_entity.name.label("source_name"),
            EntityRelationship.relationship_type,
            EntityRelationship.weight,
            target_entity.name.label("target_name"),
        )
        .join(source_entity, source_entity.id == EntityRelationship.source_entity_id)
        .join(target_entity, target_entity.id == EntityRelationship.target_entity_id)
        .limit(limit)
    ).all()
    print(f"Entity relationships (showing up to {limit})")
    for row in rows:
        print(f"  {row.source_name} -[{row.relationship_type}, weight={row.weight}]-> {row.target_name}")
    if not rows:
        print("  (none)")
    print()


def print_retrieval(db, query: str):
    print(f"Query: {query}")
    results = graph_search(db, query, top_k=5, max_hops=1)
    if not results:
        print("  (no graph retrieval results)")
        print()
        return
    for result in results:
        print(
            f"  score={result['graph_score']:.3f} chunk_id={result['chunk_id']} "
            f"document_id={result['document_id']} filename={result['filename']!r} "
            f"page={result['page_number']} chunk_index={result['chunk_index']}"
        )
        print(f"    matched_entities={[entity['name'] for entity in result['matched_entities']]}")
        print(f"    linked_entities={[entity['name'] for entity in result['entities']]}")
        print(f"    relationships={len(result['relationships'])}")
        print(f"    text={result['text'][:240]!r}")
    print()


with SessionLocal() as db:
    print_counts(db)
    print_links(db)
    print_relationships(db)
    for query in QUERIES:
        print_retrieval(db, query)
