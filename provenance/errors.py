from __future__ import annotations


class ProvenanceResolutionError(ValueError):
    """Raised when candidate provenance cannot be resolved to a stable doc_id."""

