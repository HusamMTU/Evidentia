# Validation Layer (MVP Scaffold)

This package wires the JSON schemas in `schemas/` into a small validation layer for:

- query request validation (`query-request.schema.json`)
- strict model output validation (`model-answer.schema.json`)
- citation integrity validation against selected evidence items

## Requirements

- Python 3.10+
- `jsonschema` package (declared in root `pyproject.toml`)

Install:

```bash
# from repo root
pip install -e .
# or: uv sync
```

## Example

```python
from validation import validate_model_answer_against_evidence, validate_query_request

request_payload = {"query": "Compare failure rates across reports"}
validate_query_request(request_payload)

evidence = [
    {"evidence_id": "E1", "doc_id": "doc-a", "asset_type": "text_chunk", "chunk_id": "c1", "snippet": "..."},  # simplified
    {"evidence_id": "E2", "doc_id": "doc-b", "asset_type": "figure_image", "asset_id": "a9", "asset_s3_key": "documents-assets/doc-b/a9.png"},
]

model_answer = {
    "answer": "The reports disagree on the failure rate.",
    "citations": [{"statement": "The reports disagree on the failure rate.", "evidence_ids": ["E1", "E2"]}],
    "used_evidence_ids": ["E1", "E2"],
    "limitations": []
}

validate_model_answer_against_evidence(model_answer, evidence)
```

## Notes

- The JSON schemas remain the source of truth for request/model JSON shape.
- Citation integrity is validated separately because it depends on the selected runtime evidence bundle.

Run contract fixture tests:

```bash
python -m unittest tests/test_contract_fixtures.py
```
