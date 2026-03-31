from __future__ import annotations

from http import HTTPStatus
import json
import unittest

from query_api import RetrievePage
from query_api.server import (
    QueryApplication,
    QueryServiceConfigError,
    build_runtime_application,
    handle_query_http_request,
)


class _PagedRetriever:
    def __init__(self, pages: list[RetrievePage]) -> None:
        self.pages = pages
        self._cursor = 0

    def retrieve(
        self,
        *,
        query_text: str,
        top_k: int,
        next_token: str | None = None,
        modality_hints: list[str] | None = None,
    ) -> RetrievePage:
        _ = query_text
        _ = top_k
        _ = next_token
        _ = modality_hints
        if self._cursor >= len(self.pages):
            return RetrievePage(results=[], next_token=None)
        page = self.pages[self._cursor]
        self._cursor += 1
        return page


class _Resolver:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def resolve_doc_id(
        self,
        *,
        source_uri: str | None = None,
        source_bucket: str | None = None,
        source_key: str | None = None,
    ) -> str | None:
        if source_uri:
            return self.mapping.get(source_uri)
        if source_bucket and source_key:
            return self.mapping.get(f"s3://{source_bucket}/{source_key}")
        return None


def _text_candidate(*, source_uri: str, chunk_id: str, snippet: str) -> dict[str, object]:
    return {
        "content": {"text": snippet, "type": "TEXT"},
        "location": {"s3Location": {"uri": source_uri}},
        "metadata": {"chunk_id": chunk_id, "source_uri": source_uri},
        "score": 0.91,
    }


class QueryApiServerTests(unittest.TestCase):
    def test_handle_query_http_request_returns_retrieval_only_response(self) -> None:
        app = QueryApplication(
            retriever=_PagedRetriever(
                [
                    RetrievePage(
                        results=[
                            _text_candidate(
                                source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                                chunk_id="chunk-a-1",
                                snippet="Doc A says scaling improved performance.",
                            )
                        ]
                    )
                ]
            ),
            provenance_resolver=_Resolver({"s3://raw/documents-raw/doc-a/source.pdf": "doc-a"}),
        )

        status, payload, request_payload = handle_query_http_request(
            app=app,
            raw_body=json.dumps({"query": "Return one document.", "debug": True}).encode("utf-8"),
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(request_payload, {"query": "Return one document.", "debug": True})
        self.assertEqual(payload["meta"]["scope_mode"], "unscoped")
        self.assertEqual(payload["meta"]["retrieval_summary"]["retrieved_candidates"], 1)
        self.assertEqual(payload["meta"]["retrieval_debug"]["candidates"][0]["doc_id"], "doc-a")

    def test_handle_query_http_request_returns_400_for_invalid_request(self) -> None:
        app = QueryApplication(
            retriever=_PagedRetriever([RetrievePage(results=[])]),
            provenance_resolver=_Resolver({}),
        )

        status, payload, request_payload = handle_query_http_request(
            app=app,
            raw_body=json.dumps({}).encode("utf-8"),
        )

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIsNone(request_payload)
        self.assertEqual(payload["schema_name"], "query-request")
        self.assertTrue(payload["issues"])

    def test_handle_query_http_request_rejects_invalid_json(self) -> None:
        app = QueryApplication(
            retriever=_PagedRetriever([RetrievePage(results=[])]),
            provenance_resolver=_Resolver({}),
        )

        status, payload, request_payload = handle_query_http_request(
            app=app,
            raw_body=b"{not-json",
        )

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIsNone(request_payload)
        self.assertIn("Invalid JSON request body", payload["error"])

    def test_build_runtime_application_requires_knowledge_base_id(self) -> None:
        with self.assertRaises(QueryServiceConfigError):
            build_runtime_application(env={})


if __name__ == "__main__":
    unittest.main()
