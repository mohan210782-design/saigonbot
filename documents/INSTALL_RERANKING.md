# Install FlagEmbedding to Enable Reranking

## Current Status

✅ `.env` file has `USE_RERANKING=true`  
✅ Code reads it correctly  
❌ **FlagEmbedding package is NOT installed**  
❌ Reranking fails to initialize → gets disabled  

## The Problem

When the API server starts:
1. Reads `USE_RERANKING=true` from `.env` ✅
2. Sets `self.use_reranking = True` ✅
3. Tries to import FlagEmbedding ❌ **FAILS** (package not installed)
4. Exception handler sets `self.use_reranking = False` ❌
5. Result: "Reranking: disabled" even though `.env` says `true`

## Solution: Install FlagEmbedding

```bash
cd saigonbot
pip install FlagEmbedding
```

**Note:** This will download the reranking model (~500MB) on first use.

## After Installation

1. Restart API server:
   ```bash
   python3 run_api.py
   ```

2. You should see:
   ```
   ✅ Reranking enabled
   ✅ RAG Pipeline initialized
      ...
      Reranking: enabled
   ```

## Alternative: Keep Reranking Disabled

If you don't want to install FlagEmbedding, you can still get good results with:
- Improved filtering (removes contradictions)
- Smart context limits (max 15 items)
- Better prompts

Just set `USE_RERANKING=false` in `.env` and restart.

## Recommendation

**Install FlagEmbedding** - The quality improvement is significant, especially with `top_k=40`.
