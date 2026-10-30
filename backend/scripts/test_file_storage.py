
import boto3
import hashlib
from pathlib import Path
from botocore.config import Config

ENDPOINT = "http://localhost:8333"
BUCKET = "meridian-documents"

BASE_DIR = Path(__file__).resolve().parents[2]
PDF_PATH = BASE_DIR / "sample-documents" / "sample.pdf"

DOWNLOAD_PATH = BASE_DIR / "sample-documents" / "downloaded_sample.pdf"

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id="admin",
    aws_secret_access_key="meridian-local-secret",
    region_name="us-east-1",
    config=Config(signature_version="s3v4")
)

def calculate_checksum(file_path):
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(4096), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


if not PDF_PATH.exists():
    raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

object_key = "documents/test/sample.pdf"

# Upload
s3.upload_file(
    str(PDF_PATH),
    BUCKET,
    object_key
)

print("PDF uploaded successfully!")

# Download
s3.download_file(
    BUCKET,
    object_key,
    str(DOWNLOAD_PATH)
)

print("PDF downloaded successfully!")

# Verify integrity
original_checksum = calculate_checksum(PDF_PATH)
downloaded_checksum = calculate_checksum(DOWNLOAD_PATH)

print("Original SHA256:", original_checksum)
print("Downloaded SHA256:", downloaded_checksum)

if original_checksum == downloaded_checksum:
    print("SUCCESS: File integrity verified!")
else:
    print("ERROR: File integrity mismatch!")
