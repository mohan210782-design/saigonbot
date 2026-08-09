"""
Load an exported Chikku KB payload into ChromaDB.

Reads the files written by `ingest_chikku.py` (data/processed/chikku_kb/) and
upserts them into a collection. Pre-computed vectors are used when present, so
no embedding model is needed for the upload.

Usage:
    # upload with the vectors that shipped in the export (no Ollama needed)
    python src/load_chikku_export.py

    # customer-facing subset only
    python src/load_chikku_export.py --input data/processed/chikku_kb/chikku_kb.customer.jsonl

    # re-embed from text instead of using the stored vectors
    python src/load_chikku_export.py --input data/processed/chikku_kb/chikku_kb.jsonl --embed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import chromadb
from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()


def read_jsonl(path: Path) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    root = Path(__file__).parent.parent
    default_input = root / "data" / "processed" / "chikku_kb" / "chikku_kb.embeddings.jsonl"

    parser = argparse.ArgumentParser(description="Upload an exported Chikku KB into ChromaDB")
    parser.add_argument("--input", default=str(default_input), help="path to a .jsonl export")
    parser.add_argument("--chroma-dir", default=str(root / "chikku_db"))
    parser.add_argument("--collection", default="chikku_kb")
    parser.add_argument("--embed", action="store_true", help="recompute embeddings from text")
    parser.add_argument("--reset", action="store_true", help="drop the collection first")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"export not found: {path}")

    records = read_jsonl(path)
    print(f"📄 Loaded {len(records)} records from {path.name}")

    has_vectors = bool(records) and "embedding" in records[0]
    if args.embed or not has_vectors:
        from llm_provider import get_provider

        provider = get_provider()
        print(f"🔄 Embedding {len(records)} records via {provider.embedding_model} ...")
        vectors = [provider.embed(r["text"]) for r in tqdm(records, mininterval=5.0)]
    else:
        vectors = [r["embedding"] for r in records]
        print(f"✅ Using pre-computed vectors ({len(vectors[0])}-d) — no embedding model needed")

    client = chromadb.PersistentClient(path=args.chroma_dir)
    if args.reset:
        try:
            client.delete_collection(args.collection)
            print(f"🗑️  Dropped existing collection {args.collection}")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=args.collection,
        metadata={"description": "Chikku Robotics company knowledge base", "hnsw:space": "cosine"},
    )

    batch = 100
    for i in range(0, len(records), batch):
        part = records[i:i + batch]
        collection.upsert(
            ids=[r["id"] for r in part],
            documents=[r["text"] for r in part],
            metadatas=[r["metadata"] for r in part],
            embeddings=vectors[i:i + batch],
        )

    print(f"\n✅ Upserted into {args.chroma_dir}/{args.collection}")
    print(f"   Total docs in collection: {collection.count()}")


if __name__ == "__main__":
    main()
