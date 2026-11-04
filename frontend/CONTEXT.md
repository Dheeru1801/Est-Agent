# Frontend Context

## Purpose

The frontend is a single-page Angular chat interface for the document RAG backend. It lets users check backend readiness, upload PDF/text documents, ask questions, and see answers and upload status.

## Files and folders

| Path | Purpose |
| --- | --- |
| `frontend/package.json` | Angular scripts and dependency ranges. `npm start` runs the development server; `npm run build` creates a production build. |
| `frontend/package-lock.json` | Locks npm dependency versions for repeatable installation. |
| `frontend/angular.json` | Angular CLI configuration for the application build and development server. |
| `frontend/tsconfig.json` | Shared TypeScript settings and strict Angular compiler options. |
| `frontend/tsconfig.app.json` | TypeScript compilation settings for the application source. |
| `frontend/src/` | Angular entry point and UI assets. |
| `frontend/src/main.ts` | Bootstraps the standalone Angular component and implements chat, health, and upload interactions. |
| `frontend/src/index.html` | Browser page shell with the `<app-root>` Angular mount point. |
| `frontend/src/styles.css` | Application layout, colors, typography, responsive rules, and animations. |

Generated/local-only folders include `frontend/node_modules/`, `frontend/dist/`, and `frontend/.angular/`.

## Components, types, and functions

### `src/main.ts`

| Name | Responsibility | Technologies |
| --- | --- | --- |
| `Message` | TypeScript shape for an in-memory message: `role` and `text`. | TypeScript |
| `AppComponent` | Standalone root component. Holds current draft, messages, displayed document names, loading state, backend status, and toast notice. Its inline template renders the sidebar, upload control, suggestions, conversation, and composer. | Angular standalone components, `CommonModule`, `FormsModule` |
| `constructor()` | Starts a backend health check when the component is created. | Angular component lifecycle |
| `checkHealth()` | Calls `GET http://localhost:8000/api/health` and updates the connected/configured state. | Browser `fetch`, FastAPI |
| `onKey(event)` | Sends on Enter; Shift+Enter leaves a newline in the composer. | DOM keyboard events |
| `clearChat()` | Clears the in-memory message list for a new conversation. | Angular component state |
| `send(value?)` | Posts JSON to `POST /api/chat`, appends the user and assistant messages, and manages loading and error messages. | Browser `fetch`, FastAPI |
| `upload(event)` | Sends the selected file as multipart `FormData` to `POST /api/upload`, shows an indexed/error toast, and adds the filename to the UI list. | Browser `FormData` and `fetch`, FastAPI |
| `bootstrapApplication(AppComponent)` | Starts Angular with the standalone root component. | Angular `bootstrapApplication` |

## Backend communication

The development API base URL is currently hardcoded as `http://localhost:8000/api` in `AppComponent`. The UI calls:

- `GET /health` to check configuration.
- `POST /chat` with `{"message": "..."}` to submit a chat message.
- `POST /upload` with multipart field `file` to index a document.

The upload endpoint returns the parser and image-caption count as well as the chunk count, but the current UI toast displays only the filename and chunk count.

## Current frontend status

- A minimal standalone Angular UI is implemented; no Angular routing or separate component/service files are present.
- Current component state is in memory. Refreshing the page clears chat messages, displayed sources, and notices; the documents' vectors remain stored by the backend in Pinecone.
- The UI accepts PDF, TXT, Markdown, CSV, and JSON files.
- Backend URL, UI prompts, and much of the markup are currently defined directly in `src/main.ts`.
- Authentication, persistent conversations, document deletion, and user-specific source management are not implemented.
