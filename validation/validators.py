from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .errors import CitationIntegrityError, ContractValidationError, ValidationIssue
from .schema_loader import load_schema, repo_root

try:
    import jsonschema
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - environment dependent
    jsonschema = None
    Draft202012Validator = None


def _require_jsonschema() -> None:
    if jsonschema is None or Draft202012Validator is None:
        raise RuntimeError(
            "The 'jsonschema' package is required for contract validation. "
            "Install it with: pip install jsonschema"
        )


def _json_path(parts: Iterable[Any]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def _build_validator(schema_name: str):
    _require_jsonschema()
    schema = load_schema(schema_name)

    # This covers current request/model schemas (no external refs) and is ready for
    # future local refs if the installed jsonschema version supports RefResolver.
    # Schema $id values are repo-relative (for example "schemas/query-response.schema.json"),
    # so the resolver base should be the repository root, not the schema directory.
    base_uri = (repo_root().resolve().as_uri() + "/")

    resolver = None
    if hasattr(jsonschema, "RefResolver"):
        resolver = jsonschema.RefResolver(base_uri=base_uri, referrer=schema)

    if resolver is not None:
        return Draft202012Validator(schema, resolver=resolver)
    return Draft202012Validator(schema)


def _validate_against_schema(schema_name: str, payload: Any) -> None:
    validator = _build_validator(schema_name)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return

    issues = [
        ValidationIssue(
            code="schema_validation_error",
            message=err.message,
            path=_json_path(err.path),
            details={"validator": err.validator, "schema_path": list(err.schema_path)},
        )
        for err in errors
    ]
    raise ContractValidationError(schema_name=schema_name, issues=issues)


def validate_query_request(payload: Any) -> None:
    _validate_against_schema("query-request", payload)


def validate_model_answer(payload: Any) -> None:
    _validate_against_schema("model-answer", payload)


def validate_evidence_item(payload: Any) -> None:
    _validate_against_schema("evidence-item", payload)


def validate_query_response(payload: Any) -> None:
    _validate_against_schema("query-response", payload)


def validate_citation_integrity(model_answer: dict[str, Any], evidence_items: list[dict[str, Any]]) -> None:
    evidence_ids = [item.get("evidence_id") for item in evidence_items]
    evidence_id_set = {eid for eid in evidence_ids if isinstance(eid, str)}
    issues: list[ValidationIssue] = []

    # Enforce uniqueness and presence on the evidence side (defense in depth).
    duplicates = _find_duplicates([eid for eid in evidence_ids if eid is not None])
    for dup in duplicates:
        issues.append(
            ValidationIssue(
                code="duplicate_evidence_id",
                message=f"Duplicate evidence_id '{dup}' in evidence bundle",
                path="$.evidence",
            )
        )

    for idx, item in enumerate(evidence_items):
        eid = item.get("evidence_id")
        if not isinstance(eid, str) or not eid:
            issues.append(
                ValidationIssue(
                    code="missing_evidence_id",
                    message="Evidence item missing non-empty evidence_id",
                    path=f"$.evidence[{idx}].evidence_id",
                )
            )

    for idx, citation in enumerate(model_answer.get("citations", [])):
        for jdx, cited_id in enumerate(citation.get("evidence_ids", [])):
            if cited_id not in evidence_id_set:
                issues.append(
                    ValidationIssue(
                        code="unknown_citation_evidence_id",
                        message=f"Cited evidence_id '{cited_id}' not found in selected evidence bundle",
                        path=f"$.citations[{idx}].evidence_ids[{jdx}]",
                    )
                )

    for idx, used_id in enumerate(model_answer.get("used_evidence_ids", [])):
        if used_id not in evidence_id_set:
            issues.append(
                ValidationIssue(
                    code="unknown_used_evidence_id",
                    message=f"used_evidence_ids entry '{used_id}' not found in selected evidence bundle",
                    path=f"$.used_evidence_ids[{idx}]",
                )
            )

    if issues:
        raise CitationIntegrityError(issues)


def validate_model_answer_against_evidence(
    model_answer: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> None:
    validate_model_answer(model_answer)
    validate_citation_integrity(model_answer, evidence_items)


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: set[str] = set()
    for value in values:
        if value in seen:
            dups.add(value)
        seen.add(value)
    return sorted(dups)
