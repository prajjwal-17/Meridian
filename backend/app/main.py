import hashlib
from io import BytesIO
from uuid import uuid4
from io import BytesIO
from fastapi.responses import StreamingResponse

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.dependencies import get_db
from app.models import Document
from app.storage import s3_client, BUCKET_NAME

app = FastAPI(
    title="Meridian API",
    description="Enterprise RAG Platform",
    version="0.1.0",
)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "Meridian",
    }


@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed.",
        )

    # Read file and validate size
    file_content = await file.read(MAX_FILE_SIZE + 1)

    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size cannot exceed 20 MB.",
        )

    # Validate actual PDF signature
    if not file_content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="Invalid PDF file.",
        )

    # Calculate SHA-256 checksum
    checksum = hashlib.sha256(file_content).hexdigest()

    # Generate a unique object key
    object_key = f"documents/{uuid4()}.pdf"

    # Upload original PDF to SeaweedFS
    try:
        s3_client.upload_fileobj(
            BytesIO(file_content),
            BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Failed to upload file to storage.",
        )

    # Save document metadata in PostgreSQL
    document = Document(
        filename=file.filename,
        object_key=object_key,
        content_type="application/pdf",
        file_size=len(file_content),
        checksum=checksum,
    )

    try:
        db.add(document)
        db.commit()
        db.refresh(document)

    except Exception:
        db.rollback()

        # Remove uploaded file if database operation fails
        try:
            s3_client.delete_object(
                Bucket=BUCKET_NAME,
                Key=object_key,
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail="Failed to save document metadata.",
        )

    return {
        "message": "Document uploaded successfully.",
        "document_id": document.id,
        "filename": document.filename,
        "object_key": document.object_key,
        "file_size": document.file_size,
        "checksum": document.checksum,
        "status": document.status,
    }
    
@app.get("/documents")
def get_documents(db: Session = Depends(get_db)):
    documents = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .all()
    )

    return {
        "total": len(documents),
        "documents": [
            {
                "id": doc.id,
                "filename": doc.filename,
                "object_key": doc.object_key,
                "content_type": doc.content_type,
                "file_size": doc.file_size,
                "status": doc.status,
                "checksum": doc.checksum,
                "created_at": doc.created_at,
            }
            for doc in documents
        ],
    }
    
@app.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    # Find document metadata in PostgreSQL
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .first()
    )

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    # Retrieve the original PDF from SeaweedFS
    try:
        response = s3_client.get_object(
            Bucket=BUCKET_NAME,
            Key=document.object_key,
        )

        file_content = response["Body"].read()

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Failed to retrieve document from storage.",
        )

    # Return the PDF as a downloadable response
    return StreamingResponse(
        BytesIO(file_content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{document.filename}"'
            )
        },
    )