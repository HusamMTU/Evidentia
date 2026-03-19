# Seed Corpus

This directory is the repository-facing home for the Phase 2 seed corpus.

Use it to track what we intend to ingest, why each document is in scope, and
what ingestion/verification state it is in. Keep this directory small,
reviewable, and safe to commit.

## Layout

- `manifest.csv`: canonical seed corpus inventory tracked in Git
- `source/`: tiny redistributable sample documents only
- `reports/`: small committed ingestion verification artifacts

## Manifest Contract

`manifest.csv` is the source of truth for the curated seed set. Each row should
represent one intended document and include:

- `doc_id`: stable document identifier used across raw storage and retrieval
- `doc_type`: coarse content class such as `report`, `slide_deck`, or `manual`
- `theme_tags`: pipe-delimited topical tags to help curate cross-document QA
- `modality_profile`: short label such as `text-heavy`, `table-heavy`, `figure-heavy`, or `mixed-media`
- `source_path`: repo-relative path for committed tiny samples, or an external/local path reference for non-committed documents
- `license_note`: redistribution status or provenance constraint
- `ingestion_status`: lifecycle marker such as `planned`, `uploaded`, `ingested`, or `verified`
- `notes`: freeform operator notes about why the document is included

## What To Commit

Commit:

- the manifest
- curation notes
- tiny public or otherwise redistributable sample documents
- small verification summaries that help us reason about ingestion quality

Do not commit:

- licensed or sensitive PDFs
- large raw corpora
- bucket exports or generated assets from Bedrock
- machine-specific scratch files

## Suggested Workflow

1. Add candidate rows to `manifest.csv` with `ingestion_status=planned`.
2. Place only tiny safe-to-redistribute sample files in `source/`.
3. Upload or register the real documents through the ingestion workflow.
4. Update `ingestion_status` as each document moves through upload, ingest, and verification.
5. Save concise verification artifacts in `reports/` when they are useful for debugging or review.
