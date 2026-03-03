"""
Ingest ABOUT knowledge: index data/processed/about.txt into the existing ChromaDB collection.

This script is safe to run repeatedly:
- It only adds/updates documents with ids like "about:0", "about:1", ...
- It does NOT delete or re-index menu items.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import chromadb

# Reuse helpers from the main ingestion pipeline
from ingestion import index_about_knowledge


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest about.txt into ChromaDB (doc_type=about)")
    parser.add_argument(
        "--chroma-dir",
        default=None,
        help="Path to chroma_db directory (defaults to <project_root>/chroma_db)",
    )
    parser.add_argument(
        "--about-path",
        default=None,
        help="Path to about.txt (defaults to <project_root>/data/processed/about.txt)",
    )
    parser.add_argument(
        "--model",
        default="mxbai-embed-large",
        help="Ollama embedding model (default: mxbai-embed-large)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    chroma_dir = Path(args.chroma_dir) if args.chroma_dir else (project_root / "chroma_db")
    about_path = Path(args.about_path) if args.about_path else (project_root / "data" / "processed" / "about.txt")

    if not about_path.exists():
        raise SystemExit(f"about.txt not found: {about_path}")

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_collection(name="hotel_saigon_menu")

    index_about_knowledge(collection, str(about_path), model=args.model)

    print("\n✅ About ingestion complete!")
    print(f"   Collection: hotel_saigon_menu")
    print(f"   Total docs now: {collection.count()}")


if __name__ == "__main__":
    main()

