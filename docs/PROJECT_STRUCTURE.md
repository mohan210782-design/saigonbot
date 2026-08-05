# Project Structure

This document describes the directory layout and the role of every file in the
**Chikku Robotics Voice AI RAG** backend. It is intended to help new developers
orient themselves quickly and to serve as a reference during maintenance.

> Scope: only the **core** project files are listed. Ad-hoc test/scratch scripts
> (`test_api.py`, `test_phase1.py`, `_trace_flow.py`, `_verify_products.py`,
> `simple_test.py`, `temp.html`, etc.) are intentionally omitted — they are not
> part of the runtime system.

---

## 1. Top-Level Layout

```
chikku-robotics-dev/
├── src/                      # Application source code (the backend)
├── data/                     # Knowledge base, system prompt, processed text
├── docs/                     # Project documentation (this file lives here)
├── documents/                # Legacy internal notes / change logs (reference only)
├── chroma_db/                # Generated — ChromaDB vector index (git-ignored)
├── conversations.db          # Generated — SQLite conversation history (git-ignored)
├── config.env                # Configuration TEMPLATE (committed)
├── sample.env                # Minimal sample configuration (committed)
├── .env                      # ACTIVE configuration (git-ignored, holds secrets)
├── requirements.txt          # Python dependencies
├── run_api.py                # API startup entry point
├── setup.sh                  # First-time setup helper script
├── local_to_server.sh        # rsync deploy helper to the production server
└── README.md                 # Quick-start guide (note: still restaurant-flavored)
```

### Generated / runtime artifacts

| Path | Created by | Purpose |
|------|-----------|---------|
| `chroma_db/` | `python src/ingest_robotics.py` | Persistent ChromaDB vector store (collection `chikku_robotics`, cosine metric). |
| `conversations.db` | `api.py` at first request | SQLite database storing conversation sessions and messages. |

Both are **git-ignored** and regenerated locally. Do not commit them.

---

## 2. `src/` — Application Code

All modules live flat under `src/`. `api.py` inserts `src/` onto `sys.path` at
import time, so modules import each other as top-level siblings
(e.g. `from rag import RAGPipeline`).

### 2.1 Entry point & API layer

| File | Role |
|------|------|
| **`api.py`** | FastAPI application. Defines all HTTP endpoints (`/query`, `/chat/text`, `/chat/stream`, `/chat/voice`, `/conversation/*`, `/health`, `/stats`), Pydantic request/response models, CORS, IP-based rate-limiting middleware, and the lazily-initialized `RAGPipeline` singleton. Blocking RAG work is offloaded to a `ThreadPoolExecutor` so the async event loop stays responsive. |
| **`run_api.py`** | Thin launcher. Adds `src/` to `sys.path` and starts Uvicorn with hot-reload on `0.0.0.0:8000`. Run with `python run_api.py`. |

### 2.2 RAG pipeline (the brain)

| File | Role |
|------|------|
| **`rag.py`** | The `RAGPipeline` class — the single source of truth for query processing. Implements intent classification, the 3-layer retrieval stack (FAQ cache → hybrid BM25+Dense+RRF → rerank), query rewrite, KB enrichment, LLM grounding, streaming (`query_stream()`) and non-streaming (`query()`) flows, plus retrieval/embedding/rewrite LRU caches. See [RAG_ARCHITECTURE.md](./RAG_ARCHITECTURE.md). |
| **`llm_provider.py`** | Provider abstraction over generation. `LLM_PROVIDER=ollama` → `OllamaProvider`; `LLM_PROVIDER=openai` → `OpenAIGenerationProvider`. **Embeddings always go through Ollama** (`mxbai-embed-large`) regardless of the generation provider, so the ChromaDB index stays stable when switching. Exposes `embed()`, `chat()`, and `stream_chat()`. |
| **`intent_classifier.py`** | Classifies each user query into an `IntentType` / `IntentCategory`. Embedding-based (cosine against an exemplar library, sharing one embed call with retrieval) with a deterministic **regex override** layer for edge cases (leadership keywords, polite declines, standalone acknowledgments) and a transparent **regex fallback** if the embedding provider is unavailable. |
| **`knowledge_base.py`** | Loads the structured JSON knowledge base from `data/knowledge_base/robotics/` into an in-memory singleton. Provides topic-aware keyword search, FAQ matching (exact / word-overlap / stemmed), section extraction, and lazily-cached FAQ-question embeddings used by the FAQ cache layer. |
| **`response_templates.py`** | Deterministic, hand-written responses (welcome message, identity, conversational greetings/farewells, location/contact/hours fallbacks). Prevents LLM hallucination on conversational and core-identity queries. |
| **`response_validator.py`** | Post-generation quality filter. Strips/flags forbidden phrases (AI disclaimers, "ChatGPT", technical jargon like "retrieved items"), checks length/completeness, and returns a cleaned response + quality score. Enabled via `ENABLE_RESPONSE_VALIDATION`. |

