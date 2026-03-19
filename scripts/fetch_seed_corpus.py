#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "datasets" / "seed_corpus" / "manifest.csv"
SOURCE_ROOT = (REPO_ROOT / "datasets" / "seed_corpus" / "source").resolve()
REQUIRED_COLUMNS = {
    "doc_id",
    "source_path",
    "source_url",
    "sha256",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch local seed corpus documents and verify them against manifest checksums."
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to the seed corpus manifest CSV.",
    )
    parser.add_argument(
        "--doc-id",
        action="append",
        dest="doc_ids",
        help="Fetch or verify only the specified doc_id values. May be repeated.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files even when an existing local file already matches the checksum.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-request timeout in seconds.",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise SystemExit(f"Manifest is missing required columns: {missing_list}")
        rows = [dict(row) for row in reader]
    return rows


def validate_source_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(f"Invalid source_url: {source_url!r}")

    if parsed.netloc != "arxiv.org":
        return

    if not (parsed.path.startswith("/abs/") or parsed.path.startswith("/pdf/")):
        return

    tail = parsed.path.rsplit("/", 1)[-1]
    if tail.endswith(".pdf"):
        tail = tail[:-4]
    if not re.search(r"v[0-9]+$", tail):
        raise SystemExit(
            "arXiv source_url values must pin an explicit revision such as "
            "'https://arxiv.org/pdf/1706.03762v7.pdf'."
        )


def resolve_source_path(raw_source_path: str) -> Path:
    candidate = (REPO_ROOT / raw_source_path.strip()).resolve()
    try:
        candidate.relative_to(SOURCE_ROOT)
    except ValueError as exc:
        raise SystemExit(
            f"source_path must stay under {SOURCE_ROOT.relative_to(REPO_ROOT)}, got: {raw_source_path!r}"
        ) from exc

    if candidate == SOURCE_ROOT or not candidate.name:
        raise SystemExit(f"source_path must target a file inside source/, got: {raw_source_path!r}")

    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_to_temp(url: str, destination_dir: Path, timeout: int) -> tuple[Path, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "evidentia-seed-corpus-fetcher/1.0"},
    )
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=destination_dir,
            prefix="seed-corpus-",
            suffix=".part",
        ) as temp_handle:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                temp_handle.write(chunk)
                digest.update(chunk)
            temp_path = Path(temp_handle.name)
    return temp_path, digest.hexdigest()


def fetch_row(row: dict[str, str], *, force: bool, timeout: int) -> str:
    doc_id = row["doc_id"].strip()
    source_path = resolve_source_path(row["source_path"])
    source_url = row["source_url"].strip()
    expected_sha = row["sha256"].strip().lower()

    validate_source_url(source_url)
    if not SHA256_RE.fullmatch(expected_sha):
        raise SystemExit(f"Invalid sha256 for {doc_id}: {expected_sha!r}")

    source_path.parent.mkdir(parents=True, exist_ok=True)

    if source_path.exists() and not force:
        current_sha = sha256_file(source_path)
        if current_sha == expected_sha:
            print(f"ok       {doc_id} {source_path.relative_to(REPO_ROOT)}")
            return "verified"
        print(
            f"refresh  {doc_id} checksum mismatch for existing file; re-downloading",
            file=sys.stderr,
        )

    temp_path, actual_sha = download_to_temp(source_url, source_path.parent, timeout)
    try:
        if actual_sha != expected_sha:
            raise SystemExit(
                f"Checksum mismatch for {doc_id}: expected {expected_sha}, got {actual_sha}"
            )
        shutil.move(str(temp_path), str(source_path))
    finally:
        if temp_path.exists():
            temp_path.unlink()

    print(f"fetched  {doc_id} {source_path.relative_to(REPO_ROOT)}")
    return "downloaded"


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    rows = load_manifest(manifest_path)

    requested_ids = {value.strip() for value in (args.doc_ids or []) if value.strip()}
    if requested_ids:
        rows = [row for row in rows if row["doc_id"].strip() in requested_ids]
        missing_ids = sorted(requested_ids - {row["doc_id"].strip() for row in rows})
        if missing_ids:
            raise SystemExit(f"Unknown doc_id values: {', '.join(missing_ids)}")

    downloaded = 0
    verified = 0
    for row in rows:
        result = fetch_row(row, force=args.force, timeout=args.timeout)
        if result == "downloaded":
            downloaded += 1
        else:
            verified += 1

    print(
        f"Done. downloaded={downloaded} verified={verified} total={len(rows)} manifest={manifest_path}"
    )


if __name__ == "__main__":
    main()
