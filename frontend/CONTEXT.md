# Frontend Context

## Purpose

The frontend is an Angular chat interface plus a separate Documents view for the document RAG backend. It lets users check backend readiness, upload batches or ZIP archives, trigger indexing, inspect document metadata/status, and receive SSE-streamed chat answers with activity updates.

## Files and folders

| Path | Purpose |
| --- | --- |
| `frontend/package.json` | Angular scripts and dependency ranges. `npm start` runs the development server; `npm run build` creates a production build. |
| `frontend/package-lock.json` | Locks npm dependency versions for repeatable installation. |
| `frontend/angular.json` | Angular CLI configuration for the application build and development server. |
| `frontend/tsconfig.json` | Shared TypeScript settings and strict Angular compiler options. |
| `frontend/tsconfig.app.json` | TypeScript compilation settings for the application source. |
| `frontend/src/` | Angular entry point and UI assets. |
| `frontend/src/main.ts` | Bootstraps the standalone Angular component and implements chat streaming, health, upload/index controls, polling, and the document registry view. |
| `frontend/src/index.html` | Browser page shell with the `<app-root>` Angular mount point. |
| `frontend/src/styles.css` | Application layout, colors, typography, responsive rules, and animations. |

Generated/local-only folders include `frontend/node_modules/`, `frontend/dist/`, and `frontend/.angular/`.

## Components, types, and functions

### `src/main.ts`

| Name | Responsibility | Technologies |
| --- | --- | --- |
| `ChatMessage` | In-memory chat message with role, text, progress labels, and streaming state. | TypeScript |
| `DocumentRecord` | One document row with status, file metadata, indexing details, and timestamps. | TypeScript |
| `DocumentOverview` | Paginated document rows plus total counts and counts by processing status. | TypeScript |
| `AppComponent` | Standalone root component. Renders the chat and document views; manages SSE chat state, bulk upload selection, indexing, document polling, and backend health. | Angular standalone components, `CommonModule`, `FormsModule`, Fetch Streams |
| `constructor()` | Starts backend health and document-list requests when the component is created. | Angular component lifecycle, Fetch API |
| `checkHealth()` | Calls `GET http://localhost:8000/api/health` and updates the connected/configured state. | Browser `fetch`, FastAPI |
| `onKey(event)` | Sends on Enter; Shift+Enter leaves a newline in the composer. | DOM keyboard events |
| `clearChat()` | Clears the in-memory message list for a new conversation. | Angular component state |
| `send(value?)` | Posts to `POST /api/chat`, parses SSE progress/token events, and appends answer text incrementally. | Browser Fetch Streams, SSE, FastAPI |
| `uploadSelected()` | Sends multiple files to `POST /api/documents/upload` and refreshes the document list; uploads do not trigger indexing. | Browser `FormData`, FastAPI |
| `startIndexing()` | Triggers `POST /api/documents/index`; backend status polling updates the document table. | Browser `fetch`, FastAPI background task |
| `refreshDocuments()` | Loads document totals, metadata, status, and timestamps from SQLite-backed `GET /api/documents`. | Browser `fetch`, FastAPI |
| `bootstrapApplication(AppComponent)` | Starts Angular with the standalone root component. | Angular `bootstrapApplication` |

## Backend communication

The development API base URL is currently hardcoded as `http://localhost:8000/api` in `AppComponent`. The UI calls:

- `GET /api/health` to check configuration.
- `POST /chat` with `{"message": "..."}` and reads SSE progress/token events.
- `POST /documents/upload` with repeated multipart `files` fields to save one or more files/ZIPs.
- `POST /documents/index` to index pending or previously failed uploads.
- `GET /documents` to refresh document records, counts, and indexing timestamps.

The upload response lists files saved and any rejected files. Parser, image-caption, chunk, checksum, size, content type, status, and timestamps are available in the document table and its metadata disclosure.

## Current frontend status

- A minimal standalone Angular UI is implemented; no Angular routing or separate component/service files are present.
- Current component state is in memory. Refreshing the page clears chat messages, displayed sources, and notices; the documents' vectors remain stored by the backend in Pinecone.
- The UI accepts PDF, DOCX, TXT, Markdown, CSV, JSON, and ZIP files.
- The document table uses pages of 100, polls while records are indexing, and exposes full record metadata in a disclosure panel.
- Uploading and indexing are separate actions; ZIP archives are expanded by the backend.
- Backend URL, UI prompts, and much of the markup are currently defined directly in `src/main.ts`.
- Authentication, persistent conversations, document deletion, and user-specific source management are not implemented.
