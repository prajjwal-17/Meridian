import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from io import BytesIO
from fastapi.responses import Response, StreamingResponse

from fastapi import Cookie, FastAPI, UploadFile, File, Form, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.dependencies import (
    get_authenticated_permission_context,
    get_db,
    require_admin,
)
from app.document_processor import DocumentProcessingError, process_document
from app.models import Document, User
from app.permissions import PermissionContext, can_access_document, validate_acl_metadata
from app.storage import s3_client, BUCKET_NAME
from app.answer_generation import AnswerGenerationError, answer_question
from app.auth import (
    clear_auth_cookies,
    clear_login_failures,
    create_session,
    get_current_user,
    get_session_user,
    hash_password,
    login_allowed,
    normalize_email,
    require_request_security,
    revoke_session,
    revoke_sessions,
    set_auth_cookies,
    user_roles,
    utc_now,
    verify_password,
)
from app.admin_api import router as admin_router

app = FastAPI(
    title="Meridian API",
    description="Enterprise RAG Platform",
    version="0.1.0",
)
app.include_router(admin_router)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    rerank: bool = True
    mode: str = Field(default="hybrid", pattern="^(graph|bm25|dense|hybrid)$")


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "Meridian",
    }


@app.post("/auth/login")
def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    identifier = request.identifier.strip()
    from app.auth import validate_origin

    validate_origin(http_request)
    if not login_allowed(http_request, identifier):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    normalized = normalize_email(identifier) if "@" in identifier else identifier
    user = db.query(User).filter(
        (User.email == normalized) | (User.id == identifier)
    ).first()
    if not user or not user.is_active or not verify_password(user.password_hash, request.password):
        from app.auth import record_login_failure

        record_login_failure(http_request, identifier)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    clear_login_failures(http_request, identifier)
    session_token, csrf_token = create_session(db, user)
    user.last_login_at = utc_now()
    db.commit()
    set_auth_cookies(response, session_token, csrf_token)
    response.headers["Cache-Control"] = "no-store"
    return {
        "authenticated": True,
        "user_id": user.id,
        "name": user.name,
        "must_change_password": user.must_change_password,
    }


@app.post("/auth/logout")
def logout(
    response: Response,
    _csrf: None = Depends(require_request_security),
    meridian_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_session_user),
):
    revoke_session(db, meridian_session)
    db.commit()
    clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}


@app.get("/auth/me")
def auth_me(
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_session_user),
):
    response.headers["Cache-Control"] = "no-store"
    return {
        "authenticated": True,
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "roles": sorted(user_roles(db, user.id)),
    }


@app.get("/auth/demo-accounts")
def demo_accounts():
    """Expose local demo credentials only when explicitly in development mode."""
    if os.getenv("MERIDIAN_ENV", "production").strip().lower() not in {"development", "dev", "test"}:
        raise HTTPException(status_code=404, detail="Not found.")
    manifest_path = Path(__file__).resolve().parents[1] / "test_users.json"
    if not manifest_path.exists():
        return {"accounts": []}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        accounts = payload.get("accounts", [])
        if not isinstance(accounts, list):
            raise ValueError("accounts must be a list")
        return {"accounts": accounts}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Demo account manifest is unavailable.") from exc


@app.post("/auth/change-password")
def change_password(
    request: ChangePasswordRequest,
    response: Response,
    _csrf: None = Depends(require_request_security),
    meridian_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_session_user),
):
    if not verify_password(user.password_hash, request.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    try:
        new_hash = hash_password(request.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user.password_hash = new_hash
    user.must_change_password = False
    user.password_changed_at = utc_now()
    revoke_sessions(db, user.id)
    session_token, csrf_token = create_session(db, user)
    db.commit()
    set_auth_cookies(response, session_token, csrf_token)
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True, "must_change_password": False}


@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    permission_tier: str = Form(...),
    permission_team: str | None = Form(default=None),
    permission_department: str | None = Form(default=None),
    restricted_user_ids: str | None = Form(
        default=None,
        description="Comma-separated user IDs for restricted documents",
    ),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    restricted_users = (
        [item.strip() for item in restricted_user_ids.split(",") if item.strip()]
        if restricted_user_ids
        else None
    )
    try:
        acl = validate_acl_metadata(
            permission_tier,
            permission_team,
            permission_department,
            restricted_users,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        **acl,
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

    try:
        process_document(db, document.id)
        db.refresh(document)
    except DocumentProcessingError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Document uploaded but processing failed for document {document.id}. "
                f"Retry with the document processing command. {exc}"
            ),
        ) from exc

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
def get_documents(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_admin),
):
    """Return the complete document inventory to administrators only."""
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
                "permission_tier": doc.permission_tier,
                "permission_team": doc.permission_team,
                "permission_department": doc.permission_department,
                "permission_teams": doc.permission_teams,
                "permission_departments": doc.permission_departments,
                "created_at": doc.created_at,
            }
            for doc in documents
        ],
    }


@app.get("/search")
def search_documents(
    q: str = Query(min_length=1),
    mode: str = Query(default="graph", pattern="^(graph|bm25|dense|hybrid)$"),
    top_k: int = Query(default=5, ge=1, le=20),
    rerank: bool = Query(default=False),
    db: Session = Depends(get_db),
    permission_context: PermissionContext = Depends(get_authenticated_permission_context),
):
    """Expose the existing retrieval modules to the minimal frontend."""
    if rerank and mode != "hybrid":
        raise HTTPException(
            status_code=400,
            detail="Cross-encoder reranking is currently supported for hybrid mode only.",
        )
    if mode == "graph":
        from app.graph_retrieval import graph_search

        results = graph_search(
            db, q, top_k=top_k, permission_context=permission_context
        )
    elif mode == "bm25":
        from app.bm25_retrieval import bm25_search

        results = bm25_search(
            db, q, top_k=top_k, permission_context=permission_context
        )
    elif mode == "dense":
        from app.retrieval import semantic_search

        results = semantic_search(
            db, q, top_k=top_k, permission_context=permission_context
        )
    else:
        from app.hybrid_retrieval import hybrid_search

        results = hybrid_search(
            db,
            q,
            top_k=top_k,
            permission_context=permission_context,
            rerank=rerank,
        )

    return {"query": q, "mode": mode, "results": results}


@app.post("/ask")
def ask_question(
    request: AskRequest,
    db: Session = Depends(get_db),
    permission_context: PermissionContext = Depends(get_authenticated_permission_context),
):
    """Generate a grounded answer from ACL-filtered hybrid retrieval context."""
    try:
        return answer_question(
            db,
            request.question,
            permission_context,
            top_k=request.top_k,
            rerank=request.rerank,
            mode=request.mode,
        )
    except AnswerGenerationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    
@app.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    permission_context: PermissionContext = Depends(get_authenticated_permission_context),
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
    if not can_access_document(document, permission_context):
        raise HTTPException(status_code=403, detail="You do not have access to this document.")

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
        media_type=document.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{document.filename}"'
            )
        },
    )
    
@app.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    # Find document in PostgreSQL
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

    # Delete original PDF from SeaweedFS
    try:
        s3_client.delete_object(
            Bucket=BUCKET_NAME,
            Key=document.object_key,
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Failed to delete document from storage.",
        )

    # Delete metadata from PostgreSQL
    try:
        db.delete(document)
        db.commit()

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to delete document metadata.",
        )

    return {
        "message": "Document deleted successfully.",
        "document_id": document_id,
    }
