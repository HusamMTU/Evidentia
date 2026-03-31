from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
from typing import Any, Mapping

from provenance import normalize_retrieval_candidate_doc_id


_INDEX_ARN_RE = re.compile(r"^arn:[^:]+:s3vectors:[^:]+:[0-9]{12}:bucket/([^/]+)/index/([^/]+)$")
_BUCKET_ARN_RE = re.compile(r"^arn:[^:]+:s3vectors:[^:]+:[0-9]{12}:bucket/([^/]+)$")


@dataclass(frozen=True)
class InspectorConfig:
    region: str
    vector_bucket_name: str
    index_name: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class InspectorConfigDefaults:
    region: str = ""
    vector_bucket_name: str = ""
    index_name: str = ""
    index_arn: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class InspectorEnvContext:
    knowledge_base_id: str = ""
    knowledge_base_data_source_id: str = ""
    assets_bucket_name: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class InspectorConfigError(ValueError):
    """Raised when required S3 Vectors inspector configuration is missing."""


class RetrieveInspectorConfigError(ValueError):
    """Raised when Bedrock retrieve-debug configuration is missing."""


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
    defaults = resolve_config_defaults(
        region=region,
        vector_bucket_name=vector_bucket_name,
        index_name=index_name,
        index_arn=index_arn,
        env=env,
    )

    if not defaults.region:
        raise InspectorConfigError("Missing region. Set AWS_REGION/AWS_DEFAULT_REGION or pass region.")
    if not defaults.vector_bucket_name:
        raise InspectorConfigError(
            "Missing vector bucket. Set EVIDENTIA_VECTORS_BUCKET (name or arn) or pass vector_bucket_name."
        )
    if not defaults.index_name:
        raise InspectorConfigError(
            "Missing index name. Set BEDROCK_S3_VECTORS_INDEX_NAME (arn) or pass index_name."
        )

    return InspectorConfig(
        region=defaults.region,
        vector_bucket_name=defaults.vector_bucket_name,
        index_name=defaults.index_name,
    )


def resolve_config_defaults(
    *,
    region: str | None,
    vector_bucket_name: str | None,
    index_name: str | None,
    index_arn: str | None,
    env: Mapping[str, str] | None = None,
) -> InspectorConfigDefaults:
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

    normalized_bucket = ""
    if effective_bucket:
        normalized_bucket = parse_vector_bucket_name(effective_bucket)

    return InspectorConfigDefaults(
        region=effective_region or "",
        vector_bucket_name=normalized_bucket,
        index_name=effective_index_name or "",
        index_arn=effective_index_arn or "",
    )


def build_env_context(env: Mapping[str, str] | None = None) -> InspectorEnvContext:
    env_map = env or os.environ
    return InspectorEnvContext(
        knowledge_base_id=_pick_non_empty(env_map.get("BEDROCK_KNOWLEDGE_BASE_ID")) or "",
        knowledge_base_data_source_id=_pick_non_empty(env_map.get("BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID")) or "",
        assets_bucket_name=_pick_non_empty(env_map.get("EVIDENTIA_ASSETS_BUCKET")) or "",
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


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float):
        if value.is_integer() and value >= 1:
            return int(value)
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            parsed = int(cleaned)
        except ValueError:
            try:
                parsed_float = float(cleaned)
            except ValueError:
                return None
            if parsed_float.is_integer() and parsed_float >= 1:
                return int(parsed_float)
            return None
        return parsed if parsed >= 1 else None
    return None


