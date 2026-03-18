# CUDA Out of Memory Error - Solutions

## Problem

**Error:** `cudaMalloc failed: out of memory`
- LLM model (`llama3:8b-instruct-q4_0`) is trying to use GPU
- GPU doesn't have enough memory (needs ~838MB, but not available)
- This happens on your server

## Root Cause

Ollama is trying to use GPU (CUDA) but:
- GPU memory is already occupied by other processes
- OR GPU doesn't have enough memory
- OR multiple model instances are running

## Solutions

### Solution 1: Force CPU Usage (Recommended for Servers)

Tell Ollama to use CPU instead of GPU:

**Option A: Set environment variable before starting API:**
```bash
export OLLAMA_NUM_GPU=0
python3 run_api.py
```

**Option B: Use smaller/CPU-optimized model:**
- Current: `llama3:8b-instruct-q4_0` (tries to use GPU)
- Alternative: Use a smaller model or CPU-only model

**Option C: Configure Ollama to prefer CPU:**
```bash
# Check Ollama config
ollama show llama3:8b-instruct-q4_0

# Or set in .env
OLLAMA_NUM_GPU=0
```

### Solution 2: Free GPU Memory

If you want to keep using GPU:

```bash
# Check what's using GPU
nvidia-smi

# Kill other processes using GPU
# Or restart Ollama service to free memory
```

### Solution 3: Use Smaller Model

Switch to a smaller model that fits in available memory:

```bash
# In .env, change:
LLM_MODEL=llama3:8b-instruct-q4_0  # Current (8B parameters)
# To:
LLM_MODEL=llama3.2:3b-instruct-q4_0  # Smaller (3B parameters, ~1.7GB)
# Or:
LLM_MODEL=llama3.2:1b-instruct-q4_0  # Even smaller (1B parameters, ~600MB)
```

### Solution 4: Reduce Context Size

Reduce the context window to use less memory:

In `rag.py`, reduce `num_ctx`:
```python
"num_ctx": 1024,  # Instead of 2048
```

## Recommended Fix for Server

**Best approach:** Force CPU usage since you're on a server:

1. **Add to `.env`:**
   ```
   OLLAMA_NUM_GPU=0
   ```

2. **Or set before starting API:**
   ```bash
   export OLLAMA_NUM_GPU=0
   python3 run_api.py
   ```

3. **Or modify `rag.py` to set environment variable:**
   ```python
   import os
   os.environ['OLLAMA_NUM_GPU'] = '0'  # Force CPU
   ```

## Why This Happens

- Ollama automatically tries to use GPU if available
- GPU memory is limited and shared
- Multiple processes or large models can exhaust it
- CPU is more reliable for server deployments

## Performance Impact

- **CPU:** Slightly slower (~2-3x) but more reliable
- **GPU:** Faster but requires available GPU memory
- For production servers, CPU is often more stable
