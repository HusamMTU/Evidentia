# Verification Reports

Place small committed verification artifacts here when they help document the
state of the seed corpus.

Generated runtime reports and batch logs should go under `generated/`.
That subdirectory is ignored by Git so routine ingestion runs do not create repo
noise by default.

Good fits:

- ingestion summary CSVs or JSON files
- notes about missing metadata or failed visual extraction
- one-off verification outputs that are useful during Phase 2

Avoid committing bulky exports or anything that can be reproduced cheaply from
the live environment.
