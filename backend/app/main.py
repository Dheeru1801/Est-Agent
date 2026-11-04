"""Expose the FastAPI endpoints for health checks, document uploads, and chat."""
import hashlib
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import TOOLS, build_agent
from .database import (
    create_document,
    get_document_overview,
    initialize_database,
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
def get_documents(limit: int = 100) -> dict[str, object]:
    """Return total document counts and recent records with indexing status."""
    return get_document_overview(limit)


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)) -> dict[str, str | int]:
    """Persist an uploaded file, register it, and index its chunks.

    Args:
        file: Multipart upload using one of the supported file extensions.

    Returns:
        Document ID, filename, chunk count, parser, and image-caption count.

    Raises:
        HTTPException: If the extension is unsupported or indexing fails.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_FILE_SUFFIXES:
        raise HTTPException(400, f"Supported files: {SUPPORTED_FILE_TYPES}.")
    filename = Path(file.filename or "document").name
    filename = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip(" .") or "document"
    document_id = str(uuid.uuid4())
    contents = await file.read()
    upload_path = _upload_directory() / document_id / filename
    stored_path = str(upload_path.resolve())
    registered = False
    try:
        create_document(
            document_id=document_id,
            filename=filename,
            stored_path=stored_path,
            content_type=file.content_type,
            size_bytes=len(contents),
            sha256=hashlib.sha256(contents).hexdigest(),
        )
        registered = True
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(contents)
        update_document(document_id, status="indexing")
        count, parser, image_description_count = ingest_file(stored_path, filename)
        update_document(
            document_id,
            status="indexed",
            parser=parser,
            chunk_count=count,
            image_description_count=image_description_count,
        )
        return {
            "document_id": document_id,
            "filename": filename,
            "chunks": count,
            "parser": parser,
            "image_descriptions": image_description_count,
            "message": "Document indexed successfully.",
        }
    except Exception as exc:
        if registered:
            try:
                update_document(document_id, status="failed", error=str(exc)[:2000])
            except Exception:
                pass
        raise HTTPException(500, str(exc)) from exc
    finally:
        await file.close()


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict[str, str]:
    """Invoke the LangGraph agent for one user message.

    Args:
        body: JSON request containing the user's message.

    Returns:
        The assistant's response text.

    Raises:
        HTTPException: If Gemini configuration is missing or the agent fails.
    """
    global agent
    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(
            503,
            "Set GOOGLE_API_KEY in backend/.env to enable Gemini chat.",
        )
    try:
        if agent is None:
            agent = build_agent()
        result = agent.invoke({"messages": [("user", body.message)]})
        answer = result["messages"][-1].content
        return {"answer": answer if isinstance(answer, str) else str(answer)}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
