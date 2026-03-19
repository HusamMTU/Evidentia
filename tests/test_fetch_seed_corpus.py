from __future__ import annotations

import unittest
from pathlib import Path

from scripts.fetch_seed_corpus import REPO_ROOT, SOURCE_ROOT, resolve_source_path, validate_source_url


class FetchSeedCorpusTests(unittest.TestCase):
    def test_resolve_source_path_accepts_paths_under_source_root(self) -> None:
        resolved = resolve_source_path("datasets/seed_corpus/source/sample.docx")
        self.assertEqual(resolved, SOURCE_ROOT / "sample.docx")

    def test_resolve_source_path_rejects_escape_outside_source_root(self) -> None:
        with self.assertRaises(SystemExit):
            resolve_source_path("../outside.pdf")

    def test_resolve_source_path_rejects_non_source_tree_targets(self) -> None:
        with self.assertRaises(SystemExit):
            resolve_source_path(str(Path("datasets") / "seed_corpus" / "README.md"))

    def test_validate_source_url_accepts_versioned_arxiv_pdf(self) -> None:
        validate_source_url("https://arxiv.org/pdf/1706.03762v7.pdf")

    def test_validate_source_url_accepts_non_arxiv_sources(self) -> None:
        validate_source_url("https://example.com/files/reference.docx")

    def test_validate_source_url_rejects_unversioned_arxiv_pdf(self) -> None:
        with self.assertRaises(SystemExit):
            validate_source_url("https://arxiv.org/pdf/1706.03762.pdf")


if __name__ == "__main__":
    unittest.main()
