
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

model = SentenceTransformer(MODEL_NAME)


def generate_embedding(text: str) -> list[float]:
    embedding = model.encode(
        text,
        normalize_embeddings=True
    )

    return embedding.tolist()
