# SaigonBot — Chatbot API

A RAG-based conversational AI chatbot for Saigon Indian Restaurant. Uses ChromaDB for vector search, Ollama for local embeddings, and supports **Ollama or OpenAI** for response generation — switchable via a single `.env` variable.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Data Ingestion](#data-ingestion)
- [Running the API](#running-the-api)
- [API Endpoints](#api-endpoints)
- [Switching LLM Provider](#switching-llm-provider)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)

---

## Prerequisites

1. **Python 3.10+**
   ```bash
   python3 --version
   ```

2. **pip** (comes with Python — no extra install needed)

3. **Ollama** (required for embeddings regardless of LLM provider)
   ```bash
   # Install
   curl -fsSL https://ollama.ai/install.sh | sh

   # Pull embedding model (always required)
   ollama pull mxbai-embed-large

   # Pull LLM model (only if using LLM_PROVIDER=ollama)
   ollama pull deepseek-r1:latest
   ```

4. **OpenAI API Key** — only needed if using `LLM_PROVIDER=openai`

---

## Installation

```bash
# 1. Navigate to project
cd saigonbot

# 2. (Optional) Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Configuration

Copy the template and edit:
```bash
cp config.env .env
```

Key settings in `.env`:

```env
# ── Tenant ────────────────────────────────────
TENANT=saigon                # saigon | chikku

# ── LLM Provider ──────────────────────────────
LLM_PROVIDER=ollama          # ollama | openai

# ── Ollama (embeddings always use Ollama) ─────
EMBEDDING_MODEL=mxbai-embed-large
LLM_MODEL=deepseek-r1:latest

# ── OpenAI (only when LLM_PROVIDER=openai) ────
OPENAI_API_KEY=sk-...
OPENAI_LLM_MODEL=gpt-4o-mini

# ── Retrieval ─────────────────────────────────
TOP_K=7
RERANK_K=12
USE_RERANKING=true

# ── API Server ────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
API_TIMEOUT=60
ALLOWED_ORIGINS=*
```

---

## Tenants

One codebase serves two assistants. `TENANT` in `.env` selects which:

| TENANT | Assistant | Vector store | Collection | System prompt |
|---|---|---|---|---|
| `saigon` | Saigon Indian Restaurant host | `chroma_db/` | `hotel_saigon_menu` | `data/system_prompt.txt` |
| `chikku` | Chikku Robotics support agent | `chikku_db/` | `chikku_kb` | `data/chikku_system_prompt.txt` |

The tenant decides the vector store, system prompt, intent taxonomy, retrieval
filters and response-validator rules — see `src/tenant_config.py`. Switching is a
restart, not a code change:

```bash
TENANT=chikku python run_api.py
```

Individual fields can be overridden with `CHROMA_DIR`, `COLLECTION_NAME` and
`SYSTEM_PROMPT_FILE` if a tenant needs to point somewhere else.

**How the two paths differ**

- `saigon` (`domain=restaurant`) runs the menu pipeline: dietary/protein filtering,
  dish-name extraction for orders, speech-to-text normalisation tuned to Indian food,
  and the restaurant knowledge base for hours/location/policies.
- `chikku` (`domain=company`) runs `src/company_rag.py`: a B2B support taxonomy
  (product, solution, service, technology, partnership, sales, support, company info),
  metadata-scoped retrieval by `doc_type`, and an `audience` gate so internal
  engineering docs are only readable by support-intent questions.

The response validator is tenant-aware too. Its default rules ban phrases like
"machine learning" and "artificial intelligence" as persona leaks — correct for a
restaurant host, wrong for a robotics company. `validator_allow` in the tenant config
exempts those terms for `chikku` while still blocking real persona leaks
("as an AI language model").

---

## Data Ingestion

### Restaurant (TENANT=saigon)

Run once (or whenever the menu changes) to build the ChromaDB vector index:

```bash
python src/ingestion.py
```

> Embeddings always use Ollama (`mxbai-embed-large`). Switching to OpenAI for generation does **not** require re-ingestion.

To also index restaurant "about" content:
```bash
python src/ingest_about.py
```

### Chikku Robotics (TENANT=chikku)

```bash
python src/ingest_chikku.py --include-docs --reset
```

Indexes **all 24 files** in `data/Chikku-conpany-data/` — 8 JSON, 8 PDF (via
`pdfplumber`), and 8 internal markdown docs — into `chikku_db/chikku_kb` (559 chunks),
and writes a portable export to `data/processed/chikku_kb/` (JSONL, CSV, per-doc-type
splits, and records with pre-computed vectors). See `data/processed/chikku_kb/README.md`.

Verify nothing was lost in chunking:

```bash
python src/audit_chikku_coverage.py            # per-file coverage table
python src/audit_chikku_coverage.py --verbose  # list every missing fragment
```

It checks every JSON leaf value and every non-empty PDF/markdown line against the
indexed text and fails loudly on gaps — a chunk count alone cannot catch a chunker
bug that silently drops a section.

To upload an existing export without re-embedding:

```bash
python src/load_chikku_export.py
```

---

## Running the API

```bash
python run_api.py
```

Or directly with uvicorn:
```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

API is available at `http://localhost:8000`
Interactive docs at `http://localhost:8000/docs`

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/stats` | Collection stats + active models |
| `POST` | `/query` | One-shot menu query |
| `POST` | `/chat/text` | Conversational query (with history) |
| `POST` | `/chat/stream` | Streaming response (SSE) |
| `POST` | `/conversation/new` | Create a new conversation session |
| `GET` | `/conversation/{id}/history` | Get conversation history |
| `DELETE` | `/conversation/{id}` | Clear conversation |

### Examples

```bash
# Health check
curl http://localhost:8000/health

# Query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "vegetarian options"}'

# Streaming
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "what breakfast items do you have"}' \
  --no-buffer
```

---

## Switching LLM Provider

Embeddings are always handled by Ollama (keeps the ChromaDB index stable).
Only the **generation** step switches.

### Use OpenAI
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
OPENAI_LLM_MODEL=gpt-4o-mini    # or gpt-4o, gpt-3.5-turbo
```

### Use Ollama (local)
```env
LLM_PROVIDER=ollama
LLM_MODEL=deepseek-r1:latest    # any model you've pulled
```

Restart the API after changing `.env`. No re-ingestion needed when switching providers.

---

## Troubleshooting

**Ollama connection error**
```bash
ollama serve        # start Ollama
ollama list         # verify models are pulled
```

**ChromaDB collection not found**
```bash
python src/ingestion.py
```

**Port already in use**
```bash
# Change port in .env
API_PORT=8001
# Or kill the process
lsof -ti:8000 | xargs kill -9
```

**Slow responses**
- Reduce `TOP_K` / `RERANK_K`
- Set `USE_RERANKING=false`
- Switch to `LLM_PROVIDER=openai` for faster cloud inference

**OpenAI key error**
- Ensure `OPENAI_API_KEY` is set in `.env`
- Verify key is valid at platform.openai.com

---

## Project Structure

```
saigonbot/
├── src/
│   ├── api.py                  # FastAPI server
│   ├── rag.py                  # RAG pipeline
│   ├── llm_provider.py         # Ollama / OpenAI abstraction layer
│   ├── ingestion.py            # Menu data ingestion
│   ├── ingest_about.py         # Restaurant info ingestion
│   ├── intent_classifier.py    # 45+ intent patterns
│   ├── response_validator.py   # Persona enforcement
│   ├── response_templates.py   # Deterministic responses
│   ├── knowledge_base.py       # Structured restaurant info
│   ├── chat.py                 # Conversation session manager
│   ├── database.py             # SQLite conversation storage
│   └── extract_menu.py         # PDF menu extraction
├── data/
│   ├── processed/
│   │   └── menu_items.json     # 202 menu items
│   ├── knowledge_base/         # Restaurant info JSON files
│   └── saigon.pdf              # Source menu PDF
├── chroma_db/                  # Vector database (generated)
├── conversations.db            # Conversation history (generated)
├── requirements.txt            # pip dependencies
├── config.env                  # Configuration template
├── .env                        # Active configuration (git-ignored)
├── run_api.py                  # API startup script
└── README.md
```

---

**Version:** 2.0.0 | **Updated:** 2026-03-18
