from datetime import datetime
from sqlalchemy import Column, Integer, ForeignKey, Text, UniqueConstraint, Index, JSON

from pgvector.sqlalchemy import Vector

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="uploaded")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    # ACL metadata is explicit so missing/invalid values can fail closed.
    permission_tier: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    permission_team: Mapped[str | None] = mapped_column(String(100), nullable=True)
    permission_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    restricted_user_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    embedding = Column(Vector(384), nullable=True)
    page_number = Column(Integer, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False)
    # Snapshot of the document ACL at processing time. Null is deny-by-default.
    permission_tier = Column(String(20), nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "page_number",
            "chunk_index",
            name="uq_document_page_chunk"
        ),
    )


class Entity(Base):
    """A normalized, retrievable concept mentioned by one or more chunks."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        Index("ix_entities_entity_type", "entity_type"),
        Index("ix_entities_name", "name"),
    )


class ChunkEntityMention(Base):
    """Associates an entity with the document chunk where it was mentioned."""

    __tablename__ = "chunk_entity_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chunk_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("chunk_id", "entity_id", name="uq_chunk_entity_mention"),
    )


class EntityRelationship(Base):
    """A directed, typed relationship between two normalized entities."""

    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            name="uq_entity_relationship",
        ),
        Index("ix_entity_relationship_target", "target_entity_id"),
    )
