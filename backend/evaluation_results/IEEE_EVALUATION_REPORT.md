# Meridian Enterprise Retrieval Evaluation

## Scope

This report records a read-only evaluation of the existing Meridian retrieval implementation against eight enterprise access and relevance scenarios. The evaluation was executed against the local PostgreSQL/pgvector database with Hugging Face offline mode enabled. It did not modify documents, chunks, embeddings, ACLs, or storage objects.

The evaluated modes were:

1. BM25
2. Dense vector retrieval
3. Hybrid BM25 + dense using Reciprocal Rank Fusion
4. Hybrid + cross-encoder reranking
5. Entity graph retrieval

The evaluator is reproducible from:

```text
backend/notebooks/meridian_evaluation.py
```

## Evaluation cases

The cases cover:

- HR department access.
- Engineering team and department access.
- Overlapping Finance + Operations access.
- Explicit restricted-document authorization.
- Restricted-document denial.
- Team-specific denial.
- IT department plus Infrastructure team access.
- A question with no expected relevant evidence.

Each case contains a user ID, departments, teams, relevant source IDs, forbidden source IDs, and a natural-language question. The evaluator computes relevance and authorization independently.

## Metrics

For each mode and case, the evaluator records:

- Hit@10.
- MRR@10.
- nDCG@10.
- Mean latency.
- ACL pass rate.
- Forbidden source leakage.
- Returned source IDs and chunk IDs.

The enterprise scenarios use source identities such as `HR-001` and `ENG-003`, rather than internal PostgreSQL document IDs. This keeps the evaluation stable if database IDs change.

## Measured aggregate results

| Mode | Hit@10 | MRR@10 | nDCG@10 | ACL pass rate | Mean latency |
|---|---:|---:|---:|---:|---:|
| BM25 | 1.0000 | 0.5250 | 0.5484 | 1.0000 | 11.84 ms |
| Dense | 1.0000 | 0.5625 | 0.5789 | 1.0000 | 1066.94 ms |
| Hybrid | 1.0000 | 0.5625 | 0.5789 | 1.0000 | 19.84 ms |
| Hybrid + reranker | 1.0000 | 0.6250 | 0.6250 | 1.0000 | 281.74 ms |
| Entity graph | 1.0000 | 0.4792 | 0.4832 | 1.0000 | 50.04 ms |

Observed results:

- All modes achieved Hit@10 = 1.0 on this small enterprise scenario set.
- Hybrid matched dense on MRR and nDCG.
- Hybrid + reranking produced the best MRR and nDCG in this run.
- Entity graph retrieval had lower MRR/nDCG than hybrid + reranking, despite lower average latency than dense retrieval.
- All 40 rows passed the ACL checks.
- No forbidden source IDs were returned in the final run.

These numbers should not be presented as general conclusions. The enterprise test set is small and synthetic. They are valid as a controlled demonstration of the current implementation.

## Runtime observations

The dense mode’s mean latency includes the first local embedding-model initialization. Later calls were much faster. This is why the dense mean is substantially higher than the per-query times printed after the first query.

The cross-encoder was initialized once in the evaluation process and reused across reranking calls. Hybrid+rereanking added model inference time but improved rank-sensitive metrics in this run.

The total five-mode evaluation completed in approximately 11.45 seconds after model caches were available. The first model-loading event made the initial dense and reranker calls substantially slower.

## Security results

The evaluation confirmed:

```text
ACL pass rate: 100% for every evaluated mode
Forbidden-source leakage: 0 rows
```

The permission context was constructed with the same enterprise user IDs, department names, and team names used by the existing corpus metadata. The retrieval implementations call the centralized permission filter before returning chunks. Hybrid reranking performs an additional authorization check immediately before candidate text reaches the cross-encoder.

The test also verified the important distinction between an ACL failure and a relevance failure. For example, the unsupported revenue question returned authorized HR/public material rather than finance material. That is a relevance/abstention issue, not a permission leak.

## Current limitations

- The evaluation set contains eight hand-authored scenarios, not a statistically representative enterprise benchmark.
- Expected relevance labels are document-level source labels, not manually graded passage-level labels.
- Hit@10 is saturated at 1.0 and therefore does not distinguish the modes well; MRR and nDCG are more informative here.
- Entity graph retrieval remains sensitive to rule-based entity quality and graph coverage.
- Answer factuality is not measured by these retrieval metrics.
- Citation integrity does not prove claim-level factual correctness.
- PNG plots were generated successfully after installing the optional notebook dependency and selecting the non-interactive `Agg` backend.

Install the optional notebook dependency before running in Jupyter:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r notebooks\requirements.txt
```

Then rerun the evaluator. It will generate:

```text
backend/evaluation_results/metrics_by_mode.png
backend/evaluation_results/latency_by_mode.png
backend/evaluation_results/acl_and_relevance_heatmap.png
```

## Reproduction command

```powershell
cd "C:\Users\prajj\Desktop\Enterprise RAG\backend"
$env:MERIDIAN_ENV="development"
$env:HF_HUB_OFFLINE="1"

.\.venv\Scripts\python.exe notebooks\meridian_evaluation.py
```

The evaluator writes:

```text
backend/evaluation_results/enterprise_results.csv
backend/evaluation_results/enterprise_results.json
backend/evaluation_results/enterprise_summary.json
```

## Research interpretation

The current evidence supports the following careful statement:

> On the controlled enterprise scenario set, hybrid retrieval with cross-encoder reranking produced the strongest rank-sensitive retrieval results, while all evaluated modes preserved ACL isolation. Entity graph retrieval provided an additional explainable retrieval path but showed lower rank-sensitive relevance than hybrid reranking in this evaluation.

The statement should be accompanied by the dataset size, scenario definitions, model names, top-k value, hardware, database state, and runtime measurements in an IEEE paper.
