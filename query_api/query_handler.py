from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from provenance import normalize_retrieval_candidate_doc_id
from validation import (
    validate_evidence_item,
    validate_query_request,
    validate_query_response,
)


DEFAULT_TOP_K = 8
DEFAULT_MAX_PAGES = 5
TEXT_ASSET_TYPES = {"text_chunk", "caption"}
VISUAL_ASSET_TYPES = {
    "figure_image",
    "table_image",
    "diagram",
    "chart_image",
    "embedded_image",
}
VALID_ASSET_TYPES = TEXT_ASSET_TYPES | VISUAL_ASSET_TYPES


@dataclass(frozen=True)
class RetrievePage:
    results: list[dict[str, Any]]
    next_token: str | None = None


class RetrievalBackend(Protocol):
    def retrieve(
        self,
        *,
        query_text: str,
        top_k: int,
        next_token: str | None = None,
        modality_hints: list[str] | None = None,
    ) -> RetrievePage:
        ...


class ProvenanceResolver(Protocol):
    def resolve_doc_id(
        self,
        *,
        source_uri: str | None = None,
        source_bucket: str | None = None,
        source_key: str | None = None,
    ) -> str | None:
        ...


class BedrockKnowledgeBaseRetriever:
    """Small adapter around Bedrock KB retrieval for the retrieval-only query slice."""

    def __init__(
        self,
        knowledge_base_id: str,
        *,
        region_name: str | None = None,
        client: Any | None = None,
        override_search_type: str | None = None,
    ) -> None:
        if not knowledge_base_id.strip():
            raise ValueError("knowledge_base_id must be non-empty")
        self._knowledge_base_id = knowledge_base_id
        self._override_search_type = override_search_type.strip() if override_search_type else None
        self._client = client or self._build_client(region_name=region_name)

    @staticmethod
    def _build_client(*, region_name: str | None) -> Any:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "boto3 is required for Bedrock retrieval. Install it with: pip install boto3"
            ) from exc

        kwargs = {"region_name": region_name} if region_name else {}
        return boto3.client("bedrock-agent-runtime", **kwargs)

    def retrieve(
        self,
        *,
        query_text: str,
        top_k: int,
        next_token: str | None = None,
        modality_hints: list[str] | None = None,
    ) -> RetrievePage:
        request: dict[str, Any] = {
            "knowledgeBaseId": self._knowledge_base_id,
            "retrievalQuery": {"text": query_text},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": top_k,
                }
            },
        }
        if next_token:
            request["nextToken"] = next_token
        if self._override_search_type:
            request["retrievalConfiguration"]["vectorSearchConfiguration"]["overrideSearchType"] = (
                self._override_search_type
            )

        # Modality hints are advisory in the request schema. The current Bedrock KB
        # adapter does not try to translate them into backend filters yet because the
        # required metadata contract is not guaranteed across corpora.
        _ = modality_hints

        response = self._client.retrieve(**request)
        results = response.get("retrievalResults") or []
        normalized_results = [dict(item) for item in results if isinstance(item, Mapping)]
        return RetrievePage(
            results=normalized_results,
            next_token=_first_non_empty([response.get("nextToken")]),
        )


