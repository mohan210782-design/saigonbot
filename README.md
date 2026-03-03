# Hotel Saigon Chatbot API - Setup Guide

A RAG (Retrieval-Augmented Generation) based chatbot API for Hotel Saigon menu queries. This API uses Ollama for local LLM inference, ChromaDB for vector storage, and FastAPI for the REST API server.

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Data Ingestion](#data-ingestion)
- [Running the API](#running-the-api)
- [API Endpoints](#api-endpoints)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)

## 🔧 Prerequisites

Before setting up the API, ensure you have:

1. **Python 3.9+** installed
   ```bash
   python3 --version
   ```

2. **Ollama** installed and running
   - Download from: https://ollama.ai
   - Install: `curl -fsSL https://ollama.ai/install.sh | sh`
   - Start service: `ollama serve` (or it runs automatically as a service)

3. **Required Ollama Models** - Pull these models:
   ```bash
   # Embedding model (required)
   ollama pull mxbai-embed-large
   
   # LLM model (required)
   ollama pull llama3:8b-instruct-q4_0
   # OR use the full model (slower but potentially better quality)
   # ollama pull llama3:8b-instruct
   ```

4. **System Dependencies** (if needed):
   ```bash
   # On Ubuntu/Debian
   sudo apt-get update
   sudo apt-get install -y python3-pip python3-venv build-essential
   ```

## 📦 Installation

### Step 1: Clone or Copy the Project

If you've moved the project to a new server, ensure all files are present:
```bash
cd ~/path/to/saigonbot
ls -la
```

You should see:
- `requirements.txt`
- `config.env`
- `run_api.py`
- `src/` directory
- `data/` directory
- `saigon.pdf`

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Linux/Mac
# OR
venv\Scripts\activate  # On Windows
```

### Step 3: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This will install:
- `chromadb` - Vector database
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `ollama` - Ollama client
- `PyPDF2`, `pdfplumber` - PDF parsing
- `FlagEmbedding` - Reranking (optional)
- `python-dotenv` - Environment variables

### Step 4: Verify Ollama Models

```bash
# Check if models are available
ollama list

# If models are missing, pull them:
ollama pull mxbai-embed-large
ollama pull llama3:8b-instruct-q4_0
```

## ⚙️ Configuration

### Step 1: Create `.env` File

Copy the example config file:
```bash
cp config.env .env
```

### Step 2: Edit `.env` File

Open `.env` and adjust settings as needed:

```env
# RAG Pipeline Settings
TOP_K=7                    # Number of items to retrieve
RERANK_K=4                 # Number of items after reranking

# Ollama Models
EMBEDDING_MODEL=mxbai-embed-large
LLM_MODEL=llama3:8b-instruct-q4_0

# Reranking (optional - set to true to enable)
USE_RERANKING=false

# API Server Settings
API_HOST=0.0.0.0
API_PORT=8000
```

**Important Notes:**
- `TOP_K`: Number of menu items to retrieve from vector database (higher = more items, slower)
- `RERANK_K`: Number of items after reranking (should be ≤ TOP_K)
- `USE_RERANKING`: Set to `true` for better accuracy but slower responses
- `LLM_MODEL`: Use quantized models (q4_0) for faster inference on edge devices

## 📊 Data Ingestion

Before running the API, you need to ingest the menu data into ChromaDB.

### Step 1: Verify Menu Data

Ensure the processed menu data exists:
```bash
ls -la data/processed/menu_items.json
```

If the file doesn't exist, you may need to extract it from `saigon.pdf` first (see `src/extract_menu.py`).

### Step 2: Run Ingestion Script

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Run ingestion
python3 src/ingestion.py
```

**What the ingestion script does:**
1. Loads menu items from `data/processed/menu_items.json`
2. Creates text chunks from each menu item
3. Generates embeddings using `mxbai-embed-large`
4. Stores items in ChromaDB at `chroma_db/`
5. Validates indexing with test queries

**Expected Output:**
```
📦 Loaded 500 menu items from data/processed/menu_items.json
✅ Created new collection: hotel_saigon_menu
📝 Indexing 500 menu items...
🔄 Generating embeddings using mxbai-embed-large...
[Progress bar showing embedding generation]
💾 Storing items in ChromaDB...
✅ Successfully indexed 500 items
🔍 Validating indexing with test queries...
✅ Ingestion complete!
```

**If collection already exists:**
The script will ask if you want to re-index. Type `y` to replace existing data, or `n` to skip.

### Step 3: Verify Ingestion

Check that ChromaDB was created:
```bash
ls -la chroma_db/
```

You should see:
- `chroma.sqlite3` (database file)
- A directory with UUID name (vector data)

## 🚀 Running the API

### Method 1: Using `run_api.py` (Recommended)

```bash
# Activate virtual environment
source venv/bin/activate

# Run API
python3 run_api.py
```

### Method 2: Using Uvicorn Directly

```bash
# Activate virtual environment
source venv/bin/activate

# Run from project root
uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
```

### Method 3: Using Python Module

```bash
# Activate virtual environment
source venv/bin/activate

# Run as module
python3 -m uvicorn src.api:app --host 0.0.0.0 --port 8000
```

**Expected Output:**
```
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Accessing the API

- **API Base URL**: `http://localhost:8000` (or `http://<server-ip>:8000`)
- **Interactive Docs**: `http://localhost:8000/docs` (Swagger UI)
- **Alternative Docs**: `http://localhost:8000/redoc` (ReDoc)

## 📡 API Endpoints

### Health Check
```bash
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "message": "API is running",
  "collection_count": 500
}
```

### Query Menu (Non-streaming)
```bash
POST /query
Content-Type: application/json

{
  "query": "sweet options",
  "conversation_id": "optional-uuid",
  "top_k": 7,
  "rerank_k": 4
}
```

**Response:**
```json
{
  "query": "sweet options",
  "response": "Here are some sweet options...",
  "items": [
    {
      "name": "Chocolate Cake",
      "section": "Desserts",
      "price": "50000",
      "currency": "VND",
      "tags": ["sweet", "dessert"]
    }
  ],
  "retrieved_count": 4
}
```

### Chat Text (Non-streaming with conversation)
```bash
POST /chat/text
Content-Type: application/json

{
  "query": "what are the vegetarian options?",
  "conversation_id": "optional-uuid"
}
```

### Chat Stream (Streaming with SSE)
```bash
POST /chat/stream
Content-Type: application/json

{
  "query": "show me breakfast items",
  "conversation_id": "optional-uuid"
}
```

**Response:** Server-Sent Events stream with tokens

### Create New Conversation
```bash
POST /conversation/new
```

**Response:**
```json
{
  "conversation_id": "uuid-here"
}
```

### Get Conversation History
```bash
GET /conversation/{conversation_id}/history
```

### Get Statistics
```bash
GET /stats
```

**Response:**
```json
{
  "total_items": 500,
  "embedding_model": "mxbai-embed-large",
  "llm_model": "llama3:8b-instruct-q4_0",
  "reranking_enabled": false
}
```

## 🧪 Testing

### Test Health Endpoint
```bash
curl http://localhost:8000/health
```

### Test Query Endpoint
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "sweet options"}'
```

### Test with Python
```python
import requests

response = requests.post(
    "http://localhost:8000/query",
    json={"query": "vegetarian dosa"}
)
print(response.json())
```

### Test Streaming Endpoint
```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "breakfast items"}' \
  --no-buffer
```

## 🔍 Troubleshooting

### Issue: "Ollama connection error"

**Solution:**
1. Check if Ollama is running: `ollama list`
2. Start Ollama: `ollama serve` (or restart service)
3. Verify models are pulled: `ollama list`

### Issue: "ChromaDB collection not found"

**Solution:**
1. Run ingestion script: `python3 src/ingestion.py`
2. Check `chroma_db/` directory exists
3. Verify collection name is `hotel_saigon_menu`

### Issue: "No module named 'src'"

**Solution:**
1. Make sure you're in the project root directory
2. Activate virtual environment: `source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`

### Issue: "Port 8000 already in use"

**Solution:**
1. Change port in `.env`: `API_PORT=8001`
2. Or kill process using port 8000:
   ```bash
   lsof -ti:8000 | xargs kill -9
   ```

### Issue: "Embedding model not found"

**Solution:**
```bash
ollama pull mxbai-embed-large
```

### Issue: "LLM model not found"

**Solution:**
```bash
ollama pull llama3:8b-instruct-q4_0
# OR
ollama pull llama3:8b-instruct
```

### Issue: Slow response times

**Solutions:**
1. Use quantized models (q4_0) instead of full models
2. Reduce `TOP_K` and `RERANK_K` in `.env`
3. Disable reranking: `USE_RERANKING=false`
4. Use faster hardware or GPU acceleration

### Issue: "No items found" or irrelevant results

**Solutions:**
1. Re-run ingestion: `python3 src/ingestion.py` (type `y` to re-index)
2. Check if menu data is correct: `cat data/processed/menu_items.json | head -20`
3. Increase `TOP_K` in `.env` to retrieve more items
4. Enable reranking: `USE_RERANKING=true` (slower but more accurate)

## 📁 Project Structure

```
saigonbot/
├── chroma_db/              # ChromaDB vector database (created after ingestion)
├── data/
│   ├── processed/
│   │   └── menu_items.json  # Processed menu data
│   └── saigon.pdf          # Original PDF menu
├── src/
│   ├── api.py              # FastAPI server
│   ├── rag.py              # RAG pipeline implementation
│   ├── ingestion.py        # Data ingestion script
│   ├── chat.py             # Conversation manager
│   └── extract_menu.py     # PDF extraction (if needed)
├── config.env              # Configuration template
├── .env                    # Actual configuration (create from config.env)
├── requirements.txt       # Python dependencies
├── run_api.py             # API runner script
├── SYSTEM_PROMPT.md       # LLM system prompt
├── TECHNICAL_DOC.md       # Technical documentation
└── README.md              # This file
```

## 🔄 Quick Setup Summary

For a new server, run these commands in order:

```bash
# 1. Navigate to project
cd ~/path/to/saigonbot

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Pull Ollama models
ollama pull mxbai-embed-large
ollama pull llama3:8b-instruct-q4_0

# 5. Configure environment
cp config.env .env
# Edit .env if needed

# 6. Ingest data
python3 src/ingestion.py

# 7. Run API
python3 run_api.py
```

## 📝 Notes

- **First Request Delay**: The first API request may be slow as models load into memory. Subsequent requests will be faster.
- **Memory Usage**: The API uses ~2-4GB RAM with quantized models. Full models may use more.
- **Storage**: ChromaDB typically uses 100-500MB for menu data.
- **Performance**: Quantized models (q4_0) are 2-3x faster but may have slightly lower quality.

## 🆘 Support

For issues or questions:
1. Check the logs when running the API
2. Verify all prerequisites are installed
3. Ensure Ollama models are pulled
4. Check that data ingestion completed successfully

---

**Version:** 1.0.0  
**Last Updated:** 2026-03-01
