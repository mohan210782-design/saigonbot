# API Timeout Configuration

## Overview
The API timeout is now configurable via `.env` file to handle menu queries that require RAG retrieval (which can take longer).

## Configuration

### Default Timeout
- **Default**: 60 seconds
- **Current Setting**: 120 seconds (configured in `.env`)

### How to Change

Edit `.env` file:
```bash
# API Request Timeout (seconds)
# Increase this if menu queries timeout (RAG retrieval can take time)
API_TIMEOUT=120
```

### Recommended Values

- **Identity/Restaurant Info Queries** (templates): 5-10 seconds
- **Menu Queries** (RAG): 60-120 seconds
- **Complex Menu Queries** (with reranking): 120-180 seconds

## What Uses the Timeout

1. **Test Scripts** (`test_api.py`, `simple_test.py`)
   - HTTP client timeout for API requests
   - Reads from `API_TIMEOUT` env variable

2. **API Server**
   - FastAPI handles timeouts automatically
   - No explicit timeout needed (handled by uvicorn)

## Troubleshooting

### If Menu Queries Timeout

1. **Increase timeout in `.env`**:
   ```bash
   API_TIMEOUT=180  # 3 minutes
   ```

2. **Check RAG pipeline performance**:
   - Embedding generation time
   - Vector database query time
   - LLM generation time

3. **Optimize RAG settings**:
   - Reduce `TOP_K` (fewer items to retrieve)
   - Reduce `RERANK_K` (fewer items to rerank)
   - Disable reranking if not needed

### If All Queries Timeout

1. Check if API server is running
2. Check network connectivity
3. Check server logs for errors
4. Verify Ollama is running and accessible

## Notes

- Template-based queries (identity, restaurant info) are fast (< 1 second)
- Menu queries with RAG can take 10-60 seconds depending on:
  - Number of items retrieved
  - Whether reranking is enabled
  - LLM model speed
  - System resources