def handle_post_query(
    payload: Mapping[str, Any],
    *,
    retriever: RetrievalBackend,
    provenance_resolver: ProvenanceResolver,
    top_k: int = DEFAULT_TOP_K,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    validate_query_request(payload)

    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    query_text = payload["query"].strip()
    debug_requested = bool(payload.get("debug"))
    scope = payload.get("scope")
    scope_doc_ids = _normalize_scope_doc_ids(scope)
    scope_mode = "scoped" if scope_doc_ids else "unscoped"
    modality_hints = _normalize_string_list(payload.get("modality_hints"))

    page_size = top_k if scope_mode == "unscoped" else max(top_k * 3, len(scope_doc_ids) * top_k)
    raw_candidates, pages_fetched = _collect_candidates(
        retriever=retriever,
        provenance_resolver=provenance_resolver,
        query_text=query_text,
        scope_doc_ids=scope_doc_ids,
        modality_hints=modality_hints,
        top_k=top_k,
        page_size=page_size,
        max_pages=max_pages,
    )
    evidence_items, build_stats = _normalize_candidates_to_evidence(
        raw_candidates,
        provenance_resolver=provenance_resolver,
        scope_doc_ids=scope_doc_ids,
        top_k=top_k,
    )
    retrieval_summary, debug_candidates = _build_retrieval_summary(
        candidates=raw_candidates,
        evidence_items=evidence_items,
        build_stats=build_stats,
        pages_fetched=pages_fetched,
        provenance_resolver=provenance_resolver,
    )

    insufficient_evidence = len(evidence_items) == 0
    limitations = _build_limitations(
        scope_mode=scope_mode,
        scope_doc_ids=scope_doc_ids,
        insufficient_evidence=insufficient_evidence,
        build_stats=build_stats,
    )
    response = {
        "answer": _retrieval_only_answer(insufficient_evidence=insufficient_evidence),
        "citations": [],
        "used_evidence_ids": [],
        "limitations": limitations,
        "evidence": evidence_items,
        "meta": {
            "scope_mode": scope_mode,
            "docs_contributing": len({item["doc_id"] for item in evidence_items}),
            "insufficient_evidence": insufficient_evidence,
            "retrieval_summary": retrieval_summary,
        },
    }
    if scope_doc_ids:
        response["meta"]["scoped_doc_ids"] = scope_doc_ids

    if debug_requested:
        response["meta"]["retrieval_debug"] = {
            **retrieval_summary,
            "candidates": debug_candidates,
            "drop_reasons": build_stats["drop_reasons"],
        }

    validate_query_response(response)
    return response


def _collect_candidates(
    *,
    retriever: RetrievalBackend,
    provenance_resolver: ProvenanceResolver,
    query_text: str,
    scope_doc_ids: list[str],
    modality_hints: list[str] | None,
    top_k: int,
    page_size: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], int]:
    all_results: list[dict[str, Any]] = []
    next_token: str | None = None
    pages_fetched = 0
    while pages_fetched < max_pages:
        page = retriever.retrieve(
            query_text=query_text,
            top_k=page_size,
            next_token=next_token,
            modality_hints=modality_hints,
        )
        all_results.extend(page.results)
        pages_fetched += 1
        next_token = page.next_token

        if not scope_doc_ids:
            break

        scoped_count = 0
        for candidate in all_results:
            normalized = normalize_retrieval_candidate_doc_id(
                candidate,
                resolver=provenance_resolver,
                strict=False,
            )
            if normalized.get("doc_id") in scope_doc_ids:
                scoped_count += 1
            if scoped_count >= top_k:
                break
        if scoped_count >= top_k or not next_token:
            break
    return all_results, pages_fetched


