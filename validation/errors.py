from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = "$"
    details: Any = None


class ContractValidationError(ValueError):
    def __init__(self, schema_name: str, issues: list[ValidationIssue]):
        self.schema_name = schema_name
        self.issues = issues
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        first = self.issues[0] if self.issues else None
        if not first:
            return f"{self.schema_name} validation failed"
        return f"{self.schema_name} validation failed at {first.path}: {first.message}"


class CitationIntegrityError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        first = self.issues[0] if self.issues else None
        if not first:
            return "citation integrity validation failed"
        return f"citation integrity validation failed at {first.path}: {first.message}"
