"""Persistence helpers for the document entity graph."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.entity_extractor import ExtractedEntity, extract_entities
from app.models import ChunkEntityMention, Entity, EntityRelationship


def _get_or_create_entity(db: Session, name: str, entity_type: str) -> Entity:
    normalized = name.strip().lower()
    entity = db.scalar(select(Entity).where(Entity.normalized_name == normalized))
    if entity is None:
        entity = Entity(name=name.strip(), normalized_name=normalized, entity_type=entity_type)
        db.add(entity)
        db.flush()
    return entity


def index_chunk_entities(db: Session, chunk_id: int, text: str) -> list[Entity]:
    """Extract and persist entities plus co-occurrence relationships for one chunk."""

    extracted = extract_entities(text)
    # A term can be detected by more than one conservative rule (for example,
    # an acronym that is also in the technology vocabulary). Collapse those
    # detections before persisting the unique chunk/entity constraint.
    unique_extracted: dict[str, ExtractedEntity] = {}
    for item in extracted:
        key = item.name.strip().lower()
        previous = unique_extracted.get(key)
        if previous is None:
            unique_extracted[key] = item
        else:
            unique_extracted[key] = ExtractedEntity(
                name=previous.name,
                entity_type=previous.entity_type,
                mention_count=previous.mention_count + item.mention_count,
            )

    extracted = list(unique_extracted.values())
    entities = [_get_or_create_entity(db, item.name, item.entity_type) for item in extracted]

    new_entity_ids = set()
    for item, entity in zip(extracted, entities):
        mention = db.scalar(
            select(ChunkEntityMention).where(
                ChunkEntityMention.chunk_id == chunk_id,
                ChunkEntityMention.entity_id == entity.id,
            )
        )
        if mention is None:
            db.add(ChunkEntityMention(chunk_id=chunk_id, entity_id=entity.id, mention_count=item.mention_count))
            new_entity_ids.add(entity.id)
        else:
            mention.mention_count = item.mention_count

    for source in entities:
        for target in entities:
            if source.id >= target.id:
                continue
            # Relationship weight counts indexed chunks, not repeated indexing runs.
            # On a reindex, only pairs containing a newly-added mention are new evidence.
            if not new_entity_ids or (source.id not in new_entity_ids and target.id not in new_entity_ids):
                continue
            relationship = db.scalar(
                select(EntityRelationship).where(
                    EntityRelationship.source_entity_id == source.id,
                    EntityRelationship.target_entity_id == target.id,
                    EntityRelationship.relationship_type == "co_occurs",
                )
            )
            if relationship is None:
                db.add(EntityRelationship(
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    relationship_type="co_occurs",
                    weight=1,
                ))
            else:
                relationship.weight += 1

    db.flush()
    return entities


def index_all_chunks(db: Session, reindex: bool = False) -> int:
    """Index chunks not yet represented in the graph; return chunks processed."""

    from app.models import DocumentChunk

    indexed_chunk_ids = db.scalars(select(ChunkEntityMention.chunk_id).distinct()).all()
    indexed = set(indexed_chunk_ids)
    chunks = db.scalars(select(DocumentChunk).order_by(DocumentChunk.id)).all()
    processed = 0
    for chunk in chunks:
        if reindex or chunk.id not in indexed:
            index_chunk_entities(db, chunk.id, chunk.text)
            processed += 1
    db.commit()
    return processed
