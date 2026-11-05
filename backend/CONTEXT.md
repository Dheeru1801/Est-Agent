# Backend Context

## Purpose and architecture

The backend is a FastAPI service for a document-question-answering RAG chatbot. It accepts supported files, parses and chunks them, and stores chunks in a Pinecone document index configured with integrated embeddings. Pinecone embeds both document chunks and search queries. A LangGraph agent uses Gemini, document search, and a basic calculator to answer questions.

## Files and folders

| Path | Purpose |
| --- | --- |
| `backend/.env` | Local secrets and configuration overrides. This file is ignored by Git; do not include its values in documentation or commits. |
| `backend/.env.example` | Safe template for Google AI Studio, Gemini chat/caption models, Pinecone index and namespace, and CORS. |
| `backend/pyproject.toml` | Python project metadata and dependency ranges used by uv. |
| `backend/uv.lock` | Resolved dependency versions used by `uv sync`. |
| `backend/app/` | Python application package. |
| `backend/app/__init__.py` | Package marker and short package description. |
| `backend/app/__main__.py` | Development startup entry point for `uv run python -m app`. |
| `backend/app/database.py` | SQLite connection handling, document registry schema, upload-record creation/status updates, and recent-document listing. |
| `backend/app/main.py` | FastAPI app, request model, middleware, and API routes. |
| `backend/app/agent.py` | LangGraph agent state, tools, skills, and graph construction. |
| `backend/app/knowledge.py` | Document parsing, chunking, Gemini image captions, and Pinecone integrated-embedding indexing and retrieval. |

Generated/local-only folders include `backend/.venv/` and Python `__pycache__/` directories.

## Classes and functions

### `app/main.py`

| Name | Responsibility | Technologies |
| --- | --- | --- |
| `ChatRequest` | Pydantic request model containing the user's `message`. | Pydantic |
| `health()` | Reports service status and whether the required Google and Pinecone settings are present. Routes: `/health`, `/api/health`. | FastAPI |
| `list_tools()` | Returns registered agent tool names and descriptions. Route: `/api/tools`. | FastAPI, LangChain tools |
| `get_documents(limit)` | Returns total/indexed/pending counts, counts by status, and recent document records. Route: `/api/documents`. | FastAPI, SQLite persistence module |
| `upload_documents(files, file)` | Stores one or many supported uploads, expands ZIP archives, and registers each accepted file as pending without indexing it. Routes: `/api/documents/upload`, legacy `/api/upload`. | FastAPI, Python `zipfile`, local filesystem, `database.py` |
| `index_pending_documents(background_tasks)` | Atomically claims uploaded/failed records and schedules background indexing. Route: `/api/documents/index`. | FastAPI `BackgroundTasks`, SQLite persistence module |
| `_index_claimed_documents(documents)` | Indexes each queued original file and records success/failure and timestamps. | Knowledge module, SQLite persistence module |
| `chat(body)` | Streams concise progress events and generated answer tokens as SSE. Route: `/api/chat`. | FastAPI `StreamingResponse`, LangGraph `astream_events` |

### `app/database.py`

| Name | Responsibility | Technologies |
| --- | --- | --- |
| `_database_path()` | Resolves `SQLITE_DB_PATH`, defaulting to `backend/data/rag_agent.sqlite3`. | Python `pathlib`, `os` |
| `_connection()` | Opens a SQLite connection with row mappings and commits or rolls back each transaction. | Python `sqlite3`, `contextlib` |
| `initialize_database()` | Creates the `documents` table and recent-upload index. | SQLite |
| `create_document(...)` | Records an upload before indexing, including file path, MIME type, size, and SHA-256 checksum. | SQLite |
| `update_document(...)` | Updates processing status, parser, chunk/caption counts, errors, index-start timestamp, and indexed timestamp. | SQLite |
| `claim_documents_to_index()` | Atomically marks all uploaded and failed records as indexing and returns them for the background job. | SQLite transaction |
| `recover_interrupted_indexing()` | Requeues records that were left in indexing state when the backend stopped. | SQLite |
| `get_document_overview(limit)` | Returns total, indexed, not-indexed, and pending-for-index counts, status counts, and recent records with `is_indexed` without exposing local paths. | SQLite |

### `app/agent.py`

| Name | Responsibility | Technologies |
| --- | --- | --- |
| `AgentState` | Typed graph state containing the accumulated LangChain messages. | `TypedDict`, LangGraph message reducer |
| `search_knowledge_base(query)` | Retrieves relevant passages from Pinecone for the user's question. | LangChain `@tool`, `retrieve_context()` |
| `calculator(expression)` | Parses a restricted arithmetic AST and evaluates supported numeric operations. Nested `evaluate(node)` recursively evaluates allowed nodes; arbitrary Python code is rejected. | Python `ast`, `operator` |
| `TOOLS` | Registers search and calculator tools for Gemini. | LangChain |
| `SKILLS` | Stores concise, grounded-answer behavior instructions. | Agent system prompt |
| `build_agent()` | Configures Gemini, binds tools, and compiles the LangGraph assistant/tools loop. Nested `assistant(state)` prepends the system message and invokes Gemini. | `ChatGoogleGenerativeAI`, LangGraph `StateGraph`, `ToolNode` |

