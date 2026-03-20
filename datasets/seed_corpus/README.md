# Seed Corpus

This directory is the repository-facing home for the Phase 2 seed corpus.

Use it to track what we intend to ingest, why each document is in scope, and
what ingestion/verification state it is in. Keep this directory small,
reviewable, and safe to commit.

## Layout

- `manifest.csv`: canonical seed corpus inventory tracked in Git
- `source/`: local fetched source documents, intentionally not tracked in Git
- `reports/`: small committed ingestion verification artifacts

## Manifest Contract

`manifest.csv` is the source of truth for the curated seed set. Each row should
represent one intended document and include:

- `doc_id`: stable document identifier used across raw storage and retrieval
- `doc_type`: coarse content class such as `report`, `slide_deck`, or `manual`
- `theme_tags`: pipe-delimited topical tags to help curate cross-document QA
- `modality_profile`: short label such as `text-heavy`, `table-heavy`, `figure-heavy`, or `mixed-media`
- `source_path`: repo-relative local destination for fetched documents
- `source_url`: canonical upstream URL used to fetch the document; use version-pinned URLs for revisioned sources such as arXiv
- `sha256`: expected SHA-256 checksum for the fetched file
- `license_note`: redistribution status or provenance constraint
- `ingestion_status`: lifecycle marker such as `planned`, `uploaded`, `ingested`, or `verified`
- `notes`: freeform operator notes about why the document is included

### Status Semantics

- `planned`: document is curated in the manifest but has not been staged for KB ingestion yet
- `uploaded`: source document has been staged into the raw bucket and mapped in the ingestion manifest
- `ingested`: lower-level ingestion lifecycle label used by the ingestion manifest store after a successful KB ingestion job
- `verified`: repo-facing/operator-facing status in `manifest.csv` meaning we have confirmed the document was included in a successful Bedrock knowledge base ingestion run

`verified` should be read narrowly. It means the document was successfully
ingested/indexed by the Bedrock KB for the validated batch. It does not, by
itself, prove that visual assets were extracted, retrieval quality is good, or
the later answer/provenance path has been fully validated end to end.

## What To Commit

Commit:

- the manifest
- curation notes
- fetch/verification scripts
- small verification summaries that help us reason about ingestion quality

Do not commit:

- fetched source documents under `source/`
- licensed or sensitive PDFs
- large raw corpora
- bucket exports or generated assets from Bedrock
- machine-specific scratch files

## Fetching and Verification

Use the fetch script to materialize local copies from the manifest:

```bash
python3 scripts/fetch_seed_corpus.py
```

The script downloads each document to the `source_path` listed in the manifest
and verifies the resulting file against the stored `sha256` checksum. For arXiv
sources, the manifest should use explicit revisioned URLs such as
`https://arxiv.org/pdf/1706.03762v7.pdf` instead of floating latest-version
links.

## Batch Ingestion

Use the batch ingestion wrapper to stage selected manifest rows, run one shared
Bedrock ingestion job, and evaluate the batch as a whole:

```bash
./.venv/bin/python scripts/run_seed_corpus_batch_ingestion.py --limit 5 --region us-east-1
```

By default it selects rows with `ingestion_status=planned`, uploads each source
document into the raw bucket, writes manifest mappings, starts one ingestion job
for the shared data source, and then expects the completed job to index at least
as many documents as were staged. It updates `manifest.csv` to `verified` or
`failed` and writes a JSONL report plus a batch log under
`datasets/seed_corpus/reports/generated/`.

The upload path preserves the original source filename extension, so the flow is
not limited to PDFs even though the current seed set happens to be PDF-heavy.

Checksums matter because they give us a stable fingerprint of the exact bytes we
expect. If an upstream PDF changes, a mirror serves a different file, or a
download is truncated or corrupted, the checksum will not match and the script
will fail instead of silently accepting the wrong document.

## Suggested Workflow

1. Add candidate rows to `manifest.csv` with `ingestion_status=planned`.
2. Record a `source_url` and expected `sha256` for each row.
3. Run `python3 scripts/fetch_seed_corpus.py` to materialize local copies into `source/`.
4. Run `./.venv/bin/python scripts/run_seed_corpus_batch_ingestion.py` to stage selected documents and execute one shared ingestion job for the batch.
5. Update or curate `ingestion_status` and notes after reviewing the generated report.
6. Save concise verification artifacts in `reports/` when they are useful for debugging or review.
