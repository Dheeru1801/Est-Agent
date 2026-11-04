# Groundwork — RAG agent starter

A local document-chat starter with a Python/FastAPI backend, LangChain document processing, a LangGraph tool-calling agent, Gemini chat and image captions, Pinecone integrated embeddings, and an Angular UI.

## Requirements

- Python 3.10+
- Node.js 20.11+ and npm
- A Google AI Studio API key for Gemini's free tier
- A Pinecone API key and a schema-based document index with integrated dense embedding enabled on the `chunk_text` string field

## Start the backend

From the repository root, in PowerShell:

```powershell
cd backend
uv sync
# Set GOOGLE_API_KEY in .env to your Google AI Studio key
uv run python -m app
```

The API runs at `http://localhost:8000`; interactive API docs are at `http://localhost:8000/docs`. Create a Pinecone document index with integrated embedding enabled on the `chunk_text` field before uploading documents. The backend sends chunk text and query text to Pinecone; no embedding dimension is configured in the backend. SQLite tracks upload metadata and indexing status, while original files are kept under `backend/data/uploads/`. The Gemini free tier has rate limits; Google may use free-tier content to improve its products.

## Start the Angular UI

In a second terminal from the repository root:

```powershell
cd frontend
npm install
npm start
```

Open `http://localhost:4200`. Upload PDF, TXT, Markdown, CSV, or JSON documents using the left panel. Ask questions in the chat; the agent can search indexed documents and use its calculator tool.

PDF parsing is selected automatically. The backend uses PyMuPDF4LLM for ordinary text PDFs, and routes PDFs with detected tables or very little extractable text to Docling for layout, table, and OCR processing. Docling downloads its parser model files the first time it processes a document and runs them locally. For image descriptions, the backend sends up to eight embedded figures per PDF to Gemini; this is separate from OCR and uses the configured Gemini API key and its quotas. Set `PDF_IMAGE_CAPTIONS=false` to disable captions or adjust `PDF_MAX_IMAGES_PER_FILE` and `PDF_VISION_MODEL`. The extracted Markdown and captions then use the same Pinecone indexing flow.

## Configuration

Backend settings live in `backend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_API_KEY` | unset | Google AI Studio key used for Gemini chat and image captions |
| `CHAT_MODEL` | `gemini-3.1-flash-lite` | Gemini chat model with function-calling support |
| `PDF_IMAGE_CAPTIONS` | `true` | Use Gemini to describe selected embedded PDF figures; image bytes are sent to Google's API |
| `PDF_VISION_MODEL` | `gemini-3.1-flash-lite` | Gemini model used for figure descriptions |
| `PDF_MAX_IMAGES_PER_FILE` | `8` | Maximum embedded images described per PDF |
| `PINECONE_API_KEY` | unset | Pinecone API key |
| `PINECONE_INDEX` | unset | Existing schema-based Pinecone document index name |
| `PINECONE_NAMESPACE` | `default` | Namespace used for indexing and retrieval |
| `SQLITE_DB_PATH` | `data/rag_agent.sqlite3` | SQLite database path, relative to `backend/` unless absolute |
| `UPLOADS_DIR` | `data/uploads` | Persistent directory for original uploaded files, relative to `backend/` unless absolute |
| `CORS_ORIGINS` | `http://localhost:4200` | Comma-separated allowed UI origins |

## Extend the agent

- **Tools:** define a LangChain `@tool` in `backend/app/agent.py` and add it to `TOOLS`. The LangGraph tool node exposes registered tools to the model.
- **Skills:** add reusable behavior instructions to the `SKILLS` mapping in the same file. The current `grounded_answers` and `concise` skills are combined into the agent's system instructions.
- **Loaders:** add file suffix handling in `backend/app/knowledge.py` and the matching accepted suffix in `backend/app/main.py`.

## API

- `GET /api/health` — service and API-key configuration status
- `GET /api/tools` — registered agent tools
- `GET /api/documents` — document totals, indexing counts, and recent records with status
- `POST /api/upload` — index one supported document as multipart field `file`
- `POST /api/chat` — chat with JSON body `{"message":"..."}`

This is a development starter. Before deploying it for multiple users, add authentication, per-user storage isolation, upload size limits, and a proper secret-management setup.
