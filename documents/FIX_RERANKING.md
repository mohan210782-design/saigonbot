# Fix Reranking - NumPy Version Issue

## Problem Identified

✅ `.env` has `USE_RERANKING=true`  
✅ FlagEmbedding IS installed  
❌ **FlagEmbedding fails to import due to NumPy version mismatch**

**Error:** `ImportError: numpy.core._multiarray_umath failed to import`

**Root Cause:** 
- NumPy 2.2.6 is installed
- FlagEmbedding/TensorFlow/PyTorch were compiled with NumPy 1.x
- They're incompatible

## Solution: Downgrade NumPy

```bash
cd saigonbot
pip install "numpy<2.0"
```

Then restart API server:
```bash
python3 run_api.py
```

## Alternative: Keep Reranking Disabled

If you don't want to downgrade NumPy, you can:
1. Set `USE_RERANKING=false` in `.env`
2. Rely on improved filtering + context limits
3. Still get good quality without reranking

## Why This Happens

When API server starts:
1. Reads `USE_RERANKING=true` from `.env` ✅
2. Sets `self.use_reranking = True` ✅
3. Tries to import FlagEmbedding ✅ (package exists)
4. **Import FAILS** ❌ (NumPy version mismatch)
5. Exception handler sets `self.use_reranking = False` ❌
6. Result: "Reranking: disabled"

## Recommendation

**Downgrade NumPy** - This is a common issue and the fix is simple:
```bash
pip install "numpy<2.0"
```

After downgrading, reranking will work and you'll see:
```
✅ Reranking enabled
✅ RAG Pipeline initialized
   ...
   Reranking: enabled
```
