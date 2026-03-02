from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from provenance import IngestionManifestRecord, SQLiteIngestionManifestStore, parse_s3_uri


class IngestionManifestStoreTests(unittest.TestCase):
    def test_upsert_and_lookup_by_doc_id_and_source_uri(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "manifest.db"
            store = SQLiteIngestionManifestStore(db_path)
            record = IngestionManifestRecord.from_doc_and_uri(
                doc_id="doc-123",
                source_uri="s3://raw-bucket/documents-raw/doc-123/source.pdf",
                kb_id="KB123",
                data_source_id="DS123",
                status="uploaded",
            )

            saved = store.upsert(record)
            self.assertEqual(saved.doc_id, "doc-123")
            self.assertEqual(saved.source_bucket, "raw-bucket")
            self.assertEqual(saved.source_key, "documents-raw/doc-123/source.pdf")
            self.assertEqual(saved.kb_id, "KB123")

            by_doc_id = store.get_by_doc_id("doc-123")
            self.assertIsNotNone(by_doc_id)
            assert by_doc_id is not None
            self.assertEqual(by_doc_id.source_uri, record.source_uri)

            by_source_uri = store.get_by_source_uri(record.source_uri)
            self.assertIsNotNone(by_source_uri)
            assert by_source_uri is not None
            self.assertEqual(by_source_uri.doc_id, "doc-123")

    def test_resolve_doc_id_from_source_uri_or_bucket_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "manifest.db"
            store = SQLiteIngestionManifestStore(db_path)
            store.upsert(
                IngestionManifestRecord.from_doc_and_uri(
                    doc_id="doc-abc",
                    source_uri="s3://raw-bucket/documents-raw/doc-abc/source.pdf",
                )
            )

            self.assertEqual(
                store.resolve_doc_id(source_uri="s3://raw-bucket/documents-raw/doc-abc/source.pdf"),
                "doc-abc",
            )
            self.assertEqual(
                store.resolve_doc_id(
                    source_bucket="raw-bucket",
                    source_key="documents-raw/doc-abc/source.pdf",
                ),
                "doc-abc",
            )
            self.assertIsNone(
                store.resolve_doc_id(source_uri="s3://raw-bucket/documents-raw/missing/source.pdf")
            )

    def test_upsert_updates_existing_doc_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "manifest.db"
            store = SQLiteIngestionManifestStore(db_path)

            first = store.upsert(
                IngestionManifestRecord.from_doc_and_uri(
                    doc_id="doc-777",
                    source_uri="s3://raw-bucket/documents-raw/doc-777/source.pdf",
                    status="uploaded",
                )
            )
            second = store.upsert(
                IngestionManifestRecord.from_doc_and_uri(
                    doc_id="doc-777",
                    source_uri="s3://raw-bucket/documents-raw/doc-777/source-v2.pdf",
                    status="ingested",
                )
            )

            self.assertEqual(second.status, "ingested")
            self.assertEqual(second.source_key, "documents-raw/doc-777/source-v2.pdf")
            self.assertEqual(first.created_at, second.created_at)
            self.assertNotEqual(first.updated_at, second.updated_at)

    def test_parse_s3_uri_validation(self) -> None:
        self.assertEqual(
            parse_s3_uri("s3://bucket/path/to/file.pdf"),
            ("bucket", "path/to/file.pdf"),
        )
        with self.assertRaises(ValueError):
            parse_s3_uri("https://bucket/path")
        with self.assertRaises(ValueError):
            parse_s3_uri("s3://bucket-only")


if __name__ == "__main__":
    unittest.main()

