# Chikku Robotics — Knowledge Base Export

Vendor-neutral RAG payload generated from `data/Chikku-conpany-data/`.
Every record is a ready-to-upload chunk: stable id, embedding text, and full metadata.

**All 24 source files are indexed** — 8 JSON, 8 PDF, 8 internal markdown docs — into
559 chunks. Coverage is verified: `python src/audit_chikku_coverage.py` checks every
JSON leaf value and every non-empty PDF/markdown line against the store and reports
99.97% (the single exception is one 1217-character SRS table row, longer than the
embedding model's context, which is stored split across two overlapping chunks).

Regenerate with:

```bash
python src/ingest_chikku.py --include-docs --reset          # index + export
python src/ingest_chikku.py --include-docs --export-only    # export only
python src/ingest_chikku.py --include-docs --export-only --no-embeddings
```

## Contents

| File | What it is |
|---|---|
| `chikku_kb.jsonl` | **Canonical.** All 559 chunks, one JSON record per line |
| `chikku_kb.json` | Same records as a single JSON array |
| `chikku_kb.csv` | Flat table, metadata as columns — for tools that only take CSV |
| `chikku_kb.embeddings.jsonl` | Records **plus** 1024-d vectors — upload without an embedding model |
| `chikku_kb.customer.jsonl` | Public-facing subset — JSON + PDF (330 chunks) |
| `chikku_kb.internal.jsonl` | Internal engineering docs (229 chunks) |
| `by_doc_type/*.jsonl` | One file per `doc_type` — load only FAQ, only products, etc. |
| `manifest.json` | Counts, schema, embedding model, chunking parameters |

## Record shape

```json
{
  "id": "solution:agriculture:agriculture-agritech",
  "text": "Agriculture & Agritech\nPrecision agriculture powered by robotics and AI ...",
  "metadata": {
    "doc_type": "solution",
    "category": "agriculture",
    "category_title": "Agriculture & Agritech",
    "title": "Agriculture & Agritech",
    "entity": "",
    "audience": "customer",
    "source_file": "solutions.json",
    "keywords": "Agriculture & Agritech | Crop Monitoring | Autonomous Weeding & Spraying",
    "company": "Chikku Robotics",
    "char_len": 219,
    "part_index": 0,
    "part_total": 1
  }
}
```

## Metadata fields

| Field | Meaning |
|---|---|
| `doc_type` | `identity`, `company`, `partnership`, `product`, `service`, `solution`, `technology`, `faq`, `pdfreport`, `techdoc` |
| `category` | Section key inside the source file (`healthcare`, `safety_systems`, `training`, …) |
| `category_title` | Human-readable section title |
| `title` | Chunk title |
| `entity` | Named product / partner / person / program; empty when not applicable |
| `audience` | `customer` (public-facing) or `internal` (engineering docs) |
| `source_file` | Originating file inside `data/Chikku-conpany-data` |
| `keywords` | Pipe-separated search aids |
| `company` | Constant `Chikku Robotics` |
| `source_format` | `json` \| `pdf` \| `markdown` — how the chunk was extracted |
| `char_len` | Length of the chunk text |
| `part_index` / `part_total` | Set when a long chunk was split across parts |

All metadata values are scalars — lists are pipe-joined, because Chroma rejects
list-valued metadata. Split on `" | "` if your store supports arrays.

## Chunk counts

| doc_type | count | from |
|---|---|---|
| techdoc | 229 | `Chikku_docs/*.md` (internal) |
| pdfreport | 197 | `*.pdf` |
| faq | 33 | `faq.json` |
| service | 26 | `services.json` |
| solution | 25 | `solutions.json` |
| technology | 25 | `technologies.json` |
| product | 8 | `products.json` |
| company | 7 | `company_overview.json` |
| identity | 5 | `identity.json` |
| partnership | 4 | `partnerships.json` |
| **total** | **559** | 24 files |

By source format: json 133 · pdf 197 · markdown 229
By audience: customer 330 · internal 229

## Uploading

### ChromaDB (helper script included)

```bash
# uses the shipped vectors — no Ollama required
python src/load_chikku_export.py

# customer-facing subset only
python src/load_chikku_export.py \
  --input data/processed/chikku_kb/chikku_kb.customer.jsonl --embed

# re-embed from text instead of reusing stored vectors
python src/load_chikku_export.py --embed
```

### Any other vector store

```python
import json

records = [json.loads(l) for l in open("chikku_kb.embeddings.jsonl")]

ids   = [r["id"] for r in records]
texts = [r["text"] for r in records]
metas = [r["metadata"] for r in records]
vecs  = [r["embedding"] for r in records]
```

Vectors are `mxbai-embed-large`, 1024-d, intended for **cosine** distance. Reuse
them only if your query side embeds with the same model — otherwise drop the
`embedding` field and re-embed `text` with your own model.

## Notes

- Chunk ids are deterministic, so re-uploading **upserts** rather than duplicating.
- Filter `audience == "customer"` for the support bot; internal technical docs
  stay indexed but never surface in customer answers.
- Chunks are capped at 1100 chars with 120-char overlap — sized for the
  512-token context of `mxbai-embed-large`. Raise `MAX_CHUNK_CHARS` in
  `src/ingest_chikku.py` if you move to a longer-context embedding model.
- Oversized sections split on line boundaries, so a table row or bullet is never
  cut in half. Only a single line longer than the window is hard-wrapped.
- The PDFs restate most of the JSON content but also carry summary tables, ROI
  sections and brand details the JSON lacks, so they are indexed in full. Answer-time
  near-duplicate suppression in `src/company_rag.py` stops a fact appearing twice in
  one context window.
