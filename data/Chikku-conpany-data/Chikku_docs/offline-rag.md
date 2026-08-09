# Offline RAG Pipeline

> ⚠️ **Thay đổi so với bản cũ:**
> - `ROBOTICS_INFO_RESPONSES` (4 template địa chỉ/liên hệ/giờ/about) **đã được gắn intent thật** (COMPANY_LOCATION/CONTACT/HOURS/ABOUT) — trước đây là code chết (TECH_DEBT 2.1, đã fix). Mỗi intent có regex `INFO_PATTERNS` + example phrases embed trong `embeddings.json`.
> - Đánh dấu `botName`, `fallbackEmail` export không dùng (TECH_DEBT 1.3).
> - Sửa line number phụ: `intentCosineThreshold` thật đọc ở `index.js:118` (không phải intent.js:244 — đó chỉ là default param); `semantic` switch thật ở `app.js:2582`.
> - Mọi flow/line khác đã verify đúng (bản offline-rag.md là doc chính xác nhất).

On-device retrieval used when the backend is unreachable. This doc covers the
pipeline inside `www/js/offline-rag/` and how to tune/retrain it.

For when offline mode *activates*, see [architecture.md → Online vs offline
mode](architecture.md#online-vs-offline-mode).

## File map

| File | Role |
|------|------|
| `index.js` | Orchestrator — `RAGPipeline.answer()` entry point |
| `text-normalizer.js` | ASR cleanup (filler / contractions / number words) |
| `intent.js` | Two-stage intent classifier (regex + semantic) |
| `retriever.js` | `HybridRetriever` (BM25 + dense → RRF → rerank) |
| `bm25.js` | Okapi BM25 lexical index |
| `embedder.js` | On-device MiniLM wrapper (transformers.js) |
| `knowledge-base.js` | Chunk extraction + legacy keyword matcher |
| `stemmer.js` | Lightweight suffix-stripping stemmer |
| `templates.js` | Canned identity/conversational/error responses |
| `config.js` | Bot/company identity constants |

Build-time: `scripts/build-kb-embeddings.mjs` generates
`www/assets/knowledge_base/embeddings.json`.

---

## End-to-end flow

`RAGPipeline.answer(query)` (`index.js:150`) runs:

```
query text
   │
   ▼
[1] Empty check                                  index.js:151
   │   → clarification_needed if empty
   ▼
[2] normalizeQuery(raw)                          index.js:157  (text-normalizer.js:98)
   │   lowercase → strip filler → expand contractions → number→digit → trim
   ▼
[3] isEmptyQuery(q)                              index.js:158
   │
   ▼
[4] classifyIntent(q) — REGEX FAST-PASS          index.js:163  (intent.js:173, sync)
   │   Returns { intent, category, confidence, source:'regex' }
   ▼
[5] If regex → CLARIFICATION_NEEDED and embedder ready:
   │   classifyIntentSemantic(q, …) — SEMANTIC FALLBACK   index.js:172  (intent.js:218)
   │   If sem.intent ≠ CLARIFICATION_NEEDED → overwrite intentResult
   ▼
[6] Deterministic template route?                index.js:184
   │   category === CONVERSATIONAL
   │     || category === INFO
   │     || (category === IDENTITY AND intent ∈ {WHO_ARE_YOU, WHAT_DO_YOU_DO, CAPABILITIES})
   │   If yes → answerAboutOrIdentity(q, …)     index.js:54
   │     → return { response, source:'template', matched:true }
   ▼
[7] Dense layer on? (retriever !== null)
   │   await retriever.retrieve(q)              index.js:197  (retriever.js:114)
   │     BM25 + dense cosine → RRF → top-K → rerank → confidence
   │
   ├─ confidence === 'high'  → formatChunk  → { source:'hybrid'|'bm25', matched:true }
   │
   └─ confidence === 'low'
        kb.getBestFaqMatch(q)                    index.js:210
          → hit  : { source:'faq', confidence:'medium', matched:true }
          → miss : clarificationFor(q) → { source:'clarification', matched:false }
   ▼
[8] No dense layer (legacy keyword-only):
   │   kb.searchKnowledgeBase(q)                index.js:231
   ▼
[9] gracefulFallback()                          index.js:246
       { source:'fallback', matched:false }
```

Return shape (`index.js:148`):

```ts
{
  response: string,
  offline: true,
  matched: boolean,
  confidence?: 'high' | 'medium' | 'low',
  source?: 'template' | 'hybrid' | 'bm25' | 'faq' | 'clarification' | 'keyword' | 'fallback'
}
```

---

## Intent classification (`intent.js`)

### IntentType (`intent.js:27`)
- Identity: `WHO_ARE_YOU`, `WHAT_DO_YOU_DO`, `CAPABILITIES`, `LEADERSHIP`
- Conversational: `GREETING`, `GRATITUDE`, `SMALL_TALK`, `COMPLAINT`, `FEEDBACK`
- Info: `COMPANY_LOCATION`, `COMPANY_CONTACT`, `COMPANY_HOURS`, `COMPANY_ABOUT`
  (each maps to a canned reply in `ROBOTICS_INFO_RESPONSES`)
- `CLARIFICATION_NEEDED` — sentinel for "regex gave up, route to retrieval"

### Regex fast-pass — `classifyIntent()` (`intent.js:173`)
Three pattern tables scanned in order, **first match wins** (order matters):
- `IDENTITY_PATTERNS` (`intent.js:80`) — WHO_ARE_YOU, WHAT_DO_YOU_DO,
  CAPABILITIES, LEADERSHIP.
- `INFO_PATTERNS` (`intent.js:166`) — COMPANY_LOCATION, COMPANY_CONTACT,
  COMPANY_HOURS, COMPANY_ABOUT (canned reply for address / contact / hours /
  about-the-company queries).
- `CONVERSATIONAL_PATTERNS` (`intent.js:133`) — GREETING, GRATITUDE, SMALL_TALK,
  COMPLAINT, FEEDBACK.

Confidence: `0.95` identity, `0.9` info, `0.85` conversational, `0.3` CLARIFICATION_NEEDED.

> `IDENTITY_LEADERSHIP` is detected but **not** deterministic — it has no
> template and falls through to retrieval (`index.js:41` excludes it).

### Semantic fallback — `classifyIntentSemantic()` (`intent.js:218`)
Triggered only when regex returned `CLARIFICATION_NEEDED` **and** the embedder
is ready. Embeds the query, computes dot-product cosine against every
precomputed intent-example vector, and reclassifies if `best.sim >=
intentCosineThreshold`.

### `INTENT_EXAMPLES` (`intent.js:50`)
Canonical example phrases per intent (11 groups). **These are embedded at build
time** by `build-kb-embeddings.mjs` and written to `embeddings.json:intents`.
At runtime the classifier compares only against the precomputed vectors — it
never re-embeds the example strings.

> ⚠️ **Must stay in sync.** `INTENT_EXAMPLES` in `intent.js` and in
> `build-kb-embeddings.mjs` must be byte-identical. Both files carry a "MUST
> stay in sync" comment. Edit one without the other + a rebuild and the
> semantic classifier silently uses stale vectors. See [Editing the knowledge
> base](#editing-the-knowledge-base).

---

## Hybrid retrieval (`retriever.js` + `bm25.js`)

### `retrieve(query)` (`retriever.js:114`)

1. **Lexical** — `bm25.score(query)` → `Float32Array`.
2. **Dense** (if `denseReady`) — `qVec = embedder.embed(query)`, then
   `cosineSim(qVec, vecs[i])` for all chunks.
3. **RRF fusion** (`retriever.js:142`) — for each chunk:
   `fused = 1/(rrfK + lexRank) [+ 1/(rrfK + denseRank)]`. A channel only counts
   if its score > 0 for that doc.
4. **Top-K cut** by fused score.
5. **Rerank** (`retriever.js:162`) — linear blend:
   `wFused * fused + wTitle * titleSim + wLexOverlap * lexOverlap − lowPriorityPenalty`.
   `lowPriorityPenalty` applies to chunks where `_priority==='low'` or
   `field==='description'`.
6. **Confidence** (`retriever.js:203`):
   - Dense path: `best.dense >= cosineThreshold` → `'high'` else `'low'`.
   - BM25-only: `best.bm25 >= bm25OnlyThreshold` → `'high'` else `'low'`.

### BM25 (`bm25.js`)
Standard Okapi, `k1=1.5`, `b=0.75`. Tokenization: lowercase → strip punctuation
→ drop length≤1 and `STOP_WORDS` → `stemWord()`.

### Graceful degradation
If the embedder fails to load, the retriever proceeds **BM25-only** and still
answers lexically (`retriever.js:83`). Same on per-query embed failure.

---

## Embedder (`embedder.js`)

- **Model:** `Xenova/all-MiniLM-L6-v2` (int8 quantized, 384-dim, L2-normalized).
- **Loader:** transformers.js vendored at `www/vendor/transformers/`.
- **Local model root:** `./assets/models/`. `env.allowRemoteModels = false`.
- **ORT wasm reuse:** `env.backends.onnx.wasm.wasmPaths = '/assets/ort/'` —
  shares the wake word engine's binaries. `numThreads = 1`, `proxy = false`
  (the app runs on `http` scheme, no COOP/COEP).
- **Lazy singleton:** `init()` (`embedder.js:60`) memoises an in-flight
  `extractorPromise`; race-safe.
- **`embed(text)`** (`embedder.js:77`): `extractor(text, { pooling:'mean',
  normalize:true })` → `Float32Array(384)`.
- **`cosineSim(a, b)`** (`embedder.js:93`): plain dot product (vectors are unit-length).

The MiniLM model + precomputed chunk/intent embeddings are staged by
`npm run prepare:rag` (runs `prepare:minilm-model` + `build:kb-embeddings`).

---

## Knowledge base (`knowledge-base.js`)

Eight JSON files in `www/assets/knowledge_base/`:

| File | Contents |
|------|----------|
| `company_overview.json` | company, name_origin |
| `identity.json` | brand, leadership, name_origin, bot_introduction |
| `products.json` | hardware, software, featured_products |
| `services.json` | consulting, engineering_support, training, maintenance, custom_development |
| `solutions.json` | smart_manufacturing, healthcare, warehousing_logistics, smart_cities, agriculture |
| `technologies.json` | ai, computer_vision, robotics_engineering, edge_computing, cloud_platform, safety_systems |
| `partnerships.json` | technology_partners |
| `faq.json` | title, description, faq_items[] (question/answer pairs) |

### Chunk extraction — `extractSectionContent(data)` (`knowledge-base.js:118`)
The canonical chunker shared by both the runtime retriever and the build
script (this guarantees parity). Output chunk shape:
`{ text, title, subtopic, field?, _priority? }`.

- `{question, answer}` arrays and top-level `faq_items` → `subtopic:'faq'`,
  `text = question + '\n' + answer`.
- Direct string fields (excluding `name`, `title`, `description`, `tagline`) →
  `text = 'Key: value'`.
- `description` → low-priority chunk (`_priority:'low'`, `field:'description'`).
- Item arrays (`partners`, `products`, `applications`, …) → recursively
  flattened via `flattenJsonValue()`.

### `embeddings.json` schema
```json
{
  "model": "Xenova/all-MiniLM-L6-v2",
  "dim": 384,
  "builtAt": "2026-07-23T08:40:50.169Z",
  "intents":  [ { "intent":"…", "examples":[…], "embeddings":[[384 floats]] } ],
  "chunks":   [ { "text","title","subtopic","field","section","embedding":[384 floats] } ]
}
```
> `_priority` is stripped from chunks before write; the rerank re-applies it
> at runtime via the `field==='description'` check.

---

## Templates & fallback (`templates.js`, `config.js`)

- **Welcome / identity** — `ROBOTICS_WELCOME_MESSAGE` (WHO_ARE_YOU),
  `ROBOTICS_IDENTITY_RESPONSES` (WHAT_DO_YOU_DO, CAPABILITIES — random pick
  from variants).
- **Conversational** — `ROBOTICS_CONVERSATIONAL_RESPONSES` (GREETING, GRATITUDE,
  SMALL_TALK, COMPLAINT, FEEDBACK).
- **Info** — `ROBOTICS_INFO_RESPONSES` (COMPANY_LOCATION, COMPANY_CONTACT,
  COMPANY_HOURS, COMPANY_ABOUT). Canned reply cho câu hỏi về địa chỉ / liên hệ /
  giờ hoạt động / giới thiệu công ty. Được route qua `INFO_PATTERNS`
  (`intent.js`) + `INTENT_EXAMPLES` (semantic fallback). Trước đây là code chết
  (TECH_DEBT 2.1, đã fix bằng cách thêm 4 intent thật).
- **Errors** — `ROBOTICS_ERROR_RESPONSES` (`no_results`, `clarification_needed`,
  `system_error`).
- `gracefulFallback()` — the final legacy-path message ("I don't have that
  exact detail handy…").
- `clarificationFor(query)` (`index.js:274`) — dynamic clarification that quotes
  the user's truncated query and lists answerable topics.

Identity constants (`botName`, `companyName`, `companyTagline`, `fallbackEmail`)
live in `offline-rag/config.js`. ⚠️ Chỉ `companyName` + `companyTagline` được
import; `botName` + `fallbackEmail` export nhưng 0 import (TECH_DEBT 1.3).

---

## Config knobs — `CHIKKU_CONFIG.offlineRAG`

See [configuration.md](configuration.md) for the full reference. Quick table:

| Knob | Default | Where | Effect |
|------|---------|-------|--------|
| `semantic` | `true` | app.js:2582 | Master switch. `false` → keyword-only path. |
| `rrfK` | `60` | retriever.js:147 (via `this.opts`) | RRF constant. Standard TREC value. |
| `topK` | `10` | retriever.js:147 | Candidates surviving fusion to rerank. |
| `cosineThreshold` | `0.40` | retriever.js:208 | Min dense cosine for HIGH confidence. |
| `bm25OnlyThreshold` | `8` | retriever.js:212 | Min raw BM25 for HIGH when dense off. |
| `intentCosineThreshold` | `0.60` | index.js:118 (default param `intent.js:218`) | Min cosine for semantic intent reclassification. |

Not exposed in config (change in source):
- Rerank weights (`retriever.js:50`): `wFused=1.0`, `wTitle=0.6`,
  `wLexOverlap=0.4`, `lowPriorityPenalty=0.1`.
- BM25 params (`bm25.js:53`): `k1=1.5`, `b=0.75`.

**MiniLM cosine sanity check:** related queries sit at ~0.55, unrelated ~0.05.
`cosineThreshold=0.40` is a middle ground.

---

## Editing the knowledge base

The most common maintenance task. Two cases:

### Case A: edit KB content only (no schema change)

1. Edit one or more `www/assets/knowledge_base/*.json` files.
2. **Rebuild embeddings:**
   ```bash
   npm run build:kb-embeddings
   ```
   (or `npm run sync` to also re-sync into the native projects)
3. The chunk text changed, so the precomputed vectors are now stale — the
   rebuild is mandatory, otherwise retrieval matches against old text.

### Case B: add an intent example

1. Edit `INTENT_EXAMPLES` in **both**:
   - `www/js/offline-rag/intent.js` (runtime, used for documentation/regex)
   - `scripts/build-kb-embeddings.mjs` (build, used to embed)
2. Rebuild: `npm run build:kb-embeddings`.

> When adding a **new intent type** (not just examples), you also need to: add
> the key to `IntentType` + `IntentCategory` (`intent.js`), add a pattern group
> to `IDENTITY_PATTERNS`/`INFO_PATTERNS`/`CONVERSATIONAL_PATTERNS`, add it to
> `DETERMINISTIC_INTENTS` (`index.js:41`) if it should short-circuit to a
> template, and (if it has a canned reply) add the template map entry. That is
> exactly how the 4 `COMPANY_*` info intents were wired (TECH_DEBT 2.1 fix).

### Case C: change the chunker (`extractSectionContent`)

`knowledge-base.js:118` is shared by runtime and build. Any change here means
**every chunk is different** → rebuild embeddings. Verify parity by running
the test suite:

```bash
npm run test:offline-rag    # 15 queries, must be 15/15 pass
```

---

## Tuning cheatsheet

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Bot always answers via keyword/FAQ | `semantic:false`, or `embeddings.json` missing/failed | `config.js:offlineRAG.semantic`, check console `[OFFLINE-RAG]` logs |
| Correct paraphrase → wrong intent | `intentCosineThreshold` too high, or `INTENT_EXAMPLES` drift | lower threshold, rebuild embeddings |
| Confident wrong answer | `cosineThreshold` too low | raise it |
| Too many clarification prompts | `cosineThreshold` too high, or `bm25OnlyThreshold` too high | lower one/both |
| Embedder never ready | MiniLM model not staged, or ORT wasm missing | `npm run prepare:rag`; check `assets/models/` and `assets/ort/` |
| Description blurbs beating spec chunks | `lowPriorityPenalty` too small or `field:'description'` missing | inspect `embeddings.json` chunks |
| First query slow | `warmUp()` not awaited | check `index.js:135` |

Validate any tuning change with `npm run test:offline-rag` before shipping.
