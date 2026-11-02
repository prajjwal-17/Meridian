
import tiktoken

encoding = tiktoken.get_encoding("cl100k_base")


def create_chunks(
    text: str,
    chunk_size: int = 500,
    overlap: int = 100
) -> list[dict]:

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("Invalid overlap value")

    tokens = encoding.encode(text)

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(tokens):

        end = min(start + chunk_size, len(tokens))

        chunk_tokens = tokens[start:end]

        chunks.append({
            "chunk_index": chunk_index,
            "text": encoding.decode(chunk_tokens),
            "token_count": len(chunk_tokens)
        })

        chunk_index += 1

        # Stop when the final token has been processed
        if end == len(tokens):
            break

        start = end - overlap

    return chunks
