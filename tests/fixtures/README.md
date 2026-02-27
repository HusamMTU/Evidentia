# Fixture Catalog

These fixtures are valid examples for the contract schemas introduced in Phase 0 and used for Phase 3 scaffolding.

- `query-request.unscoped.valid.json`: unscoped (multi-document default) query request
- `query-request.scoped.valid.json`: explicitly scoped query request
- `model-answer.valid.json`: strict LLM JSON output example
- `evidence-item.text.valid.json`: valid text evidence item
- `evidence-item.visual.valid.json`: valid visual evidence item
- `query-response.valid.json`: API response example with evidence payload and metadata

Notes:

- `query-response.valid.json` embeds evidence items and is the main end-to-end contract fixture.
- Citation integrity (model answer IDs matching selected evidence IDs) is validated at runtime and also holds for the provided fixtures.

Run fixture validation:

```bash
python -m unittest tests/test_contract_fixtures.py
```
