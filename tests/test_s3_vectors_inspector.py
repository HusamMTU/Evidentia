from __future__ import annotations

from datetime import date, datetime
import json
import unittest

from tools.s3_vectors_inspector.inspector import (
    InspectorConfigError,
    InspectorConfig,
    S3VectorsInspectorClient,
    build_config,
    build_env_context,
    parse_index_arn,
    parse_vector_bucket_name,
    resolve_config_defaults,
    summarize_by_data_source,
    summarize_vector,
)
from tools.s3_vectors_inspector.server import _json_compatible


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

    def test_resolve_config_defaults_returns_partial_values_without_error(self) -> None:
        defaults = resolve_config_defaults(
            region=None,
            vector_bucket_name=None,
            index_name=None,
            index_arn="arn:aws:s3vectors:us-east-1:123456789012:bucket/vb/index/idx",
            env={"AWS_REGION": "us-east-1"},
        )
        self.assertEqual(defaults.region, "us-east-1")
        self.assertEqual(defaults.vector_bucket_name, "vb")
        self.assertEqual(defaults.index_name, "idx")
        self.assertTrue(defaults.index_arn.endswith("bucket/vb/index/idx"))

    def test_build_env_context_reads_relevant_values(self) -> None:
        env_context = build_env_context(
            {
                "BEDROCK_KNOWLEDGE_BASE_ID": "KB123",
                "BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID": "DS123",
                "EVIDENTIA_ASSETS_BUCKET": "assets-bucket",
            }
        )
        self.assertEqual(env_context.knowledge_base_id, "KB123")
        self.assertEqual(env_context.knowledge_base_data_source_id, "DS123")
        self.assertEqual(env_context.assets_bucket_name, "assets-bucket")

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
        self.assertEqual(summary["text_length"], len("A short body of text"))
        self.assertEqual(summary["related_content_types"]["S3"], 1)

    def test_summarize_vector_marks_current_data_source(self) -> None:
        vector = {
            "key": "vec-1",
            "metadata": {
                "x-amz-bedrock-kb-data-source-id": "CURRENT",
                "x-amz-bedrock-kb-source-file-modality": "TEXT",
            },
        }
        summary = summarize_vector(vector, current_data_source_id="CURRENT")
        self.assertTrue(summary["is_current_data_source"])

    def test_summarize_by_data_source_counts(self) -> None:
        vectors = [
            {"metadata": {"x-amz-bedrock-kb-data-source-id": "A", "x-amz-bedrock-kb-source-file-modality": "TEXT"}},
            {"metadata": {"x-amz-bedrock-kb-data-source-id": "A", "x-amz-bedrock-kb-source-file-modality": "TEXT"}},
            {"metadata": {"x-amz-bedrock-kb-data-source-id": "B", "x-amz-bedrock-kb-source-file-modality": "IMAGE"}},
        ]
        summary = summarize_by_data_source(vectors, current_data_source_id="A")
        self.assertEqual(summary["data_source_counts"]["A"], 2)
        self.assertEqual(summary["data_source_counts"]["B"], 1)
        self.assertEqual(summary["modality_counts"]["TEXT"], 2)
        self.assertEqual(summary["modality_counts"]["IMAGE"], 1)
        self.assertEqual(summary["current_data_source_vector_count"], 2)
        self.assertEqual(summary["historical_data_source_ids"], ["B"])
        self.assertEqual(summary["historical_data_source_vector_count"], 1)

    def test_json_compatible_serializes_nested_dates(self) -> None:
        payload = {
            "createdAt": datetime(2026, 3, 5, 14, 30, 0),
            "items": [{"updatedAt": date(2026, 3, 5)}],
        }
        encoded = json.dumps(_json_compatible(payload))
        self.assertIn('"2026-03-05T14:30:00"', encoded)
        self.assertIn('"2026-03-05"', encoded)

    def test_get_index_returns_index_payload(self) -> None:
        class DummyBotoClient:
            def get_index(self, **kwargs):
                self.kwargs = kwargs
                return {"index": {"dimension": 1024, "dataType": "float32"}}

        boto_client = DummyBotoClient()
        client = S3VectorsInspectorClient(
            config=InspectorConfig(region="us-east-1", vector_bucket_name="vb", index_name="idx"),
            boto_client=boto_client,
        )

        index = client.get_index()
        self.assertEqual(index["dimension"], 1024)
        self.assertEqual(index["dataType"], "float32")
        self.assertEqual(
            boto_client.kwargs,
            {"vectorBucketName": "vb", "indexName": "idx"},
        )


if __name__ == "__main__":
    unittest.main()
