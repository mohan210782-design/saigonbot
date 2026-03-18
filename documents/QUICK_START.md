# Quick Start Guide

## 🚀 Fast Setup (New Server)

### Automated Setup
```bash
cd ~/path/to/saigonbot
chmod +x setup.sh
./setup.sh
```

### Manual Setup
```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Pull Ollama models
ollama pull mxbai-embed-large
ollama pull llama3:8b-instruct-q4_0

# 4. Configure
cp config.env .env

# 5. Ingest data
python3 src/ingestion.py

# 6. Run API
python3 run_api.py
```

## 📋 Common Commands

### Start API Server
```bash
source venv/bin/activate
python3 run_api.py
```

### Re-ingest Data
```bash
source venv/bin/activate
python3 src/ingestion.py
# Type 'y' when asked to re-index
```

### Check API Health
```bash
curl http://localhost:8000/health
```

### Test Query
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "sweet options"}'
```

### View API Docs
Open in browser: `http://localhost:8000/docs`

## 🔧 Configuration

Edit `.env` file to change settings:
- `TOP_K`: Number of items to retrieve (default: 7)
- `RERANK_K`: Items after reranking (default: 4)
- `LLM_MODEL`: LLM model name
- `API_PORT`: Server port (default: 8000)

## 🐛 Quick Troubleshooting

| Issue | Solution |
|-------|----------|
| "Ollama connection error" | `ollama serve` or restart Ollama service |
| "Collection not found" | Run `python3 src/ingestion.py` |
| "Port 8000 in use" | Change `API_PORT` in `.env` |
| "Model not found" | `ollama pull <model-name>` |
| Slow responses | Use quantized models (q4_0), reduce TOP_K |

## 📚 Full Documentation

See [README.md](README.md) for complete documentation.
