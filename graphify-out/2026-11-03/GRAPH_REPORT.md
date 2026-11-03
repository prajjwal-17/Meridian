# Graph Report - Enterprise RAG  (2026-11-03)

## Corpus Check
- 33 files · ~4,785 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 2 file(s) not represented in the graph (top: .example 1, (none) 1)

## Summary
- 147 nodes · 396 edges · 7 communities
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
- database.py
- graph_retrieval.py
- entity_graph.py
- Document

## God Nodes (most connected - your core abstractions)
1. `Document` - 27 edges
2. `DocumentChunk` - 22 edges
3. `process_document()` - 18 edges
4. `index_chunk_entities()` - 16 edges
5. `Entity` - 16 edges
6. `ChunkEntityMention` - 15 edges
7. `Base` - 14 edges
8. `EntityRelationship` - 14 edges
9. `EntityGraphTests` - 14 edges
10. `graph_search()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `bm25_search()` --uses--> `Document`  [INFERRED]
  backend/app/bm25_retrieval.py → backend/app/models.py
- `bm25_search()` --uses--> `DocumentChunk`  [INFERRED]
  backend/app/bm25_retrieval.py → backend/app/models.py
- `upload_document()` --uses--> `DocumentProcessingError`  [INFERRED]
  backend/app/main.py → backend/app/document_processor.py
- `process_document()` --uses--> `Document`  [INFERRED]
  backend/app/document_processor.py → backend/app/models.py
- `index_chunk_entities()` --uses--> `Entity`  [INFERRED]
  backend/app/entity_graph.py → backend/app/models.py

## Import Cycles
- None detected.

## Communities (7 total, 0 thin omitted)

### Community 0 - "main.py"
Cohesion: 0.16
Nodes (15): get_db(), delete_document(), download_document(), get_documents(), health_check(), Session, upload_document(), delete (+7 more)

### Community 1 - "document_processor.py"
Cohesion: 0.11
Nodes (21): argparse, create_chunks(), DocumentProcessingError, generate_embedding(), process_document(), ProcessingResult, Session, Idempotent PDF-to-chunks processing workflow. (+13 more)

### Community 2 - "sqlalchemy_orm"
Cohesion: 0.18
Nodes (11): bm25_search(), Session, tokenize(), generate_embedding(), hybrid_search(), Session, Session, semantic_search() (+3 more)

### Community 4 - "database.py"
Cohesion: 0.13
Nodes (12): download_file(), Upload a file to SeaweedFS., Download a file from SeaweedFS., upload_file(), boto3, botocore_config, botocore_exceptions, dotenv (+4 more)

### Community 6 - "graph_retrieval.py"
Cohesion: 0.24
Nodes (9): extract_entities(), ExtractedEntity, _normalise(), Deterministic entity extraction from document chunks. The extractor…, Extract high-signal technical, organizational, and concept entities., Standalone graph retrieval over persisted entities and chunk mentions., collections, dataclasses (+1 more)

### Community 7 - "entity_graph.py"
Cohesion: 0.22
Nodes (9): _get_or_create_entity(), index_all_chunks(), index_chunk_entities(), Session, Persistence helpers for the document entity graph., Extract and persist entities plus co-occurrence relationships for one chunk., Index chunks not yet represented in the graph; return chunks processed., Non-destructively apply the current extractor to all existing chunks. (+1 more)

### Community 8 - "Document"
Cohesion: 0.15
Nodes (24): Base, graph_search(), Session, Find query entities, traverse relationships, and return related chunks., ChunkEntityMention, Document, DocumentChunk, Entity (+16 more)

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Document` connect `Document` to `main.py`, `document_processor.py`, `sqlalchemy_orm`, `graph_retrieval.py`?**
  _High betweenness centrality (0.168) - this node is a cross-community bridge._
- **Why does `process_document()` connect `document_processor.py` to `Document`, `main.py`, `entity_graph.py`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `DocumentChunk` connect `Document` to `document_processor.py`, `sqlalchemy_orm`, `graph_retrieval.py`, `entity_graph.py`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `Document` (e.g. with `bm25_search()` and `process_document()`) actually correct?**
  _`Document` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `DocumentChunk` (e.g. with `bm25_search()` and `index_all_chunks()`) actually correct?**
  _`DocumentChunk` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Should `document_processor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11083743842364532 - nodes in this community are weakly interconnected._
- **Should `database.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12631578947368421 - nodes in this community are weakly interconnected._