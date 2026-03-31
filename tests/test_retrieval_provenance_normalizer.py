from __future__ import annotations

import unittest

from provenance import ProvenanceResolutionError, normalize_retrieval_candidate_doc_id


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


class RetrievalProvenanceNormalizerTests(unittest.TestCase):
    def test_preserves_existing_doc_id_when_present(self) -> None:
        resolver = _Resolver({})
        candidate = {
            "doc_id": "doc-existing",
            "metadata": {"source_uri": "s3://raw/documents-raw/doc-existing/source.pdf"},
        }
        normalized = normalize_retrieval_candidate_doc_id(candidate, resolver=resolver, strict=True)
        self.assertEqual(normalized["doc_id"], "doc-existing")
        self.assertEqual(normalized["metadata"]["doc_id"], "doc-existing")

    def test_resolves_doc_id_from_source_uri(self) -> None:
        resolver = _Resolver({"s3://raw/documents-raw/doc-1/source.pdf": "doc-1"})
        candidate = {"metadata": {"source_uri": "s3://raw/documents-raw/doc-1/source.pdf"}}
        normalized = normalize_retrieval_candidate_doc_id(candidate, resolver=resolver, strict=True)
        self.assertEqual(normalized["doc_id"], "doc-1")

    def test_resolves_doc_id_from_location_bucket_and_key(self) -> None:
        resolver = _Resolver({"s3://raw/documents-raw/doc-2/source.pdf": "doc-2"})
        candidate = {"location": {"s3Location": {"bucketName": "raw", "objectKey": "documents-raw/doc-2/source.pdf"}}}
        normalized = normalize_retrieval_candidate_doc_id(candidate, resolver=resolver, strict=True)
        self.assertEqual(normalized["doc_id"], "doc-2")
        self.assertEqual(normalized["metadata"]["source_uri"], "s3://raw/documents-raw/doc-2/source.pdf")

    def test_raises_in_strict_mode_when_unresolvable(self) -> None:
        resolver = _Resolver({})
        candidate = {"metadata": {"source_uri": "s3://raw/documents-raw/missing/source.pdf"}}
        with self.assertRaises(ProvenanceResolutionError):
            normalize_retrieval_candidate_doc_id(candidate, resolver=resolver, strict=True)

    def test_non_strict_mode_allows_unresolved_candidate(self) -> None:
        resolver = _Resolver({})
        candidate = {"metadata": {"source_uri": "s3://raw/documents-raw/missing/source.pdf"}}
        normalized = normalize_retrieval_candidate_doc_id(candidate, resolver=resolver, strict=False)
        self.assertNotIn("doc_id", normalized)
        self.assertEqual(normalized["metadata"]["source_uri"], "s3://raw/documents-raw/missing/source.pdf")

    def test_preserves_asset_source_uri_and_asset_key_without_affecting_doc_resolution(self) -> None:
        resolver = _Resolver({"s3://raw/documents-raw/doc-3/source.pdf": "doc-3"})
        candidate = {
            "location": {"s3Location": {"uri": "s3://raw/documents-raw/doc-3/source.pdf"}},
            "metadata": {
                "x-amz-bedrock-kb-byte-content-source": (
                    "s3://assets/aws/bedrock/knowledge_bases/KB123/DS456/asset-1.png"
                )
            },
        }

        normalized = normalize_retrieval_candidate_doc_id(candidate, resolver=resolver, strict=True)

        self.assertEqual(normalized["doc_id"], "doc-3")
        self.assertEqual(normalized["metadata"]["source_uri"], "s3://raw/documents-raw/doc-3/source.pdf")
        self.assertEqual(
            normalized["metadata"]["asset_source_uri"],
            "s3://assets/aws/bedrock/knowledge_bases/KB123/DS456/asset-1.png",
        )
        self.assertEqual(
            normalized["metadata"]["asset_s3_key"],
            "aws/bedrock/knowledge_bases/KB123/DS456/asset-1.png",
        )

    def test_normalizes_source_file_modality_into_stable_metadata_field(self) -> None:
        resolver = _Resolver({"s3://raw/documents-raw/doc-4/source.pdf": "doc-4"})
        candidate = {
            "metadata": {
                "source_uri": "s3://raw/documents-raw/doc-4/source.pdf",
                "x-amz-bedrock-kb-source-file-modality": "text",
            }
        }

        normalized = normalize_retrieval_candidate_doc_id(candidate, resolver=resolver, strict=True)

        self.assertEqual(normalized["metadata"]["source_file_modality"], "TEXT")


if __name__ == "__main__":
    unittest.main()