def _pick_non_empty_metadata(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return None


def _normalize_source_file_modality(metadata_map: Mapping[str, Any]) -> str | None:
    modality = _pick_non_empty_metadata(
        metadata_map.get("source_file_modality"),
        metadata_map.get("sourceFileModality"),
        metadata_map.get("x-amz-bedrock-kb-source-file-modality"),
    )
    if modality is None:
        return None
    return modality.upper()


def _extract_location(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    location = candidate.get("location")
    if isinstance(location, Mapping):
        s3_location = location.get("s3Location")
        if isinstance(s3_location, Mapping):
            return s3_location
        return location
    return {}


def _extract_source_uri(candidate: Mapping[str, Any], metadata_map: Mapping[str, Any]) -> str | None:
    location_map = _extract_location(candidate)
    return _pick_non_empty_metadata(
        metadata_map.get("source_uri"),
        metadata_map.get("sourceUri"),
        metadata_map.get("x-amz-bedrock-kb-source-uri"),
        candidate.get("source_uri"),
        candidate.get("sourceUri"),
        location_map.get("uri"),
        location_map.get("s3Uri"),
    )


def _extract_asset_source_uri(candidate: Mapping[str, Any], metadata_map: Mapping[str, Any]) -> str | None:
    return _pick_non_empty_metadata(
        metadata_map.get("asset_source_uri"),
        metadata_map.get("asset_s3_uri"),
        metadata_map.get("assetS3Uri"),
        metadata_map.get("supplemental_uri"),
        metadata_map.get("supplementalUri"),
        metadata_map.get("x-amz-bedrock-kb-byte-content-source"),
        candidate.get("asset_source_uri"),
        candidate.get("asset_s3_uri"),
        candidate.get("assetS3Uri"),
        candidate.get("supplemental_uri"),
        candidate.get("supplementalUri"),
    )


def _s3_uri_to_key(s3_uri: str | None) -> str | None:
    if s3_uri is None or not s3_uri.startswith("s3://"):
        return None
    _, _, remainder = s3_uri.partition("s3://")
    bucket_sep = remainder.find("/")
    if bucket_sep == -1:
        return None
    key = remainder[bucket_sep + 1 :].strip()
    return key or None


def _derive_asset_id(locator: str | None) -> str | None:
    if locator is None:
        return None
    leaf = locator.rsplit("/", 1)[-1].strip()
    if not leaf:
        return None
    stem, _, _ = leaf.partition(".")
    return stem or leaf


def _normalize_content_type(content_map: Mapping[str, Any]) -> str | None:
    value = _pick_non_empty_metadata(content_map.get("type"))
    if value is None:
        return None
    return value.upper()


def _compact_text(value: str | None, *, max_length: int = 180) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split()).strip()
    if not compact:
        return None
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3] + "..."


def _extract_data_uri_mime_type(byte_content: Any) -> str | None:
    if not isinstance(byte_content, str):
        return None
    if not byte_content.startswith("data:"):
        return None
    header, _, _ = byte_content.partition(",")
    mime_type = header[5:].split(";", 1)[0].strip()
    return mime_type or None


def summarize_vector(
    vector: Mapping[str, Any],
    *,
    current_data_source_id: str | None = None,
) -> dict[str, Any]:
    key = vector.get("key")
    metadata = vector.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}
    parsed_meta = parse_bedrock_metadata(metadata_map)

    source = parsed_meta.get("source")
    source_uri = source.get("sourceLocation") if isinstance(source, Mapping) else None

    related_contents = parsed_meta.get("relatedContents")
    related_count = len(related_contents) if isinstance(related_contents, list) else 0
    related_content_types: dict[str, int] = {}
    if isinstance(related_contents, list):
        for item in related_contents:
            if not isinstance(item, Mapping):
                continue
            location_type = item.get("locationType")
            label = location_type if isinstance(location_type, str) and location_type else "<unknown>"
            related_content_types[label] = related_content_types.get(label, 0) + 1

    text_value = metadata_map.get("AMAZON_BEDROCK_TEXT")
    text_preview = None
    text_length = 0
    if isinstance(text_value, str) and text_value:
        compact = " ".join(text_value.split())
        text_preview = compact[:180] + ("..." if len(compact) > 180 else "")
        text_length = len(text_value)

    data_source_id = metadata_map.get("x-amz-bedrock-kb-data-source-id")
    is_current_data_source: bool | None = None
    if current_data_source_id:
        is_current_data_source = data_source_id == current_data_source_id

    source_file_modality = _normalize_source_file_modality(metadata_map)
    page_number = _coerce_positive_int(
        metadata_map.get("x-amz-bedrock-kb-document-page-number") or parsed_meta.get("pageNumber")
    )

    return {
        "key": key,
        "data_source_id": data_source_id,
        "source_file_modality": source_file_modality,
        "mime_type": metadata_map.get("x-amz-bedrock-kb-source-file-mime-type"),
        "page_number": page_number,
        "source_uri": source_uri,
        "related_asset_count": related_count,
        "related_content_types": related_content_types,
        "text_preview": text_preview,
        "text_length": text_length,
        "is_current_data_source": is_current_data_source,
    }


