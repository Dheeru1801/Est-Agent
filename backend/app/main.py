import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import TOOLS, build_agent
from .knowledge import ingest_file

load_dotenv()
app = FastAPI(title="RAG Agent API", version="0.1.0")
origins = os.getenv("CORS_ORIGINS", "http://localhost:4200").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
agent = None


class ChatRequest(BaseModel):
    message: str


@app.get("/health", include_in_schema=False)
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "configured": all(os.getenv(key) for key in ("GOOGLE_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX")),
    }


@app.get("/api/tools")
def list_tools():
    return {"tools": [{"name": t.name, "description": t.description} for t in TOOLS]}


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".csv", ".json"}:
        raise HTTPException(400, "Supported files: PDF, TXT, Markdown, CSV, and JSON.")
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        count = ingest_file(tmp_path, file.filename or "document")
        return {"filename": file.filename, "chunks": count, "message": "Document indexed successfully."}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/chat")
def chat(body: ChatRequest):
    global agent
    if not os.getenv("GOOGLE_API_KEY"):
        raise HTTPException(503, "Set GOOGLE_API_KEY in backend/.env to enable Gemini chat and embeddings.")
    try:
        if agent is None:
            agent = build_agent()
        result = agent.invoke({"messages": [("user", body.message)]})
        answer = result["messages"][-1].content
        return {"answer": answer if isinstance(answer, str) else str(answer)}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
