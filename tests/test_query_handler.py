from __future__ import annotations

import unittest

from query_api import BedrockKnowledgeBaseRetriever, RetrievePage, handle_post_query


class _FakeResolver:
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


class _PagedRetriever:
    def __init__(self, pages: list[RetrievePage]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []
        self._cursor = 0

    def retrieve(
        self,
        *,
        query_text: str,
        top_k: int,
        next_token: str | None = None,
        modality_hints: list[str] | None = None,
    ) -> RetrievePage:
        self.calls.append(
            {
                "query_text": query_text,
                "top_k": top_k,
                "next_token": next_token,
                "modality_hints": modality_hints,
            }
        )
        if self._cursor >= len(self.pages):
            return RetrievePage(results=[], next_token=None)
        page = self.pages[self._cursor]
        self._cursor += 1
        return page


class _ClientStub:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def retrieve(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.response


def _text_candidate(
    *,
    source_uri: str,
    chunk_id: str,
    snippet: str,
    doc_id: str | None = None,
    page: int = 1,
    doc_type: str = "research_paper",
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "source_uri": source_uri,
        "chunk_id": chunk_id,
        "page": page,
        "doc_type": doc_type,
    }
    if doc_id is not None:
        metadata["doc_id"] = doc_id
    return {
        "content": {"text": snippet, "type": "TEXT"},
        "location": {"s3Location": {"uri": source_uri}},
        "metadata": metadata,
        "score": 0.92,
    }


def _visual_candidate(
    *,
    source_uri: str,
    doc_id: str,
    asset_id: str,
    asset_s3_key: str,
    caption: str,
    page: int = 1,
) -> dict[str, object]:
    return {
        "location": {"s3Location": {"uri": source_uri}},
        "metadata": {
            "doc_id": doc_id,
            "doc_type": "research_paper",
            "asset_type": "table_image",
            "asset_id": asset_id,
            "asset_s3_key": asset_s3_key,
            "caption": caption,
            "page": page,
        },
        "score": 0.87,
    }


def _bedrock_image_candidate(
    *,
    source_uri: str,
    asset_source_uri: str | None,
    description: str,
    page_number: float = 1.0,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "x-amz-bedrock-kb-source-file-modality": "TEXT",
        "x-amz-bedrock-kb-document-page-number": page_number,
        "x-amz-bedrock-kb-description": description,
    }
    if asset_source_uri is not None:
        metadata["x-amz-bedrock-kb-byte-content-source"] = asset_source_uri
    return {
        "content": {"type": "IMAGE", "byteContent": "data:image/png;base64,ZmFrZQ=="},
        "location": {"s3Location": {"uri": source_uri}},
        "metadata": metadata,
        "score": 0.74,
    }


class QueryHandlerTests(unittest.TestCase):
    def test_unscoped_query_returns_multi_doc_evidence(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                            chunk_id="chunk-a-1",
                            snippet="Doc A says scaling improved performance.",
                        ),
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-b/source.pdf",
                            chunk_id="chunk-b-1",
                            snippet="Doc B reports the same trend with a different threshold.",
                        ),
                    ]
                )
            ]
        )
        resolver = _FakeResolver(
            {
                "s3://raw/documents-raw/doc-a/source.pdf": "doc-a",
                "s3://raw/documents-raw/doc-b/source.pdf": "doc-b",
            }
        )

        response = handle_post_query(
            {"query": "Compare scaling behavior across the indexed papers.", "debug": True},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(response["meta"]["scope_mode"], "unscoped")
        self.assertEqual(response["meta"]["docs_contributing"], 2)
        self.assertFalse(response["meta"]["insufficient_evidence"])
        self.assertEqual([item["doc_id"] for item in response["evidence"]], ["doc-a", "doc-b"])
        self.assertEqual([item["evidence_id"] for item in response["evidence"]], ["E1", "E2"])
        self.assertEqual(response["citations"], [])
        self.assertEqual(response["used_evidence_ids"], [])
        self.assertIn("Retrieval-only mode", response["answer"])
        summary = response["meta"]["retrieval_summary"]
        self.assertEqual(summary["retrieved_candidates"], 2)
        self.assertEqual(summary["returned_evidence"], 2)
        self.assertEqual(summary["doc_distribution"], {"doc-a": 1, "doc-b": 1})
        self.assertEqual(summary["candidate_content_type_counts"], {"TEXT": 2})
        self.assertEqual(summary["source_file_modality_counts"], {"<missing>": 2})
        self.assertIn("retrieval_debug", response["meta"])
        self.assertEqual(response["meta"]["retrieval_debug"]["dropped_candidates"], 0)

    def test_non_debug_query_omits_retrieval_debug_block(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                            chunk_id="chunk-a-1",
                            snippet="Doc A says scaling improved performance.",
                            doc_id="doc-a",
                        )
                    ]
                )
            ]
        )
        resolver = _FakeResolver({})

        response = handle_post_query(
            {"query": "Return one document."},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertNotIn("retrieval_debug", response["meta"])
        self.assertEqual(response["meta"]["retrieval_summary"]["retrieved_candidates"], 1)
        self.assertEqual(response["meta"]["retrieval_summary"]["returned_evidence"], 1)

    def test_same_input_returns_deterministic_response(self) -> None:
        pages = [
            RetrievePage(
                results=[
                    _text_candidate(
                        source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                        chunk_id="chunk-a-1",
                        snippet="Doc A says scaling improved performance.",
                    ),
                    _text_candidate(
                        source_uri="s3://raw/documents-raw/doc-b/source.pdf",
                        chunk_id="chunk-b-1",
                        snippet="Doc B reports the same trend with a different threshold.",
                    ),
                ]
            )
        ]
        resolver = _FakeResolver(
            {
                "s3://raw/documents-raw/doc-a/source.pdf": "doc-a",
                "s3://raw/documents-raw/doc-b/source.pdf": "doc-b",
            }
        )

        first = handle_post_query(
            {"query": "Compare scaling behavior across the indexed papers.", "debug": True},
            retriever=_PagedRetriever(pages),
            provenance_resolver=resolver,
        )
        second = handle_post_query(
            {"query": "Compare scaling behavior across the indexed papers.", "debug": True},
            retriever=_PagedRetriever(pages),
            provenance_resolver=resolver,
        )

        self.assertEqual(first, second)

    def test_scoped_query_filters_out_of_scope_docs(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                            chunk_id="chunk-a-1",
                            snippet="Doc A text.",
                        ),
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-b/source.pdf",
                            chunk_id="chunk-b-1",
                            snippet="Doc B text.",
                        ),
                    ]
                )
            ]
        )
        resolver = _FakeResolver(
            {
                "s3://raw/documents-raw/doc-a/source.pdf": "doc-a",
                "s3://raw/documents-raw/doc-b/source.pdf": "doc-b",
            }
        )

        response = handle_post_query(
            {
                "query": "What does doc A say?",
                "scope": {"doc_ids": ["doc-a"], "scope_reason": "explicit_doc_id"},
            },
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(response["meta"]["scope_mode"], "scoped")
        self.assertEqual(response["meta"]["scoped_doc_ids"], ["doc-a"])
        self.assertEqual(len(response["evidence"]), 1)
        self.assertEqual(response["evidence"][0]["doc_id"], "doc-a")

    def test_scoped_query_paginates_until_in_scope_candidate_found(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-b/source.pdf",
                            chunk_id="chunk-b-1",
                            snippet="Out of scope text.",
                        )
                    ],
                    next_token="page-2",
                ),
                RetrievePage(
                    results=[
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                            chunk_id="chunk-a-1",
                            snippet="In-scope text.",
                        )
                    ],
                    next_token=None,
                ),
            ]
        )
        resolver = _FakeResolver(
            {
                "s3://raw/documents-raw/doc-a/source.pdf": "doc-a",
                "s3://raw/documents-raw/doc-b/source.pdf": "doc-b",
            }
        )

        response = handle_post_query(
            {
                "query": "Find the in-scope passage.",
                "scope": {"doc_ids": ["doc-a"], "scope_reason": "ui_selection"},
            },
            retriever=retriever,
            provenance_resolver=resolver,
            top_k=1,
            max_pages=3,
        )

        self.assertEqual(len(retriever.calls), 2)
        self.assertEqual(response["evidence"][0]["doc_id"], "doc-a")

    def test_zero_candidates_returns_insufficient_evidence_response(self) -> None:
        retriever = _PagedRetriever([RetrievePage(results=[])])
        resolver = _FakeResolver({})

        response = handle_post_query(
            {"query": "Find evidence that is not present."},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(response["evidence"], [])
        self.assertTrue(response["meta"]["insufficient_evidence"])
        self.assertIn("No retrieved evidence matched the request.", response["limitations"])

    def test_unresolved_candidate_is_dropped_and_reported(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                            chunk_id="chunk-a-1",
                            snippet="Resolved text.",
                        ),
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/missing/source.pdf",
                            chunk_id="chunk-x-1",
                            snippet="Unresolved text.",
                        ),
                    ]
                )
            ]
        )
        resolver = _FakeResolver({"s3://raw/documents-raw/doc-a/source.pdf": "doc-a"})

        response = handle_post_query(
            {"query": "Return whatever you can resolve.", "debug": True},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(len(response["evidence"]), 1)
        self.assertEqual(response["evidence"][0]["doc_id"], "doc-a")
        self.assertIn("doc provenance could not be resolved", " ".join(response["limitations"]))
        debug = response["meta"]["retrieval_debug"]
        self.assertEqual(debug["retrieved_candidates"], 2)
        self.assertEqual(debug["returned_evidence"], 1)
        self.assertEqual(debug["dropped_candidates"], 1)
        self.assertEqual(debug["drop_reasons"][0]["reason"], "unresolved_doc_id")
        self.assertEqual(debug["drop_reasons"][0]["candidate_index"], 1)
        self.assertEqual(len(debug["candidates"]), 2)
        self.assertFalse(debug["candidates"][0]["dropped"])
        self.assertEqual(debug["candidates"][0]["rank"], 1)
        self.assertEqual(debug["candidates"][0]["doc_id"], "doc-a")
        self.assertTrue(debug["candidates"][1]["dropped"])
        self.assertEqual(debug["candidates"][1]["drop_reason"], "unresolved_doc_id")

    def test_debug_exposes_exact_normalization_reason(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        {
                            "content": {"type": "TEXT"},
                            "location": {
                                "s3Location": {
                                    "uri": "s3://raw/documents-raw/doc-a/source.pdf",
                                }
                            },
                            "metadata": {
                                "x-amz-bedrock-kb-source-file-modality": "TEXT",
                                "x-amz-bedrock-kb-chunk-id": "chunk-a-1",
                            },
                            "score": 0.42,
                        }
                    ]
                )
            ]
        )
        resolver = _FakeResolver({"s3://raw/documents-raw/doc-a/source.pdf": "doc-a"})

        response = handle_post_query(
            {"query": "Show exact drop reasons.", "debug": True},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(response["evidence"], [])
        debug = response["meta"]["retrieval_debug"]
        self.assertEqual(debug["dropped_candidates"], 1)
        self.assertEqual(debug["drop_reasons"][0]["reason"], "missing_text_snippet")
        self.assertIn("missing text snippet", debug["drop_reasons"][0]["detail"])
        self.assertEqual(debug["drop_reasons"][0]["doc_id"], "doc-a")
        self.assertEqual(debug["drop_reasons"][0]["source_uri"], "s3://raw/documents-raw/doc-a/source.pdf")
        self.assertEqual(debug["drop_reasons"][0]["candidate_content_type"], "TEXT")
        self.assertEqual(debug["drop_reasons"][0]["source_file_modality"], "TEXT")
        self.assertEqual(debug["candidates"][0]["rank"], 1)
        self.assertTrue(debug["candidates"][0]["dropped"])
        self.assertEqual(debug["candidates"][0]["drop_reason"], "missing_text_snippet")
        self.assertEqual(debug["candidates"][0]["metadata"]["x-amz-bedrock-kb-chunk-id"], "chunk-a-1")

    def test_debug_exposes_scope_filter_reason(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _text_candidate(
                            source_uri="s3://raw/documents-raw/doc-b/source.pdf",
                            chunk_id="chunk-b-1",
                            snippet="Out of scope text.",
                        )
                    ]
                )
            ]
        )
        resolver = _FakeResolver({"s3://raw/documents-raw/doc-b/source.pdf": "doc-b"})

        response = handle_post_query(
            {
                "query": "Restrict to doc A.",
                "debug": True,
                "scope": {"doc_ids": ["doc-a"], "scope_reason": "explicit_doc_id"},
            },
            retriever=retriever,
            provenance_resolver=resolver,
        )

        debug = response["meta"]["retrieval_debug"]
        self.assertEqual(debug["filtered_out_of_scope"], 1)
        self.assertEqual(debug["drop_reasons"][0]["reason"], "filtered_out_of_scope")
        self.assertEqual(debug["drop_reasons"][0]["doc_id"], "doc-b")

    def test_visual_candidate_normalizes_to_schema_valid_evidence(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _visual_candidate(
                            source_uri="s3://raw/documents-raw/doc-v/source.pdf",
                            doc_id="doc-v",
                            asset_id="asset-1",
                            asset_s3_key="aws/bedrock/knowledge_bases/KB/DS/asset-1.png",
                            caption="Important table.",
                            page=9,
                        )
                    ]
                )
            ]
        )
        resolver = _FakeResolver({})

        response = handle_post_query(
            {"query": "Show the important table."},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        evidence = response["evidence"][0]
        self.assertEqual(evidence["asset_type"], "table_image")
        self.assertEqual(evidence["asset_id"], "asset-1")
        self.assertEqual(evidence["asset_s3_key"], "aws/bedrock/knowledge_bases/KB/DS/asset-1.png")

    def test_bedrock_image_result_from_text_source_normalizes_as_visual_evidence(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _bedrock_image_candidate(
                            source_uri="s3://raw/documents-raw/doc-v/source.pdf",
                            asset_source_uri="s3://assets/aws/bedrock/knowledge_bases/KB/DS/af5a9332-1fd7-4ae1-a3f4.png",
                            description="Table 2 compares model quality.",
                            page_number=7.0,
                        )
                    ]
                )
            ]
        )
        resolver = _FakeResolver({"s3://raw/documents-raw/doc-v/source.pdf": "doc-v"})

        response = handle_post_query(
            {"query": "Show the table comparing model quality."},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(len(response["evidence"]), 1)
        evidence = response["evidence"][0]
        self.assertEqual(evidence["doc_id"], "doc-v")
        self.assertEqual(evidence["asset_type"], "table_image")
        self.assertEqual(evidence["asset_id"], "af5a9332-1fd7-4ae1-a3f4")
        self.assertEqual(
            evidence["asset_s3_key"],
            "aws/bedrock/knowledge_bases/KB/DS/af5a9332-1fd7-4ae1-a3f4.png",
        )
        self.assertEqual(evidence["page"], 7)
        self.assertEqual(evidence["caption"], "Table 2 compares model quality.")

    def test_image_result_missing_asset_locator_reports_raw_modalities(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        _bedrock_image_candidate(
                            source_uri="s3://raw/documents-raw/doc-v/source.pdf",
                            asset_source_uri=None,
                            description="Figure 4 architecture overview.",
                        )
                    ]
                )
            ]
        )
        resolver = _FakeResolver({"s3://raw/documents-raw/doc-v/source.pdf": "doc-v"})

        response = handle_post_query(
            {"query": "Show the architecture figure.", "debug": True},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(response["evidence"], [])
        debug = response["meta"]["retrieval_debug"]
        self.assertEqual(debug["dropped_candidates"], 1)
        self.assertEqual(debug["drop_reasons"][0]["reason"], "missing_visual_asset_id")
        self.assertEqual(debug["drop_reasons"][0]["candidate_content_type"], "IMAGE")
        self.assertEqual(debug["drop_reasons"][0]["source_file_modality"], "TEXT")
        self.assertEqual(debug["drop_reasons"][0]["asset_type"], "figure_image")

    def test_bedrock_text_metadata_keys_normalize_correctly(self) -> None:
        retriever = _PagedRetriever(
            [
                RetrievePage(
                    results=[
                        {
                            "content": {"text": "Transformer details.", "type": "TEXT"},
                            "location": {
                                "s3Location": {
                                    "uri": "s3://raw/documents-raw/doc-a/source.pdf",
                                }
                            },
                            "metadata": {
                                "x-amz-bedrock-kb-source-file-modality": "TEXT",
                                "x-amz-bedrock-kb-chunk-id": "chunk-a-aws",
                            },
                            "score": 0.91,
                        }
                    ]
                )
            ]
        )
        resolver = _FakeResolver({"s3://raw/documents-raw/doc-a/source.pdf": "doc-a"})

        response = handle_post_query(
            {"query": "What does the transformer paper say?"},
            retriever=retriever,
            provenance_resolver=resolver,
        )

        self.assertEqual(len(response["evidence"]), 1)
        self.assertEqual(response["evidence"][0]["doc_id"], "doc-a")
        self.assertEqual(response["evidence"][0]["chunk_id"], "chunk-a-aws")


class BedrockKnowledgeBaseRetrieverTests(unittest.TestCase):
    def test_retrieve_builds_bedrock_request(self) -> None:
        client = _ClientStub(
            {
                "retrievalResults": [
                    _text_candidate(
                        source_uri="s3://raw/documents-raw/doc-a/source.pdf",
                        chunk_id="chunk-a-1",
                        snippet="Doc A text.",
                        doc_id="doc-a",
                    )
                ],
                "nextToken": "token-2",
            }
        )
        retriever = BedrockKnowledgeBaseRetriever(
            "KB12345678",
            client=client,
            override_search_type="SEMANTIC",
        )

        page = retriever.retrieve(
            query_text="Compare the indexed papers.",
            top_k=6,
            next_token="token-1",
            modality_hints=["text_chunk"],
        )

        self.assertEqual(page.next_token, "token-2")
        self.assertEqual(len(page.results), 1)
        self.assertEqual(client.calls[0]["knowledgeBaseId"], "KB12345678")
        self.assertEqual(client.calls[0]["nextToken"], "token-1")
        self.assertEqual(client.calls[0]["retrievalQuery"], {"text": "Compare the indexed papers."})
        self.assertEqual(
            client.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]["numberOfResults"],
            6,
        )
        self.assertEqual(
            client.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]["overrideSearchType"],
            "SEMANTIC",
        )


if __name__ == "__main__":
    unittest.main()
