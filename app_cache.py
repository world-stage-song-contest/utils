"""Shared, cross-platform SQLite cache for recap rendering and uploads."""

# pyright: reportMissingImports=false

from __future__ import annotations

from pathlib import Path
import sqlite3

from platformdirs import user_cache_path


APP_NAME = "world-stage-recap-maker"
DATABASE_FILENAME = "world-stage-cache.sqlite3"


def database_path() -> Path:
    return Path(user_cache_path(APP_NAME, appauthor=False, ensure_exists=True)) / DATABASE_FILENAME


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), timeout=30)
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def initialize_database() -> Path:
    """Create the shared cache tables and return the database location."""
    database = database_path()
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recap_outputs (
                path TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_cache (
                endpoint_url TEXT NOT NULL,
                bucket TEXT NOT NULL,
                object_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (endpoint_url, bucket, object_name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recap_api_cache (
                url TEXT PRIMARY KEY,
                etag TEXT,
                path TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    return database


def cached_recap_fingerprint(output: Path) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT fingerprint FROM recap_outputs WHERE path = ?", (str(output.absolute()),)
        ).fetchone()
    return None if row is None else str(row[0])


def store_recap_fingerprint(output: Path, fingerprint: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO recap_outputs (path, fingerprint) VALUES (?, ?)
            ON CONFLICT(path) DO UPDATE SET fingerprint = excluded.fingerprint
            """,
            (str(output.absolute()), fingerprint),
        )


def is_cached_upload(path: Path, endpoint_url: str, bucket: str, object_name: str | None = None) -> bool:
    stat = path.stat()
    object_name = object_name or path.name
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT source_path, size, mtime_ns FROM upload_cache
            WHERE endpoint_url = ? AND bucket = ? AND object_name = ?
            """,
            (endpoint_url, bucket, object_name),
        ).fetchone()
    return row == (str(path.resolve()), stat.st_size, stat.st_mtime_ns)


def store_upload(path: Path, endpoint_url: str, bucket: str, object_name: str | None = None) -> None:
    stat = path.stat()
    object_name = object_name or path.name
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO upload_cache (endpoint_url, bucket, object_name, source_path, size, mtime_ns)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint_url, bucket, object_name) DO UPDATE SET
                source_path = excluded.source_path,
                size = excluded.size,
                mtime_ns = excluded.mtime_ns,
                uploaded_at = CURRENT_TIMESTAMP
            """,
            (endpoint_url, bucket, object_name, str(path.resolve()), stat.st_size, stat.st_mtime_ns),
        )


def clear_upload_cache() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM upload_cache")


def cached_api_response(url: str) -> tuple[str | None, Path] | None:
    with _connect() as conn:
        row = conn.execute("SELECT etag, path FROM recap_api_cache WHERE url = ?", (url,)).fetchone()
    return None if row is None else (row[0], Path(row[1]))


def store_api_response(url: str, etag: str | None, path: Path) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO recap_api_cache (url, etag, path) VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, path = excluded.path,
                updated_at = CURRENT_TIMESTAMP
            """,
            (url, etag, str(path.resolve())),
        )
