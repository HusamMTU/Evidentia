#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse

# Allow running as: python query_api/server.py
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from provenance import DynamoIngestionManifestStore, SOURCE_URI_INDEX_NAME
from query_api.query_handler import (
    DEFAULT_MAX_PAGES,
    DEFAULT_TOP_K,
    BedrockKnowledgeBaseRetriever,
    handle_post_query,
)
from validation.errors import ContractValidationError


class QueryServiceConfigError(ValueError):
    pass


class NullProvenanceResolver:
    def resolve_doc_id(
        self,
        *,
        source_uri: str | None = None,
        source_bucket: str | None = None,
        source_key: str | None = None,
    ) -> str | None:
        _ = source_uri
        _ = source_bucket
        _ = source_key
        return None


class QueryApplication:
    def __init__(
        self,
        *,
        retriever: Any,
        provenance_resolver: Any,
        top_k: int = DEFAULT_TOP_K,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self._retriever = retriever
        self._provenance_resolver = provenance_resolver
        self._top_k = top_k
        self._max_pages = max_pages

    def handle_query(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return handle_post_query(
            payload,
            retriever=self._retriever,
            provenance_resolver=self._provenance_resolver,
            top_k=self._top_k,
            max_pages=self._max_pages,
        )


def _serialize_contract_validation_error(exc: ContractValidationError) -> dict[str, Any]:
    return {
        "error": str(exc),
        "schema_name": exc.schema_name,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "path": issue.path,
                "details": issue.details,
            }
            for issue in exc.issues
        ],
    }


def handle_query_http_request(
    *,
    app: QueryApplication,
    raw_body: bytes,
) -> tuple[HTTPStatus, dict[str, Any], Mapping[str, Any] | None]:
    try:
        if not raw_body:
            raise ValueError("Request body must not be empty.")
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Request body must be a JSON object.")
        response = app.handle_query(payload)
        return HTTPStatus.OK, response, payload
    except json.JSONDecodeError as exc:
        return HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON request body: {exc.msg}"}, None
    except ContractValidationError as exc:
        return HTTPStatus.BAD_REQUEST, _serialize_contract_validation_error(exc), None
    except ValueError as exc:
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}, None
    except Exception as exc:  # pragma: no cover - runtime behavior
        return HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Unexpected server error: {exc}"}, None


class QueryApiHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        app: QueryApplication,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.app = app


class QueryApiHandler(BaseHTTPRequestHandler):
    server_version = "evidentia-query-api/0.1"

    @property
    def app(self) -> QueryApplication:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print(f"[{self.log_date_time_string()}] {self.address_string()} {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json({"ok": True})
            return
        self._json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/query":
            self._json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            raw_body = self._read_body()
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        status, response, request_payload = handle_query_http_request(app=self.app, raw_body=raw_body)
        if status == HTTPStatus.OK and isinstance(request_payload, Mapping):
            self._log_query_result(request_payload, response)
        self._json(response, status=status)

    def _read_body(self) -> bytes:
        content_length = self.headers.get("Content-Length", "").strip()
        if not content_length:
            raise ValueError("Missing Content-Length header.")
        try:
            expected_bytes = int(content_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc
        if expected_bytes < 0:
            raise ValueError("Invalid Content-Length header.")
        raw_body = self.rfile.read(expected_bytes)
        return raw_body

    def _log_query_result(self, payload: Mapping[str, Any], response: Mapping[str, Any]) -> None:
        meta = response.get("meta")
        meta_map = meta if isinstance(meta, Mapping) else {}
        summary = meta_map.get("retrieval_summary")
        summary_map = summary if isinstance(summary, Mapping) else {}
        event = {
            "event": "query_request",
            "request_id": payload.get("request_id"),
            "scope_mode": meta_map.get("scope_mode"),
            "debug": bool(payload.get("debug")),
            "retrieved_candidates": summary_map.get("retrieved_candidates"),
            "returned_evidence": summary_map.get("returned_evidence"),
            "dropped_candidates": summary_map.get("dropped_candidates"),
            "filtered_out_of_scope": summary_map.get("filtered_out_of_scope"),
            "pages_fetched": summary_map.get("pages_fetched"),
            "doc_distribution": summary_map.get("doc_distribution"),
            "candidate_content_type_counts": summary_map.get("candidate_content_type_counts"),
            "source_file_modality_counts": summary_map.get("source_file_modality_counts"),
        }
        print(json.dumps(event, ensure_ascii=True, sort_keys=True))

    def _json(self, payload: Mapping[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _env_int(name: str, *, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise QueryServiceConfigError(f"{name} must be an integer, got: {raw!r}") from exc
    if parsed < minimum:
        raise QueryServiceConfigError(f"{name} must be >= {minimum}, got: {parsed}")
    return parsed


def build_runtime_application(*, env: Mapping[str, str] | None = None) -> QueryApplication:
    env_map = env or os.environ
    knowledge_base_id = env_map.get("BEDROCK_KNOWLEDGE_BASE_ID", "").strip()
    if not knowledge_base_id:
        raise QueryServiceConfigError(
            "Missing BEDROCK_KNOWLEDGE_BASE_ID. Set it before starting the query API server."
        )

    region = env_map.get("AWS_REGION", "").strip() or env_map.get("AWS_DEFAULT_REGION", "").strip() or None
    override_search_type = env_map.get("BEDROCK_RETRIEVAL_OVERRIDE_SEARCH_TYPE", "").strip() or None
    top_k = _env_int("QUERY_API_TOP_K", default=DEFAULT_TOP_K)
    max_pages = _env_int("QUERY_API_MAX_PAGES", default=DEFAULT_MAX_PAGES)

    retriever = BedrockKnowledgeBaseRetriever(
        knowledge_base_id,
        region_name=region,
        override_search_type=override_search_type,
    )

    table_name = env_map.get("EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME", "").strip()
    if table_name:
        source_uri_index_name = (
            env_map.get("EVIDENTIA_INGESTION_MANIFEST_SOURCE_URI_INDEX", "").strip() or SOURCE_URI_INDEX_NAME
        )
        provenance_resolver: Any = DynamoIngestionManifestStore(
            table_name,
            region_name=region,
            source_uri_index_name=source_uri_index_name,
        )
    else:
        provenance_resolver = NullProvenanceResolver()

    return QueryApplication(
        retriever=retriever,
        provenance_resolver=provenance_resolver,
        top_k=top_k,
        max_pages=max_pages,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrieval-only query API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = build_runtime_application()
    server = QueryApiHTTPServer((args.host, args.port), QueryApiHandler, app=app)
    print(f"Query API listening at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
