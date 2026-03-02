from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_s3_uri(source_uri: str) -> tuple[str, str]:
    if not source_uri.startswith("s3://"):
        raise ValueError(f"source_uri must start with s3://, got: {source_uri!r}")

    body = source_uri[5:]
    if "/" not in body:
        raise ValueError(f"source_uri must include object key, got: {source_uri!r}")

    bucket, key = body.split("/", 1)
    if not bucket or not key:
        raise ValueError(f"source_uri must include non-empty bucket/key, got: {source_uri!r}")
    return bucket, key


def make_s3_uri(bucket: str, key: str) -> str:
    bucket_clean = bucket.strip()
    key_clean = key.lstrip("/")
    if not bucket_clean or not key_clean:
        raise ValueError("bucket and key must be non-empty")
    return f"s3://{bucket_clean}/{key_clean}"


@dataclass(frozen=True)
class IngestionManifestRecord:
    doc_id: str
    source_uri: str
    source_bucket: str
    source_key: str
    status: str = "registered"
    kb_id: str | None = None
    data_source_id: str | None = None
    ingestion_job_id: str | None = None
    source_etag: str | None = None
    source_version_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_doc_and_uri(
        cls,
        *,
        doc_id: str,
        source_uri: str,
        status: str = "registered",
        kb_id: str | None = None,
        data_source_id: str | None = None,
        ingestion_job_id: str | None = None,
        source_etag: str | None = None,
        source_version_id: str | None = None,
    ) -> "IngestionManifestRecord":
        bucket, key = parse_s3_uri(source_uri)
        return cls(
            doc_id=doc_id,
            source_uri=source_uri,
            source_bucket=bucket,
            source_key=key,
            status=status,
            kb_id=kb_id,
            data_source_id=data_source_id,
            ingestion_job_id=ingestion_job_id,
            source_etag=source_etag,
            source_version_id=source_version_id,
        )


class SQLiteIngestionManifestStore:
    """Durable doc_id <-> source URI mapping used for provenance joins."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_manifest (
                    doc_id TEXT PRIMARY KEY,
                    source_uri TEXT NOT NULL UNIQUE,
                    source_bucket TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    kb_id TEXT,
                    data_source_id TEXT,
                    ingestion_job_id TEXT,
                    source_etag TEXT,
                    source_version_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_manifest_source_uri ON ingestion_manifest(source_uri)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingestion_manifest_doc_id ON ingestion_manifest(doc_id)"
            )

    def upsert(self, record: IngestionManifestRecord) -> IngestionManifestRecord:
        if not record.doc_id.strip():
            raise ValueError("doc_id must be non-empty")

        now = _utc_now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT created_at FROM ingestion_manifest WHERE doc_id = ?",
                (record.doc_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing is not None else now

            conn.execute(
                """
                INSERT INTO ingestion_manifest (
                    doc_id,
                    source_uri,
                    source_bucket,
                    source_key,
                    status,
                    kb_id,
                    data_source_id,
                    ingestion_job_id,
                    source_etag,
                    source_version_id,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    source_uri=excluded.source_uri,
                    source_bucket=excluded.source_bucket,
                    source_key=excluded.source_key,
                    status=excluded.status,
                    kb_id=excluded.kb_id,
                    data_source_id=excluded.data_source_id,
                    ingestion_job_id=excluded.ingestion_job_id,
                    source_etag=excluded.source_etag,
                    source_version_id=excluded.source_version_id,
                    updated_at=excluded.updated_at
                """,
                (
                    record.doc_id,
                    record.source_uri,
                    record.source_bucket,
                    record.source_key,
                    record.status,
                    record.kb_id,
                    record.data_source_id,
                    record.ingestion_job_id,
                    record.source_etag,
                    record.source_version_id,
                    created_at,
                    now,
                ),
            )
        return self.get_by_doc_id(record.doc_id)  # type: ignore[return-value]

    def get_by_doc_id(self, doc_id: str) -> IngestionManifestRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_manifest WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_source_uri(self, source_uri: str) -> IngestionManifestRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_manifest WHERE source_uri = ?",
                (source_uri,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def resolve_doc_id(
        self,
        *,
        source_uri: str | None = None,
        source_bucket: str | None = None,
        source_key: str | None = None,
    ) -> str | None:
        if source_uri:
            record = self.get_by_source_uri(source_uri)
            return record.doc_id if record else None

        if source_bucket and source_key:
            return self.resolve_doc_id(source_uri=make_s3_uri(source_bucket, source_key))
        return None

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> IngestionManifestRecord:
        return IngestionManifestRecord(
            doc_id=row["doc_id"],
            source_uri=row["source_uri"],
            source_bucket=row["source_bucket"],
            source_key=row["source_key"],
            status=row["status"],
            kb_id=row["kb_id"],
            data_source_id=row["data_source_id"],
            ingestion_job_id=row["ingestion_job_id"],
            source_etag=row["source_etag"],
            source_version_id=row["source_version_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

