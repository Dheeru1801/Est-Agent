# Project Context

## Overview

This repository contains a document-question-answering RAG chatbot. The Angular UI uploads documents and sends questions to a FastAPI backend. The backend parses and chunks documents, uses Pinecone integrated embeddings to index and retrieve text, and uses a LangGraph agent with Gemini for chat and image captions.

## Repository structure

```text
.
|-- .gitignore
|-- CONTEXT.md
|-- readme.md
|-- backend/
|   |-- CONTEXT.md
|   |-- .env                  # Local secrets; values intentionally omitted
|   |-- .env.example
|   |-- pyproject.toml
|   |-- uv.lock
|   `-- app/
|       |-- __init__.py
|       |-- __main__.py
|       |-- agent.py
|       |-- database.py
|       |-- knowledge.py
|       `-- main.py
`-- frontend/
    |-- CONTEXT.md
    |-- angular.json
    |-- package.json
    |-- package-lock.json
    |-- tsconfig.json
    |-- tsconfig.app.json
    `-- src/
        |-- index.html
        |-- main.ts
        `-- styles.css
```

Generated/local-only directories include `.git/`, `backend/.venv/`, `backend/data/` (SQLite database and original uploads), Python `__pycache__/`, `frontend/node_modules/`, `frontend/dist/`, and `frontend/.angular/`.

## Component guides

- [Backend context](backend/CONTEXT.md): backend files, functions, libraries, ingestion flow, configuration, and status.
- [Frontend context](frontend/CONTEXT.md): frontend files, component functions, API calls, and status.

## Current project status

- Backend stack: FastAPI, LangChain, LangGraph, Gemini chat/vision, PyMuPDF4LLM/Docling, and Pinecone integrated embeddings.
- SQLite stores upload metadata, checksums, processing status, parser, and indexing counts; original file bytes are kept in the local uploads directory.
- Frontend stack: Angular 19 and TypeScript.
- Supported uploads: PDF, TXT, Markdown, CSV, and JSON.
- PDF routing selects PyMuPDF4LLM or Docling using text-density and table-detection signals. Selected embedded raster images can be captioned by Gemini.
- Chunking is heading-aware where headings are detected, with recursive paragraph/character splitting as fallback.
- Authentication, per-user storage isolation, document deletion/replacement, and persisted chat history are not yet implemented.