def _normalize_candidates_to_evidence(
    candidates: list[dict[str, Any]],
    *,
    provenance_resolver: ProvenanceResolver,
    scope_doc_ids: list[str],
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    dropped_unresolved = 0
    dropped_invalid = 0
    filtered_out_of_scope = 0
    drop_reasons: list[dict[str, Any]] = []

    for candidate_index, candidate in enumerate(candidates):
        normalized = normalize_retrieval_candidate_doc_id(
            candidate,
            resolver=provenance_resolver,
            strict=False,
        )
        doc_id = _first_non_empty(
            [
                normalized.get("doc_id"),
                _as_mapping(normalized.get("metadata")).get("doc_id"),
            ]
        )
        if doc_id is None:
            dropped_unresolved += 1
            drop_reasons.append(
                _drop_reason_event(
                    candidate_index=candidate_index,
                    candidate=normalized,
                    reason="unresolved_doc_id",
                    detail="doc_id could not be resolved from retrieval provenance and ingestion manifest mapping.",
                )
            )
            continue
        if scope_doc_ids and doc_id not in scope_doc_ids:
            filtered_out_of_scope += 1
            drop_reasons.append(
                _drop_reason_event(
                    candidate_index=candidate_index,
                    candidate=normalized,
                    reason="filtered_out_of_scope",
                    detail="candidate doc_id was not included in the explicit request scope.",
                    doc_id=doc_id,
                )
            )
            continue

        evidence, normalization_issue = _normalize_candidate_to_evidence(
            normalized,
            evidence_id=f"E{len(evidence_items) + 1}",
        )
        if evidence is None:
            dropped_invalid += 1
            detail = normalization_issue or "candidate could not be normalized into a canonical evidence item."
            drop_reasons.append(
                _drop_reason_event(
                    candidate_index=candidate_index,
                    candidate=normalized,
                    reason=_reason_code_from_detail(detail),
                    detail=detail,
                    doc_id=doc_id,
                )
            )
            continue

        dedup_key = _evidence_dedup_key(evidence)
        if dedup_key in seen_keys:
            drop_reasons.append(
                _drop_reason_event(
                    candidate_index=candidate_index,
                    candidate=normalized,
                    reason="duplicate_evidence_item",
                    detail="candidate normalized to an evidence item already present in the request-local bundle.",
                    doc_id=doc_id,
                    asset_type=str(evidence["asset_type"]),
                )
            )
            continue
        seen_keys.add(dedup_key)

        try:
            validate_evidence_item(evidence)
        except Exception as exc:
            dropped_invalid += 1
            drop_reasons.append(
                _drop_reason_event(
                    candidate_index=candidate_index,
                    candidate=normalized,
                    reason="schema_validation_error",
                    detail=f"normalized evidence failed schema validation: {exc}",
                    doc_id=doc_id,
                    asset_type=str(evidence["asset_type"]),
                )
            )
            seen_keys.discard(dedup_key)
            continue
        evidence_items.append(evidence)
        if len(evidence_items) >= top_k:
            break

    return evidence_items, {
        "dropped_unresolved": dropped_unresolved,
        "dropped_invalid": dropped_invalid,
        "filtered_out_of_scope": filtered_out_of_scope,
        "drop_reasons": drop_reasons,
    }


def _normalize_candidate_to_evidence(
    candidate: Mapping[str, Any],
    *,
    evidence_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    metadata = _as_mapping(candidate.get("metadata"))
    content = _as_mapping(candidate.get("content"))
    location = _extract_location(candidate)

    doc_id = _first_non_empty([candidate.get("doc_id"), metadata.get("doc_id")])
    if doc_id is None:
        return None, "missing resolved doc_id"

    asset_type = _normalize_asset_type(metadata, content)
    if asset_type is None:
        return None, "unsupported or missing asset_type"

    evidence: dict[str, Any] = {
        "evidence_id": evidence_id,
        "doc_id": doc_id,
        "asset_type": asset_type,
    }

    doc_type = _first_non_empty([metadata.get("doc_type"), metadata.get("docType"), candidate.get("doc_type")])
    if doc_type is not None:
        evidence["doc_type"] = doc_type

    page = _first_coercible_positive_int(
        [
            metadata.get("page"),
            metadata.get("page_number"),
            metadata.get("pageNumber"),
            metadata.get("x-amz-bedrock-kb-document-page-number"),
        ]
    )
    if page is not None:
        evidence["page"] = page

    section = _first_non_empty([metadata.get("section"), metadata.get("section_title"), metadata.get("sectionTitle")])
    if section is not None:
        evidence["section"] = section

    snippet = _first_non_empty([content.get("text"), metadata.get("snippet")])
    caption = _first_non_empty(
        [
            metadata.get("caption"),
            metadata.get("asset_caption"),
            metadata.get("x-amz-bedrock-kb-description"),
        ]
    )
    asset_source_uri = _extract_asset_source_uri(candidate, metadata)
    asset_s3_key = _extract_asset_s3_key(candidate, metadata)
    asset_id = _first_non_empty(
        [
            metadata.get("asset_id"),
            metadata.get("assetId"),
            metadata.get("x-amz-bedrock-kb-asset-id"),
            _derive_asset_id_from_locator(asset_s3_key or asset_source_uri),
        ]
    )
    chunk_id = _first_non_empty(
        [
            metadata.get("chunk_id"),
            metadata.get("chunkId"),
            metadata.get("x-amz-bedrock-kb-chunk-id"),
        ]
    )
    presigned_url = _first_non_empty([metadata.get("presigned_url"), metadata.get("presignedUrl")])

    if asset_type == "text_chunk":
        if chunk_id is None:
            return None, "missing text chunk_id"
        if snippet is None:
            return None, "missing text snippet"
        evidence["chunk_id"] = chunk_id
        evidence["snippet"] = snippet
        return evidence, None

    if asset_type == "caption":
        if asset_id is None:
            return None, "missing caption asset_id"
        evidence["asset_id"] = asset_id
        if caption is not None:
            evidence["caption"] = caption
        elif snippet is not None:
            evidence["caption"] = snippet
        return evidence, None

    if asset_type in VISUAL_ASSET_TYPES:
        if asset_id is None:
            return None, "missing visual asset_id"
        if asset_s3_key is None:
            return None, "missing visual asset_s3_key"
        evidence["asset_id"] = asset_id
        evidence["asset_s3_key"] = asset_s3_key
        if caption is not None:
            evidence["caption"] = caption
        if presigned_url is not None:
            evidence["presigned_url"] = presigned_url
        return evidence, None

    return None, "unsupported asset_type after normalization"


def _build_limitations(
    *,
    scope_mode: str,
    scope_doc_ids: list[str],
    insufficient_evidence: bool,
    build_stats: dict[str, int],
) -> list[str]:
    limitations = ["Retrieval-only mode: no synthesized answer is returned yet."]
    if insufficient_evidence:
        if scope_mode == "scoped":
            limitations.insert(
                0,
                "No retrieved evidence matched the requested scope: " + ", ".join(scope_doc_ids),
            )
        else:
            limitations.insert(0, "No retrieved evidence matched the request.")
    if build_stats["dropped_unresolved"] > 0:
        limitations.append(
            f"Dropped {build_stats['dropped_unresolved']} retrieval candidate(s) because doc provenance could not be resolved."
        )
    if build_stats["dropped_invalid"] > 0:
        limitations.append(
            f"Dropped {build_stats['dropped_invalid']} retrieval candidate(s) because they could not be normalized into canonical evidence items."
        )
    return limitations


def _build_retrieval_summary(
    *,
    candidates: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    build_stats: dict[str, Any],
    pages_fetched: int,
    provenance_resolver: ProvenanceResolver,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    drop_reason_by_index = {
        int(event["candidate_index"]): event
        for event in build_stats["drop_reasons"]
        if isinstance(event, Mapping) and isinstance(event.get("candidate_index"), int)
    }
    candidate_rows = [
        _summarize_candidate_for_debug(
            candidate,
            rank=index + 1,
            provenance_resolver=provenance_resolver,
            drop_event=drop_reason_by_index.get(index),
        )
        for index, candidate in enumerate(candidates)
    ]

    summary = {
        "retrieved_candidates": len(candidates),
        "returned_evidence": len(evidence_items),
        "dropped_candidates": len(build_stats["drop_reasons"]),
        "filtered_out_of_scope": int(build_stats.get("filtered_out_of_scope", 0)),
        "pages_fetched": pages_fetched,
        "doc_distribution": _count_by_label(candidate_rows, "doc_id", default_label="<unresolved>"),
        "candidate_content_type_counts": _count_by_label(
            candidate_rows, "candidate_content_type", default_label="<missing>"
        ),
        "source_file_modality_counts": _count_by_label(
            candidate_rows, "source_file_modality", default_label="<missing>"
        ),
    }
    return summary, candidate_rows


def _retrieval_only_answer(*, insufficient_evidence: bool) -> str:
    if insufficient_evidence:
        return "Retrieval-only mode found insufficient evidence to answer the request."
    return "Retrieval-only mode returned candidate evidence without synthesizing a final answer."


def _normalize_scope_doc_ids(scope: Any) -> list[str]:
    if not isinstance(scope, Mapping):
        return []
    return _normalize_string_list(scope.get("doc_ids"))


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _normalize_asset_type(metadata: Mapping[str, Any], content: Mapping[str, Any]) -> str | None:
    explicit_asset_type = _first_non_empty(
        [
            metadata.get("asset_type"),
            metadata.get("assetType"),
            metadata.get("modality"),
        ]
    )
    if explicit_asset_type in VALID_ASSET_TYPES:
        return explicit_asset_type
    if explicit_asset_type is not None and explicit_asset_type.lower() == "text":
        return "text_chunk"

    content_type = _normalize_candidate_content_type(content)
    if content_type == "TEXT":
        return "text_chunk"
    if content_type == "IMAGE":
        return _infer_visual_asset_type(metadata)
    if _first_non_empty(
        [
            content.get("text"),
            metadata.get("chunk_id"),
            metadata.get("chunkId"),
            metadata.get("x-amz-bedrock-kb-chunk-id"),
        ]
    ) is not None:
        return "text_chunk"

    source_file_modality = _normalize_source_file_modality(metadata)
    if source_file_modality == "TEXT":
        return "text_chunk"
    if source_file_modality == "IMAGE":
        return _infer_visual_asset_type(metadata)
    return None


def _extract_asset_source_uri(candidate: Mapping[str, Any], metadata: Mapping[str, Any]) -> str | None:
    return _first_non_empty(
        [
            metadata.get("asset_s3_uri"),
            metadata.get("assetS3Uri"),
            metadata.get("supplemental_uri"),
            metadata.get("supplementalUri"),
            metadata.get("x-amz-bedrock-kb-byte-content-source"),
            candidate.get("asset_s3_uri"),
            candidate.get("assetS3Uri"),
            candidate.get("supplemental_uri"),
            candidate.get("supplementalUri"),
        ]
    )


def _extract_asset_s3_key(candidate: Mapping[str, Any], metadata: Mapping[str, Any]) -> str | None:
    explicit_key = _first_non_empty(
        [
            metadata.get("asset_s3_key"),
            metadata.get("assetS3Key"),
            metadata.get("s3_key"),
        ]
    )
    if explicit_key is not None:
        return explicit_key

    s3_uri = _extract_asset_source_uri(candidate, metadata)
    if s3_uri is None or not s3_uri.startswith("s3://"):
        return None

    _, _, remainder = s3_uri.partition("s3://")
    bucket_sep = remainder.find("/")
    if bucket_sep == -1:
        return None
    key = remainder[bucket_sep + 1 :].strip()
    return key or None


def _extract_location(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    location = candidate.get("location")
    if not isinstance(location, Mapping):
        return {}
    s3_location = location.get("s3Location")
    if isinstance(s3_location, Mapping):
        return s3_location
    return location


def _summarize_candidate_for_debug(
    candidate: Mapping[str, Any],
    *,
    rank: int,
    provenance_resolver: ProvenanceResolver,
    drop_event: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized = normalize_retrieval_candidate_doc_id(
        candidate,
        resolver=provenance_resolver,
        strict=False,
    )
    metadata = _as_mapping(normalized.get("metadata"))
    content = _as_mapping(normalized.get("content"))
    location = _extract_location(normalized)

    source_uri = _first_non_empty(
        [
            metadata.get("source_uri"),
            metadata.get("sourceUri"),
            metadata.get("x-amz-bedrock-kb-source-uri"),
            location.get("uri"),
            location.get("s3Uri"),
        ]
    )
    doc_id = _first_non_empty([normalized.get("doc_id"), metadata.get("doc_id")])
    candidate_content_type = _normalize_candidate_content_type(content)
    source_file_modality = _normalize_source_file_modality(metadata)
    asset_type = _normalize_asset_type(metadata, content)
    asset_source_uri = _extract_asset_source_uri(normalized, metadata)
    asset_s3_key = _extract_asset_s3_key(normalized, metadata)
    asset_id = _first_non_empty(
        [
            metadata.get("asset_id"),
            metadata.get("assetId"),
            metadata.get("x-amz-bedrock-kb-asset-id"),
            _derive_asset_id_from_locator(asset_s3_key or asset_source_uri),
        ]
    )
    chunk_id = _first_non_empty(
        [
            metadata.get("chunk_id"),
            metadata.get("chunkId"),
            metadata.get("x-amz-bedrock-kb-chunk-id"),
        ]
    )
    page = _first_coercible_positive_int(
        [
            metadata.get("page"),
            metadata.get("page_number"),
            metadata.get("pageNumber"),
            metadata.get("x-amz-bedrock-kb-document-page-number"),
        ]
    )
    score = normalized.get("score")
    snippet = _first_non_empty([content.get("text"), metadata.get("snippet")])
    description = _first_non_empty(
        [
            metadata.get("caption"),
            metadata.get("asset_caption"),
            metadata.get("x-amz-bedrock-kb-description"),
        ]
    )

    row: dict[str, Any] = {
        "rank": rank,
        "dropped": drop_event is not None,
        "metadata": dict(metadata),
    }
    if drop_event is not None:
        drop_reason = drop_event.get("reason")
        if isinstance(drop_reason, str) and drop_reason:
            row["drop_reason"] = drop_reason
    if doc_id is not None:
        row["doc_id"] = doc_id
    if source_uri is not None:
        row["source_uri"] = source_uri
    if asset_source_uri is not None:
        row["asset_source_uri"] = asset_source_uri
    if candidate_content_type is not None:
        row["candidate_content_type"] = candidate_content_type
    if source_file_modality is not None:
        row["source_file_modality"] = source_file_modality
    if asset_type is not None:
        row["asset_type"] = asset_type
    if chunk_id is not None:
        row["chunk_id"] = chunk_id
    if asset_id is not None:
        row["asset_id"] = asset_id
    if page is not None:
        row["page"] = page
    if isinstance(score, (int, float)):
        row["score"] = float(score)
    if snippet is not None:
        row["text_preview"] = _truncate_preview(snippet)
    if description is not None:
        row["description_preview"] = _truncate_preview(description)
    return row


def _drop_reason_event(
    *,
    candidate_index: int,
    candidate: Mapping[str, Any],
    reason: str,
    detail: str,
    doc_id: str | None = None,
    asset_type: str | None = None,
) -> dict[str, Any]:
    metadata = _as_mapping(candidate.get("metadata"))
    location = _extract_location(candidate)
    content = _as_mapping(candidate.get("content"))
    event: dict[str, Any] = {
        "candidate_index": candidate_index,
        "reason": reason,
        "detail": detail,
    }

    resolved_doc_id = _first_non_empty([doc_id, candidate.get("doc_id"), metadata.get("doc_id")])
    if resolved_doc_id is not None:
        event["doc_id"] = resolved_doc_id

    source_uri = _first_non_empty(
        [
            metadata.get("source_uri"),
            metadata.get("sourceUri"),
            metadata.get("x-amz-bedrock-kb-source-uri"),
            location.get("uri"),
            location.get("s3Uri"),
        ]
    )
    if source_uri is not None:
        event["source_uri"] = source_uri

    candidate_content_type = _normalize_candidate_content_type(content)
    if candidate_content_type is not None:
        event["candidate_content_type"] = candidate_content_type

    source_file_modality = _normalize_source_file_modality(metadata)
    if source_file_modality is not None:
        event["source_file_modality"] = source_file_modality

    asset_source_uri = _extract_asset_source_uri(candidate, metadata)
    if asset_source_uri is not None:
        event["asset_source_uri"] = asset_source_uri

    normalized_asset_type = _first_non_empty(
        [
            asset_type,
            _normalize_asset_type(metadata, content),
            metadata.get("asset_type"),
            metadata.get("assetType"),
            metadata.get("modality"),
            source_file_modality,
        ]
    )
    if normalized_asset_type is not None:
        event["asset_type"] = normalized_asset_type

    score = candidate.get("score")
    if isinstance(score, (int, float)):
        event["score"] = float(score)
    return event


def _reason_code_from_detail(detail: str) -> str:
    mapping = {
        "missing text chunk_id": "missing_text_chunk_id",
        "missing text snippet": "missing_text_snippet",
        "missing caption asset_id": "missing_caption_asset_id",
        "missing visual asset_id": "missing_visual_asset_id",
        "missing visual asset_s3_key": "missing_visual_asset_s3_key",
        "unsupported or missing asset_type": "unsupported_asset_type",
        "missing resolved doc_id": "missing_resolved_doc_id",
    }
    return mapping.get(detail, "normalization_error")


def _evidence_dedup_key(evidence: Mapping[str, Any]) -> tuple[str, str, str]:
    doc_id = str(evidence["doc_id"])
    if isinstance(evidence.get("chunk_id"), str):
        return ("chunk", doc_id, evidence["chunk_id"])
    if isinstance(evidence.get("asset_id"), str):
        return ("asset", doc_id, evidence["asset_id"])
    raise ValueError("Evidence item must have chunk_id or asset_id")


def _count_by_label(
    rows: list[Mapping[str, Any]],
    field: str,
    *,
    default_label: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        label = value if isinstance(value, str) and value else default_label
        counts[str(label)] = counts.get(str(label), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _truncate_preview(value: str, *, limit: int = 180) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _first_coercible_positive_int(values: list[Any]) -> int | None:
    for value in values:
        parsed = _coerce_positive_int(value)
        if parsed is not None:
            return parsed
    return None


def _coerce_positive_int(value: Any) -> int | None:
    if value is None:
        return None
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


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalize_candidate_content_type(content: Mapping[str, Any]) -> str | None:
    content_type = _first_non_empty([content.get("type")])
    if content_type is None:
        return None
    return content_type.strip().upper()


def _normalize_source_file_modality(metadata: Mapping[str, Any]) -> str | None:
    source_file_modality = _first_non_empty(
        [
            metadata.get("source_file_modality"),
            metadata.get("sourceFileModality"),
            metadata.get("x-amz-bedrock-kb-source-file-modality"),
        ]
    )
    if source_file_modality is None:
        return None
    return source_file_modality.strip().upper()


def _infer_visual_asset_type(metadata: Mapping[str, Any]) -> str:
    description = _first_non_empty(
        [
            metadata.get("asset_type_hint"),
            metadata.get("caption"),
            metadata.get("asset_caption"),
            metadata.get("x-amz-bedrock-kb-description"),
        ]
    )
    if description is not None:
        lowered = description.lower()
        if "table" in lowered:
            return "table_image"
        if "chart" in lowered:
            return "chart_image"
        if "diagram" in lowered:
            return "diagram"
        if "figure" in lowered:
            return "figure_image"
    return "embedded_image"


def _derive_asset_id_from_locator(locator: str | None) -> str | None:
    if locator is None:
        return None
    leaf = locator.rsplit("/", 1)[-1].strip()
    if not leaf:
        return None
    stem, _, _ = leaf.partition(".")
    return stem or leaf


def _first_non_empty(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return None
