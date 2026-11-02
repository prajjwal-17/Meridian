
import fitz


def extract_pdf_text(pdf_bytes: bytes) -> list[dict]:
    """
    Extract text from a PDF, preserving page numbers.

    Returns:
        A list containing page number and extracted text.
    """

    pages = []

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()

            pages.append({
                "page_number": page_number,
                "text": text
            })

    return pages