def summarize_retrieval_result(
    result: Mapping[str, Any],
    *,
    rank: int,
    provenance_resolver: Any | None = None,
) -> dict[str, Any]:
    normalized = dict(result)
    if provenance_resolver is not None:
        normalized = normalize_retrieval_candidate_doc_id(result, resolver=provenance_resolver, strict=False)

    metadata = normalized.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}
    content = normalized.get("content")
    content_map = content if isinstance(content, Mapping) else {}

    source_uri = _extract_source_uri(normalized, metadata_map)
    asset_source_uri = _extract_asset_source_uri(normalized, metadata_map)
    asset_s3_key = _pick_non_empty_metadata(
        metadata_map.get("asset_s3_key"),
        metadata_map.get("assetS3Key"),
        metadata_map.get("s3_key"),
        _s3_uri_to_key(asset_source_uri),
    )
    chunk_id = _pick_non_empty_metadata(
        metadata_map.get("chunk_id"),
        metadata_map.get("chunkId"),
        metadata_map.get("x-amz-bedrock-kb-chunk-id"),
    )
    asset_id = _pick_non_empty_metadata(
        metadata_map.get("asset_id"),
        metadata_map.get("assetId"),
        metadata_map.get("x-amz-bedrock-kb-asset-id"),
        _derive_asset_id(asset_s3_key or asset_source_uri),
    )
    text_preview = _compact_text(_pick_non_empty_metadata(content_map.get("text")))
    description_preview = _compact_text(
        _pick_non_empty_metadata(
            metadata_map.get("caption"),
            metadata_map.get("asset_caption"),
            metadata_map.get("x-amz-bedrock-kb-description"),
        )
    )
    score = normalized.get("score")

    return {
        "rank": rank,
        "content_type": _normalize_content_type(content_map),
        "source_file_modality": _normalize_source_file_modality(metadata_map),
        "doc_id": _pick_non_empty_metadata(normalized.get("doc_id"), metadata_map.get("doc_id")),
        "data_source_id": _pick_non_empty_metadata(metadata_map.get("x-amz-bedrock-kb-data-source-id")),
        "chunk_id": chunk_id,
        "asset_id": asset_id,
        "asset_source_uri": asset_source_uri,
        "asset_s3_key": asset_s3_key,
        "source_uri": source_uri,
        "page_number": _coerce_positive_int(
            metadata_map.get("page")
            or metadata_map.get("page_number")
            or metadata_map.get("pageNumber")
            or metadata_map.get("x-amz-bedrock-kb-document-page-number")
        ),
        "text_preview": text_preview,
        "description_preview": description_preview,
        "has_byte_content": isinstance(content_map.get("byteContent"), str) and bool(content_map.get("byteContent")),
        "byte_content_mime_type": _extract_data_uri_mime_type(content_map.get("byteContent")),
        "score": float(score) if isinstance(score, (int, float)) else None,
    }


