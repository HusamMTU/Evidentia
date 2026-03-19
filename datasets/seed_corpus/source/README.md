# Source Documents

This directory is for locally fetched source documents referenced by
`../manifest.csv`.

The intended workflow is:

1. keep metadata, URLs, and checksums in `../manifest.csv`
2. fetch local copies with `python3 scripts/fetch_seed_corpus.py`
3. let Git ignore the fetched PDFs

This keeps the repository reproducible without turning Git into a dataset store.

If you already fetched documents here locally, they should match the `sha256`
values recorded in the manifest. If they do not, re-run the fetch script and let
it refresh the file from the canonical `source_url`.
