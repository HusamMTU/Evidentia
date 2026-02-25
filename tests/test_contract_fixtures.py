from __future__ import annotations

import json
import unittest
from pathlib import Path

from validation import (
    validate_citation_integrity,
    validate_evidence_item,
    validate_model_answer,
    validate_query_request,
    validate_query_response,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_json(name: str):
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


class ContractFixtureTests(unittest.TestCase):
    def test_query_request_fixtures_validate(self) -> None:
        validate_query_request(_load_json("query-request.unscoped.valid.json"))
        validate_query_request(_load_json("query-request.scoped.valid.json"))

    def test_model_answer_fixture_validates(self) -> None:
        validate_model_answer(_load_json("model-answer.valid.json"))

    def test_evidence_item_fixtures_validate(self) -> None:
        validate_evidence_item(_load_json("evidence-item.text.valid.json"))
        validate_evidence_item(_load_json("evidence-item.visual.valid.json"))

    def test_query_response_fixture_validates(self) -> None:
        validate_query_response(_load_json("query-response.valid.json"))

    def test_model_answer_citation_integrity_matches_evidence_fixtures(self) -> None:
        model_answer = _load_json("model-answer.valid.json")
        evidence = [
            _load_json("evidence-item.text.valid.json"),
            _load_json("evidence-item.visual.valid.json"),
        ]
        validate_citation_integrity(model_answer, evidence)

    def test_query_response_embedded_citations_match_embedded_evidence(self) -> None:
        query_response = _load_json("query-response.valid.json")
        model_answer_view = {
            "answer": query_response["answer"],
            "citations": query_response["citations"],
            "used_evidence_ids": query_response["used_evidence_ids"],
            "limitations": query_response["limitations"],
        }
        validate_citation_integrity(model_answer_view, query_response["evidence"])


if __name__ == "__main__":
    unittest.main()