def summarize_retrieve_response(
    response: Mapping[str, Any],
    *,
    provenance_resolver: Any | None = None,
) -> dict[str, Any]:
    raw_results = response.get("retrievalResults")
    results = raw_results if isinstance(raw_results, list) else []
    rows = [
        summarize_retrieval_result(result, rank=index + 1, provenance_resolver=provenance_resolver)
        for index, result in enumerate(results)
        if isinstance(result, Mapping)
    ]
    content_type_counts: dict[str, int] = {}
    source_file_modality_counts: dict[str, int] = {}
    resolved_doc_ids: list[str] = []

    for row in rows:
        content_type = row.get("content_type") or "<missing>"
        source_file_modality = row.get("source_file_modality") or "<missing>"
        content_type_counts[str(content_type)] = content_type_counts.get(str(content_type), 0) + 1
        source_file_modality_counts[str(source_file_modality)] = (
            source_file_modality_counts.get(str(source_file_modality), 0) + 1
        )
        doc_id = row.get("doc_id")
        if isinstance(doc_id, str) and doc_id and doc_id not in resolved_doc_ids:
            resolved_doc_ids.append(doc_id)

    return {
        "rows": rows,
        "summary": {
            "retrieved_result_count": len(rows),
            "content_type_counts": dict(sorted(content_type_counts.items(), key=lambda item: (-item[1], item[0]))),
            "source_file_modality_counts": dict(
                sorted(source_file_modality_counts.items(), key=lambda item: (-item[1], item[0]))
            ),
            "resolved_doc_ids": resolved_doc_ids,
            "resolved_doc_count": len(resolved_doc_ids),
        },
        "next_token": _pick_non_empty_metadata(response.get("nextToken")),
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

    def get_index(self) -> dict[str, Any]:
        response = self._client.get_index(
            vectorBucketName=self.config.vector_bucket_name,
            indexName=self.config.index_name,
        )
        index = response.get("index")
        return index if isinstance(index, dict) else {}

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


class BedrockRetrieveInspectorClient:
    def __init__(self, *, knowledge_base_id: str, region: str, boto_client: Any) -> None:
        knowledge_base_clean = knowledge_base_id.strip()
        region_clean = region.strip()
        if not knowledge_base_clean:
            raise RetrieveInspectorConfigError("Missing knowledge base ID.")
        if not region_clean:
            raise RetrieveInspectorConfigError("Missing region.")
        self.knowledge_base_id = knowledge_base_clean
        self.region = region_clean
        self._client = boto_client

    @classmethod
    def from_runtime(cls, *, knowledge_base_id: str, region: str) -> "BedrockRetrieveInspectorClient":
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - runtime environment dependent
            raise RuntimeError("boto3 is required to run Bedrock retrieve debug.") from exc

        client = boto3.client("bedrock-agent-runtime", region_name=region)
        return cls(knowledge_base_id=knowledge_base_id, region=region, boto_client=client)

    def retrieve(
        self,
        *,
        query_text: str,
        top_k: int,
        next_token: str | None = None,
        override_search_type: str | None = None,
    ) -> dict[str, Any]:
        query_clean = query_text.strip()
        if not query_clean:
            raise ValueError("query_text must be non-empty")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")

        request: dict[str, Any] = {
            "knowledgeBaseId": self.knowledge_base_id,
            "retrievalQuery": {"text": query_clean},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": top_k,
                }
            },
        }
        if next_token:
            request["nextToken"] = next_token
        if override_search_type and override_search_type.strip():
            request["retrievalConfiguration"]["vectorSearchConfiguration"]["overrideSearchType"] = (
                override_search_type.strip()
            )
        return self._client.retrieve(**request)


def summarize_by_data_source(
    vectors: list[Mapping[str, Any]],
    *,
    current_data_source_id: str | None = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    source_file_modality_counts: dict[str, int] = {}

    for vector in vectors:
        metadata = vector.get("metadata")
        metadata_map = metadata if isinstance(metadata, Mapping) else {}

        ds_id = metadata_map.get("x-amz-bedrock-kb-data-source-id")
        if isinstance(ds_id, str) and ds_id:
            counts[ds_id] = counts.get(ds_id, 0) + 1
        else:
            counts["<missing>"] = counts.get("<missing>", 0) + 1

        source_file_modality = _normalize_source_file_modality(metadata_map)
        if isinstance(source_file_modality, str) and source_file_modality:
            source_file_modality_counts[source_file_modality] = (
                source_file_modality_counts.get(source_file_modality, 0) + 1
            )
        else:
            source_file_modality_counts["<missing>"] = source_file_modality_counts.get("<missing>", 0) + 1

    active_data_source_ids = [ds_id for ds_id in counts if ds_id != "<missing>"]
    historical_data_source_ids = [
        ds_id for ds_id in active_data_source_ids if current_data_source_id and ds_id != current_data_source_id
    ]
    historical_count = sum(counts[ds_id] for ds_id in historical_data_source_ids)

    return {
        "data_source_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
        "source_file_modality_counts": dict(
            sorted(source_file_modality_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "current_data_source_id": current_data_source_id or "",
        "current_data_source_vector_count": counts.get(current_data_source_id, 0) if current_data_source_id else 0,
        "historical_data_source_ids": historical_data_source_ids,
        "historical_data_source_vector_count": historical_count,
        "unique_data_source_count": len(active_data_source_ids),
    }
