#!/bin/bash
# Hotel Saigon Chatbot API - Automated Setup Script

set -e  # Exit on error

echo "=========================================="
echo "Hotel Saigon Chatbot API - Setup"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check Python version
echo "1. Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 is not installed${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo -e "${GREEN}✓${NC} Python version: $(python3 --version)"
echo ""

# Check Ollama
echo "2. Checking Ollama..."
if ! command -v ollama &> /dev/null; then
    echo -e "${YELLOW}⚠ Ollama is not installed${NC}"
    echo "   Install from: https://ollama.ai"
    echo "   Or run: curl -fsSL https://ollama.ai/install.sh | sh"
    read -p "   Continue anyway? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Ollama is installed"
    OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
    echo "   Version: $OLLAMA_VERSION"
fi
echo ""

# Create virtual environment
echo "3. Creating virtual environment..."
if [ -d "venv" ]; then
    echo -e "${YELLOW}⚠ Virtual environment already exists${NC}"
    read -p "   Remove and recreate? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf venv
        python3 -m venv venv
        echo -e "${GREEN}✓${NC} Virtual environment created"
    else
        echo -e "${GREEN}✓${NC} Using existing virtual environment"
    fi
else
    python3 -m venv venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi
echo ""

# Activate virtual environment
echo "4. Activating virtual environment..."
source venv/bin/activate
echo -e "${GREEN}✓${NC} Virtual environment activated"
echo ""

# Upgrade pip
echo "5. Upgrading pip..."
pip install --upgrade pip --quiet
echo -e "${GREEN}✓${NC} pip upgraded"
echo ""

# Install dependencies
echo "6. Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}✓${NC} Dependencies installed"
else
    echo -e "${RED}✗ requirements.txt not found${NC}"
    exit 1
fi
echo ""

# Check Ollama models
echo "7. Checking Ollama models..."
if command -v ollama &> /dev/null; then
    echo "   Checking for mxbai-embed-large..."
    if ollama list | grep -q "mxbai-embed-large"; then
        echo -e "${GREEN}✓${NC} mxbai-embed-large found"
    else
        echo -e "${YELLOW}⚠ mxbai-embed-large not found${NC}"
        read -p "   Pull mxbai-embed-large now? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "   Pulling mxbai-embed-large (this may take a few minutes)..."
            ollama pull mxbai-embed-large
            echo -e "${GREEN}✓${NC} mxbai-embed-large pulled"
        fi
    fi
    
    echo "   Checking for llama3:8b-instruct-q4_0..."
    if ollama list | grep -q "llama3:8b-instruct-q4_0"; then
        echo -e "${GREEN}✓${NC} llama3:8b-instruct-q4_0 found"
    else
        echo -e "${YELLOW}⚠ llama3:8b-instruct-q4_0 not found${NC}"
        read -p "   Pull llama3:8b-instruct-q4_0 now? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "   Pulling llama3:8b-instruct-q4_0 (this may take several minutes)..."
            ollama pull llama3:8b-instruct-q4_0
            echo -e "${GREEN}✓${NC} llama3:8b-instruct-q4_0 pulled"
        fi
    fi
else
    echo -e "${YELLOW}⚠ Skipping Ollama model check (Ollama not installed)${NC}"
fi
echo ""

# Create .env file
echo "8. Setting up configuration..."
if [ -f ".env" ]; then
    echo -e "${YELLOW}⚠ .env file already exists${NC}"
    read -p "   Overwrite with config.env? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp config.env .env
        echo -e "${GREEN}✓${NC} .env file created from config.env"
    else
        echo -e "${GREEN}✓${NC} Keeping existing .env file"
    fi
elif [ -f "config.env" ]; then
    cp config.env .env
    echo -e "${GREEN}✓${NC} .env file created from config.env"
else
    echo -e "${RED}✗ config.env not found${NC}"
    exit 1
fi
echo ""

# Check menu data
echo "9. Checking menu data..."
if [ -f "data/processed/menu_items.json" ]; then
    ITEM_COUNT=$(python3 -c "import json; print(len(json.load(open('data/processed/menu_items.json'))))" 2>/dev/null || echo "unknown")
    echo -e "${GREEN}✓${NC} Menu data found (items: $ITEM_COUNT)"
else
    echo -e "${YELLOW}⚠ Menu data not found at data/processed/menu_items.json${NC}"
    echo "   You may need to extract it from saigon.pdf first"
fi
echo ""

# Ask about ingestion
echo "10. Data ingestion..."
if [ -d "chroma_db" ] && [ "$(ls -A chroma_db 2>/dev/null)" ]; then
    echo -e "${YELLOW}⚠ ChromaDB already exists${NC}"
    read -p "   Run ingestion anyway? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "   Running ingestion (this may take several minutes)..."
        python3 src/ingestion.py
        echo -e "${GREEN}✓${NC} Ingestion complete"
    else
        echo -e "${GREEN}✓${NC} Skipping ingestion"
    fi
else
    if [ -f "data/processed/menu_items.json" ]; then
        read -p "   Run data ingestion now? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "   Running ingestion (this may take several minutes)..."
            python3 src/ingestion.py
            echo -e "${GREEN}✓${NC} Ingestion complete"
        else
            echo -e "${YELLOW}⚠ Skipping ingestion - you'll need to run it later${NC}"
            echo "   Run: python3 src/ingestion.py"
        fi
    else
        echo -e "${YELLOW}⚠ Cannot run ingestion - menu data not found${NC}"
    fi
fi
echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Activate virtual environment:"
echo "   source venv/bin/activate"
echo ""
echo "2. (If not done) Run data ingestion:"
echo "   python3 src/ingestion.py"
echo ""
echo "3. Start the API server:"
echo "   python3 run_api.py"
echo ""
echo "4. Access the API:"
echo "   - API: http://localhost:8000"
echo "   - Docs: http://localhost:8000/docs"
echo ""
echo "For detailed instructions, see README.md"
echo ""
