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
    """Create or migrate the document registry schema."""
    with _connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
        ).fetchone()
        if table is None:
            _create_documents_table(connection)
        else:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(documents)").fetchall()
            }
            schema = table["sql"] or ""
            if not {"uploaded_at", "index_started_at", "indexed_at"}.issubset(columns) \
                    or "'uploaded'" not in schema:
                _migrate_documents_table(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_created_at "
            "ON documents(created_at DESC)"
        )


def _create_documents_table(connection: sqlite3.Connection) -> None:
    """Create the current document registry schema."""
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
                status IN ('uploaded', 'indexing', 'indexed', 'failed')
            ),
            parser TEXT,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            image_description_count INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            uploaded_at TEXT NOT NULL,
            index_started_at TEXT,
            indexed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _migrate_documents_table(connection: sqlite3.Connection) -> None:
    """Migrate rows from the original upload-and-index schema."""
    old_rows = connection.execute("SELECT * FROM documents").fetchall()
    connection.execute("DROP INDEX IF EXISTS idx_documents_created_at")
    connection.execute("ALTER TABLE documents RENAME TO documents_legacy")
    _create_documents_table(connection)
    for row in old_rows:
        old = dict(row)
        old_status = old.get("status", "uploaded")
        status = "uploaded" if old_status in {"uploading", "indexing"} else old_status
        created_at = old.get("created_at") or _utc_now()
        updated_at = old.get("updated_at") or created_at
        connection.execute(
            """
            INSERT INTO documents (
                id, filename, stored_path, content_type, size_bytes, sha256,
                status, parser, chunk_count, image_description_count, error,
                uploaded_at, index_started_at, indexed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                old["id"], old["filename"], old["stored_path"],
                old.get("content_type"), old.get("size_bytes", 0),
                old.get("sha256", ""), status, old.get("parser"),
                old.get("chunk_count", 0), old.get("image_description_count", 0),
                old.get("error"), created_at,
                updated_at if old_status == "indexing" else None,
                updated_at if old_status == "indexed" else None,
                created_at, updated_at,
            ),
        )
    connection.execute("DROP TABLE documents_legacy")


def create_document(
    *,
    document_id: str,
    filename: str,
    stored_path: str,
    content_type: str | None,
    size_bytes: int,
    sha256: str,
) -> str:
    """Register a saved upload without starting indexing."""
    now = _utc_now()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO documents (
                id, filename, stored_path, content_type, size_bytes, sha256,
                status, uploaded_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'uploaded', ?, ?, ?)
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
                now,
            ),
        )
    return now


def update_document(
    document_id: str,
    *,
    status: str,
    parser: str | None = None,
    chunk_count: int | None = None,
    image_description_count: int | None = None,
    error: str | None = None,
) -> None:
    """Update upload processing status and its indexing results."""
    now = _utc_now()
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE documents
            SET status = ?, parser = COALESCE(?, parser),
                chunk_count = COALESCE(?, chunk_count),
                image_description_count = COALESCE(?, image_description_count),
                error = ?,
                index_started_at = CASE WHEN ? = 'indexing' THEN ? ELSE index_started_at END,
                indexed_at = CASE WHEN ? = 'indexed' THEN ? ELSE indexed_at END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                parser,
                chunk_count,
                image_description_count,
                error,
                status,
                now,
                status,
                now,
                now,
                document_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Document {document_id} was not found in the database.")


def claim_documents_to_index() -> list[dict[str, object]]:
    """Atomically mark uploaded or failed records for indexing."""
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT id, filename, stored_path
            FROM documents
            WHERE status IN ('uploaded', 'failed')
            ORDER BY uploaded_at ASC
            """
        ).fetchall()
        now = _utc_now()
        connection.executemany(
            """
            UPDATE documents
            SET status = 'indexing', index_started_at = ?, indexed_at = NULL,
                parser = NULL, chunk_count = 0, image_description_count = 0,
                error = NULL, updated_at = ?
            WHERE id = ?
            """,
            [(now, now, row["id"]) for row in rows],
        )
    return [dict(row) for row in rows]


def recover_interrupted_indexing() -> None:
    """Return records left indexing by a stopped server to the retry queue."""
    with _connection() as connection:
        connection.execute(
            """
            UPDATE documents
            SET status = 'uploaded', index_started_at = NULL, updated_at = ?
            WHERE status = 'indexing'
            """,
            (_utc_now(),),
        )


def get_document_overview(limit: int = 100, offset: int = 0) -> dict[str, object]:
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
                   uploaded_at, index_started_at, indexed_at, created_at, updated_at
            FROM documents
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
    status_counts = dict.fromkeys(
        ("uploaded", "indexing", "indexed", "failed"), 0
    )
    status_counts.update({row["status"]: row["count"] for row in status_rows})
    indexed_documents = status_counts["indexed"]
    documents = [dict(row) for row in rows]
    for document in documents:
        document["is_indexed"] = document["status"] == "indexed"
    return {
        "total_documents": total_documents,
        "indexed_documents": indexed_documents,
        "not_indexed_documents": total_documents - indexed_documents,
        "pending_documents": status_counts["uploaded"] + status_counts["failed"],
        "status_counts": status_counts,
        "documents": documents,
    }
