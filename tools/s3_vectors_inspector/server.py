#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

# Allow running as: python tools/s3_vectors_inspector/server.py
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.s3_vectors_inspector.inspector import (
    InspectorConfigError,
    S3VectorsInspectorClient,
    build_config,
    build_env_context,
    parse_bedrock_metadata,
    resolve_config_defaults,
    summarize_by_data_source,
    summarize_vector,
)


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"


def _first_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0]
    return value if value.strip() else None


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid integer value: {value!r}") from exc
    return max(minimum, min(maximum, parsed))


def _json_compatible(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_compatible(item) for item in value]
    return value


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class InspectorHandler(BaseHTTPRequestHandler):
    server_version = "s3-vectors-inspector/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print(f"[{self.log_date_time_string()}] {self.address_string()} {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            self._serve_file(STATIC_DIR / "index.html", content_type="text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", content_type="text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", content_type="application/javascript; charset=utf-8")
            return

        if path.startswith("/api/"):
            self._handle_api(path, parse_qs(parsed.query))
            return

        self._json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_api(self, path: str, params: dict[str, list[str]]) -> None:
        try:
            if path == "/api/health":
                self._json({"ok": True})
                return
            if path == "/api/config":
                defaults = self._resolve_config_defaults_from_params(params)
                validation_error = None
                try:
                    self._build_config_from_params(params)
                except InspectorConfigError as exc:
                    validation_error = str(exc)
                self._json(
                    {
                        "config": defaults.as_dict(),
                        "env_context": self._build_env_context().as_dict(),
                        "validation_error": validation_error,
                    }
                )
                return
            if path == "/api/vector-buckets":
                self._handle_vector_buckets(params)
                return
            if path == "/api/indexes":
                self._handle_indexes(params)
                return
            if path == "/api/index":
                self._handle_index(params)
                return
            if path == "/api/vectors":
                self._handle_vectors(params)
                return
            if path == "/api/vector":
                self._handle_vector(params)
                return
            if path == "/api/query-by-key":
                self._handle_query_by_key(params)
                return
            if path == "/api/data-source-summary":
                self._handle_data_source_summary(params)
                return
            self._json({"error": f"Unknown API path: {path}"}, status=HTTPStatus.NOT_FOUND)
        except InspectorConfigError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except KeyError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - runtime behavior
            self._json({"error": f"Unexpected server error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _build_config_from_params(self, params: dict[str, list[str]]):
        return build_config(
            region=_first_value(params, "region"),
            vector_bucket_name=_first_value(params, "vector_bucket_name"),
            index_name=_first_value(params, "index_name"),
            index_arn=_first_value(params, "index_arn"),
            env=os.environ,
        )

    def _resolve_config_defaults_from_params(self, params: dict[str, list[str]]):
        return resolve_config_defaults(
            region=_first_value(params, "region"),
            vector_bucket_name=_first_value(params, "vector_bucket_name"),
            index_name=_first_value(params, "index_name"),
            index_arn=_first_value(params, "index_arn"),
            env=os.environ,
        )

    def _build_env_context(self):
        return build_env_context(os.environ)

    def _client_from_params(self, params: dict[str, list[str]]) -> S3VectorsInspectorClient:
        return S3VectorsInspectorClient.from_config(self._build_config_from_params(params))

    def _s3vectors_boto_client(self, *, region: str):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - runtime environment dependent
            raise RuntimeError("boto3 is required to run the S3 Vectors inspector.") from exc
        return boto3.client("s3vectors", region_name=region)

    def _handle_vector_buckets(self, params: dict[str, list[str]]) -> None:
        region = _first_value(params, "region") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if not region:
            raise InspectorConfigError("Missing region. Set AWS_REGION or pass ?region=...")

        client = self._s3vectors_boto_client(region=region)

        max_results = _parse_int(_first_value(params, "max_results"), default=100, minimum=1, maximum=500)
        next_token = _first_value(params, "next_token")
        kwargs: dict[str, Any] = {"maxResults": max_results}
        if next_token:
            kwargs["nextToken"] = next_token
        response = client.list_vector_buckets(**kwargs)
        self._json(
            {
                "vector_buckets": response.get("vectorBuckets", []),
                "next_token": response.get("nextToken"),
                "region": region,
            }
        )

    def _handle_indexes(self, params: dict[str, list[str]]) -> None:
        defaults = self._resolve_config_defaults_from_params(params)
        if not defaults.region:
            raise InspectorConfigError("Missing region. Set AWS_REGION/AWS_DEFAULT_REGION or pass region.")

        vector_bucket_name = _first_value(params, "vector_bucket_name") or defaults.vector_bucket_name
        if not vector_bucket_name:
            raise InspectorConfigError(
                "Missing vector bucket. Set EVIDENTIA_VECTORS_BUCKET (name or arn) or pass vector_bucket_name."
            )

        client = self._s3vectors_boto_client(region=defaults.region)
        max_results = _parse_int(_first_value(params, "max_results"), default=100, minimum=1, maximum=500)
        next_token = _first_value(params, "next_token")
        kwargs: dict[str, Any] = {"vectorBucketName": vector_bucket_name, "maxResults": max_results}
        if next_token:
            kwargs["nextToken"] = next_token
        response = client.list_indexes(**kwargs)
        self._json(
            {
                "indexes": response.get("indexes", []),
                "next_token": response.get("nextToken"),
                "config": {
                    "region": defaults.region,
                    "vector_bucket_name": vector_bucket_name,
                    "index_name": defaults.index_name,
                    "index_arn": defaults.index_arn,
                },
            }
        )

    def _handle_index(self, params: dict[str, list[str]]) -> None:
        client = self._client_from_params(params)
        index = client.get_index()
        self._json(
            {
                "config": client.config.as_dict(),
                "index": index,
                "dimension": index.get("dimension"),
                "distance_metric": index.get("distanceMetric"),
                "data_type": index.get("dataType"),
            }
        )

    def _handle_vectors(self, params: dict[str, list[str]]) -> None:
        client = self._client_from_params(params)
        env_context = self._build_env_context()
        max_results = _parse_int(_first_value(params, "max_results"), default=50, minimum=1, maximum=200)
        next_token = _first_value(params, "next_token")
        return_metadata = _parse_bool(_first_value(params, "return_metadata"), default=True)
        return_data = _parse_bool(_first_value(params, "return_data"), default=False)

        response = client.list_vectors(
            max_results=max_results,
            next_token=next_token,
            return_metadata=return_metadata,
            return_data=return_data,
        )
        vectors = response.get("vectors", [])
        rows = [
            summarize_vector(vector, current_data_source_id=env_context.knowledge_base_data_source_id or None)
            for vector in vectors
        ]

        self._json(
            {
                "config": client.config.as_dict(),
                "env_context": env_context.as_dict(),
                "rows": rows,
                "vectors": vectors,
                "next_token": response.get("nextToken"),
            }
        )

    def _handle_vector(self, params: dict[str, list[str]]) -> None:
        client = self._client_from_params(params)
        env_context = self._build_env_context()
        key = _first_value(params, "key")
        if not key:
            raise ValueError("Missing required query parameter: key")

        return_metadata = _parse_bool(_first_value(params, "return_metadata"), default=True)
        return_data = _parse_bool(_first_value(params, "return_data"), default=True)

        vector = client.get_vector(key=key, return_metadata=return_metadata, return_data=return_data)
        if vector is None:
            raise KeyError(f"Vector key not found: {key}")

        metadata = vector.get("metadata")
        parsed_meta = parse_bedrock_metadata(metadata if isinstance(metadata, dict) else {})

        self._json(
            {
                "config": client.config.as_dict(),
                "vector": vector,
                "summary": summarize_vector(
                    vector,
                    current_data_source_id=env_context.knowledge_base_data_source_id or None,
                ),
                "parsed_bedrock_metadata": parsed_meta,
            }
        )

    def _handle_query_by_key(self, params: dict[str, list[str]]) -> None:
        client = self._client_from_params(params)
        env_context = self._build_env_context()
        key = _first_value(params, "key")
        if not key:
            raise ValueError("Missing required query parameter: key")

        top_k = _parse_int(_first_value(params, "top_k"), default=10, minimum=1, maximum=100)
        return_metadata = _parse_bool(_first_value(params, "return_metadata"), default=True)

        response = client.query_by_key(key=key, top_k=top_k, return_metadata=return_metadata)
        matches = response.get("matches", [])
        self._json(
            {
                "config": client.config.as_dict(),
                "distance_metric": response.get("distance_metric"),
                "seed": summarize_vector(
                    response["seed"],
                    current_data_source_id=env_context.knowledge_base_data_source_id or None,
                ),
                "matches": [
                    {
                        "summary": summarize_vector(
                            match,
                            current_data_source_id=env_context.knowledge_base_data_source_id or None,
                        ),
                        "distance": match.get("distance"),
                        "key": match.get("key"),
                    }
                    for match in matches
                ],
            }
        )

    def _handle_data_source_summary(self, params: dict[str, list[str]]) -> None:
        client = self._client_from_params(params)
        env_context = self._build_env_context()
        sample_size = _parse_int(_first_value(params, "sample_size"), default=200, minimum=1, maximum=1000)

        response = client.list_vectors(
            max_results=sample_size,
            next_token=None,
            return_metadata=True,
            return_data=False,
        )
        vectors = response.get("vectors", [])
        summary = summarize_by_data_source(
            vectors,
            current_data_source_id=env_context.knowledge_base_data_source_id or None,
        )

        self._json(
            {
                "config": client.config.as_dict(),
                "env_context": env_context.as_dict(),
                "sample_size": len(vectors),
                **summary,
            }
        )

    def _serve_file(self, path: Path, *, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self._json({"error": "File not found"}, status=HTTPStatus.NOT_FOUND)
            return
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(_json_compatible(payload), ensure_ascii=True, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only UI for inspecting S3 Vectors content.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="Port to bind (default: 8787)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), InspectorHandler)
    print(f"S3 Vectors Inspector listening at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
