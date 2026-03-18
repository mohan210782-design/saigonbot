# Reranking Issue - FlagEmbedding Not Installed

## Problem

Even though `USE_RERANKING=true` in `.env`, reranking shows as "disabled" because:
- **FlagEmbedding package is NOT installed**
- When import fails, code sets `self.use_reranking = False`

## Solution Options

### Option 1: Install FlagEmbedding (Recommended for Best Quality)

```bash
cd saigonbot
pip install FlagEmbedding
```

Then restart API server:
```bash
python3 run_api.py
```

**Pros:**
- Best quality responses
- Items prioritized by semantic similarity
- Works great with top_k=40

**Cons:**
- Adds ~200-500ms latency
- Requires additional dependency

### Option 2: Use Improved Filtering Only (Faster, Still Good)

Keep `USE_RERANKING=false` and rely on:
- Improved filtering (removes contradictions)
- Smart context limits (max 15 items)
- Better prompts

**Pros:**
- Faster (no reranking latency)
- Still good quality with improved filtering
- No additional dependencies

**Cons:**
- Slightly lower quality than with reranking
- Items not prioritized by semantic similarity

## Current Status

- ✅ `.env` file exists with `USE_RERANKING=true`
- ✅ `RERANK_K=12` configured
- ❌ FlagEmbedding NOT installed
- ❌ Reranking disabled due to missing dependency

## Recommendation

For production: **Install FlagEmbedding** - the quality improvement is worth the small latency cost.

For development/testing: **Keep reranking disabled** - improved filtering + context limits should be sufficient.
