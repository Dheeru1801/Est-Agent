"""SQLite persistence for uploaded document records."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "data" / "rag_agent.sqlite3"


def _database_path() -> Path:
    """Resolve the configured SQLite database path."""
    configured_path = Path(os.getenv("SQLITE_DB_PATH", str(DEFAULT_DATABASE_PATH)))
    if not configured_path.is_absolute():
        configured_path = BACKEND_DIR / configured_path
    return configured_path


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Open a configured SQLite connection and close it after use."""
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def initialize_database() -> None:
    """Create the document registry table if it does not already exist."""
    with _connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                content_type TEXT,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('uploading', 'indexing', 'indexed', 'failed')
                ),
                parser TEXT,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                image_description_count INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_created_at "
            "ON documents(created_at DESC)"
        )


def create_document(
    *,
    document_id: str,
    filename: str,
    stored_path: str,
    content_type: str | None,
    size_bytes: int,
    sha256: str,
) -> None:
    """Register a persisted upload before document parsing and indexing."""
    now = _utc_now()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO documents (
                id, filename, stored_path, content_type, size_bytes, sha256,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'uploading', ?, ?)
            """,
            (
                document_id,
                filename,
                stored_path,
                content_type,
                size_bytes,
                sha256,
                now,
                now,
            ),
        )


def update_document(
    document_id: str,
    *,
    status: str,
    parser: str | None = None,
    chunk_count: int = 0,
    image_description_count: int = 0,
    error: str | None = None,
) -> None:
    """Update upload processing status and its indexing results."""
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE documents
            SET status = ?, parser = ?, chunk_count = ?,
                image_description_count = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                parser,
                chunk_count,
                image_description_count,
                error,
                _utc_now(),
                document_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Document {document_id} was not found in the database.")


def get_document_overview(limit: int = 100) -> dict[str, object]:
    """Return total counts and recent document records without file paths."""
    with _connection() as connection:
        total_documents = connection.execute(
            "SELECT COUNT(*) FROM documents"
        ).fetchone()[0]
        status_rows = connection.execute(
            "SELECT status, COUNT(*) AS count FROM documents GROUP BY status"
        ).fetchall()
        rows = connection.execute(
            """
            SELECT id, filename, content_type, size_bytes, sha256, status,
                   parser, chunk_count, image_description_count, error,
                   created_at, updated_at
            FROM documents
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
    status_counts = {
        status: 0
        for status in ("uploading", "indexing", "indexed", "failed")
    }
    status_counts.update({row["status"]: row["count"] for row in status_rows})
    indexed_documents = status_counts["indexed"]
    documents = [dict(row) for row in rows]
    for document in documents:
        document["is_indexed"] = document["status"] == "indexed"
    return {
        "total_documents": total_documents,
        "indexed_documents": indexed_documents,
        "not_indexed_documents": total_documents - indexed_documents,
        "status_counts": status_counts,
        "documents": documents,
    }
