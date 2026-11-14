# Meridian High-Level Design (HLD)

## 1. System overview

Meridian is an enterprise Retrieval-Augmented Generation (RAG) platform with:

- A React/Vite frontend for chat, document upload, and graph exploration.
- A FastAPI backend for authentication, ACL enforcement, ingestion, retrieval, reranking, and grounded answer generation.
- PostgreSQL with pgvector for metadata, ACL-aware chunks, and embeddings.
- SeaweedFS for original document object storage.
- Ollama for local grounded response generation.

## 2. Mermaid architecture diagram

```mermaid
flowchart LR
    U[Enterprise User] --> FE[Frontend\nReact + Vite]
    FE -->|/search, /ask, /upload| API[Backend API\nFastAPI]

    API --> AUTH[Auth + RBAC + ACL\nPermissionContext]
    API --> INGEST[Document Ingestion\nExtract -> Chunk -> Embed]
    API --> RET[Retrieval Layer\nBM25 | Dense | Hybrid | Graph]
    API --> RERANK[Cross-Encoder\nReranker]
    API --> GEN[Grounded Answer Generation\nCitation Mapping]

    INGEST --> DB[(PostgreSQL + pgvector)]
    RET --> DB
    AUTH --> DB
    RERANK --> DB
    GEN --> OLLAMA[Ollama Local LLM]

    API --> FS[(SeaweedFS\nDocument Blob Storage)]
    INGEST --> FS
```

## 3. Request flow (HLD)

1. User signs in and accesses Meridian through the frontend.
2. Frontend calls backend APIs for search, ask, and document operations.
3. Backend resolves user identity and builds `PermissionContext`.
4. ACL filtering determines authorized chunks before retrieval/reranking.
5. Retrieval runs in selected mode (BM25, Dense, Hybrid, or Graph).
6. Optional reranking improves relevance ordering.
7. For `/ask`, only authorized evidence is passed to Ollama.
8. Backend returns answer + citations + retrieval metadata to frontend.

## 4. Data flow (ingestion)

1. Upload document from frontend.
2. Backend stores original file in SeaweedFS.
3. Backend extracts text, chunks content, computes embeddings.
4. Backend persists document/chunk/ACL/embedding metadata in PostgreSQL + pgvector.
5. Entity extraction/indexing updates graph-aware retrieval structures.

## 5. Security and access control boundaries

- ACL decisions are centralized in backend permission logic.
- Unauthorized chunks are filtered out before retrieval output is used by reranker or LLM context.
- Platform roles and document ACLs are evaluated through database-backed user/team/department mappings.
