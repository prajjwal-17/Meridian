
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.hybrid_retrieval import hybrid_search


db = SessionLocal()

try:
    query = "What operating system concepts should a CSE scientist know?"

    results = hybrid_search(
        db=db,
        query=query,
        top_k=5
    )

    print("\n========== HYBRID SEARCH RESULTS ==========")
    print(f"Query: {query}")
    print(f"Results found: {len(results)}")

    for index, result in enumerate(results, start=1):
        print(f"\n--- Result {index} ---")
        print(f"Document: {result['filename']}")
        print(f"Page: {result['page_number']}")
        print(f"Chunk: {result['chunk_index']}")
        print(f"RRF score: {result['rrf_score']:.6f}")
        print(f"Sources: {result['retrieval_sources']}")
        print(f"Text:\n{result['text']}")

finally:
    db.close()
