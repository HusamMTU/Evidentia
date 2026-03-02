# Provenance Manifest

This module provides the canonical `doc_id <-> source_uri` join layer used during retrieval normalization.

## Why

Bedrock-managed extracted asset keys may not include `doc_id`, so `doc_id` must be resolved from ingestion/retrieval provenance metadata.

## Components

- `manifest_store.py`: DynamoDB-backed manifest persistence
- `retrieval_normalizer.py`: candidate normalization with manifest-backed `doc_id` resolution
- `errors.py`: provenance resolution errors

## DynamoDB Contract

- Table PK: `doc_id` (String)
- GSI: `source_uri-index` on `source_uri` (String)

## CLI Utility

Use `scripts/register_ingestion_manifest.py` to upsert mappings:

```bash
python3 scripts/register_ingestion_manifest.py \
  --doc-id smoke-20260302T120000Z \
  --source-uri s3://my-raw-bucket/documents-raw/smoke-20260302T120000Z/source.pdf \
  --table-name EvidentiaFoundation-dev-ingestion-manifest \
  --region us-east-1
```
