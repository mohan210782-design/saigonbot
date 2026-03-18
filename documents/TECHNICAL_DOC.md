# Hotel Saigon Chatbot - Technical Development Plan

## Overview
RAG-based chatbot for Hotel Saigon menu queries. Optimized for lightweight deployment on Jetson/Raspberry Pi.

## Architecture

### Components
1. **Data Ingestion**: PDF → Clean chunks + metadata → ChromaDB
2. **Embedding**: Ollama mxbai-embed-large (local)
3. **Vector Store**: ChromaDB (lightweight, embedded)
4. **Reranking**: bge-reranker-v2-m3 (optional, via HuggingFace)
5. **Generation**: Ollama llama3:latest (local)
6. **API**: FastAPI (lightweight web framework)

### Technology Stack
- **Python 3.9+**
- **ChromaDB**: Embedded vector database
- **Ollama**: Local LLM & embeddings
- **FastAPI**: REST API server
- **FlagEmbedding**: Reranking (optional)
- **PyPDF2/pdfplumber**: PDF parsing

## Development Steps

### Phase 1: Data Preparation
1. Extract menu data from `saigon.pdf`
2. Clean and normalize text (prices, names, descriptions)
3. Create structured chunks (1 item per chunk)
4. Generate metadata schema:
   - `id`, `section`, `item_name`, `price`, `currency`, `tags`, `source`, `page`

### Phase 2: Ingestion Pipeline
1. Setup ChromaDB collection
2. Generate embeddings using mxbai-embed-large
3. Store chunks + metadata in ChromaDB
4. Validate indexing (test queries)

### Phase 3: RAG Pipeline
1. Query embedding (mxbai-embed-large)
2. ChromaDB retrieval (top-k: 10-20)
3. Optional reranking (bge-reranker-v2-m3)
4. LLM generation (llama3) with context
5. Response formatting

### Phase 4: API Development
1. FastAPI endpoints:
   - `/query` - Chat endpoint
   - `/health` - Health check
2. Error handling
3. Response validation

### Phase 5: Optimization for Edge Devices
1. Model quantization (if needed)
2. Batch processing optimization
3. Memory management
4. Caching strategies

### Phase 6: Testing & Validation
1. Test common queries
2. Accuracy validation
3. Performance benchmarking
4. Edge device testing

## Lightweight Considerations

### For Raspberry Pi/Jetson:
- **ChromaDB**: Embedded mode (no separate server, ~50MB)
- **Ollama**: Local models (no cloud API, no network calls)
- **FastAPI**: Minimal dependencies (~10MB)
- **Memory**: Optimize batch sizes, limit concurrent requests
- **Storage**: ChromaDB persistence on disk (~100-500MB for menu data)
- **Lazy Loading**: Load models only when needed
- **Caching**: Cache frequent queries
- **Reranking**: Optional (can skip for lighter footprint)

### Lightweight Optimizations:
1. **Smaller Models** (if llama3 too heavy):
   - Use `gemma3:latest` (3.3GB) instead of llama3 (4.7GB)
   - Or `llama2:latest` (3.8GB)
2. **Skip Reranking**: Use ChromaDB similarity only (saves ~500MB RAM)
3. **Efficient Chunking**: Smaller chunks = faster retrieval
4. **Batch Processing**: Process embeddings in small batches
5. **Connection Pooling**: Reuse Ollama connections

### Resource Requirements (Estimated)
- **RAM**: 3-4GB (with optimizations)
  - Ollama models: 2-3GB
  - ChromaDB: 100-200MB
  - Python/FastAPI: 200-300MB
- **Storage**: 5-8GB (models + ChromaDB)
- **CPU**: Multi-core recommended (2+ cores)

## Project Structure
```
saigonbot/
├── data/
│   ├── saigon.pdf
│   └── processed/          # Cleaned menu data
├── src/
│   ├── ingestion.py        # PDF → ChromaDB pipeline
│   ├── rag.py              # RAG query pipeline
│   ├── api.py              # FastAPI server
│   └── utils.py            # Helpers
├── chroma_db/              # ChromaDB storage
├── requirements.txt
├── config.yaml             # Configuration
└── TECHNICAL_DOC.md
```

## Deployment Strategy
1. **Development**: Local testing on Mac
2. **Validation**: Test on Raspberry Pi/Jetson
3. **Production**: Deploy optimized version

## Next Steps
1. Setup project structure
2. Create requirements.txt
3. Implement data extraction
4. Build ingestion pipeline
5. Develop RAG pipeline
6. Create API server
