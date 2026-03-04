from __future__ import annotations

import unittest

from tools.s3_vectors_inspector.inspector import (
    InspectorConfigError,
    build_config,
    parse_index_arn,
    parse_vector_bucket_name,
    summarize_by_data_source,
    summarize_vector,
)


class S3VectorsInspectorTests(unittest.TestCase):
    def test_parse_index_arn(self) -> None:
        bucket, index = parse_index_arn(
            "arn:aws:s3vectors:us-east-1:123456789012:bucket/my-bucket/index/my-index"
        )
        self.assertEqual(bucket, "my-bucket")
        self.assertEqual(index, "my-index")

    def test_parse_index_arn_rejects_invalid(self) -> None:
        with self.assertRaises(InspectorConfigError):
            parse_index_arn("arn:aws:s3vectors:us-east-1:123456789012:bucket/my-bucket")

    def test_parse_vector_bucket_name_from_arn(self) -> None:
        name = parse_vector_bucket_name("arn:aws:s3vectors:us-east-1:123456789012:bucket/my-vb")
        self.assertEqual(name, "my-vb")

    def test_build_config_uses_index_arn_for_missing_values(self) -> None:
        config = build_config(
            region="us-east-1",
            vector_bucket_name=None,
            index_name=None,
            index_arn="arn:aws:s3vectors:us-east-1:123456789012:bucket/vb/index/idx",
            env={},
        )
        self.assertEqual(config.region, "us-east-1")
        self.assertEqual(config.vector_bucket_name, "vb")
        self.assertEqual(config.index_name, "idx")

    def test_summarize_vector_extracts_source_and_related_assets(self) -> None:
        vector = {
            "key": "vec-1",
            "metadata": {
                "x-amz-bedrock-kb-data-source-id": "DS1",
                "x-amz-bedrock-kb-source-file-modality": "TEXT",
                "AMAZON_BEDROCK_TEXT": "A short body of text",
                "AMAZON_BEDROCK_METADATA": (
                    '{"source":{"sourceLocation":"s3://raw/documents-raw/doc-1/source.pdf"},'
                    '"relatedContents":[{"locationType":"S3"}]}'
                ),
            },
        }
        summary = summarize_vector(vector)
        self.assertEqual(summary["source_uri"], "s3://raw/documents-raw/doc-1/source.pdf")
        self.assertEqual(summary["related_asset_count"], 1)
        self.assertEqual(summary["data_source_id"], "DS1")

    def test_summarize_by_data_source_counts(self) -> None:
        vectors = [
            {"metadata": {"x-amz-bedrock-kb-data-source-id": "A", "x-amz-bedrock-kb-source-file-modality": "TEXT"}},
            {"metadata": {"x-amz-bedrock-kb-data-source-id": "A", "x-amz-bedrock-kb-source-file-modality": "TEXT"}},
            {"metadata": {"x-amz-bedrock-kb-data-source-id": "B", "x-amz-bedrock-kb-source-file-modality": "IMAGE"}},
        ]
        summary = summarize_by_data_source(vectors)
        self.assertEqual(summary["data_source_counts"]["A"], 2)
        self.assertEqual(summary["data_source_counts"]["B"], 1)
        self.assertEqual(summary["modality_counts"]["TEXT"], 2)
        self.assertEqual(summary["modality_counts"]["IMAGE"], 1)


if __name__ == "__main__":
    unittest.main()
