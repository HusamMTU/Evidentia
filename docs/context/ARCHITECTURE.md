# Architecture Overview

This system implements a **multi-document multimodal grounded QA engine**.

Multi-document support is **default behavior**, not an extension.

---

# High-Level Flow

## Ingestion Path

1. Raw documents → `documents-raw/`
2. Bedrock Knowledge Base ingestion
3. Advanced parsing extracts visuals → `documents-assets/`
4. Text + assets embedded → S3 Vectors

---

## Query Path

1. User query → API
2. KB Retrieve (multi-document)
3. Evidence Builder (merge + rerank)
4. Claude Vision invocation
5. JSON answer + evidence returned

---

# Storage Layer

## Raw Documents

S3: `documents-raw/{doc_id}/source.pdf`

## Extracted Assets

S3: `documents-assets/{doc_id}/{asset_id}.png`

---

# Knowledge Base Layer

* Multimodal KB over unstructured docs
* Advanced parsing enabled
* Vector store: S3 Vectors
* Metadata kept minimal but joinable

---

# Retrieval Strategy

## Default Behavior

* Retrieve across all documents.
* Do not pre-filter by `doc_id`.

## Scoped Queries

If query includes:

* Explicit document identifier
* UI document selection

Then filter by `doc_id`.

---

# Evidence Builder

## Responsibilities

* Merge multi-pass retrieval results
* Group by `(doc_id, asset_id)` or `(doc_id, chunk_id)`
* Limit per-document dominance
* Preserve cross-document diversity

## Per-Document Caps (MVP)

* Max 3 text snippets per doc
* Max 2 visuals per doc
* Max total visuals: 3

---

# Bundle Types

1. Text-only
2. Visual-led
3. Table-led
4. Cross-document comparison

Bundles may contain multiple `doc_id`s.

---

# Reranking Signals

* Rank fusion
* Modality match
* Explicit numeric reference
* Evidence density
* Cross-document support consistency

---

# Claude Invocation Layer

Input:

* Question
* Evidence list (text + images)

Instructions:

* Only use evidence
* Cite evidence IDs
* Output strict JSON

Validation:

* Reject non-JSON responses
* Validate citation references exist

---

# Citation Model

Each evidence item includes:

For text:

* `doc_id`
* `chunk_id`
* `page`
* snippet

For visuals:

* `doc_id`
* `asset_id`
* `asset_s3_key`
* caption (if present)
* presigned URL

---

# Security Model

* KB role: read raw docs, write assets, write vectors
* API role: retrieve from KB, read asset bucket for presigning, invoke Claude
* Presigned URLs expire within short window

---

# Observability

Track:

* Retrieval coverage per doc
* Number of docs contributing to answer
* Evidence bundle size
* Citation precision errors
* Insufficient evidence responses

---

# Multi-Document First-Class Requirements

The system must:

* Aggregate evidence across documents.
* Support cross-document comparison questions.
* Cite document identifiers explicitly.
* Prevent single-document dominance unless query explicitly scoped.
* Allow balanced synthesis from heterogeneous sources.

No architectural change should be required to support cross-document QA.

---

If you want next-level refinement, I can now:

* Add a formal **System Invariants** section (very useful for guiding autonomous coding agents).
* Or create a **docs/context/DEVELOPMENT_PLAN.md** with phased milestones aligned to this architecture.
