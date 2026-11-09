"""Standalone graph retrieval over persisted entities and chunk mentions."""

from __future__ import annotations

from collections import deque
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.entity_extractor import extract_entities
from app.models import ChunkEntityMention, Document, DocumentChunk, Entity, EntityRelationship
from app.permissions import PermissionContext, authorized_chunk_ids


def graph_search(
    db: Session,
    query: str,
    top_k: int = 5,
    max_hops: int = 1,
    permission_context: PermissionContext | None = None,
) -> list[dict]:
    """Find query entities, traverse relationships, and return related chunks."""

    if not query.strip():
        raise ValueError("Search query cannot be empty")
    if top_k <= 0 or max_hops < 0:
        raise ValueError("top_k must be positive and max_hops cannot be negative")

    terms = {item.name.lower() for item in extract_entities(query)}
    query_words = {word.lower() for word in re.findall(r"[A-Za-z0-9_+-]+", query) if len(word) > 2}
    if not terms:
        terms = query_words

    matched = db.scalars(
        select(Entity).where(
            or_(*[
                Entity.normalized_name.like(f"%{term}%")
                for term in terms
            ])
        )
    ).all() if terms else []

    distances = {entity.id: 0 for entity in matched}
    entities_by_id = {entity.id: entity for entity in matched}
    traversed_relationships = []
    queue = deque(matched)
    while queue:
        entity = queue.popleft()
        distance = distances[entity.id]
        if distance >= max_hops:
            continue
        edges = db.scalars(
            select(EntityRelationship).where(
                or_(
                    EntityRelationship.source_entity_id == entity.id,
                    EntityRelationship.target_entity_id == entity.id,
                ),
                # Broad co-occurrence is useful for analysis but is not a
                # sufficiently specific retrieval signal. Only explicitly
                # typed relationships may propagate a query beyond direct
                # chunk mentions.
                EntityRelationship.relationship_type != "co_occurs",
            )
        ).all()
        for edge in edges:
            neighbour_id = edge.target_entity_id if edge.source_entity_id == entity.id else edge.source_entity_id
            if neighbour_id not in distances:
                neighbour = db.get(Entity, neighbour_id)
                distances[neighbour_id] = distance + 1
                entities_by_id[neighbour_id] = neighbour
                queue.append(neighbour)
            traversed_relationships.append(edge)

    if not distances:
        return []

    allowed_ids = authorized_chunk_ids(
        db, permission_context or PermissionContext()
    )
    if not allowed_ids:
        return []

    mentions = db.scalars(
        select(ChunkEntityMention).where(
            ChunkEntityMention.entity_id.in_(distances),
            ChunkEntityMention.chunk_id.in_(allowed_ids),
        )
    ).all()
    scores = {}
    for mention in mentions:
        entity_distance = distances[mention.entity_id]
        direct_score = 1.0 if entity_distance == 0 else 0.5 / (1 + entity_distance)
        scores[mention.chunk_id] = max(scores.get(mention.chunk_id, 0), direct_score)

    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(scores))).all()
    documents = {doc.id: doc.filename for doc in db.scalars(select(Document)).all()}
    results = [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "filename": documents.get(chunk.document_id),
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "graph_score": scores[chunk.id],
            "matched_entities": [
                {
                    "id": entity.id,
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                }
                for entity in matched
            ],
            "entities": [
                {
                    "id": entity_id,
                    "name": entities_by_id[entity_id].name,
                    "entity_type": entities_by_id[entity_id].entity_type,
                    "distance": distances[entity_id],
                }
                for entity_id in {
                    mention.entity_id
                    for mention in mentions
                    if mention.chunk_id == chunk.id
                }
                if entity_id in entities_by_id
            ],
            "relationships": [
                {
                    "source_entity_id": edge.source_entity_id,
                    "target_entity_id": edge.target_entity_id,
                    "relationship_type": edge.relationship_type,
                    "weight": edge.weight,
                }
                for edge in traversed_relationships
            ],
        }
        for chunk in chunks
    ]
    results.sort(key=lambda result: result["graph_score"], reverse=True)
    return results[:top_k]
