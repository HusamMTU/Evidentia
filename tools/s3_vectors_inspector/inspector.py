from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
from typing import Any, Mapping


_INDEX_ARN_RE = re.compile(r"^arn:[^:]+:s3vectors:[^:]+:[0-9]{12}:bucket/([^/]+)/index/([^/]+)$")
_BUCKET_ARN_RE = re.compile(r"^arn:[^:]+:s3vectors:[^:]+:[0-9]{12}:bucket/([^/]+)$")


@dataclass(frozen=True)
class InspectorConfig:
    region: str
    vector_bucket_name: str
    index_name: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class InspectorConfigError(ValueError):
    """Raised when required S3 Vectors inspector configuration is missing."""


def parse_index_arn(index_arn: str) -> tuple[str, str]:
    match = _INDEX_ARN_RE.match(index_arn.strip())
    if not match:
        raise InspectorConfigError(
            "Invalid index ARN. Expected arn:...:s3vectors:<region>:<account>:bucket/<bucket>/index/<index>."
        )
    return match.group(1), match.group(2)


def parse_vector_bucket_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InspectorConfigError("Vector bucket value is empty.")

    arn_match = _BUCKET_ARN_RE.match(cleaned)
    if arn_match:
        return arn_match.group(1)

    return cleaned


def _pick_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def build_config(
    *,
    region: str | None,
    vector_bucket_name: str | None,
    index_name: str | None,
    index_arn: str | None,
    env: Mapping[str, str] | None = None,
) -> InspectorConfig:
    env_map = env or os.environ

    effective_region = _pick_non_empty(region, env_map.get("AWS_REGION"), env_map.get("AWS_DEFAULT_REGION"))
    effective_index_arn = _pick_non_empty(index_arn, env_map.get("BEDROCK_S3_VECTORS_INDEX_NAME"))
    effective_bucket = _pick_non_empty(vector_bucket_name, env_map.get("EVIDENTIA_VECTORS_BUCKET"))
    effective_index_name = _pick_non_empty(index_name)

    if effective_index_arn:
        try:
            arn_bucket, arn_index = parse_index_arn(effective_index_arn)
        except InspectorConfigError:
            # BEDROCK_S3_VECTORS_INDEX_NAME can be unset/empty or malformed in local dev.
            arn_bucket = ""
            arn_index = ""
        if not effective_bucket and arn_bucket:
            effective_bucket = arn_bucket
        if not effective_index_name and arn_index:
            effective_index_name = arn_index

    if not effective_region:
        raise InspectorConfigError("Missing region. Set AWS_REGION/AWS_DEFAULT_REGION or pass region.")
    if not effective_bucket:
        raise InspectorConfigError(
            "Missing vector bucket. Set EVIDENTIA_VECTORS_BUCKET (name or arn) or pass vector_bucket_name."
        )
    if not effective_index_name:
        raise InspectorConfigError(
            "Missing index name. Set BEDROCK_S3_VECTORS_INDEX_NAME (arn) or pass index_name."
        )

    return InspectorConfig(
        region=effective_region,
        vector_bucket_name=parse_vector_bucket_name(effective_bucket),
        index_name=effective_index_name,
    )


def parse_bedrock_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    raw = metadata.get("AMAZON_BEDROCK_METADATA")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def summarize_vector(vector: Mapping[str, Any]) -> dict[str, Any]:
    key = vector.get("key")
    metadata = vector.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}
    parsed_meta = parse_bedrock_metadata(metadata_map)

    source = parsed_meta.get("source")
    source_uri = source.get("sourceLocation") if isinstance(source, Mapping) else None

    related_contents = parsed_meta.get("relatedContents")
    related_count = len(related_contents) if isinstance(related_contents, list) else 0

    text_value = metadata_map.get("AMAZON_BEDROCK_TEXT")
    text_preview = None
    if isinstance(text_value, str) and text_value:
        compact = " ".join(text_value.split())
        text_preview = compact[:180] + ("..." if len(compact) > 180 else "")

    return {
        "key": key,
        "data_source_id": metadata_map.get("x-amz-bedrock-kb-data-source-id"),
        "modality": metadata_map.get("x-amz-bedrock-kb-source-file-modality"),
        "mime_type": metadata_map.get("x-amz-bedrock-kb-source-file-mime-type"),
        "page_number": metadata_map.get("x-amz-bedrock-kb-document-page-number") or parsed_meta.get("pageNumber"),
        "source_uri": source_uri,
        "related_asset_count": related_count,
        "text_preview": text_preview,
    }


