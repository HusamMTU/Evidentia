# System Overview

Build a **Multimodal Grounded Document Intelligence System** that answers questions using:

* Text
* Tables
* Figures
* Charts
* Diagrams
* Embedded images

The system supports **multi-document reasoning by default** and produces answers with **explicit, structured citations** to all supporting evidence.

---

# Core Guarantees

1. **Evidence-First**
   The model never answers without retrieved evidence.

2. **Multi-Document by Default**
   Retrieval and reasoning operate across all indexed documents unless explicitly scoped.

3. **Modality-Agnostic**
   Text and visual elements are treated as equal evidence sources.

4. **Traceable Outputs**
   Every non-trivial claim must cite one or more evidence items with document identifiers.

5. **Deterministic Retrieval Layer**
   Retrieval and evidence assembly are deterministic and independent of the LLM.

---

# Supported Document Types

System must support heterogeneous documents:

* Research papers
* Technical manuals
* Contracts
* Inspection reports
* Compliance documents
* Enterprise reports
* Slide decks (PDF)
* Mixed-media documents

The system must not assume:

* Academic structure
* Fixed section names
* Presence of “Figure 1” patterns
* Single-document scope

---

# Knowledge Layer

* Amazon Bedrock Knowledge Base
* Vector store: Amazon S3 Vectors
* Advanced parsing enabled to extract:

  * Text chunks
  * Tables
  * Figures
  * Charts
  * Embedded images

---

# Metadata Schema (Generic & Cross-Doc Ready)

Each indexed item must include:

| Field          | Description                                             |
| -------------- | ------------------------------------------------------- |
| `doc_id`       | Unique document identifier                              |
| `doc_type`     | Document category                                       |
| `asset_type`   | text_chunk, caption, figure_image, table_image, diagram |
| `asset_id`     | Unique asset identifier                                 |
| `asset_s3_key` | S3 path (visuals only)                                  |
| `page`         | Optional page number                                    |
| `section`      | Optional heading                                        |
| `chunk_id`     | KB chunk identifier                                     |

Constraints:

* ≤1KB metadata
* ≤35 metadata keys

---

# Query Processing Pipeline

## Step 1 — Retrieval (Multi-Document Default)

* Perform broad semantic retrieval across all documents.
* Perform optional targeted retrieval if modality cues detected.
* Do not restrict by `doc_id` unless user explicitly scopes the query.

---

## Step 2 — Evidence Bundle Construction

Construct a **cross-document evidence bundle**:

### Text Snippets

* 2–8 high-relevance chunks.
* Allow multiple `doc_id`s.
* Cap per-document contributions to prevent dominance.

### Visual Assets

* 0–3 figures/tables/diagrams.
* Include captions where available.
* May originate from different documents.

### Deduplication

* Deduplicate by `(doc_id, asset_id)` or `(doc_id, chunk_id)`.
* Maintain diversity across documents when the query implies comparison or aggregation.

---

## Step 3 — Reranking

Score candidate bundles using:

* Reciprocal Rank Fusion
* Modality alignment
* Explicit references
* Evidence density
* Cross-document agreement boost (if multiple documents support same claim)

Select top bundle.

---

# Answer Generation (Claude Vision)

Claude must:

* Use only provided evidence.
* Cite each meaningful claim.
* Indicate document identifiers in citations.
* State when evidence is insufficient.

---

# Required Output Format

```json
{
  "answer": "...",
  "citations": [
    {
      "statement": "...",
      "evidence_ids": ["E2","E5"]
    }
  ],
  "used_evidence_ids": ["E1","E2","E5"],
  "limitations": ["..."]
}
```

Each evidence ID must map to:

* `doc_id`
* `asset_type`
* `asset_id` or `chunk_id`
* Optional `page`

---

# Evaluation Strategy

Test across:

* Text-only questions
* Visual interpretation
* Table reasoning
* Cross-document comparison
* Contradiction detection
* Citation correctness

Metrics:

* Evidence Recall@K
* Citation precision
* Cross-document synthesis accuracy
* Hallucination rate

---

# Non-Goals (MVP)

* Full document knowledge graph
* Advanced contradiction detection
* Automated table normalization
* Fine-tuned rerank model

---

# Long-Term Evolution

* Cross-document reasoning improvements
* Structured table extraction
* Confidence scoring
* Enterprise audit logs
* Domain adapters