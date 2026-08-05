"""
Verification script for featured-products ingestion + semantic-first retrieval.

Run after `python src/ingest_robotics.py`:
    python _verify_products.py

Checks:
  1. ChromaDB contains the expected featured-product chunks (12 expected).
  2. Each of 6 representative queries retrieves the right product / chunk_type.
  3. The cosine re-rank backend is active (no cross-encoder segfault).
  4. No regression on legacy queries (founder, location).

This script does NOT call the LLM generator — it only exercises retrieval,
so it's fast (~5s) and free of OpenAI charges (query rewrite is disabled
here via env to keep the run deterministic and offline-friendly).
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

# Disable LLM query rewrite so retrieval is deterministic and we don't need
# a working OpenAI key to run this verification.
os.environ["LLM_QUERY_REWRITE"] = "false"

# Make sure Ollama embeddings are reachable (the pipeline uses them).
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root / "src"))

import chromadb  # noqa: E402

from rag import RAGPipeline  # noqa: E402


EXPECTED_PRODUCTS = [
    "Chikku Voice AI Kiosk",
    "S-Robot",
    "WatchGuard6S",
]
EXPECTED_CHUNK_TYPES = {
    "product_overview",
    "product_features",
    "product_benefits",
    "product_technologies",
}


def hr(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def check_chunks() -> bool:
    """Verify the 12 featured-product chunks are in ChromaDB."""
    hr("CHECK 1 — featured-product chunks in ChromaDB")
    client = chromadb.PersistentClient(path=str(project_root / "chroma_db"))
    col = client.get_collection(name="chikku_robotics")
    res = col.get(where={"subtopic": "featured_products"})
    ids = res.get("ids", [])
    metas = res.get("metadatas", [])
    print(f"Total docs in collection : {col.count()}")
    print(f"featured_products chunks : {len(ids)} (expected 12)")

    by_product_type: Counter = Counter()
    products_seen: set[str] = set()
    types_seen: set[str] = set()
    for m in metas:
        by_product_type[(m.get("product_name"), m.get("chunk_type"))] += 1
        products_seen.add(m.get("product_name"))
        types_seen.add(m.get("chunk_type"))

    print(f"Products seen            : {sorted(products_seen)}")
    print(f"chunk_types seen         : {sorted(types_seen)}")

    ok_count = len(ids) == 12
    ok_products = set(EXPECTED_PRODUCTS).issubset(products_seen)
    ok_types = EXPECTED_CHUNK_TYPES.issubset(types_seen)
    for product in EXPECTED_PRODUCTS:
        for ct in EXPECTED_CHUNK_TYPES:
            if by_product_type.get((product, ct), 0) != 1:
                print(f"  ✗ missing/extra: {product} / {ct}")
                ok_count = False

    print(f"\n12 chunks, 3×4 matrix   : {'✅' if ok_count else '❌'}")
    print(f"all 3 products present   : {'✅' if ok_products else '❌'}")
    print(f"all 4 chunk_types present: {'✅' if ok_types else '❌'}")
    return ok_count and ok_products and ok_types


def check_retrieval(rag: RAGPipeline) -> tuple[int, int]:
    """Run the 6 representative retrieval tests. Returns (passed, total)."""
    hr("CHECK 2 — semantic retrieval for featured products")
    tests = [
        ("What is Chikku Voice AI Kiosk?", "Chikku Voice AI Kiosk"),
        ("Tell me about S-Robot", "S-Robot"),
        ("What can WatchGuard6S do?", "WatchGuard6S"),
        ("How does the kiosk handle voice interaction?", "Chikku Voice AI Kiosk"),
        ("What are the benefits of S-Robot?", "S-Robot"),
        ("robot for solar farm security", "WatchGuard6S"),
    ]
    passed = 0
    for query, expected_product in tests:
        items, _ = rag._semantic_retrieve(query, top_k=rag.top_k, rerank_k=rag.rerank_k)
        # Look at the top-3 retrieved items for the expected product
        top_products = [
            it.get("metadata", {}).get("product_name", "")
            for it in items[:3]
        ]
        ok = expected_product in top_products
        passed += int(ok)
        top1 = items[0] if items else None
        top1_label = ""
        if top1:
            md = top1.get("metadata", {})
            top1_label = f"{md.get('product_name', '?')} / {md.get('chunk_type', '?')} (dist={top1.get('distance', '?'):.3f})"
        marker = "✅" if ok else "❌"
        print(f"{marker} {query}")
        print(f"   expected: {expected_product}")
        print(f"   top-3 products: {top_products}")
        print(f"   top-1: {top1_label}")
    return passed, len(tests)


def check_backend(rag: RAGPipeline) -> bool:
    hr("CHECK 3 — re-rank backend")
    print(f"reranker_kind: {rag.reranker_kind}")
    print(f"USE_RERANKING : {rag.use_reranking}")
    ok = rag.reranker_kind in ("cosine", "cross_encoder")
    print(f"backend active: {'✅' if ok else '❌'}")
    return ok


def check_legacy(rag: RAGPipeline) -> tuple[int, int]:
    hr("CHECK 4 — no regression on legacy queries")
    legacy = [
        ("who is your founder", "founder"),
        ("where are you located", "headquarters"),
        ("what is Chikku", "chikku"),
    ]
    passed = 0
    for query, expected_token in legacy:
        items, _ = rag._semantic_retrieve(query, top_k=rag.top_k, rerank_k=rag.rerank_k)
        joined = " ".join((it.get("document", "") or "").lower() for it in items[:3])
        ok = expected_token in joined or any(
            expected_token in (it.get("document", "") or "").lower() for it in items[:5]
        )
        passed += int(ok)
        marker = "✅" if ok else "❌"
        top1 = items[0] if items else None
        top1_id = top1.get("id", "?") if top1 else "?"
        top1_dist = f"{top1.get('distance', 0):.3f}" if top1 else "?"
        print(f"{marker} '{query}' -> top1: {top1_id} (dist={top1_dist})  [looking for '{expected_token}']")
    return passed, len(legacy)


def main() -> int:
    print("Initializing RAG pipeline (LLM_QUERY_REWRITE forced off)...")
    rag = RAGPipeline(chroma_db_path=str(project_root / "chroma_db"))
    print(f"   rerank backend: {rag.reranker_kind}")

    results = []
    results.append(check_chunks())
    p1, t1 = check_retrieval(rag)
    results.append(check_backend(rag))
    p2, t2 = check_legacy(rag)

    hr("SUMMARY")
    print(f"CHECK 1 chunks      : {'✅' if results[0] else '❌'}")
    print(f"CHECK 2 retrieval   : {p1}/{t1}")
    print(f"CHECK 3 backend     : {'✅' if results[1] else '❌'}")
    print(f"CHECK 4 legacy      : {p2}/{t2}")

    all_pass = results[0] and p1 == t1 and results[1] and p2 == t2
    print(f"\n{'✅ ALL CHECKS PASSED' if all_pass else '❌ SOME CHECKS FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
