# Meridian Testing and Retrieval Notes

## What we tested

Meridian was tested as a working FastAPI application backed by PostgreSQL/pgvector, SeaweedFS, the local embedding models, and Ollama. The tests covered both retrieval behavior and the security boundary around document access.

The main test areas were:

- PDF ingestion, extraction, chunking, embeddings, and entity indexing.
- BM25 keyword retrieval.
- Dense vector retrieval using the existing SentenceTransformer embedding model.
- Hybrid retrieval using BM25 + dense Reciprocal Rank Fusion (RRF).
- Optional cross-encoder reranking.
- Entity graph retrieval.
- Document-level ACL filtering for public, department, team, and restricted documents.
- Grounded `/ask` responses through the local Ollama model.
- Multiple fictional users with different departments and team memberships.

The tests deliberately distinguished two concerns:

1. **Authorization:** whether a user is allowed to see a document.
2. **Relevance:** whether the returned document actually answers the question.

A result can be authorized but still be a weak or irrelevant match. The live tests check both where the API exposes enough information to do so.

## Retrieval pipeline

### BM25

BM25 is implemented in `backend/app/bm25_retrieval.py`, mainly in `bm25_search()`.

The implementation tokenizes the query and every authorized chunk, calculates document frequency and term frequency, and ranks chunks by BM25 score. It calculates corpus statistics over the chunks returned after ACL filtering, so an unauthorized chunk is not part of the searchable BM25 corpus.

The focused tests are:

- `backend/scripts/test_bm25_search.py`
- `backend/scripts/test_acl_permissions.py`
- `backend/scripts/test_acl_live.py`

### Dense retrieval

Dense retrieval is implemented in `backend/app/retrieval.py`, in `semantic_search()`.

The query is embedded using the existing lazy-loaded embedding model. PostgreSQL/pgvector orders chunks by cosine distance, ignores chunks without embeddings, and applies the authorized chunk ID filter before returning results.

The focused tests are:

- `backend/scripts/test_semantic_search.py`
- `backend/scripts/test_scifact_acl.py`
- `backend/scripts/test_acl_live.py`

### Hybrid retrieval and RRF

Hybrid retrieval is implemented in `backend/app/hybrid_retrieval.py`, in `hybrid_search()`.

It first requests up to `candidate_k` results from BM25 and dense retrieval. It then identifies chunks by document/page/chunk position and adds one reciprocal-rank contribution for each retrieval list in which the chunk appears.

The RRF calculation is applied at `backend/app/hybrid_retrieval.py:83-85`:

```python
# Reciprocal Rank Fusion
fused_results[key]["rrf_score"] += (
    1 / (rrf_k + rank)
)
```

The default `rrf_k` is `60`. Results are sorted by `rrf_score` at `backend/app/hybrid_retrieval.py:99`, and the original score is retained in every result as `rrf_score`.

When reranking is enabled, the hybrid results are ACL-checked again immediately before their text is passed to the cross-encoder. This defense-in-depth check is at `backend/app/hybrid_retrieval.py:113-120`.

The focused tests are:

- `backend/scripts/test_hybrid_search.py`
- `backend/scripts/test_reranker.py`
- `backend/scripts/test_reranker_live.py`

## Cross-encoder reranking

The reranker is isolated in `backend/app/reranker.py`, in `rerank_candidates()`.

The model is loaded lazily and reused within the process. It scores `(query, chunk_text)` pairs and sorts candidates by descending `cross_encoder_score`. The original `rrf_score` remains separate, so RRF and cross-encoder scores are not confused.

The reranker also requires an explicit `PermissionContext` and an ACL-filtered set of authorized chunk IDs. Candidates without an authorized persisted chunk ID are removed before the model sees their text.

The live reranker validation checks:

- `rerank=false` returns hybrid results with RRF scores and no cross-encoder scores.
- `rerank=true` returns cross-encoder scores while preserving RRF scores.
- Scores are ordered descending.
- The cross-encoder receives only authorized candidates.
- Missing identity is rejected with HTTP 401.

Reranking generally improves precision because it evaluates query/passage relevance jointly instead of relying only on lexical overlap or vector similarity. It costs more time than plain hybrid retrieval because every candidate passage must be scored by the cross-encoder.

## Entity graph retrieval

Entity graph retrieval is implemented in `backend/app/graph_retrieval.py`, in `graph_search()`.

The graph path:

1. Extracts query entities using `backend/app/entity_extractor.py`.
2. Matches persisted entities.
3. Traverses explicitly typed relationships.
4. Excludes broad `co_occurs` relationships from relevance propagation.
5. Restricts mentions to ACL-authorized chunks.
6. Returns graph metadata such as matched entities, relationships, and graph scores.

The related persistence and indexing logic is in `backend/app/entity_graph.py`. Focused tests are in:

- `backend/scripts/test_entity_graph.py`
- `backend/scripts/diagnose_entity_graph.py`
- `backend/scripts/refresh_entity_graph.py`

