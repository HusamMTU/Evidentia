# S3 Vectors Inspector (Scaffold)

A small read-only web UI for browsing S3 Vectors index contents, inspired by Attu-style workflows.

## What It Does

- Loads active S3 Vectors config from env (`AWS_REGION`, `EVIDENTIA_VECTORS_BUCKET`, `BEDROCK_S3_VECTORS_INDEX_NAME`) or query params.
- Discovers vector buckets and indexes from the selected region.
- Lists vectors with metadata summaries.
- Highlights whether vectors belong to the current Bedrock KB data source or a historical one.
- Inspects a selected vector summary, parsed Bedrock metadata, raw payload, and current index dimension.
- Shows data source/modality distribution summaries.
- Runs similarity search by selected vector key (`QueryVectors` using that key's embedding).

## Quick Start

From repo root:

```bash
set -a; source .env; set +a
.venv/bin/python tools/s3_vectors_inspector/server.py --host 127.0.0.1 --port 8787
```

Then open:

- `http://127.0.0.1:8787`

## Optional Run Helper

```bash
./scripts/run_s3_vectors_inspector.sh --port 8787
```

## Required IAM (Read-Only)

- `s3vectors:ListVectorBuckets`
- `s3vectors:ListIndexes`
- `s3vectors:GetIndex`
- `s3vectors:ListVectors`
- `s3vectors:GetVectors`
- `s3vectors:QueryVectors`

Optional for asset preview extensions:

- `s3:GetObject` on the extracted assets bucket/prefix

## Notes

- This is a scaffold, not a production-hardened admin app.
- It does not mutate vector data.
- Large metadata fields are intentionally summarized in the table view, with raw JSON available in the selection panel.
