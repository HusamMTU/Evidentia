# Seed Ingestion Validation

Validation date: March 19, 2026

This note records the live AWS verification pass for the initial 10-paper seed
corpus. It is the committed summary of the live runs; detailed runtime logs were
written under `datasets/seed_corpus/reports/generated/` and then cleaned up.

## Outcome

- The first 5 seed documents were indexed successfully by Bedrock ingestion job
  `2YBRBPCGF3`.
- The next 5 seed documents were indexed successfully by Bedrock ingestion job
  `DE1NSQS1TL`.
- A later rerun for 4 of the first-batch documents (`KIMBDI4FOZ`) completed as a
  no-op with `new=0`; that was expected because those documents had already been
  indexed by the earlier shared ingestion job.
- All 10 rows in `datasets/seed_corpus/manifest.csv` are now marked
  `ingestion_status=verified`.

## Job Summary

### Job `2YBRBPCGF3`

- Date: March 19, 2026
- Status: `COMPLETE`
- Stats: `scanned=5`, `new=5`, `modified=0`, `failed=0`
- Covered docs:
  - `paper-attention-2017`
  - `paper-bert-2018`
  - `paper-gpt3-2020`
  - `paper-scaling-laws-2020`
  - `paper-rag-2020`

### Job `DE1NSQS1TL`

- Date: March 19, 2026
- Status: `COMPLETE`
- Stats: `scanned=10`, `new=5`, `modified=0`, `failed=0`
- Covered docs:
  - `paper-instructgpt-2022`
  - `paper-cot-2022`
  - `paper-chinchilla-2022`
  - `paper-palm-2022`
  - `paper-llama-2023`

## Notes

- The shared Bedrock data source means one ingestion job can index multiple
  staged documents. The batch ingestion script was updated to reflect that model
  instead of treating each selected document as an isolated smoke run.
- During validation, both the legacy doc-scoped assets prefixes and the
  Bedrock-managed assets prefix reported zero extracted assets. That may be
  acceptable for text-only PDFs, but visual asset extraction is still not
  evidenced by this seed set alone.