### 2.3 Ingestion

| File | Role |
|------|------|
| **`ingest_robotics.py`** | Builds the ChromaDB `chikku_robotics` collection. Reads every JSON in `data/knowledge_base/robotics/`, splits them into fine-grained chunks (one per FAQ item, product, person, array item, plus section overviews; `featured_products` get up to 4 chunks each — overview/features/benefits/technologies), embeds them with Ollama, and **upserts** into ChromaDB. Safe to re-run. Idempotent by stable document IDs. Run with `python src/ingest_robotics.py`. |

### 2.4 Conversation & persistence

| File | Role |
|------|------|
| **`chat.py`** | `ConversationManager` — session lifecycle on top of the DB. Handles session resume/expiry (30-min inactivity timeout), and exposes `get_history()` in the message-list shape the RAG pipeline expects. A global `conversation_manager` singleton is imported by `api.py`. |
| **`database.py`** | `ConversationDB` — SQLite layer with three tables (`conversations`, `messages`, `user_preferences`) and indexes on `session_id`, `conversation_id`, timestamps. Stores conversation history and (optional) user preferences. |

### 2.5 Cross-cutting concerns

| File | Role |
|------|------|
| **`bot_config.py`** | Identity configuration singleton (`BotIdentity` dataclass). Holds the bot name, company name/tagline, API title/version, ChromaDB collection name (`chikku_robotics`), and the resolved file paths for the system prompt and about text. Also exposes `resolve_path()` and `is_robotics()`. |
| **`errors.py`** | Typed exception hierarchy (`RetrievalError`, `LLMError`, `IntentError`, `DatabaseError`, `ValidationError`, `SystemError`) plus `handle_error()`, which maps any exception to a user-friendly, persona-safe message. |
| **`rate_limit.py`** | Simple fixed-window in-memory rate limiter (per client IP). Configured by `RATE_LIMIT_ENABLED`, `RATE_LIMIT_WINDOW_SECONDS`, `RATE_LIMIT_MAX_REQUESTS`. Single-instance only — not cluster-safe. |
| **`logging_config.py`** | Structured logging setup. Optional JSON formatter (via `USE_JSON_LOGS`) and a `RequestLogger` context manager that records request IDs and latency. |

---

## 3. `data/` — Knowledge & Prompts

```
data/
├── system_prompt_robotics.txt     # The LLM system prompt (persona + grounding rules)
├── sample_queries.txt             # Example queries (reference / test data)
├── fine_tuning_*.json             # Legacy fine-tuning datasets (reference only)
├── processed/
│   └── about_robotics.txt         # Static company text injected into the system prompt
└── knowledge_base/
    └── robotics/                  # Source of truth for company knowledge
        ├── company_overview.json
        ├── identity.json
        ├── products.json
        ├── services.json
        ├── solutions.json
        ├── technologies.json
        ├── partnerships.json
        ├── faq.json
        ├── S-Robot-product.pdf    # Source PDF (reference, not ingested)
        └── *.md / *.pdf           # Human-readable / printable copies of the JSON
```

### 3.1 System prompt — `data/system_prompt_robotics.txt`

The full persona and grounding instructions sent to the LLM. It defines the
"Chikku the service robot" character, the forbidden phrases, response style,
and the `{context}` placeholder that `RAGPipeline` fills with retrieved chunks
at query time. Edit this file to change bot behavior — no code change needed.

