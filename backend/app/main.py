"""Expose the FastAPI endpoints for health checks, document uploads, and chat."""
import hashlib
import io
import json
import mimetypes
import os
import re
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from .agent import TOOLS, build_agent
from .database import (
    claim_documents_to_index,
    create_document,
    get_document_overview,
    initialize_database,
    recover_interrupted_indexing,
    update_document,
)
from .knowledge import (
    SUPPORTED_FILE_SUFFIXES,
    SUPPORTED_FILE_TYPES,
    ingest_file,
)

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize local persistence before serving requests."""
    initialize_database()
    recover_interrupted_indexing()
    yield


app = FastAPI(title="RAG Agent API", version="0.1.0", lifespan=lifespan)
origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:4200").split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
agent: Any | None = None
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _upload_directory() -> Path:
    """Resolve the persistent directory used for original uploaded files."""
    configured_path = Path(os.getenv("UPLOADS_DIR", str(BACKEND_DIR / "data" / "uploads")))
    if not configured_path.is_absolute():
        configured_path = BACKEND_DIR / configured_path
    return configured_path


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_FILES = 500
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 500 * 1024 * 1024


def _safe_filename(filename: str) -> str:
    """Return a sanitized base filename without directory components."""
    base_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", base_name).strip(" .")
    return safe_name or "document"


def _save_uploaded_document(
    filename: str,
    contents: bytes,
    content_type: str | None,
) -> dict[str, object]:
    """Persist one supported file and register it for a later indexing run."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FILE_SUFFIXES:
        raise ValueError(f"Unsupported file type for {filename}.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError(f"{filename} exceeds the 100 MB per-file upload limit.")
    if not contents:
        raise ValueError(f"{filename} is empty.")

    filename = _safe_filename(filename)
    document_id = str(uuid.uuid4())
    upload_path = _upload_directory() / document_id / filename
    stored_path = str(upload_path.resolve())
    try:
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(contents)
        uploaded_at = create_document(
            document_id=document_id,
            filename=filename,
            stored_path=stored_path,
            content_type=content_type or mimetypes.guess_type(filename)[0],
            size_bytes=len(contents),
            sha256=hashlib.sha256(contents).hexdigest(),
        )
    except Exception:
        upload_path.unlink(missing_ok=True)
        try:
            upload_path.parent.rmdir()
        except OSError:
            pass
        raise
    return {
        "id": document_id,
        "filename": filename,
        "status": "uploaded",
        "is_indexed": False,
        "size_bytes": len(contents),
        "uploaded_at": uploaded_at,
    }


def _index_claimed_documents(documents: list[dict[str, object]]) -> None:
    """Index queued uploads sequentially and record each result in SQLite."""
    for document in documents:
        document_id = str(document["id"])
        try:
            count, parser, image_description_count = ingest_file(
                str(document["stored_path"]),
                str(document["filename"]),
                document_id=document_id,
            )
            if count == 0:
                raise ValueError("No indexable text was extracted from this document.")
            update_document(
                document_id,
                status="indexed",
                parser=parser,
                chunk_count=count,
                image_description_count=image_description_count,
                error=None,
            )
        except Exception as exc:
            update_document(document_id, status="failed", error=str(exc)[:2000])


def _sse_event(event: str, payload: dict[str, object]) -> str:
    """Serialize one server-sent event frame."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ChatRequest(BaseModel):
    """Request payload for a user chat message."""

    message: str


@app.get("/health", include_in_schema=False)
@app.get("/api/health")
def health() -> dict[str, str | bool]:
    """Report service availability and whether required credentials exist."""
    return {
        "status": "ok",
        "configured": all(
            os.getenv(key)
            for key in ("GOOGLE_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX")
        ),
    }


@app.get("/api/tools")
def list_tools() -> dict[str, list[dict[str, str]]]:
    """Return the names and descriptions of tools registered with the agent."""
    return {"tools": [{"name": t.name, "description": t.description} for t in TOOLS]}


@app.get("/api/documents")
def get_documents(limit: int = 100, offset: int = 0) -> dict[str, object]:
    """Return total document counts and recent records with indexing status."""
    return get_document_overview(limit, offset)


@app.post("/api/upload")
@app.post("/api/documents/upload")
async def upload_documents(
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
) -> dict[str, object]:
    """Persist one or more files without indexing them.

    Args:
        files: Repeated multipart `files` fields for bulk uploads.
        file: Optional legacy single-file multipart field.

    Returns:
        Stored document records and per-file upload errors.

    Raises:
        HTTPException: If no file is supplied.
    """
    uploads = list(files or [])
    if file is not None:
        uploads.append(file)
    if not uploads:
        raise HTTPException(400, "Select at least one file to upload.")

    uploaded: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    try:
        for upload in uploads:
            original_name = _safe_filename(upload.filename or "document")
            try:
                contents = await upload.read()
                suffix = Path(original_name).suffix.lower()
                if suffix == ".zip":
                    if len(contents) > MAX_UPLOAD_BYTES:
                        raise ValueError("ZIP file exceeds the 100 MB upload limit.")
                    try:
                        archive = zipfile.ZipFile(io.BytesIO(contents))
                    except zipfile.BadZipFile as exc:
                        raise ValueError("The uploaded ZIP file is invalid.") from exc
                    with archive:
                        entries = [item for item in archive.infolist() if not item.is_dir()]
                        if len(entries) > MAX_ARCHIVE_FILES:
                            raise ValueError(
                                f"ZIP file contains more than {MAX_ARCHIVE_FILES} entries."
                            )
                        total_size = sum(item.file_size for item in entries)
                        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                            raise ValueError("ZIP contents exceed the 500 MB expanded-size limit.")
                        for entry in entries:
                            entry_name = _safe_filename(entry.filename)
                            if Path(entry_name).suffix.lower() not in SUPPORTED_FILE_SUFFIXES:
                                errors.append({
                                    "filename": entry_name,
                                    "error": "Unsupported file type inside ZIP; skipped.",
                                })
                                continue
                            try:
                                entry_contents = archive.read(entry)
                                uploaded.append(_save_uploaded_document(
                                    entry_name,
                                    entry_contents,
                                    mimetypes.guess_type(entry_name)[0],
                                ))
                            except Exception as exc:
                                errors.append({"filename": entry_name, "error": str(exc)})
                else:
                    uploaded.append(_save_uploaded_document(
                        original_name,
                        contents,
                        upload.content_type,
                    ))
            except Exception as exc:
                errors.append({"filename": original_name, "error": str(exc)})
    finally:
        for upload in uploads:
            await upload.close()
    return {
        "uploaded_count": len(uploaded),
        "rejected_count": len(errors),
        "documents": uploaded,
        "errors": errors,
        "message": "Files are saved and ready for indexing.",
    }


@app.post("/api/documents/index", status_code=202)
def index_pending_documents(background_tasks: BackgroundTasks) -> dict[str, object]:
    """Queue every uploaded or previously failed document for indexing."""
    documents = claim_documents_to_index()
    if not documents:
        return {
            "queued_count": 0,
            "document_ids": [],
            "message": "There are no uploaded or failed documents to index.",
        }
    background_tasks.add_task(_index_claimed_documents, documents)
    return {
        "queued_count": len(documents),
        "document_ids": [document["id"] for document in documents],
        "message": "Indexing has started. Poll GET /api/documents for status updates.",
    }


@app.post("/api/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    """Stream safe activity updates and generated answer tokens as SSE.

    Args:
        body: JSON request containing the user's message.

    Returns:
        Server-sent events for progress, answer tokens, completion, or errors.

    Raises:
        HTTPException: If Gemini configuration is missing or the agent fails.
    """
    global agent
    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(
            503,
            "Set GOOGLE_API_KEY in backend/.env to enable Gemini chat.",
        )

    async def event_stream():
        """Yield public activity labels and answer text without private reasoning."""
        global agent
        yield _sse_event("progress", {"message": "THINKING · Reviewing your request"})
        try:
            if agent is None:
                agent = build_agent()
            async for event in agent.astream_events(
                {"messages": [("user", body.message)]},
                version="v2",
            ):
                event_name = event.get("event")
                tool_name = event.get("name")
                if event_name == "on_tool_start":
                    activity = {
                        "search_knowledge_base": "SEARCHING · Looking through your documents",
                        "calculator": "CALCULATING · Running a calculation",
                    }.get(tool_name, "Using an assistant tool")
                    yield _sse_event("progress", {"message": activity})
                elif event_name == "on_tool_end":
                    activity = {
                        "search_knowledge_base": "Document search complete",
                        "calculator": "Calculation complete",
                    }.get(tool_name, "Tool completed")
                    yield _sse_event("progress", {"message": activity})
                elif event_name == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    content = getattr(chunk, "content", "")
                    if isinstance(content, str) and content:
                        yield _sse_event("token", {"text": content})
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                token = part.get("text", "")
                                if token:
                                    yield _sse_event("token", {"text": token})
            yield _sse_event("done", {"message": "Response complete"})
        except Exception as exc:
            yield _sse_event("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
