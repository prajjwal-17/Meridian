import csv
import json
import shutil
import ssl
import urllib.request
import zipfile

from pathlib import Path

import certifi


# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "data"
ZIP_PATH = DATA_DIR / "scifact.zip"
EXTRACT_DIR = DATA_DIR / "scifact"

URL = (
    "https://public.ukp.informatik.tu-darmstadt.de/"
    "thakur/BEIR/datasets/scifact.zip"
)


# ==========================================
# DOWNLOAD DATASET
# ==========================================

def download_dataset():

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not ZIP_PATH.exists():

        print("Downloading BEIR SciFact dataset...")

        # Use Certifi's trusted CA certificate bundle.
        ssl_context = ssl.create_default_context(
            cafile=certifi.where()
        )

        request = urllib.request.Request(
            URL,
            headers={
                "User-Agent": "Meridian-RAG-Dataset-Downloader/1.0"
            }
        )

        try:
            with urllib.request.urlopen(
                request,
                context=ssl_context,
                timeout=120
            ) as response:

                with open(ZIP_PATH, "wb") as output:
                    shutil.copyfileobj(response, output)

            print("Download completed.")

        except Exception:
            if ZIP_PATH.exists():
                ZIP_PATH.unlink()

            raise

    else:
        print("Dataset archive already exists.")

    # ======================================
    # EXTRACT DATASET
    # ======================================

    if not (EXTRACT_DIR / "corpus.jsonl").exists():

        print("Extracting dataset...")

        with zipfile.ZipFile(ZIP_PATH, "r") as archive:
            archive.extractall(DATA_DIR)

        print("Extraction completed.")

    # ======================================
    # VERIFY FILES
    # ======================================

    print("\nChecking dataset files...")

    required_files = [
        EXTRACT_DIR / "corpus.jsonl",
        EXTRACT_DIR / "queries.jsonl",
        EXTRACT_DIR / "qrels" / "test.tsv"
    ]

    for file_path in required_files:

        if not file_path.exists():
            raise FileNotFoundError(
                f"Missing dataset file: {file_path}"
            )

        print(f"FOUND: {file_path.relative_to(BASE_DIR)}")

    return EXTRACT_DIR


# ==========================================
# INSPECT DATASET
# ==========================================

def inspect_dataset(dataset_dir):

    corpus_path = dataset_dir / "corpus.jsonl"
    queries_path = dataset_dir / "queries.jsonl"
    qrels_path = dataset_dir / "qrels" / "test.tsv"

    with open(corpus_path, encoding="utf-8") as file:
        document_count = sum(1 for _ in file)

    with open(queries_path, encoding="utf-8") as file:
        query_count = sum(1 for _ in file)

    with open(qrels_path, encoding="utf-8") as file:
        relevance_count = sum(1 for _ in file) - 1

    print("\n========== SCIFACT DATASET ==========")

    print(f"Documents: {document_count}")
    print(f"Queries: {query_count}")
    print(f"Relevance judgments: {relevance_count}")

    # Sample document
    print("\nSample document:")

    with open(corpus_path, encoding="utf-8") as file:
        document = json.loads(next(file))

    print("ID:", document["_id"])
    print("Title:", document["title"])
    print("Text:", document["text"][:300])

    # Sample query
    print("\nSample query:")

    with open(queries_path, encoding="utf-8") as file:
        query = json.loads(next(file))

    print("ID:", query["_id"])
    print("Text:", query["text"])

    # Sample relevance judgment
    print("\nSample relevance judgment:")

    with open(qrels_path, encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter="\t")
        print(next(reader))


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":

    dataset_dir = download_dataset()

    inspect_dataset(dataset_dir)