from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .errors import ProvenanceResolutionError
from .manifest_store import make_s3_uri


class DocIdResolver(Protocol):
    def resolve_doc_id(
        self,
        *,
        source_uri: str | None = None,
        source_bucket: str | None = None,
        source_key: str | None = None,
    ) -> str | None:
        ...


def _first_non_empty(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                return trimmed
    return None


def _extract_location(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    location = candidate.get("location")
    if isinstance(location, Mapping):
        s3_location = location.get("s3Location")
        if isinstance(s3_location, Mapping):
            return s3_location
        return location
    return {}


def _extract_source_provenance(candidate: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    metadata = candidate.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}
    location_map = _extract_location(candidate)

    source_uri = _first_non_empty(
        [
            metadata_map.get("source_uri"),
            metadata_map.get("sourceUri"),
            metadata_map.get("source_s3_uri"),
            metadata_map.get("s3_uri"),
            metadata_map.get("x-amz-bedrock-kb-source-uri"),
            candidate.get("source_uri"),
            candidate.get("sourceUri"),
            candidate.get("source_s3_uri"),
            location_map.get("uri"),
            location_map.get("s3Uri"),
        ]
    )

    source_bucket = _first_non_empty(
        [
            metadata_map.get("source_bucket"),
            metadata_map.get("s3_bucket"),
            candidate.get("source_bucket"),
            location_map.get("bucketName"),
            location_map.get("bucket"),
        ]
    )
    source_key = _first_non_empty(
        [
            metadata_map.get("source_key"),
            metadata_map.get("s3_key"),
            candidate.get("source_key"),
            location_map.get("objectKey"),
            location_map.get("key"),
        ]
    )

    if source_uri is None and source_bucket and source_key:
        source_uri = make_s3_uri(source_bucket, source_key)

    return source_uri, source_bucket, source_key


def normalize_retrieval_candidate_doc_id(
    candidate: Mapping[str, Any],
    *,
    resolver: DocIdResolver,
    strict: bool = True,
) -> dict[str, Any]:
    """Normalize doc_id for a retrieval candidate using ingestion provenance mapping."""

    normalized = dict(candidate)
    metadata = candidate.get("metadata")
    metadata_map = dict(metadata) if isinstance(metadata, Mapping) else {}

    existing_doc_id = _first_non_empty([metadata_map.get("doc_id"), candidate.get("doc_id")])
    source_uri, source_bucket, source_key = _extract_source_provenance(candidate)

    resolved_doc_id = existing_doc_id or resolver.resolve_doc_id(
        source_uri=source_uri,
        source_bucket=source_bucket,
        source_key=source_key,
    )

    if resolved_doc_id is None and strict:
        raise ProvenanceResolutionError(
            "Unable to resolve doc_id from retrieval candidate provenance. "
            "Expected source URI/bucket-key that exists in ingestion manifest store."
        )

    if resolved_doc_id is not None:
        normalized["doc_id"] = resolved_doc_id
        metadata_map["doc_id"] = resolved_doc_id

    if source_uri is not None:
        metadata_map["source_uri"] = source_uri

    normalized["metadata"] = metadata_map
    return normalized