class S3VectorsInspectorClient:
    def __init__(self, config: InspectorConfig, boto_client: Any) -> None:
        self.config = config
        self._client = boto_client

    @classmethod
    def from_config(cls, config: InspectorConfig) -> "S3VectorsInspectorClient":
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - runtime environment dependent
            raise RuntimeError("boto3 is required to run the S3 Vectors inspector.") from exc

        client = boto3.client("s3vectors", region_name=config.region)
        return cls(config=config, boto_client=client)

    def list_vector_buckets(self, *, max_results: int = 100, next_token: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"maxResults": max_results}
        if next_token:
            kwargs["nextToken"] = next_token
        return self._client.list_vector_buckets(**kwargs)

    def list_indexes(
        self,
        *,
        vector_bucket_name: str | None = None,
        max_results: int = 100,
        next_token: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "vectorBucketName": vector_bucket_name or self.config.vector_bucket_name,
            "maxResults": max_results,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        return self._client.list_indexes(**kwargs)

    def list_vectors(
        self,
        *,
        max_results: int,
        next_token: str | None = None,
        return_metadata: bool = True,
        return_data: bool = False,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "vectorBucketName": self.config.vector_bucket_name,
            "indexName": self.config.index_name,
            "maxResults": max_results,
            "returnMetadata": return_metadata,
            "returnData": return_data,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        return self._client.list_vectors(**kwargs)

    def get_vector(
        self,
        *,
        key: str,
        return_metadata: bool = True,
        return_data: bool = True,
    ) -> dict[str, Any] | None:
        response = self._client.get_vectors(
            vectorBucketName=self.config.vector_bucket_name,
            indexName=self.config.index_name,
            keys=[key],
            returnMetadata=return_metadata,
            returnData=return_data,
        )
        vectors = response.get("vectors", [])
        if not vectors:
            return None
        return vectors[0]

    def query_by_key(
        self,
        *,
        key: str,
        top_k: int,
        return_metadata: bool = True,
    ) -> dict[str, Any]:
        seed = self.get_vector(key=key, return_metadata=return_metadata, return_data=True)
        if seed is None:
            raise KeyError(f"Vector key not found: {key}")

        data = seed.get("data") if isinstance(seed, Mapping) else None
        float_data = data.get("float32") if isinstance(data, Mapping) else None
        if not isinstance(float_data, list) or not float_data:
            raise ValueError(f"Vector key '{key}' has no float32 data.")

        response = self._client.query_vectors(
            vectorBucketName=self.config.vector_bucket_name,
            indexName=self.config.index_name,
            queryVector={"float32": float_data},
            topK=top_k,
            returnDistance=True,
            returnMetadata=return_metadata,
        )
        return {
            "seed": seed,
            "distance_metric": response.get("distanceMetric"),
            "matches": response.get("vectors", []),
        }


def summarize_by_data_source(vectors: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    modality_counts: dict[str, int] = {}

    for vector in vectors:
        metadata = vector.get("metadata")
        metadata_map = metadata if isinstance(metadata, Mapping) else {}

        ds_id = metadata_map.get("x-amz-bedrock-kb-data-source-id")
        if isinstance(ds_id, str) and ds_id:
            counts[ds_id] = counts.get(ds_id, 0) + 1
        else:
            counts["<missing>"] = counts.get("<missing>", 0) + 1

        modality = metadata_map.get("x-amz-bedrock-kb-source-file-modality")
        if isinstance(modality, str) and modality:
            modality_counts[modality] = modality_counts.get(modality, 0) + 1
        else:
            modality_counts["<missing>"] = modality_counts.get("<missing>", 0) + 1

    return {
        "data_source_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
        "modality_counts": dict(sorted(modality_counts.items(), key=lambda item: (-item[1], item[0]))),
    }
