# Groundwork — RAG agent starter

A local document-chat starter with a Python/FastAPI backend, LangChain document processing, a LangGraph tool-calling agent, Gemini chat and embeddings, Pinecone vector storage, and an Angular UI.

## Requirements

- Python 3.10+
- Node.js 20.11+ and npm
- A Google AI Studio API key for Gemini's free tier
- A Pinecone API key and an index configured for the embedding dimension used by the selected embedding model

## Start the backend

From the repository root, in PowerShell:

```powershell
cd backend
uv sync
# Set GOOGLE_API_KEY in .env to your Google AI Studio key
uv run python -m app
```

The API runs at `http://localhost:8000`; interactive API docs are at `http://localhost:8000/docs`. Create a Pinecone index with dimension `384` and cosine metric before uploading documents. The Gemini free tier has rate limits; Google may use free-tier content to improve its products.

## Start the Angular UI

In a second terminal from the repository root:

```powershell
cd frontend
npm install
npm start
```

Open `http://localhost:4200`. Upload PDF, TXT, Markdown, CSV, or JSON documents using the left panel. Ask questions in the chat; the agent can search indexed documents and use its calculator tool.

## Configuration

Backend settings live in `backend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_API_KEY` | unset | Google AI Studio key used for Gemini chat and embeddings |
| `CHAT_MODEL` | `gemini-3.1-flash-lite` | Gemini chat model with function-calling support |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Gemini retrieval embedding model |
| `EMBEDDING_DIMENSION` | `384` | Embedding vector size; must match the Pinecone index dimension |
| `PINECONE_API_KEY` | unset | Pinecone API key |
| `PINECONE_INDEX` | unset | Existing Pinecone index name |
| `CORS_ORIGINS` | `http://localhost:4200` | Comma-separated allowed UI origins |

## Extend the agent

- **Tools:** define a LangChain `@tool` in `backend/app/agent.py` and add it to `TOOLS`. The LangGraph tool node exposes registered tools to the model.
- **Skills:** add reusable behavior instructions to the `SKILLS` mapping in the same file. The current `grounded_answers` and `concise` skills are combined into the agent's system instructions.
- **Loaders:** add file suffix handling in `backend/app/knowledge.py` and the matching accepted suffix in `backend/app/main.py`.

## API

- `GET /api/health` — service and API-key configuration status
- `GET /api/tools` — registered agent tools
- `POST /api/upload` — index one supported document as multipart field `file`
- `POST /api/chat` — chat with JSON body `{"message":"..."}`

This is a development starter. Before deploying it for multiple users, add authentication, per-user storage isolation, upload size limits, and a proper secret-management setup.
