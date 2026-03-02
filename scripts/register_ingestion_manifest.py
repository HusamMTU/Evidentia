#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from provenance import IngestionManifestRecord, SQLiteIngestionManifestStore, make_s3_uri  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persist doc_id <-> source object URI mapping in local ingestion manifest store."
    )
    parser.add_argument("--doc-id", required=True, help="Stable document identifier")
    parser.add_argument(
        "--source-uri",
        help="Source object URI in s3://bucket/key form (preferred)",
    )
    parser.add_argument("--source-bucket", help="Source object bucket (alternative to --source-uri)")
    parser.add_argument("--source-key", help="Source object key (alternative to --source-uri)")
    parser.add_argument(
        "--db-path",
        default=".evidentia/ingestion_manifest.db",
        help="SQLite DB path for manifest store",
    )
    parser.add_argument("--status", default="registered", help="Ingestion status label")
    parser.add_argument("--kb-id", help="Knowledge base ID for provenance context")
    parser.add_argument("--data-source-id", help="Knowledge base data source ID for provenance context")
    parser.add_argument("--ingestion-job-id", help="Bedrock ingestion job ID")
    parser.add_argument("--source-etag", help="Raw object ETag")
    parser.add_argument("--source-version-id", help="Raw object version ID")
    return parser.parse_args()


def resolve_source_uri(args: argparse.Namespace) -> str:
    if args.source_uri:
        return args.source_uri
    if args.source_bucket and args.source_key:
        return make_s3_uri(args.source_bucket, args.source_key)
    raise SystemExit("Either --source-uri or both --source-bucket/--source-key are required.")


def main() -> None:
    args = parse_args()
    source_uri = resolve_source_uri(args)

    store = SQLiteIngestionManifestStore(args.db_path)
    record = IngestionManifestRecord.from_doc_and_uri(
        doc_id=args.doc_id,
        source_uri=source_uri,
        status=args.status,
        kb_id=args.kb_id,
        data_source_id=args.data_source_id,
        ingestion_job_id=args.ingestion_job_id,
        source_etag=args.source_etag,
        source_version_id=args.source_version_id,
    )
    saved = store.upsert(record)
    print("Manifest upserted")
    print(f"  doc_id={saved.doc_id}")
    print(f"  source_uri={saved.source_uri}")
    print(f"  status={saved.status}")
    if saved.kb_id:
        print(f"  kb_id={saved.kb_id}")
    if saved.data_source_id:
        print(f"  data_source_id={saved.data_source_id}")
    if saved.ingestion_job_id:
        print(f"  ingestion_job_id={saved.ingestion_job_id}")
    print(f"  db_path={args.db_path}")


if __name__ == "__main__":
    main()

