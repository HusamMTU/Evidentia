from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_DIR = _REPO_ROOT / "schemas"


def _schema_path(name: str) -> Path:
    filename = f"{name}.schema.json" if not name.endswith(".schema.json") else name
    return _SCHEMA_DIR / filename


@lru_cache(maxsize=16)
def load_schema(name: str) -> dict[str, Any]:
    path = _schema_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def schema_dir() -> Path:
    return _SCHEMA_DIR


def repo_root() -> Path:
    return _REPO_ROOT