### `app/knowledge.py`

| Name | Responsibility | Technologies |
| --- | --- | --- |
| `_heading_for_line(lines, index)` | Recognizes Markdown headings and conservative standalone title-like lines. | Python `re` |
| `_heading_sections(doc)` | Parses heading paths and section text. Nested `save_body()` saves the body under the active heading path. | LangChain `Document`, Python `re` |
| `_split_document(doc)` | Groups small heading sections and recursively splits oversized groups; falls back to recursive text splitting when there are no headings. Nested `emit_group()` creates chunk documents and heading metadata. | `RecursiveCharacterTextSplitter` |
| `_load_pdf_with_pymupdf4llm(path)` | Extracts page Markdown and reports text density/table signals for routing. | PyMuPDF4LLM |
| `_load_pdf_with_docling(path)` | Extracts structured Markdown and enables OCR, table parsing, and heading hierarchy. | Docling |
| `_load_pdf(path)` | Routes ordinary PDFs to PyMuPDF4LLM and sparse-text or table-containing PDFs to Docling. | PyMuPDF4LLM, Docling |
| `_load_docx(path)` | Extracts Word paragraphs, headings, and tables into text/Markdown for chunking. | `python-docx` |
| `_describe_pdf_images(path)` | Selects embedded raster figures, sends up to the configured limit to Gemini, and returns caption documents. Errors are logged while text indexing continues. | PyMuPDF, Google GenAI |
| `_pinecone_index()` | Validates Pinecone credentials and index name, creates the SDK index handle, and caches it for the process. | Pinecone Python SDK, `lru_cache` |
| `_pinecone_namespace()` | Returns the configured namespace, defaulting to `default`. | Python `os` |
| `_record_fields(metadata)` | Converts chunk metadata into JSON-compatible Pinecone document fields. | Python `json` |
| `ingest_file(path, filename, document_id)` | Loads supported files, adds source metadata, parses/chunks them, writes records to Pinecone, and returns chunk count, parser, and image-caption count. The stable upload ID contributes to vector ID generation. Pinecone generates dense embeddings from `chunk_text`. | TextLoader, PyMuPDF4LLM, Docling, python-docx, Google GenAI for image captions, Pinecone document API |
| `retrieve_context(query)` | Uses Pinecone's integrated model to embed the query, retrieves the four nearest chunks, and formats their source/page labels for the agent. | Pinecone document search API |

### `app/__main__.py`

| Name | Responsibility | Technologies |
| --- | --- | --- |
| `main()` | Runs the local development server on port 8000 with reload enabled. | Uvicorn |

## Current backend status

- API routes: health, tool listing, document listing, separate document upload/index, and streaming chat.
- Supported uploads: PDF, DOCX, TXT, Markdown, CSV, and JSON. ZIP upload expands supported archive entries, up to 500 files and 500 MB total expanded size.
- Ordinary text PDFs use PyMuPDF4LLM. PDFs with detected tables or an average below 80 extracted characters per page use Docling. Docling's OCR/layout models run locally and can download on first use.
- Image captions are enabled by default for up to eight selected raster images per PDF. Their image bytes are sent to Gemini using `PDF_VISION_MODEL`; set `PDF_IMAGE_CAPTIONS=false` to disable this. Vector-only diagrams are not captured by this pass.
- Chunks target 1,000 characters with 150-character overlap. Markdown headings are retained in the text and heading metadata; files without detected headings use recursive paragraph/character splitting.
- Pinecone's integrated embedding model generates vectors from the `chunk_text` field during indexing and embeds search queries during retrieval. Configure the Pinecone index schema to enable integrated embedding on `chunk_text`; no Gemini embedding key or dimension setting is used.
- Pinecone records are written to the `PINECONE_NAMESPACE` namespace (default `default`). `PINECONE_INDEX` must name the schema-based Pinecone index, and its embedded text field must be named `chunk_text`.
- Original uploads persist under `UPLOADS_DIR` (default `backend/data/uploads/`). SQLite stores each file's checksum, metadata, upload/index timestamps, status, parser, and indexing counts in `SQLITE_DB_PATH` (default `backend/data/rag_agent.sqlite3`).
- `POST /api/documents/upload` accepts bulk `files` fields and ZIP archives, saving records in `uploaded` status without indexing.
- `POST /api/documents/index` queues all `uploaded` and `failed` records for background indexing. Repeated requests do not duplicate in-progress jobs.
- `GET /api/documents` returns total/indexed/not-indexed/pending counts, counts per status, and recent records with `status`, `is_indexed`, `uploaded_at`, `index_started_at`, and `indexed_at`.
- `POST /api/chat` returns SSE `progress`, `token`, `done`, and `error` events. Progress labels describe tool activity; the API does not expose private model reasoning.
- Authentication, per-user vector isolation, document deletion/replacement, and persisted chat history are not implemented.
- Tests have not been run for the latest cleanup.