### 3.2 About text — `data/processed/about_robotics.txt`

A short static company description. Loaded by `RAGPipeline` and injected into
the system prompt as a `COMPANY INFORMATION` section, so the bot always knows
core facts (mission, name origin, offices, email) even without retrieval.

### 3.3 Knowledge base JSON — `data/knowledge_base/robotics/*.json`

Each file is one topic section. The ingestion script turns them into
retrievable chunks, and the keyword-based KB search uses the topic map in
`knowledge_base.py`.

| File | Topic | Contents |
|------|-------|----------|
| `company_overview.json` | `company_overview` | Mission, vision, headquarters, global offices, email. |
| `identity.json` | `identity` | Brand identity, name origin / meaning, founders, leadership. |
| `products.json` | `products` | Hardware & software product lists, plus the `featured_products` array (Chikku Voice AI Kiosk, S-Robot, WatchGuard6S) with detailed specs. |
| `services.json` | `services` | Consulting, engineering support, training, maintenance programs. |
| `solutions.json` | `solutions` | Industry solutions: manufacturing, healthcare, warehousing, smart cities, etc. |
| `technologies.json` | `technologies` | Core tech: ML, Computer Vision, NLP, edge computing, the Chikku Brain AI platform. |
| `partnerships.json` | `partnerships` | Strategic partners, alliances, university & government collaborations. |
| `faq.json` | `faq` | Curated Q&A pairs (cost, location, contact, capabilities, …). The highest-precision source for factoid questions. |

> The matching `.md` and `.pdf` files are human-readable/printable renderings of
> the same content. Only the `.json` files are read by the code. The `S-Robot-product.pdf`
> is a source reference PDF and is **not** ingested by `ingest_robotics.py`.

---

## 4. `docs/` — Documentation

| File | Contents |
|------|----------|
| `VOICE_FILLER_GUIDE.md` | Frontend integration guide for the `/chat/voice` SSE streaming endpoint and the filler signal. |
| `PROJECT_STRUCTURE.md` | This file. |
| `RAG_ARCHITECTURE.md` | The RAG pipeline architecture, retrieval layers, and the models in use. |

## 5. `documents/` — Legacy Notes (reference only)

Historical internal notes from earlier development phases (fine-tuning analysis,
reranking install notes, quick-start drafts, timeout config, etc.). These are
**not** authoritative and may be outdated — prefer `docs/` for current
information. Safe to ignore during normal maintenance.

---

## 6. Configuration files

| File | Committed? | Purpose |
|------|-----------|---------|
| `config.env` | ✅ Yes | Full annotated configuration **template**. Copy to `.env` and edit. |
| `sample.env` | ✅ Yes | Minimal sample configuration. |
| `.env` | ❌ No (git-ignored) | **Active** configuration read at runtime via `python-dotenv`. Holds secrets (e.g. `OPENAI_API_KEY`). Never commit. |
| `requirements.txt` | ✅ Yes | Python dependencies. |

---

## 7. Request lifecycle — which file does what

A single `/chat/voice` request flows through the codebase like this:

```
HTTP request
  └─ api.py            (validation, rate limit, CORS, conversation lookup)
      └─ rag.py  RAGPipeline.query_stream()
            ├─ intent_classifier.py   → IntentType + shared query embedding
            ├─ response_templates.py   → deterministic answer (greetings/identity)
            ├─ knowledge_base.py       → FAQ cache lookup (Layer 1)
            ├─ llm_provider.py         → query rewrite + embed (Layer 2 prep)
            ├─ rag.py _hybrid_retrieve → BM25 + Dense + RRF (Layer 2)
            ├─ rag.py rerank           → cosine / cross-encoder (Layer 3)
            ├─ response_validator.py   → strip AI disclaimers
            └─ llm_provider.py         → final LLM generation
  └─ chat.py / database.py  → persist user + assistant turns to SQLite
  └─ SSE response stream back to the client
```

For the full pipeline explanation (intent routing, the three retrieval layers,
the filler signal, and the models behind each step), see
[RAG_ARCHITECTURE.md](./RAG_ARCHITECTURE.md).
