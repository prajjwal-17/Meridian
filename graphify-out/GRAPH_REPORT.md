# Graph Report - Enterprise RAG  (2026-11-03)

## Corpus Check
- 33 files · ~5,000 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 2 file(s) not represented in the graph (top: .example 1, (none) 1)

## Summary
- 149 nodes · 404 edges · 8 communities (7 shown, 1 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 41 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2d99c799`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- main.py
- document_processor.py
- sqlalchemy_orm
- DocumentProcessorTests
- test_file_storage.py
- index_chunk_entities
- database.py
- Document

## God Nodes (most connected - your core abstractions)
1. `Document` - 28 edges
2. `DocumentChunk` - 23 edges
3. `process_document()` - 18 edges
4. `index_chunk_entities()` - 17 edges
5. `Entity` - 16 edges
6. `ChunkEntityMention` - 15 edges
7. `EntityGraphTests` - 15 edges
8. `Base` - 14 edges
9. `graph_search()` - 14 edges
10. `EntityRelationship` - 14 edges

## Surprising Connections (you probably didn't know these)
- `bm25_search()` --uses--> `Document`  [INFERRED]
  backend/app/bm25_retrieval.py → backend/app/models.py
- `bm25_search()` --uses--> `DocumentChunk`  [INFERRED]
  backend/app/bm25_retrieval.py → backend/app/models.py
- `DocumentProcessorTests` --uses--> `Base`  [INFERRED]
  backend/scripts/test_document_processor.py → backend/app/database.py
- `process_document()` --uses--> `Document`  [INFERRED]
  backend/app/document_processor.py → backend/app/models.py
- `index_chunk_entities()` --uses--> `Entity`  [INFERRED]
  backend/app/entity_graph.py → backend/app/models.py

## Import Cycles
- None detected.

## Communities (8 total, 1 thin omitted)

### Community 0 - "main.py"
Cohesion: 0.14
Nodes (18): get_db(), DocumentProcessingError, Raised after a document is retained but processing failed., delete_document(), download_document(), get_documents(), health_check(), Session (+10 more)

### Community 1 - "document_processor.py"
Cohesion: 0.11
Nodes (20): create_chunks(), generate_embedding(), process_document(), ProcessingResult, Session, Idempotent PDF-to-chunks processing workflow., Load the embedding model only when a chunk actually needs embedding., Extract, chunk, embed, and graph-index one document without duplicates. (+12 more)

### Community 2 - "sqlalchemy_orm"
Cohesion: 0.18
Nodes (12): bm25_search(), Session, tokenize(), generate_embedding(), hybrid_search(), Session, Session, semantic_search() (+4 more)

### Community 4 - "test_file_storage.py"
Cohesion: 0.33
Nodes (4): boto3, botocore_config, botocore_exceptions, hashlib

### Community 6 - "index_chunk_entities"
Cohesion: 0.21
Nodes (12): extract_entities(), ExtractedEntity, _is_usable_proper_name(), _normalise(), Deterministic entity extraction from document chunks. The extractor…, Extract high-signal technical, organizational, and concept entities., _get_or_create_entity(), index_chunk_entities() (+4 more)

### Community 7 - "database.py"
Cohesion: 0.21
Nodes (10): argparse, index_all_chunks(), Persistence helpers for the document entity graph., Index chunks not yet represented in the graph; return chunks processed., Process existing uploaded documents without uploading them again., Non-destructively apply the current extractor to all existing chunks., pathlib, sqlalchemy (+2 more)

### Community 8 - "Document"
Cohesion: 0.15
Nodes (24): Base, graph_search(), Session, Standalone graph retrieval over persisted entities and chunk mentions., Find query entities, traverse relationships, and return related chunks., ChunkEntityMention, Document, DocumentChunk (+16 more)

## Knowledge Gaps
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Document` connect `Document` to `main.py`, `document_processor.py`, `sqlalchemy_orm`, `DocumentProcessorTests`, `database.py`?**
  _High betweenness centrality (0.170) - this node is a cross-community bridge._
- **Why does `process_document()` connect `document_processor.py` to `main.py`, `DocumentProcessorTests`, `index_chunk_entities`, `database.py`, `Document`?**
  _High betweenness centrality (0.098) - this node is a cross-community bridge._
- **Why does `DocumentChunk` connect `Document` to `document_processor.py`, `sqlalchemy_orm`, `DocumentProcessorTests`, `database.py`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `Document` (e.g. with `bm25_search()` and `process_document()`) actually correct?**
  _`Document` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `DocumentChunk` (e.g. with `bm25_search()` and `index_all_chunks()`) actually correct?**
  _`DocumentChunk` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Should `main.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1368421052631579 - nodes in this community are weakly interconnected._
- **Should `document_processor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11396011396011396 - nodes in this community are weakly interconnected._