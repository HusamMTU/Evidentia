from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "run_seed_corpus_batch_ingestion.py"
SPEC = importlib.util.spec_from_file_location("run_seed_corpus_batch_ingestion", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SeedCorpusBatchIngestionTests(unittest.TestCase):
    def test_normalize_status_filters_defaults_to_planned(self) -> None:
        self.assertEqual(MODULE.normalize_status_filters(None), {"planned"})

    def test_select_rows_filters_by_status_doc_id_and_limit(self) -> None:
        rows = [
            {"doc_id": "a", "ingestion_status": "planned"},
            {"doc_id": "b", "ingestion_status": "verified"},
            {"doc_id": "c", "ingestion_status": "planned"},
        ]
        selected = MODULE.select_rows(
            rows,
            doc_ids=["c", "a"],
            statuses={"planned"},
            limit=1,
        )
        self.assertEqual([row["doc_id"] for row in selected], ["a"])

    def test_source_object_key_preserves_suffixes(self) -> None:
        self.assertEqual(
            MODULE.source_object_key("doc-1", Path("/tmp/example.pdf")),
            "documents-raw/doc-1/source.pdf",
        )
        self.assertEqual(
            MODULE.source_object_key("doc-2", Path("/tmp/archive.tar.gz")),
            "documents-raw/doc-2/source.tar.gz",
        )

    def test_source_object_key_supports_extensionless_files(self) -> None:
        self.assertEqual(
            MODULE.source_object_key("doc-3", Path("/tmp/sourcefile")),
            "documents-raw/doc-3/source",
        )

    def test_normalize_aws_text_treats_multiline_none_as_empty(self) -> None:
        self.assertIsNone(MODULE.normalize_aws_text("None\nNone\n"))

    def test_assess_batch_summary_accepts_expected_index_count(self) -> None:
        summary = {"final_status": "COMPLETE", "new": 4, "modified": 1, "failed": 0}
        self.assertIsNone(MODULE.assess_batch_summary(summary, expected_documents=5))

    def test_assess_batch_summary_rejects_under_indexed_batch(self) -> None:
        summary = {"final_status": "COMPLETE", "new": 1, "modified": 0, "failed": 0}
        message = MODULE.assess_batch_summary(summary, expected_documents=2)
        self.assertIn("indexed_total=1", message)
        self.assertIn("Expected at least 2", message)

    def test_assess_batch_summary_rejects_failed_documents(self) -> None:
        summary = {
            "final_status": "COMPLETE",
            "new": 3,
            "modified": 0,
            "failed": 1,
            "failure_reasons": ["bad doc"],
        }
        message = MODULE.assess_batch_summary(summary, expected_documents=3)
        self.assertIn("failed=1", message)
        self.assertIn("bad doc", message)

    def test_write_manifest_round_trips_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.csv"
            manifest_path.write_text(
                "doc_id,ingestion_status,source_path\n"
                "doc-1,planned,datasets/seed_corpus/source/doc-1.pdf\n",
                encoding="utf-8",
            )
            fieldnames, rows = MODULE.load_manifest(manifest_path)
            rows[0]["ingestion_status"] = "verified"
            MODULE.write_manifest(manifest_path, fieldnames, rows)
            _, written_rows = MODULE.load_manifest(manifest_path)
            self.assertEqual(written_rows[0]["ingestion_status"], "verified")

    def test_log_directory_for_report_derives_stable_path(self) -> None:
        report_path = Path("/tmp/example/seed_ingestion_20260319T120000Z.jsonl")
        logs_dir = MODULE.log_directory_for_report(report_path)
        self.assertEqual(str(logs_dir), "/tmp/example/seed_ingestion_20260319T120000Z_logs")


if __name__ == "__main__":
    unittest.main()
