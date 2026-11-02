
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.storage import s3_client, BUCKET_NAME
from app.pdf_extractor import extract_pdf_text

OBJECT_KEY = "documents/63f1c926-e2d8-47ab-93c7-ea7218604dc5.pdf"

response = s3_client.get_object(
    Bucket=BUCKET_NAME,
    Key=OBJECT_KEY
)

pdf_bytes = response["Body"].read()

pages = extract_pdf_text(pdf_bytes)

total_characters = 0
empty_pages = 0

for page in pages:
    text = page["text"]
    total_characters += len(text)

    if not text:
        empty_pages += 1

    print(f"\n--- Page {page['page_number']} ---")
    print(text)

print("\n========== EXTRACTION SUMMARY ==========")
print(f"Total pages: {len(pages)}")
print(f"Total characters: {total_characters}")
print(f"Empty pages: {empty_pages}")
