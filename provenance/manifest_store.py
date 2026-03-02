from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


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


SOURCE_URI_INDEX_NAME = "source_uri-index"


class DynamoTableClient(Protocol):
    def put_item(self, *, Item: dict[str, Any]) -> Any:
        ...

    def get_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:
        ...

    def query(self, **kwargs: Any) -> dict[str, Any]:
        ...


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

    def to_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "doc_id": self.doc_id,
            "source_uri": self.source_uri,
            "source_bucket": self.source_bucket,
            "source_key": self.source_key,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        optional_fields = {
            "kb_id": self.kb_id,
            "data_source_id": self.data_source_id,
            "ingestion_job_id": self.ingestion_job_id,
            "source_etag": self.source_etag,
            "source_version_id": self.source_version_id,
        }
        for key, value in optional_fields.items():
            if value is not None:
                item[key] = value
        return item

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "IngestionManifestRecord":
        return cls(
            doc_id=item["doc_id"],
            source_uri=item["source_uri"],
            source_bucket=item["source_bucket"],
            source_key=item["source_key"],
            status=item["status"],
            kb_id=item.get("kb_id"),
            data_source_id=item.get("data_source_id"),
            ingestion_job_id=item.get("ingestion_job_id"),
            source_etag=item.get("source_etag"),
            source_version_id=item.get("source_version_id"),
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
        )

class DynamoIngestionManifestStore:
    """Durable doc_id <-> source URI mapping backed by DynamoDB."""

    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        source_uri_index_name: str = SOURCE_URI_INDEX_NAME,
        table: DynamoTableClient | None = None,
    ) -> None:
        if not table_name.strip():
            raise ValueError("table_name must be non-empty")
        self._table_name = table_name
        self._source_uri_index_name = source_uri_index_name
        self._table = table or self._build_table_resource(table_name=table_name, region_name=region_name)

    @staticmethod
    def _build_table_resource(*, table_name: str, region_name: str | None) -> DynamoTableClient:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "boto3 is required for DynamoDB-backed ingestion manifest store. "
                "Install it with: pip install boto3"
            ) from exc

        dynamodb = boto3.resource("dynamodb", region_name=region_name) if region_name else boto3.resource(
            "dynamodb"
        )
        return dynamodb.Table(table_name)

    def upsert(self, record: IngestionManifestRecord) -> IngestionManifestRecord:
        if not record.doc_id.strip():
            raise ValueError("doc_id must be non-empty")

        source_owner = self.get_by_source_uri(record.source_uri)
        if source_owner and source_owner.doc_id != record.doc_id:
            raise ValueError(
                f"source_uri {record.source_uri!r} is already mapped to doc_id "
                f"{source_owner.doc_id!r}"
            )

        now = _utc_now_iso()
        existing = self.get_by_doc_id(record.doc_id)
        created_at = existing.created_at if existing and existing.created_at else now
        persisted = IngestionManifestRecord(
            doc_id=record.doc_id,
            source_uri=record.source_uri,
            source_bucket=record.source_bucket,
            source_key=record.source_key,
            status=record.status,
            kb_id=record.kb_id,
            data_source_id=record.data_source_id,
            ingestion_job_id=record.ingestion_job_id,
            source_etag=record.source_etag,
            source_version_id=record.source_version_id,
            created_at=created_at,
            updated_at=now,
        )
        self._table.put_item(Item=persisted.to_item())
        return persisted

    def get_by_doc_id(self, doc_id: str) -> IngestionManifestRecord | None:
        response = self._table.get_item(Key={"doc_id": doc_id})
        item = response.get("Item")
        if item is None:
            return None
        return IngestionManifestRecord.from_item(item)

    def get_by_source_uri(self, source_uri: str) -> IngestionManifestRecord | None:
        response = self._table.query(
            IndexName=self._source_uri_index_name,
            KeyConditionExpression="source_uri = :source_uri",
            ExpressionAttributeValues={":source_uri": source_uri},
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        return IngestionManifestRecord.from_item(items[0])

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