The graph path is often faster for a narrow, entity-driven question because it searches a smaller relationship/mention surface. However, the current rule-based entity extraction and graph data are less precise than hybrid retrieval plus cross-encoder reranking. We observed noisy entity classifications and weak graph matches in some earlier tests. Therefore, entity graph retrieval is useful for exploration and direct entity connections, but it should not currently be treated as the highest-quality answer path.

That is a measured product observation from the current demo corpus, not a universal performance claim. The formal SciFact benchmark evaluated BM25, dense, hybrid, and hybrid plus reranking; graph retrieval was not part of that four-way benchmark.

## ACL enforcement

ACL logic is centralized in `backend/app/permissions.py`.

`PermissionContext` carries the development identity and its permissions. `authorized_chunk_ids()` resolves the chunks that the context may access. The same centralized policy is reused by:

- `backend/app/bm25_retrieval.py:31-32`
- `backend/app/retrieval.py:30-31`
- `backend/app/graph_retrieval.py:78-79`
- `backend/app/hybrid_retrieval.py:113-120`
- `backend/app/answer_generation.py:303`

The API routes are registered in `backend/app/main.py`:

- `GET /search` at line 354.
- `POST /ask` at line 401.

Both routes receive the permission context through the authenticated dependency. Missing identity fails closed. The important security sequence is:

```text
authenticated identity
        -> PermissionContext
        -> authorized chunk IDs
        -> retrieval candidates
        -> optional reranking
        -> evidence selection
        -> Ollama context
```

Unauthorized chunks are therefore excluded before reranking, evidence selection, and answer generation. The live multi-user tests specifically checked that users could retrieve documents from their department or team while forbidden documents did not appear in results or citations.

## Answer generation and citations

Grounded answer generation is implemented in `backend/app/answer_generation.py` and exposed through `POST /ask` in `backend/app/main.py`.

The answer pipeline:

1. Selects the requested retrieval mode.
2. Preserves the authenticated `PermissionContext`.
3. Applies the existing reranker by default for `/ask` unless explicitly disabled.
4. Selects evidence from authorized results.
5. Assigns stable citation IDs such as `C1` and `C2`.
6. Sends only selected authorized passages to the local Ollama model.
7. Validates citations against actual retrieved chunks.

The answer response preserves document ID, chunk ID, filename, page number, source identity, RRF score, and cross-encoder score when available. Citation integrity tests verify that answer citations map back to real retrieved document/chunk pairs.

Citation integrity is not the same as factual verification. A citation can point to a real chunk while the answer still overstates or misinterprets that chunk. Claim-level verification has intentionally not been implemented yet.

## Multi-user validation

The reusable live scenario runner is:

```text
backend/scripts/test_multi_user_scenarios.py
```

It exercises fictional users across HR, Engineering, Finance, IT/Security, and Operations. Scenarios cover:

- Department-authorized documents.
- Team-authorized documents.
- Restricted documents.
- Users with multiple department/team memberships.
- Unauthorized cross-department questions.
- Questions with insufficient evidence.
- BM25, dense, and hybrid modes.
- Grounded `/ask` answers through Ollama.

The latest recorded live run completed with:

```text
Total passed checks: 40
Total failed checks: 0
```

The live answer-generation validation also completed with 41 checks passed and 0 failures. These results validate API behavior, ACL isolation, response structure, citation mapping, and local Ollama connectivity. They do not prove that every generated sentence is factually correct.

## Main limitations found

- Entity graph retrieval is currently less accurate than hybrid plus cross-encoder reranking because rule-based extraction and graph relationships can be noisy.
- BM25 and dense retrieval can return authorized but weakly relevant passages; authorization does not guarantee relevance.
- Cross-encoder reranking improves candidate ordering but adds significant inference cost.
- Citation validation confirms source identity and chunk mapping, not claim-level truth.
- Live answer quality depends on the local Ollama model and its prompt-following behavior.
- The graph path was validated functionally, but it was not included in the formal SciFact metric comparison.

## Useful verification commands

From the backend directory:

```powershell
$env:HF_HUB_OFFLINE="1"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:OLLAMA_MODEL="llama3:latest"

.\.venv\Scripts\python.exe scripts\test_bm25_search.py
.\.venv\Scripts\python.exe scripts\test_semantic_search.py
.\.venv\Scripts\python.exe scripts\test_hybrid_search.py
.\.venv\Scripts\python.exe scripts\test_reranker.py
.\.venv\Scripts\python.exe scripts\test_reranker_live.py
.\.venv\Scripts\python.exe scripts\test_entity_graph.py
.\.venv\Scripts\python.exe scripts\test_acl_permissions.py
.\.venv\Scripts\python.exe scripts\test_multi_user_scenarios.py --timeout 180
.\.venv\Scripts\python.exe scripts\test_answer_generation.py
.\.venv\Scripts\python.exe scripts\test_answer_generation_live.py --timeout 180
```

The frontend build is checked separately from `frontend/`:

```powershell
npm.cmd run build
```

