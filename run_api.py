#!/usr/bin/env python3
"""
Run the Hotel Saigon Chatbot API server
"""
import uvicorn
from pathlib import Path
import sys

# Add src to path
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True  # Auto-reload on code changes for development
    )
