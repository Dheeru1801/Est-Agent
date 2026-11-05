# Groundwork - RAG agent starter

A local document-chat application with an Angular frontend and Python/FastAPI backend. It parses and chunks documents, stores searchable records in Pinecone using integrated embeddings, and uses a LangGraph agent with Gemini for chat, retrieval, and image captions.

## Requirements

- Python 3.10+
- uv
- Node.js 20.11+ and npm
- Google AI Studio API key
- Pinecone API key and schema-based index configured for integrated dense embedding on the `chunk_text` field

## Start the backend

From the repository root, in PowerShell:

```powershell
cd backend
uv sync
# Set GOOGLE_API_KEY, PINECONE_API_KEY, and PINECONE_INDEX in .env
uv run python -m app
```

The API runs at `http://localhost:8000`. Interactive API documentation is at `http://localhost:8000/docs`.

## Start the frontend

In a second terminal from the repository root:

```powershell
cd frontend
npm install
npm start
```

Open `http://localhost:4200`. Use the Documents page to upload PDF, DOCX, TXT, Markdown, CSV, or JSON files, or ZIP archives containing supported files. Uploading saves the originals and SQLite metadata without indexing. Trigger indexing separately. The chat streams activity events and generated answer text over SSE.

## Document ingestion

Create a Pinecone document index with integrated embedding enabled for the `chunk_text` field. Upload files using `POST /api/documents/upload`; then call `POST /api/documents/index` to index all uploaded and previously failed records. Poll `GET /api/documents` for status and timestamps. Each file or ZIP archive is limited to 100 MB; an archive may contain up to 500 files and 500 MB expanded content.

PDF parser selection is automatic. Ordinary text PDFs use PyMuPDF4LLM; PDFs with detected tables or fewer than 80 extracted characters per page on average use Docling for layout, table, and OCR processing. Docling model files may download the first time and processing runs locally. Image captioning is separate from OCR: up to eight selected embedded raster images per PDF are sent to Gemini. Set `PDF_IMAGE_CAPTIONS=false` to disable captions or adjust `PDF_MAX_IMAGES_PER_FILE` and `PDF_VISION_MODEL`.

## Configuration

Backend settings are read from `backend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_API_KEY` | unset | Google AI Studio key for Gemini chat and image captions |
| `CHAT_MODEL` | `gemini-3.1-flash-lite` | Gemini chat model |
| `PDF_IMAGE_CAPTIONS` | `true` | Enable Gemini captions for selected PDF figures |
| `PDF_VISION_MODEL` | `gemini-3.1-flash-lite` | Gemini model used for image descriptions |
| `PDF_MAX_IMAGES_PER_FILE` | `8` | Maximum captioned embedded images per PDF |
| `PINECONE_API_KEY` | unset | Pinecone API key |
| `PINECONE_INDEX` | unset | Existing Pinecone integrated-embedding index name |
| `PINECONE_NAMESPACE` | `default` | Namespace used for indexing and retrieval |
| `SQLITE_DB_PATH` | `data/rag_agent.sqlite3` | SQLite file path, relative to `backend/` unless absolute |
| `UPLOADS_DIR` | `data/uploads` | Original file directory, relative to `backend/` unless absolute |
| `CORS_ORIGINS` | `http://localhost:4200` | Comma-separated allowed frontend origins |

## API

- `GET /api/health` - service status and required-configuration presence
- `GET /api/tools` - tools registered with the agent
- `GET /api/documents?limit=100&offset=0` - global totals/status counts and a page of document metadata
- `POST /api/documents/upload` - multipart `files` fields; accepts one or multiple supported files and ZIP archives; does not index
- `POST /api/documents/index` - queues all uploaded and failed documents for background indexing
- `POST /api/chat` - JSON `{"message":"..."}`; returns SSE `progress`, `token`, `done`, or `error` events

## Extend the agent

- Add a LangChain `@tool` in `backend/app/agent.py` and register it in `TOOLS`.
- Add reusable agent behavior instructions to the `SKILLS` mapping in the same file.
- Add supported loaders and suffix handling in `backend/app/knowledge.py` and the matching upload validation in `backend/app/main.py`.

## Architecture and project notes

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system HLD and LLD, [CONTEXT.md](CONTEXT.md) for the repository overview, [backend/CONTEXT.md](backend/CONTEXT.md) for backend modules and functions, and [frontend/CONTEXT.md](frontend/CONTEXT.md) for the Angular application.

This is a development starter. Multi-user deployment needs authentication, per-user storage/vector isolation, request-wide upload limits, rate limiting, and production secret management. Gemini's free tier has rate limits; Google may use free-tier content to improve its products.
