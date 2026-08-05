"""
RAG Pipeline: Query processing with retrieval and generation
"""
import chromadb
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import sys
import os
import re
import json
import math
from collections import OrderedDict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Force CPU usage for Ollama if OLLAMA_NUM_GPU is set in .env
# This prevents CUDA out of memory errors on servers
if os.getenv("OLLAMA_NUM_GPU") is not None:
    os.environ['OLLAMA_NUM_GPU'] = os.getenv("OLLAMA_NUM_GPU")
elif os.getenv("FORCE_CPU", "false").lower() == "true":
    # Alternative: Use FORCE_CPU=true in .env to disable GPU
    os.environ['OLLAMA_NUM_GPU'] = '0'

# Import intent classifier
from intent_classifier import get_intent_classifier, IntentCategory, IntentType
# Import response templates
from response_templates import get_template, get_welcome_message, get_error_response
# Import error handling
from errors import (
    RetrievalError, LLMError, IntentError, DatabaseError,
    ValidationError, SystemError, handle_error
)
# Import response validator
from response_validator import get_validator
# Import knowledge base
from knowledge_base import get_knowledge_base
# Import LLM provider abstraction
from llm_provider import get_provider
# Import bot identity configuration
from bot_config import get_bot_config, is_robotics, resolve_path


class RAGPipeline:
    def __init__(
        self,
        chroma_db_path: str = "chroma_db",
        collection_name: Optional[str] = None,
        embedding_model: Optional[str] = None,
        llm_model: Optional[str] = None,
        use_reranking: Optional[bool] = None,
        top_k: Optional[int] = None,
        rerank_k: Optional[int] = None
    ):
        """Initialize RAG Pipeline"""
        # Load bot identity config
        self.bot_cfg = get_bot_config()
        
        # Initialize LLM provider (Ollama or OpenAI based on LLM_PROVIDER env var)
        self.provider = get_provider()
        # Model names are owned by the provider; keep as attributes for logging/errors
        self.embedding_model = self.provider.embedding_model
        self.llm_model = self.provider.llm_model
        self.use_reranking = use_reranking if use_reranking is not None else os.getenv("USE_RERANKING", "false").lower() == "true"
        # LLM-based query rewrite for semantic retrieval. When enabled, the
        # user's query is rephrased into 2-3 variants before retrieval to
        # improve recall on paraphrases (replaces the old rule-based
        # synonym/plural expansion which was restaurant-flavored and could
        # not cover robotics vocabulary like "kiosk", "solar", "surveillance").
        self.use_llm_query_rewrite = os.getenv("LLM_QUERY_REWRITE", "true").lower() == "true"
        # FAQ fast-path: when enabled, the system checks FAQ/KB for an exact or
        # high-confidence keyword match BEFORE running expensive semantic search.
        # FAQ hits return in <100ms instead of 3-5s. Set to false to always use
        # semantic search for richer synthesized answers.
        self.faq_fast_path = os.getenv("FAQ_FAST_PATH_ENABLED", "true").lower() == "true"

        # --- NEW (pipeline v2): conditional query rewrite, FAQ cache layer,
        # and hybrid (BM25 + Dense + RRF) retrieval. Each has safe defaults so
        # the pipeline still works if a dependency is missing. ---

        # Conditional query rewrite: only rewrite short / pronoun-bearing /
        # context-bearing queries. Clear, specific queries skip the LLM rewrite
        # entirely, saving ~0.3-0.5s for the majority of traffic.
        self.rewrite_min_words = max(1, int(os.getenv("REWRITE_MIN_WORDS", "4")))
        self.rewrite_on_pronoun = os.getenv("REWRITE_ON_PRONOUN", "true").lower() == "true"

        # FAQ cache layer (layer 1): strict FAQ-question embedding cosine bar.
        # High threshold (0.75) prevents the keyword-overlap "query stealing"
        # bug where "what is chikku brain" was matched to the leadership FAQ.
        self.faq_cache_enabled = os.getenv("FAQ_CACHE_ENABLED", "true").lower() == "true"
        try:
            self.faq_embedding_threshold = float(os.getenv("FAQ_EMBEDDING_THRESHOLD", "0.75"))
        except (ValueError, TypeError):
            self.faq_embedding_threshold = 0.75

        # Filler signal (for the streaming /chat/voice endpoint): when the FAQ
        # cache MISSES (step 3) and the pipeline is about to enter the slow
        # hybrid-retrieval + LLM-generation steps (4-8, ~4-6s), query_stream()
        # emits a {'type': 'filler'} event so the frontend can speak a filler
        # sentence while waiting. The frontend owns the filler text. Setting
        # this to false suppresses only the filler event — the stream still
        # sends the final response normally.
        self.filler_signal_enabled = os.getenv("FILLER_SIGNAL_ENABLED", "true").lower() == "true"

        # Hybrid search (layer 2): BM25 + Dense + RRF fusion.
        self.hybrid_search_enabled = os.getenv("HYBRID_SEARCH_ENABLED", "true").lower() == "true"
        self.bm25_candidates = max(5, int(os.getenv("BM25_CANDIDATES", "20")))
        self.dense_candidates = max(5, int(os.getenv("DENSE_CANDIDATES", "20")))
        try:
            self.rrf_k = max(1, int(os.getenv("RRF_K", "60")))
        except (ValueError, TypeError):
            self.rrf_k = 60

        # BM25 index — lazily built on first hybrid retrieval. None if either
        # rank_bm25 is not installed or the index build failed; in that case
        # _hybrid_retrieve transparently degrades to dense-only retrieval.
        self._bm25 = None
        self._bm25_docs: List[str] = []
        self._bm25_ids: List[str] = []
        self._bm25_metadatas: List[Dict] = []
        try:
            from rank_bm25 import BM25Okapi  # noqa: F401
            self._bm25_available = True
        except ImportError:
            self._bm25_available = False
        
        # Ensure top_k and rerank_k are valid integers (minimum 1)
        # Reduced defaults for faster processing
        env_top_k = os.getenv("TOP_K", "7")
        env_rerank_k = os.getenv("RERANK_K", "4")
        try:
            self.top_k = top_k if top_k is not None else max(1, int(env_top_k))
        except (ValueError, TypeError):
            self.top_k = 10
        
        try:
            self.rerank_k = rerank_k if rerank_k is not None else max(1, int(env_rerank_k))
        except (ValueError, TypeError):
            self.rerank_k = 5

        # Similarity threshold for filtering out irrelevant retrieval results.
        # With cosine distance (hnsw:space=cosine), ChromaDB returns
        # distance = 1 - cosine_similarity, so 0.0 = identical, up to 2.0 = opposite.
        # Any result above this distance is considered irrelevant and dropped.
        # This prevents low-quality context from being fed to the LLM (the main
        # cause of hallucination on out-of-scope queries like "who is your leader?").
        try:
            self.similarity_threshold = float(os.getenv("SIMILARITY_THRESHOLD", "0.55"))
        except (ValueError, TypeError):
            self.similarity_threshold = 0.55
        
        # Setup ChromaDB
        client = chromadb.PersistentClient(path=chroma_db_path)
        if collection_name is None:
            collection_name = self.bot_cfg.collection_name
        self.collection = client.get_collection(name=collection_name)
        
        # Reranking strategy (optional):
        #   "cross_encoder" → FlagEmbedding bge-reranker-v2-m3 (best accuracy
        #                     but loads a 2.2GB model — and on some torch /
        #                     transformers / Windows combos it segfaults at
        #                     load time, which Python cannot catch).
        #   "cosine"        → re-score candidates by cosine similarity using
        #                     the SAME embedding model already used for
        #                     retrieval. Still fully semantic (no keywords),
        #                     cheap, and crash-free. This is the safe default.
        #   "auto"          → prefer cross_encoder, fall back to cosine on any
        #                     init error. NOTE: a segfault cannot be caught,
        #                     so "auto" will NOT save you from a bad torch
        #                     build — set "cosine" explicitly if you see crashes.
        reranker_backend = os.getenv("RERANKER_BACKEND", "cosine").lower().strip()
        self.reranker = None
        self.reranker_kind: str = "none"  # "cross_encoder" | "cosine" | "none"
        if self.use_reranking:
            want_cross_encoder = reranker_backend in ("cross_encoder", "auto")
            if want_cross_encoder:
                try:
                    from FlagEmbedding import FlagReranker
                    self.reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)
                    self.reranker_kind = "cross_encoder"
                    print("✅ Reranking: FlagEmbedding cross-encoder (bge-reranker-v2-m3)")
                except ImportError:
                    print("⚠️  FlagEmbedding not installed — using cosine re-rank instead.")
                    print("   Install for cross-encoder accuracy: pip install FlagEmbedding")
                    self.reranker_kind = "cosine"
                except Exception as e:
                    print(f"⚠️  Cross-encoder init failed: {e}")
                    if reranker_backend == "auto":
                        print("   Falling back to cosine re-rank (auto mode).")
                        self.reranker_kind = "cosine"
                    else:
                        print("   Set RERANKER_BACKEND=cosine or auto to avoid this.")
                        raise
            else:
                self.reranker_kind = "cosine"
                print("✅ Reranking: cosine re-rank (semantic, lightweight)")
        else:
            print("ℹ️  Reranking disabled (set USE_RERANKING=true in .env to enable)")
        
        print(f"✅ RAG Pipeline initialized")
        print(f"   Embedding model: {self.embedding_model}")
        print(f"   LLM model: {self.llm_model}")
        print(f"   Top K: {self.top_k}")
        print(f"   Rerank K: {self.rerank_k}")
        print(f"   Similarity threshold: {self.similarity_threshold}")
        print(f"   Reranking: {'enabled' if self.use_reranking else 'disabled'}")
        print(f"   LLM query rewrite: {'enabled' if self.use_llm_query_rewrite else 'disabled'}")
        print(f"   FAQ fast-path: {'enabled' if self.faq_fast_path else 'disabled'}")
        print(f"   FAQ cache layer: {'enabled' if self.faq_cache_enabled else 'disabled'} "
              f"(cosine≥{self.faq_embedding_threshold})")
        print(f"   Filler signal: {'enabled' if self.filler_signal_enabled else 'disabled'} "
              f"(streaming /chat/voice)")
        print(f"   Hybrid search: {'enabled' if self.hybrid_search_enabled else 'disabled'} "
              f"(BM25={'available' if self._bm25_available else 'MISSING (dense-only fallback)'}, "
              f"RRF k={self.rrf_k})")
        print(f"   Conditional rewrite: min_words={self.rewrite_min_words}, "
              f"on_pronoun={self.rewrite_on_pronoun}")

        # Load system prompt from file (configurable via BOT_IDENTITY in .env)
        self.base_system_prompt: str = ""
        try:
            prompt_path = resolve_path(self.bot_cfg.system_prompt_file)
            if prompt_path.exists():
                self.base_system_prompt = prompt_path.read_text(encoding="utf-8").strip()
                print(f"✅ Loaded system prompt from {prompt_path.name}")
            else:
                print(f"⚠️  System prompt file not found: {prompt_path}")
        except Exception as e:
            print(f"⚠️  Failed to load system prompt file: {e}")

        # Load static company information from about file for use in system prompt
        self.company_info: str = ""
        try:
            about_path = resolve_path(self.bot_cfg.about_file)
            if about_path.exists():
                text = about_path.read_text(encoding="utf-8").strip()
                if text:
                    self.company_info = text
                    print(f"✅ Loaded company information from {about_path.name}")
                else:
                    print(f"⚠️  {about_path.name} is empty, company info section will be omitted")
            else:
                print(f"⚠️  {about_path.name} not found, company info section will be omitted")
        except Exception as e:
            print(f"⚠️  Failed to load {self.bot_cfg.about_file}: {e}")
            self.company_info = ""
        
        # Load knowledge base
        self.knowledge_base = get_knowledge_base()
        print("✅ Knowledge base initialized")

        # Simple in-memory retrieval cache (for menu queries)
        self.enable_cache = os.getenv("RAG_CACHE_ENABLED", "true").lower() == "true"
        self.cache_max_size = max(10, int(os.getenv("RAG_CACHE_MAX_SIZE", "100")))
        # key: (query, top_k, doc_type) -> list[Dict]
        self._retrieval_cache: "OrderedDict[Tuple[str, int, Optional[str]], List[Dict]]" = OrderedDict()
        
        # Embedding cache (for faster repeated queries)
        self.enable_embedding_cache = os.getenv("EMBEDDING_CACHE_ENABLED", "true").lower() == "true"
        self.embedding_cache_max_size = max(50, int(os.getenv("EMBEDDING_CACHE_MAX_SIZE", "200")))
        # key: query_text -> List[float]
        self._embedding_cache: "OrderedDict[str, List[float]]" = OrderedDict()

        # Query-rewrite cache (LLM rephrasings) — key: original query -> List[str]
        self._rewrite_cache: "OrderedDict[str, List[str]]" = OrderedDict()
        self._rewrite_cache_max_size = max(20, int(os.getenv("QUERY_REWRITE_CACHE_MAX_SIZE", "100")))

        # Dedicated rewrite/STT-correction provider (small fast LOCAL model by
        # default — see llm_provider.get_rewrite_provider). Separate from the
        # main generation provider so e.g. OpenAI generation can coexist with
        # a local Ollama rewriter. None → rewrite silently disabled.
        from llm_provider import get_rewrite_provider
        self._rewrite_provider = get_rewrite_provider()
        self.rewrite_glossary_enabled = os.getenv("REWRITE_GLOSSARY_ENABLED", "true").lower() == "true"
        self._entity_glossary: Optional[Dict] = None  # lazily loaded on first rewrite

        # Multi-hop query decomposition (compare/multi-entity questions).
        # OFF by default — opt-in via env for users who ask many comparison
        # questions. When ON, queries containing compare/vs/and/difference
        # markers are split into sub-queries by the rewrite LLM and each is
        # retrieved separately, then results are merged (deduped).
        self.query_decompose_enabled = os.getenv("QUERY_DECOMPOSE_ENABLED", "false").lower() == "true"

        # Context construction budget (after retrieval, before LLM).
        # Truncates the deduped/reordered context so it never exceeds this
        # many approximate tokens (4 chars ≈ 1 token).
        try:
            self.max_context_tokens = max(256, int(os.getenv("MAX_CONTEXT_TOKENS", "1500")))
        except (ValueError, TypeError):
            self.max_context_tokens = 1500

    def _load_entity_glossary(self) -> Dict:
        """Lazily load data/entity_glossary.json for rewrite prompt injection.

        Cached on the instance. Returns {} if missing — rewrite still works
        but without the canonical-vocabulary hint (slightly worse on STT
        errors for proper nouns).
        """
        if self._entity_glossary is not None:
            return self._entity_glossary
        try:
            gp = Path(__file__).parent.parent / "data" / "entity_glossary.json"
            if gp.exists():
                self._entity_glossary = json.loads(gp.read_text(encoding="utf-8"))
            else:
                self._entity_glossary = {}
        except Exception as e:
            print(f"⚠️  Entity glossary load failed: {e}")
            self._entity_glossary = {}
        return self._entity_glossary

    def _greeting(self) -> str:
        """Robotics greeting."""
        return "Hello!"

    def _role_description(self) -> str:
        """Role description for user prompts."""
        return f"an intelligent service robot at {self.bot_cfg.company_name}"

    def _context_label(self) -> str:
        """Label for context section in user prompts."""
        return "Reference Information"

    def _identity_fallback_prompt(self, context: str) -> str:
        """Fallback system prompt (when system_prompt file missing)."""
        return f"You are Chikku, an intelligent service robot representing {self.bot_cfg.company_name}. {self.bot_cfg.company_tagline}\n\nReference Context:\n{context}"

    def _get_contact_fallback(self) -> str:
        """Identity-aware fallback phone/contact."""
        if self.bot_cfg.fallback_phone:
            return self.bot_cfg.fallback_phone
        if self.bot_cfg.fallback_email:
            return self.bot_cfg.fallback_email
        return ""

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text (with caching)"""
        # Normalize text for cache key
        cache_key = text.strip().lower()
        
        # Check embedding cache first
        if self.enable_embedding_cache and cache_key in self._embedding_cache:
            # Move to end (LRU)
            embedding = self._embedding_cache.pop(cache_key)
            self._embedding_cache[cache_key] = embedding
            return embedding
        
        # Generate embedding
        try:
            embedding = self.provider.embed(text)
            
            # Cache embedding
            if self.enable_embedding_cache:
                if len(self._embedding_cache) >= self.embedding_cache_max_size:
                    # Remove oldest (first) item
                    self._embedding_cache.popitem(last=False)
                self._embedding_cache[cache_key] = embedding
            
            return embedding
        except Exception as e:
            raise RetrievalError(f"Failed to generate embedding: {str(e)}", query=text)
    
    def retrieve(
        self, query: str, top_k: int = 10, doc_type: Optional[str] = None,
        query_embedding: Optional[List[float]] = None
    ) -> List[Dict]:
        """Retrieve relevant items from ChromaDB.

        Args:
            query: the user query (or rewrite variant)
            top_k: number of results to return
            doc_type: optional 'menu' or 'about' filter
            query_embedding: optional pre-computed embedding for `query`.
                When provided for the SAME query string, the caller avoids a
                duplicate embedding call (intent classification + retrieval
                can share one embedding).
        """
        cache_key = (query, top_k, doc_type)

        # Check cache first
        if self.enable_cache and cache_key in self._retrieval_cache:
            print(f"🧠 Using cached retrieval results for query: '{query}'")
            # Move to end to mark as recently used
            items = self._retrieval_cache.pop(cache_key)
            self._retrieval_cache[cache_key] = items
            return items[:top_k]

        # Get query embedding (reuse caller's if provided and query unchanged)
        if query_embedding is not None:
            q_emb = query_embedding
        else:
            q_emb = self.get_embedding(query)
        
        # Always query without filter first (for backward compatibility)
        # Then filter manually if doc_type is specified
        query_params = {
            "query_embeddings": [q_emb],
            "n_results": top_k * 2 if doc_type else top_k  # Get more if we need to filter
        }
        
        # Search in ChromaDB (without doc_type filter for backward compatibility)
        results = self.collection.query(**query_params)

        # Format results, dropping anything below the similarity threshold.
        # This is the primary hallucination guard: without it ChromaDB always
        # returns top_k chunks regardless of relevance, flooding the LLM context
        # with irrelevant text that it then "synthesizes" into fabricated facts.
        retrieved_items = []
        if results['ids'] and len(results['ids'][0]) > 0:
            for i in range(len(results['ids'][0])):
                distance = results['distances'][0][i]
                if distance > self.similarity_threshold:
                    continue  # too dissimilar — skip
                item = {
                    'id': results['ids'][0][i],
                    'distance': distance,
                    'document': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i]
                }
                retrieved_items.append(item)
        
        # Filter by doc_type if requested
        # Menu items are identified by item_name presence (ingestion.py never sets doc_type on them).
        # About docs have doc_type="about" set explicitly by ingest_about.py.
        # Never use has_doc_type branch — it drops all menu items when any about doc appears in results.
        if doc_type and retrieved_items:
            if doc_type == "menu":
                retrieved_items = [item for item in retrieved_items
                                   if item.get('metadata', {}).get('item_name')]
            elif doc_type == "about":
                retrieved_items = [item for item in retrieved_items
                                   if item.get('metadata', {}).get('doc_type') == 'about']

            # Trim to requested top_k after filtering
            retrieved_items = retrieved_items[:top_k]
        
        # Cache the results
        if self.enable_cache:
            self._retrieval_cache[cache_key] = retrieved_items
            # Evict least recently used if cache is too big
            if len(self._retrieval_cache) > self.cache_max_size:
                self._retrieval_cache.popitem(last=False)
        
        return retrieved_items
    
    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Cosine similarity between two vectors. Returns 0.0 on degenerate input."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / math.sqrt(na * nb)

    def rerank(self, query: str, items: List[Dict], top_k: int = 5) -> List[Dict]:
        """Rerank retrieved items using the configured backend.

        - cross_encoder : FlagEmbedding bge-reranker-v2-m3 (query/doc pairs)
        - cosine        : re-score by cosine similarity between the query
                          embedding and each candidate's text embedding, using
                          the SAME embedding model used for retrieval. This is
                          semantic (no keyword matching) and crash-free.
        """
        # Ensure top_k is at least 1
        top_k = max(1, int(top_k))

        if not items:
            return items

        # Backend dispatch
        if not self.use_reranking or self.reranker_kind == "none":
            return items[:top_k]

        # --- Cross-encoder path ---
        if self.reranker_kind == "cross_encoder" and self.reranker is not None:
            pairs = [[query, item.get('document', '')] for item in items]
            try:
                scores = self.reranker.compute_score(pairs)
                if not isinstance(scores, list):
                    scores = [scores]
                for i, item in enumerate(items):
                    item['rerank_score'] = float(scores[i]) if i < len(scores) else 0.0
                items.sort(key=lambda x: x.get('rerank_score', 0.0), reverse=True)
                return items[:top_k]
            except Exception as e:
                # Cross-encoder failed at scoring time — degrade gracefully to
                # cosine rather than returning an unranked list.
                print(f"⚠️  Cross-encoder scoring failed, using cosine re-rank: {e}")

        # --- Cosine path (fallback or configured default) ---
        # Re-score every candidate against the query embedding. Candidates come
        # from ChromaDB which doesn't expose stored embeddings via the query()
        # API in a stable way, so we re-embed candidate texts here. This costs
        # one batched embed call per rerank — acceptable for a shortlist.
        try:
            query_emb = self.get_embedding(query)
            for item in items:
                doc_emb = self.get_embedding(item.get('document', ''))
                item['rerank_score'] = self._cosine_similarity(query_emb, doc_emb)
            items.sort(key=lambda x: x.get('rerank_score', 0.0), reverse=True)
        except Exception as e:
            # Last resort: keep ChromaDB's distance ordering (already semantic)
            print(f"⚠️  Cosine re-rank failed, keeping retrieval order: {e}")
            items.sort(key=lambda x: x.get('distance', 999.0))

        return items[:top_k]

    def format_context(self, items: List[Dict]) -> str:
        """Format retrieved items as context for LLM (generic text chunks).

        Delegates to _construct_context, which applies deduplication,
        lost-in-the-middle reordering, and length truncation before formatting.
        """
        constructed = self._construct_context(items)
        return self._format_context_generic(constructed)

    def _format_context_generic(self, items: List[Dict]) -> str:
        """Format retrieved text chunks generically (for non-menu identities like robotics)"""
        context_parts = []
        for i, item in enumerate(items):
            doc = item.get('document', '')
            if doc:
                context_parts.append(f"[{i+1}] {doc}")
        return "\n\n".join(context_parts)

    def _construct_context(self, items: List[Dict]) -> List[Dict]:
        """Dedup + reorder + truncate the retrieved shortlist for the LLM.

        Implements three context-quality improvements before formatting:
          1. DEDUP — collapse near-duplicate chunks (same normalized text),
             keeping the highest-scored copy. Hybrid retrieval + KB enrichment
             often surface the same fact via multiple paths; feeding duplicates
             wastes context budget and biases the LLM toward repeated facts.
          2. REORDER — mitigate "lost in the middle": LLMs attend best to the
             START and END of a long context, so we place the most-relevant
             chunks at the extremes and the least-relevant in the middle.
             Relevance ≈ rerank_score (or inverse distance as fallback).
          3. TRUNCATE — cap total context length at MAX_CONTEXT_TOKENS (≈4
             chars/token) by dropping the lowest-relevance chunks first.

        Input items are assumed already reranked (highest relevance first) by
        the caller. Returns a NEW list (does not mutate input).
        """
        if not items:
            return []

        # --- 1. Dedup by normalized document text ---
        seen: set = set()
        deduped: List[Dict] = []
        for item in items:
            doc = (item.get('document', '') or '').strip()
            if not doc:
                continue
            # Normalize: collapse whitespace, lowercase, strip the
            # contextual-retrieval <Context: ...> prefix so two chunks that
            # differ only in their generated context are treated as dupes.
            norm_body = re.sub(r'<Context:.*?>\n?', '', doc, flags=re.DOTALL)
            norm = re.sub(r'\s+', ' ', norm_body.lower()).strip()
            # Use a signature of the first ~300 chars — full-text dedup is
            # expensive and unnecessary; prefix overlap catches real dupes.
            sig = norm[:300]
            if sig in seen:
                continue
            seen.add(sig)
            deduped.append(item)

        if not deduped:
            return []

        # Relevance score for ordering: prefer rerank_score, fall back to
        # inverse distance, then to original rank order.
        def _relevance(item: Dict, idx: int) -> float:
            if 'rerank_score' in item:
                try:
                    return float(item['rerank_score'])
                except (TypeError, ValueError):
                    pass
            dist = item.get('distance')
            try:
                # cosine distance 0..2 → higher relevance = lower distance
                return 1.0 - float(dist)
            except (TypeError, ValueError):
                return -idx  # stable fallback: earlier = more relevant

        ranked = sorted(
            enumerate(deduped),
            key=lambda pair: _relevance(pair[1], pair[0]),
            reverse=True,
        )
        ordered_by_rel = [item for _, item in ranked]

        # --- 2. Truncate to token budget (drop lowest-relevance first) ---
        # Approximate tokens as len(text)//4. Drop from the END (lowest rel)
        # until we fit. Always keep at least the top-1 chunk.
        budget_chars = self.max_context_tokens * 4
        kept: List[Dict] = []
        total = 0
        for item in ordered_by_rel:
            doc_len = len((item.get('document', '') or ''))
            if kept and total + doc_len > budget_chars:
                break
            kept.append(item)
            total += doc_len

        if not kept:
            kept = [ordered_by_rel[0]]

        # --- 3. Lost-in-the-middle reordering ---
        # We have `kept` sorted by relevance DESC. Interleave so the most-
        # relevant chunks land at positions 0, n-1, 2, n-3, ... (start+end
        # emphasis). Concretely: take pairs from the front and place one at
        # the head and one at the tail of the output, alternating.
        if len(kept) <= 2:
            return kept
        # Split into two halves; reverse the second half; interleave.
        mid = (len(kept) + 1) // 2
        front = kept[:mid]            # most relevant (DESC)
        back = list(reversed(kept[mid:]))  # least relevant, reversed
        # Interleave: front[0], back[0], front[1], back[1], ...
        # Because back is shorter (or equal), append remaining front at end.
        interleaved: List[Dict] = []
        for i in range(mid):
            interleaved.append(front[i])
            if i < len(back):
                interleaved.append(back[i])
        return interleaved

    def _company_info_section(self) -> str:
        """
        Build a company information section for the system prompt from the about file.
        This is static knowledge (address, description, products), separate from RAG retrieval.
        """
        if not self.company_info:
            return ""
        return (
            f"\n\nCOMPANY INFORMATION (for internal reference):\n"
            f"{self.company_info}\n"
        )
    
    def _is_new_session(self, conversation_history: Optional[List[Dict]]) -> bool:
        """
        Check if this is a new conversation session (no previous messages).
        Returns True if conversation_history is None or empty.
        """
        return not conversation_history or len(conversation_history) == 0
    
    def _get_welcome_message(self) -> str:
        """
        Returns the merged welcome message that should be shown only once per session.
        """
        return get_welcome_message()
    
    def _sanitize_conversation_history(self, history: List[Dict]) -> List[Dict]:
        """
        Sanitize conversation history to prevent hallucination.
        Only includes user queries, not full assistant responses.
        This allows contextual understanding without copying wrong responses.
        """
        if not history:
            return []
        
        sanitized = []
        for msg in history:
            if msg.get('role') == 'user':
                # Include user queries - they provide context for understanding references
                sanitized.append({
                    "role": "user",
                    "content": msg.get('content', '')
                })
            # Skip assistant messages - they can cause contamination
            # The retrieved items in context are sufficient for generating responses
        
        return sanitized
    
    def _build_system_prompt(self, context: str, conversation_history: Optional[List[Dict]] = None) -> str:
        """
        Build the complete system prompt with welcome message (only for new sessions) and restaurant info.
        
        NOTE: We intentionally ignore SYSTEM_PROMPT.md and always use this strong, inline prompt,
        so that menu queries cannot fall back to a weaker external prompt that allows AI disclaimers.
        """
        # Check if this is a new session
        is_new_session = self._is_new_session(conversation_history)
        
        # Load base prompt from file, fall back to minimal inline prompt
        if self.base_system_prompt:
            base_prompt = self.base_system_prompt.replace('{context}', context)
        else:
            base_prompt = self._identity_fallback_prompt(context)
        
        # Add welcome message section if this is a new session
        welcome_section = ""
        if is_new_session:
            welcome_section = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━
WELCOME MESSAGE TO USE (ONLY FOR FIRST MESSAGE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━

When the user sends their first message (greeting, "who are you", or any query), respond with this exact welcome message:

{self._get_welcome_message()}

CRITICAL: Only show this welcome message ONCE at the very beginning of a new conversation. After showing it, continue normally and NEVER repeat it again in the same session.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Inject static company information (about file) into the system prompt
        company_info_section = self._company_info_section()
        
        # Combine all parts
        final_prompt = base_prompt + welcome_section + company_info_section
        
        return final_prompt
    
    def generate_response_stream(
        self,
        query: str,
        context: str,
        conversation_history: Optional[List[Dict]] = None
    ):
        """Generate streaming response using LLM"""
        # Build system prompt with welcome message (only for new sessions) and restaurant info
        system_prompt = self._build_system_prompt(context, conversation_history)
        
        # Build messages with conversation history
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history (last few messages for context)
        # Reduced from 6 to 4 for faster processing
        if conversation_history:
            for msg in conversation_history[-4:]:  # Last 4 messages for context
                if msg.get('role') in ['user', 'assistant']:
                    messages.append({
                        "role": msg['role'],
                        "content": msg['content']
                    })
        
        # Add current query with explicit instructions
        greeting = self._greeting()
        context_label = self._context_label()
        role_desc = self._role_description()
        user_prompt = f"""Customer Question: {query}

CRITICAL INSTRUCTIONS:
1. Start with "{greeting}" followed by an appropriate emoji 🤖
2. Answer the question using ONLY the {context_label} below
3. If the user asks about a SPECIFIC entity (e.g. "Tell me about S-Robot", "the kiosk"), focus on THAT entity only — do NOT list all products unless the user asks for all of them.
4. If the user genuinely asks about MULTIPLE entities ("what robots do you have", "compare X and Y"), then include all of them.
5. Synthesize naturally — don't copy-paste, never read metadata or "<Context: ...>" prefixes aloud
6. End with a warm follow-up question
7. You ARE Chikku, {role_desc} - speak naturally

GROUNDING (MOST IMPORTANT):
- If the {context_label} does NOT contain the answer, say: "I don't have that exact detail handy, but I'd love to tell you about what we do! What would you like to know?"
- NEVER invent names, people, numbers, or facts not present in the {context_label}.
- Do NOT use general world knowledge about leadership, people, or companies.

{context_label}:
{context}

Respond naturally as Chikku."""
        messages.append({"role": "user", "content": user_prompt})
        
        try:
            print(f"🔄 Streaming LLM response ({self.llm_model})...")
            
            llm_options = {
                "max_tokens": 500,
                "temperature": 0.4,
                "top_p": 0.9,
                "num_ctx": 2048,
            }

            full_response = ""
            for content in self.provider.stream_chat(messages, llm_options):
                full_response += content
                yield content
            
            # Validate full response after streaming (if enabled)
            # Note: For streaming, we can't modify the stream, but we log validation issues
            if full_response:
                validator = get_validator()
                validation = validator.validate(full_response, query=query, context_provided=bool(context))
                
                if not validation['valid']:
                    print(f"⚠️  Streamed response validation failed (score: {validation['score']:.2f})")
                    print(f"   Issues: {validation['issues']}")
                    # Note: Streamed responses are already sent, so we can't modify them
                    # This is mainly for monitoring/logging purposes
                        
        except Exception as e:
            print(f"❌ LLM streaming error: {str(e)}")
            yield f"\n\n[Error: {str(e)}]"
    
    def generate_response(
        self,
        query: str,
        context: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """Generate response using LLM with semantic context."""
        
        system_prompt = self._build_system_prompt(context, conversation_history)
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-6:]:
                if msg.get('role') == 'user':
                    messages.append({"role": "user", "content": msg.get('content', '')})
        
        # Build user prompt optimized for semantic knowledge retrieval
        greeting = self._greeting()
        role_desc = self._role_description()
        context_label = self._context_label()
        user_prompt = f"""Customer Question: {query}

CRITICAL INSTRUCTIONS:
1. Start with "{greeting}" followed by an appropriate emoji 🤖
2. Answer the question using ONLY the {context_label} below
3. If the user asks about a SPECIFIC entity (e.g. "Tell me about S-Robot", "the kiosk", "Tell me about S robot"), focus on THAT entity only — do NOT list all products unless the user asks for all of them.
4. If the user genuinely asks about MULTIPLE entities ("what robots do you have", "compare X and Y"), then include all of them.
5. Be complete and thorough for the chosen entity — the customer wants a substantive answer (2-5 sentences depending on complexity)
6. Synthesize information naturally — don't just copy-paste, never read metadata or "<Context: ...>" prefixes aloud
7. End with a warm follow-up question

GROUNDING (MOST IMPORTANT):
- If the {context_label} does NOT contain the answer, say: "I don't have that exact detail handy, but I'd love to tell you about what we do! What would you like to know?"
- NEVER invent names, people, numbers, or facts not present in the {context_label}.
- Do NOT use general world knowledge about leadership, people, or companies.

FORBIDDEN PHRASES - NEVER USE:
- "I'm an AI" or "as an AI" or "AI model"
- "based on my capabilities" or "within this context"
- "retrieved items", "validation", "according to the reference"
- Menu/food/restaurant terms (you are a robotics company representative)

{context_label}:
{context}

Respond naturally as Chikku — be warm, knowledgeable, and enthusiastic about robotics!"""
        messages.append({"role": "user", "content": user_prompt})
        
        try:
            print(f"🔄 Calling LLM ({self.llm_model})...")
            
            llm_options = {
                "max_tokens": 500,
                "temperature": 0.2,
                "top_p": 0.85,
                "num_ctx": 2048,
            }

            result = self.provider.chat(messages, llm_options)
            print(f"✅ LLM response received")
            if not result or len(result.strip()) == 0:
                return "I couldn't generate a response. Please try rephrasing your query."
            
            # Validate response quality (if enabled)
            validator = get_validator()
            validation = validator.validate(result, query=query, context_provided=bool(context))
            
            if not validation['valid']:
                print(f"⚠️  Response validation failed (score: {validation['score']:.2f})")
                if validator.enabled:
                    result = validation['cleaned_response']
                    print(f"✅ Using cleaned response")
            
            return result
        except Exception as e:
            print(f"❌ LLM error: {str(e)}")
            import traceback
            traceback.print_exc()
            error_msg = handle_error(LLMError(str(e), model=self.llm_model), context={
                "query": query, "model": self.llm_model
            })
            return error_msg
    
    def _classify_intent(self, query: str):
        """
        Classify query intent using intent classifier.
        Returns IntentResult object.
        """
        try:
            classifier = get_intent_classifier()
            return classifier.classify_intent(query)
        except Exception as e:
            print(f"⚠️  Intent classification error: {str(e)}")
            from intent_classifier import IntentResult, IntentType, IntentCategory
            return IntentResult(
                intent_type=IntentType.CLARIFICATION_NEEDED,
                confidence=0.3,
                category=IntentCategory.CLARIFICATION,
                requires_clarification=True
            )

    def _classify_intent_with_embedding(self, query: str):
        """Classify intent and opportunistically return the query embedding.

        The embedding-based classifier embeds the query internally; we re-fetch
        it once more here ONLY if classification fell back to regex mode (in
        which case no embedding was computed). When embedding mode ran, the
        cached embedding from get_embedding() (same query, LRU cache) is
        returned with no extra cost — so retrieval can share it.

        Returns (IntentResult, Optional[List[float]]).
        """
        intent_result = self._classify_intent(query)
        query_embedding = None
        try:
            # The embedding cache (LRU keyed by stripped+lower) makes this a
            # no-op when the classifier already embedded the same query.
            query_embedding = self.get_embedding(query)
        except Exception:
            pass  # retrieval will embed on its own
        return intent_result, query_embedding

    def _try_faq_answer(self, query: str) -> Optional[str]:
        """
        Smart knowledge base search — tries FAQ exact matching FIRST
        (most precise for factoid questions like "who is the owner"),
        then falls back to topic-aware KB search for broader queries.
        Returns formatted answer string if found, None otherwise.
        """
        # Step 1: FAQ exact/keyword matching FIRST — most precise source.
        # FAQ has curated Q&A pairs like "Who is your owner?" → answer.
        # This catches queries with slight wording variations (e.g.
        # "who is the owner" vs "who is your owner") via word-overlap scoring.
        answer = self.knowledge_base.get_best_faq_match(query)
        if answer:
            print(f"📋 Found FAQ answer for: '{query[:80]}...'")
            return f"{answer}\n\nIs there anything else I can help you with? 😊"
        
        # Step 2: Fallback to topic-aware KB search (searches structured JSON
        # sections like identity.json, products.json, etc. by keyword topic).
        kb_answer = self.knowledge_base.search_knowledge_base(query)
        if kb_answer:
            print(f"📋 Found KB answer (topic-aware) for: '{query[:80]}...'")
            return kb_answer
        
        return None
    
    def answer_about_or_identity(self, query: str, conversation_history: Optional[List[Dict]] = None, intent_result=None) -> str:
        """
        Generate response for identity/about queries without menu retrieval.
        Uses deterministic welcome message for identity queries to prevent LLM hallucinations.
        """
        query_lower = query.lower().strip()
        is_new_session = self._is_new_session(conversation_history)

        # Check if it's a greeting/identity query.
        # Use word-boundary matching for short tokens to avoid false positives
        # (e.g. bare substring 'hi' matching inside "chikku", or 'hey' in "they").
        def _has_phrase(phrase: str) -> bool:
            if len(phrase) <= 4:
                return bool(re.search(r'\b' + re.escape(phrase) + r'\b', query_lower))
            return phrase in query_lower

        is_greeting = any(_has_phrase(phrase) for phrase in [
            'who are you', 'what are you', 'who is chikku', 'what is chikku',
            'hello', 'hi', 'hey', 'namaste', 'greetings'
        ])
        
        # Check if it's an "about" query (identity-aware)
        if is_robotics():
            is_about_query = any(phrase in query_lower for phrase in [
                'tell me about', 'about chikku', 'about robotics', 'about the company',
                'what is chikku robotics', 'who is chikku robotics'
            ])
        else:
            is_about_query = any(phrase in query_lower for phrase in [
                'tell me about', 'about saigon', 'about restaurant', 'about the restaurant'
            ])

        # Leadership/founder queries are handled by the semantic RAG path in query(),
        # NOT here. They are excluded from the deterministic intent set so they flow
        # through ChromaDB retrieval → LLM synthesis (proper RAG). Nothing to do here.

        # DETERMINISTIC: Use templates for identity queries
        # This prevents LLM from hallucinating ChatGPT responses
        if is_greeting:
            if intent_result and intent_result.intent_type:
                template = get_template(intent_result.intent_type)
                if template:
                    if is_new_session and intent_result.intent_type == IntentType.IDENTITY_WHO_ARE_YOU:
                        print("✅ Returning welcome message (deterministic, new session)")
                        return template
                    elif not is_new_session:
                        print("✅ Returning identity response (deterministic)")
                        return template

            # Fallback
            if is_new_session:
                print("✅ Returning welcome message (deterministic, new session)")
                return self._get_welcome_message()
            else:
                print("✅ Returning identity response (deterministic)")
                company_name = self.bot_cfg.company_name
                if is_robotics():
                    return f"I'm Chikku, an intelligent service robot at {company_name}. {self.bot_cfg.company_tagline} I'm here to tell you all about our AI and robotics work! What would you like to know? 🤖"
                return f"I'm Chikku, your personal food companion, flavor guide, and menu expert at {company_name}. I'm here to help you discover the perfect dish! What are you craving today? 😊"

        # Check if template exists for restaurant info queries
        # Use knowledge base data to populate templates
        if intent_result and intent_result.intent_type:
            # Use knowledge base for restaurant info queries
            if intent_result.intent_type == IntentType.RESTAURANT_LOCATION:
                kb_location = self.knowledge_base.format_location()
                if kb_location:
                    print(f"✅ Using knowledge base for location")
                    return kb_location
            
            elif intent_result.intent_type == IntentType.RESTAURANT_HOURS:
                kb_hours = self.knowledge_base.format_hours()
                if kb_hours:
                    print(f"✅ Using knowledge base for hours")
                    return kb_hours
            
            elif intent_result.intent_type == IntentType.RESTAURANT_CONTACT:
                kb_contact = self.knowledge_base.format_contact()
                if kb_contact:
                    print(f"✅ Using knowledge base for contact")
                    return kb_contact
            
            elif intent_result.intent_type == IntentType.RESTAURANT_PARKING:
                if is_robotics():
                    # Robotics: no parking info — fall through to template or generic response
                    template = get_template(intent_result.intent_type)
                    if template:
                        print(f"✅ Using template for {intent_result.intent_type.value}")
                        return template
                    # Generic fallback
                    return f"I don't have specific parking information, but you can reach us at {self._get_contact_fallback()} and our team will be happy to assist! 😊"
                else:
                    accessibility = self.knowledge_base.get_accessibility()
                    if accessibility and accessibility.get('parking'):
                        parking_info = accessibility['parking']
                        contact = self._get_contact_fallback() or "+84 (028) 6291 3672"
                        return f"""🅿️ **Parking Information**

{parking_info.get('alternatives', 'Street parking available')}

For the best parking options, I'd recommend calling us at {contact}, and our team can guide you to the nearest parking! 😊"""
            
            elif intent_result.intent_type == IntentType.RESTAURANT_ACCESSIBILITY:
                if is_robotics():
                    # Robotics: no specific accessibility info — fall through to template or generic
                    template = get_template(intent_result.intent_type)
                    if template:
                        print(f"✅ Using template for {intent_result.intent_type.value}")
                        return template
                    return f"For accessibility-related questions, please reach out to us at {self._get_contact_fallback()}. We're committed to making our technology accessible to everyone! 😊"
                else:
                    accessibility = self.knowledge_base.get_accessibility()
                    if accessibility:
                        wheelchair = accessibility.get('wheelchair_access', {})
                        contact = self._get_contact_fallback() or "+84 (028) 6291 3672"
                        return f"""♿ **Accessibility**

We're committed to making our space accessible to all guests. We are located on the ground floor with easy access.

{wheelchair.get('details', 'Ground floor with easy access')}

For specific accessibility needs or questions, please call us at {contact}, and we'll be happy to assist you! 😊"""
            
            # Check template as fallback
            template = get_template(intent_result.intent_type)
            if template:
                print(f"✅ Using template for {intent_result.intent_type.value}")
                return template
        
        # For "about" queries without template, use knowledge base or LLM
        if is_about_query:
            # Try knowledge base first
            kb_info = self.knowledge_base.get_restaurant_info_text()
            company_name = self.bot_cfg.company_name
            if kb_info:
                print("📋 Using knowledge base for about query")
                return f"""Welcome to {company_name}! ✨

{kb_info}

I'm Chikku, your intelligent assistant here. How can I help you today?"""
            
            # Fallback to LLM with company info
            # Initialize system_prompt from the base prompt so it is always bound,
            # even when company_info is empty (prevents a NameError below).
            system_prompt = self._build_system_prompt(
                f"COMPANY INFORMATION:\n{self.company_info}" if self.company_info else "",
                conversation_history,
            )
            if self.company_info:
                print("📋 Generating about response using company info...")

            # Build messages with VERY STRICT instructions
            messages = [{"role": "system", "content": system_prompt}]
            
            # Add conversation history
            if conversation_history:
                for msg in conversation_history[-4:]:
                    if msg.get('role') in ['user', 'assistant']:
                        messages.append({
                            "role": msg['role'],
                            "content": msg['content']
                        })
            
            # Add user query with STRICT instructions
            company_name = self.bot_cfg.company_name
            info_label = "Company Information" if is_robotics() else "Restaurant Information"
            user_prompt = f"""Query: {query}

CRITICAL INSTRUCTIONS:
- You are Chikku, {self._role_description()}.
- You are NOT an AI model, NOT ChatGPT, NOT a language model.
- Answer using ONLY the information provided below.
- Sound warm, human, and professional.
- NEVER mention AI, ChatGPT, models, or technology.

{info_label}:
{self.company_info}

Now answer the query naturally as Chikku."""
            
            messages.append({"role": "user", "content": user_prompt})
            
            try:
                print(f"🔄 Generating about response ({self.llm_model})...")
                
                llm_options = {
                    "max_tokens": 300,
                    "temperature": 0.4,
                    "top_p": 0.9,
                    "num_ctx": 2048,
                }

                result = self.provider.chat(messages, llm_options).strip()
                
                # Safety check: if response contains AI disclaimers, use fallback
                ai_keywords = ['chatgpt', 'ai model', 'language model', 'artificial intelligence', 'openai', 'google']
                if any(keyword in result.lower() for keyword in ai_keywords):
                    print("⚠️  LLM generated AI disclaimer, using fallback")
                    # Return company info directly formatted nicely
                    company_name = self.bot_cfg.company_name
                    return f"""Welcome to {company_name}! ✨

{self.company_info}

I'm Chikku, your intelligent assistant here. How can I help you today?"""
                
                if result:
                    return result
                else:
                    # Fallback
                    company_name = self.bot_cfg.company_name
                    return f"""Welcome to {company_name}! ✨

{self.company_info}

I'm Chikku, your intelligent assistant here. How can I help you today?"""
            except Exception as e:
                print(f"❌ LLM error in answer_about_or_identity: {str(e)}")
                # Fallback
                company_name = self.bot_cfg.company_name
                return f"""Welcome to {company_name}! ✨

{self.company_info}

I'm Chikku, your intelligent assistant here. How can I help you today?"""
        
        # Default fallback — try FAQ before giving a generic response
        faq_answer = self._try_faq_answer(query)
        if faq_answer:
            print(f"✅ Answered from FAQ (final fallback)")
            return faq_answer
        
        company_name = self.bot_cfg.company_name
        return f"I'm Chikku, your intelligent assistant at {company_name}. How can I help you today?"
    
    def answer_service_query(self, query: str, conversation_history: Optional[List[Dict]] = None, intent_result=None) -> str:
        """
        Handle service queries (reservations, events, etc.)
        Uses knowledge base data + templates to prevent LLM hallucinations.
        NOTE: Reservation flow is single-turn (no complex dialog) by design.
        """
        if not intent_result or not intent_result.intent_type:
            # Fallback
            contact = self._get_contact_fallback() or "+84 (028) 6291 3672"
            return f"""I can help you with reservations, events, and more!

For service inquiries, please contact us at:
📞 {contact}

Or tell me what you need, and I'll guide you! 😊"""
        
        intent_type = intent_result.intent_type
        
        # Use knowledge base for service queries
        if intent_type == IntentType.SERVICE_RESERVATION:
            contact = self.knowledge_base.get_contact()
            default_phone = self._get_contact_fallback() or "+84 (028) 6291 3672"
            phone = contact.get('phone', {}).get('formatted', default_phone) if contact else default_phone
            return (
                f"I'd be happy to help you with a reservation. ✨\n\n"
                f"For the fastest and most accurate booking, please call us directly at 📞 {phone}.\n\n"
                "If you share your preferred date, time, and number of guests here, I can also help you double‑check availability style (but final confirmation is always through our team). 😊"
            )
        
        elif intent_type == IntentType.SERVICE_DELIVERY:
            delivery_info = self.knowledge_base.get_delivery_info()
            if delivery_info:
                contact = self.knowledge_base.get_contact()
                default_phone = self._get_contact_fallback() or "+84 (028) 6291 3672"
                phone = contact.get('phone', {}).get('formatted', default_phone) if contact else default_phone
                
                return f"""We offer delivery services! 🚚

For delivery orders, please call us at:
📞 {phone}

Our team will be happy to help you place your order and arrange delivery to your location.

What would you like to order? I can help you explore our menu! 🍽️"""
        
        elif intent_type == IntentType.SERVICE_EVENT_BOOKING:
            events_info = self.knowledge_base.get_events_info()
            if events_info:
                contact = self.knowledge_base.get_contact()
                default_phone = self._get_contact_fallback() or "+84 (028) 6291 3672"
                phone = contact.get('phone', {}).get('formatted', default_phone) if contact else default_phone
                
                event_types = events_info.get('event_types', {})
                types_list = [k.replace('_', ' ').title() for k in event_types.keys() if event_types[k].get('available')]
                
                return f"""We'd love to host your event! 🎉

**We offer:**
{chr(10).join(f'• {t}' for t in types_list)}

For event bookings, please call us at:
📞 {phone}

Our team can customize menus and arrangements to make your event memorable! Tell me what kind of event you're planning, and I can help! 😊"""
        
        elif intent_type == IntentType.SERVICE_CATERING:
            catering_info = self.knowledge_base.get_catering_info()
            if catering_info:
                contact = self.knowledge_base.get_contact()
                default_phone = self._get_contact_fallback() or "+84 (028) 6291 3672"
                phone = contact.get('phone', {}).get('formatted', default_phone) if contact else default_phone
                
                return f"""We offer catering services! 🍽️

For catering inquiries and custom menus, please call us at:
📞 {phone}

We can tailor our menu to your event needs. Tell me about your event, and I can help guide you! 😊"""
        
        # Fallback to template
        template = get_template(intent_type)
        if template:
            print(f"✅ Using template for {intent_type.value}")
            return template
        
        # Final fallback — try FAQ before generic response
        faq_answer = self._try_faq_answer(query)
        if faq_answer:
            print(f"✅ Answered from FAQ (service fallback)")
            return faq_answer
        
        contact = self._get_contact_fallback() or "+84 (028) 6291 3672"
        return f"""I can help you with reservations, events, and more!

For service inquiries, please contact us at:
📞 {contact}

Or tell me what you need, and I'll guide you! 😊"""
    
    def ask_clarification(self, query: str, intent_result=None) -> str:
        """
        Ask user for clarification when intent is unclear.
        Uses deterministic template.
        """
        return get_error_response('clarification_needed')
    
    def _rewrite_query_llm(
        self, query: str, conversation_history: Optional[List[Dict]] = None
    ) -> List[str]:
        """
        Generate semantic paraphrases of the query via the LLM for better
        retrieval recall. When conversation_history is provided, the LLM also
        corrects likely speech-to-text errors by comparing the current query
        against previously discussed topics (e.g. "EST robot" → "S-robot" if
        the user was just talking about S-robots).

        Uses the DEDICATED rewrite provider (self._rewrite_provider, a small
        fast LOCAL model by default — see llm_provider.get_rewrite_provider)
        rather than the main generation provider. This keeps STT correction
        latency low (~50-200ms with llama3.2:3b) and decouples it from the
        (possibly OpenAI, slower/costlier) generation model.

        The entity glossary (data/entity_glossary.json) is injected into the
        prompt so the rewriter knows the canonical vocabulary (S-Robot,
        WatchGuard6S, Chikku Voice AI Kiosk, cobots, ...) and can fix STT
        mangling of proper nouns.

        Returns a list of query variants — ALWAYS including the original query
        as the first element so retrieval quality never drops below baseline.

        Safety:
          - Skipped for very short queries (<=6 chars) and pure greetings —
            not worth the latency and the LLM tends to echo them verbatim.
          - On any LLM error/timeout (or if no rewrite provider is configured),
            returns [query] (no crash).
          - Semantic-drift guard: drops any variant that introduces more than
            2 new significant words, which would mean the LLM changed intent.
          - Results are cached (LRU) keyed by (query, context_hash) —
            context-dependent rewrites use a different cache key.
        """
        # Baseline: original query is always present
        variants = [query]
        stripped = query.strip()

        if not self.use_llm_query_rewrite or self._rewrite_provider is None:
            return variants

        # Skip short / greeting-like queries — rewrite adds nothing useful
        if len(stripped) <= 6:
            return variants
        query_lower = stripped.lower()
        if re.fullmatch(r'(hi|hello|hey|namaste|thanks?|ok|yes|no|cool|great)!\.?', query_lower):
            return variants

        # Build context summary from recent conversation (last 6 messages,
        # both user AND assistant — the assistant's replies confirm what was
        # actually discussed and are strong evidence for STT correction).
        context_summary = ""
        recent_user_queries: List[str] = []
        if conversation_history:
            recent_msgs = conversation_history[-6:]  # last 6 messages
            lines: List[str] = []
            for msg in recent_msgs:
                role = msg.get('role', '')
                content = (msg.get('content', '') or '').strip()
                if not content:
                    continue
                if role == 'user':
                    recent_user_queries.append(content)
                    lines.append(f"User: {content}")
                elif role == 'assistant':
                    # Truncate long assistant responses to avoid noise
                    short = content[:200] + ("..." if len(content) > 200 else "")
                    lines.append(f"Assistant: {short}")
            if lines:
                context_summary = (
                    "Recent conversation history (use for STT error detection):\n"
                    + "\n".join(lines)
                    + "\n\n"
                )

        # Cache: include a hash of recent queries so context changes invalidate cache
        cache_key = stripped
        if recent_user_queries:
            context_hash = hash(tuple(recent_user_queries[-2:]))
            cache_key = f"{stripped}||ctx:{context_hash}"
        if cache_key in self._rewrite_cache:
            return self._rewrite_cache[cache_key]

        try:
            # Build a glossary hint so the rewriter fixes STT mangling of
            # proper nouns. List canonical names + their known STT variants.
            glossary_hint = ""
            if self.rewrite_glossary_enabled:
                glossary = self._load_entity_glossary()
                if glossary:
                    lines_g = []
                    for canonical, info in glossary.get("products", {}).items():
                        aliases = info.get("aliases", [])
                        # Show a few STT-prone aliases as examples
                        examples = ", ".join(aliases[:5]) if aliases else ""
                        cat = info.get("category", "")
                        lines_g.append(
                            f"- {canonical} ({cat}) — may be misheard as: {examples}"
                        )
                    glossary_hint = (
                        "CANONICAL VOCABULARY (Chikku Robotics products). If the "
                        "user's query contains a misheard variant, use the CANONICAL "
                        "form in your rephrasings:\n"
                        + "\n".join(lines_g)
                        + "\n\n"
                    )

            system_content = (
                "You rephrase a customer's spoken question about Chikku Robotics "
                "(an AI & robotics company) into 2-3 ALTERNATIVE phrasings that "
                "keep the same intent. Rules:\n"
                "1. Output ONLY the rephrasings, one per line. No numbering, "
                "no bullets, no preamble, no explanation.\n"
                "2. Each line must be a full question someone could ask.\n"
                "3. Use different vocabulary/word order — do NOT just shuffle words.\n"
                "4. Do NOT answer the question. Do NOT add new facts or product names\n"
                "   that are NOT in the canonical vocabulary list below.\n"
                "5. If the input is already clear, still produce 2 rephrasings.\n"
                "6. **Speech-to-text correction**: The user's spoken query likely "
                "contains recognition errors. Fix obvious mishearings using the "
                "canonical vocabulary and (if provided) the conversation history.\n"
                "   - Product/model names are ESPECIALLY prone to STT errors "
                "('EST robot' → 'S-Robot', 'watch guards' → 'WatchGuard6S').\n"
                "   - Always use the CORRECTED canonical form in your output.\n"
                "   - When in doubt, keep the original wording and rephrase normally."
            )
            if glossary_hint:
                system_content = glossary_hint + system_content
            messages = [
                {"role": "system", "content": system_content},
            ]
            if context_summary:
                messages.append({"role": "system", "content": context_summary})
            messages.append({"role": "user", "content": stripped})
            # Use the dedicated (fast, local) rewrite provider, NOT the main
            # generation provider. Low temperature for determinism.
            raw = self._rewrite_provider.chat(
                messages, {"max_tokens": 150, "temperature": 0.2}
            ).strip()

            # Parse lines, clean them up
            orig_words = set(re.findall(r'\b\w+\b', query_lower))
            for line in raw.splitlines():
                line = line.strip().strip('"').strip("'").lstrip('-•*0123456789. )')
                line = line.rstrip('?').strip()
                if not line or len(line) < 3:
                    continue
                if line.lower() == query_lower:
                    continue  # duplicate of original
                # Semantic-drift guard: reject if the variant invents too many
                # new significant words (likely an intent change, not a rephrase).
                # NOTE: canonical entity names from the glossary are allowed even
                # if "new" — they are corrections, not drift. So exclude known
                # canonical tokens from the drift check.
                glossary = self._load_entity_glossary() if self.rewrite_glossary_enabled else {}
                canonical_tokens = set()
                for canon in glossary.get("products", {}):
                    canonical_tokens.update(re.findall(r'[a-z0-9]+', canon.lower()))
                line_words = set(re.findall(r'\b\w+\b', line.lower()))
                new_sig = [w for w in (line_words - orig_words)
                           if len(w) > 3 and w not in canonical_tokens]
                if len(new_sig) > 2:
                    continue
                variants.append(line)
                if len(variants) >= 3:  # original + up to 2 rephrasings
                    break

            if len(variants) > 1:
                print(f"🔍 Rewrite ({getattr(self._rewrite_provider, 'model', '?')}): "
                      f"{len(variants) - 1} variant(s): {variants[1:]}")
        except Exception as e:
            # Never let query rewrite break retrieval — fall back to original
            print(f"⚠️  Query rewrite failed, using original only: {e}")

        # Cache (even single-element result, to avoid retrying the same query)
        self._rewrite_cache[cache_key] = variants
        if len(self._rewrite_cache) > self._rewrite_cache_max_size:
            self._rewrite_cache.popitem(last=False)

        return variants

    # ------------------------------------------------------------------
    # Conditional query rewrite gate
    # ------------------------------------------------------------------

    def _should_rewrite(
        self, query: str, conversation_history: Optional[List[Dict]] = None
    ) -> bool:
        """Decide whether the LLM query-rewrite step is worth running.

        Rewrite is run ONLY when the query is plausibly ambiguous or could
        benefit from STT correction. Clear, specific queries skip the LLM
        call entirely — this saves ~0.3-0.5s for the majority of traffic
        without hurting recall (clear queries already retrieve well).

        Triggers (any one is enough):
          - word count < REWRITE_MIN_WORDS (e.g. "kiosk?", "ai?")
          - pronoun reference (it/this/that/they/he/she) — needs context to resolve
          - conversation history is present — opportunity for STT correction
        """
        if not self.use_llm_query_rewrite:
            return False
        stripped = (query or "").strip()
        if not stripped:
            return False
        # Word-count trigger
        word_count = len(stripped.split())
        if word_count < self.rewrite_min_words:
            return True
        # Pronoun trigger
        if self.rewrite_on_pronoun and re.search(
            r'\b(it|this|that|these|those|they|them|he|she|his|her|its)\b',
            stripped, re.IGNORECASE
        ):
            return True
        # Conversation-history trigger (STT correction opportunity)
        if conversation_history:
            return True
        return False

    # ------------------------------------------------------------------
    # BM25 index (lazy, defensive — degrades to dense-only if unavailable)
    # ------------------------------------------------------------------

    @staticmethod
    def _bm25_tokenize(text: str) -> List[str]:
        """Simple tokenizer for BM25: lowercase alphanumeric tokens, len > 1.

        NOTE: this static fallback is kept for compatibility; the instance
        method _bm25_tokenize_aliasaware() below is what's actually used by
        the index and the query path, because it also expands entity aliases
        so STT variants ('s robot', 'watch guards') tokenize to the same
        canonical terms as the stored chunks.
        """
        return [t for t in re.findall(r'[a-z0-9]+', (text or "").lower()) if len(t) > 2]

    def _load_alias_map(self) -> Dict[str, str]:
        """Build a {alias_lower: canonical_key} map from data/entity_glossary.json.

        The canonical_key is the REPLACEMENT text used by _normalize_aliases.
        For canonical names that contain a single-letter token (e.g. "S-Robot"
        → tokens ["s","robot"], where "s" would be dropped by the len>2 BM25
        tokenizer), we COMPACT the name into one token ("srobot") so it
        survives tokenization. For normal multi-word names ("Chikku Voice AI
        Kiosk"), we keep the spaced form because no token is dropped.

        Cached on the instance after first build. Returns {} if the glossary
        is missing, so the tokenizer degrades to plain tokenization.
        """
        if hasattr(self, "_alias_map"):
            return self._alias_map
        alias_map: Dict[str, str] = {}

        def _canonical_key(canonical: str) -> str:
            tokens = re.findall(r'[a-z0-9]+', canonical.lower())
            # If any token is a single char (would be dropped by len>2 filter),
            # compact the whole name into one token so it survives.
            if any(len(t) <= 2 for t in tokens):
                return "".join(tokens)
            return " ".join(tokens)

        try:
            glossary_path = Path(__file__).parent.parent / "data" / "entity_glossary.json"
            if glossary_path.exists():
                glossary = json.loads(glossary_path.read_text(encoding="utf-8"))
                # Products: canonical + all aliases → canonical key
                for canonical, info in glossary.get("products", {}).items():
                    canon_key = _canonical_key(canonical)
                    names = [canonical] + list(info.get("aliases", []))
                    for name in names:
                        if name:
                            alias_map[name.strip().lower()] = canon_key
                # Company terms
                for canonical, aliases in glossary.get("company_terms", {}).items():
                    canon_key = _canonical_key(canonical)
                    names = [canonical] + list(aliases)
                    for name in names:
                        if name:
                            alias_map[name.strip().lower()] = canon_key
        except Exception as e:
            print(f"⚠️  Alias map build failed (BM25 will be plain): {e}")
        self._alias_map = alias_map
        return alias_map

    def _normalize_aliases(self, text: str) -> str:
        """Replace STT entity variants in `text` with their canonical name.

        Word-boundary matching prevents partial substitutions. This makes
        'tell me about s robot' and 'tell me about the s-robot' produce the
        SAME token sequence for BM25, so keyword recall no longer depends on
        exact hyphenation or spacing.
        """
        alias_map = self._load_alias_map()
        if not alias_map:
            return text
        out = text
        # Sort by length DESC so multi-word aliases match before their parts
        for alias in sorted(alias_map.keys(), key=len, reverse=True):
            canonical = alias_map[alias]
            # Use word boundaries; escape regex specials in the alias
            pattern = r'\b' + re.escape(alias) + r'\b'
            out = re.sub(pattern, canonical, out, flags=re.IGNORECASE)
        return out

    def _bm25_tokenize_aliasaware(self, text: str) -> List[str]:
        """Alias-aware tokenizer: expand STT variants, then tokenize len > 2.

        Len threshold is 3 (was 1) because single-letter tokens like 's' are
        noise in BM25; the alias expansion turns 's robot' into 'srobot'
        (canonical) BEFORE tokenization, so the short-letter problem is moot.
        """
        normalized = self._normalize_aliases(text or "")
        return [t for t in re.findall(r'[a-z0-9]+', normalized.lower()) if len(t) > 2]

    def _ensure_bm25_index(self) -> bool:
        """Lazily build the BM25 index from the ChromaDB collection's documents.

        Returns True if the index is ready, False if rank_bm25 is unavailable
        or the build failed (caller falls back to dense-only retrieval).
        """
        if self._bm25 is not None:
            return True
        if not self._bm25_available:
            return False
        try:
            from rank_bm25 import BM25Okapi
            data = self.collection.get(include=["documents", "metadatas"])
            docs = data.get("documents", []) or []
            ids = data.get("ids", []) or []
            metas = data.get("metadatas", []) or []
            if not docs:
                return False
            tokenized = [self._bm25_tokenize_aliasaware(d) for d in docs]
            self._bm25 = BM25Okapi(tokenized)
            self._bm25_docs = list(docs)
            self._bm25_ids = list(ids)
            self._bm25_metadatas = list(metas)
            print(f"✅ BM25 index built over {len(docs)} documents")
            return True
        except Exception as e:
            print(f"⚠️  BM25 index build failed ({e}) — dense-only retrieval active.")
            self._bm25 = None
            return False

    def _bm25_search(self, query: str, n: int) -> List[Dict]:
        """Return top-n BM25 hits as retrieval-shaped dicts."""
        if not self._ensure_bm25_index():
            return []
        try:
            scores = self._bm25.get_scores(self._bm25_tokenize_aliasaware(query))
        except Exception as e:
            print(f"⚠️  BM25 scoring failed: {e}")
            return []
        # Pair scores with (id, doc, meta), sort desc, take top-n positive scores
        ranked = sorted(
            zip(scores, self._bm25_ids, self._bm25_docs, self._bm25_metadatas),
            key=lambda x: x[0], reverse=True
        )
        items: List[Dict] = []
        for score, item_id, doc, meta in ranked[:n]:
            if score <= 0:
                break
            items.append({
                'id': item_id,
                'document': doc,
                'metadata': meta or {},
                'bm25_score': float(score),
                'distance': 0.0,  # not a dense distance; rerank uses rerank_score
            })
        return items

    # ------------------------------------------------------------------
    # Multi-hop query decomposition (env-gated)
    # ------------------------------------------------------------------

    # Markers that suggest a multi-entity / comparison question worth
    # decomposing into sub-queries. Word-boundary matched, case-insensitive.
    _DECOMPOSE_MARKERS = re.compile(
        r'\b(compare|comparison|versus|vs\.?|difference between|differences between|'
        r'better than|worse than|or\b)\b',
        re.IGNORECASE,
    )

    def _should_decompose(self, query: str) -> bool:
        """True if the query looks like a multi-entity comparison question.

        Requires QUERY_DECOMPOSE_ENABLED=true AND a comparison marker AND
        at least 2 distinct capitalized/token entities (heuristic). Returns
        False otherwise so single-entity queries skip the extra LLM call.
        """
        if not self.query_decompose_enabled or self._rewrite_provider is None:
            return False
        stripped = (query or "").strip()
        if len(stripped) < 10:
            return False
        if not self._DECOMPOSE_MARKERS.search(stripped):
            return False
        return True

    def _decompose_query(self, query: str) -> List[str]:
        """Split a comparison question into per-entity sub-queries.

        Returns [query] (no decomposition) on any failure, when the query is
        not actually multi-entity, or when decomposition is disabled. Never
        raises — callers treat the result as a list of retrieval queries.
        """
        if not self._should_decompose(query):
            return [query]
        try:
            system = (
                "You split a multi-entity comparison question about Chikku "
                "Robotics into separate single-entity sub-questions, so each "
                "can be retrieved independently. Rules:\n"
                "1. Output ONE sub-question per line. No numbering, no preamble.\n"
                "2. Each sub-question must be a complete question about ONE "
                "entity only (e.g. one product).\n"
                "3. If the input is NOT actually a comparison (single entity), "
                "output exactly ONE line: the original question, lightly cleaned.\n"
                "4. Use canonical Chikku product names (S-Robot, WatchGuard6S, "
                "Chikku Voice AI Kiosk, cobots, ...) — fix any misheard names.\n"
                "5. Max 4 sub-questions."
            )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": query.strip()},
            ]
            raw = self._rewrite_provider.chat(
                messages, {"max_tokens": 120, "temperature": 0.0}
            ).strip()
            subs: List[str] = []
            for line in raw.splitlines():
                line = line.strip().strip('"').strip("'").lstrip('-•*0123456789. )')
                line = line.rstrip('?').strip()
                if len(line) >= 3:
                    subs.append(line)
                if len(subs) >= 4:
                    break
            if len(subs) >= 2:
                print(f"🔀 Decomposed into {len(subs)} sub-queries: {subs}")
                return subs
            # Model decided it's single-entity — use the (possibly cleaned) line
            if subs:
                return subs
        except Exception as e:
            print(f"⚠️  Query decomposition failed, treating as single query: {e}")
        return [query]

    # ------------------------------------------------------------------
    # Hybrid retrieval: BM25 + Dense + RRF fusion
    # ------------------------------------------------------------------

    def _rrf_fuse(
        self, dense_items: List[Dict], bm25_items: List[Dict], top_k: int
    ) -> List[Dict]:
        """Reciprocal Rank Fusion (RRF) of dense and BM25 result lists.

        score(doc) = sum over lists of 1 / (k + rank_in_list)
        Standard k=60. Documents present in only one list still contribute
        (they just get a single term). Output is deduplicated by id and
        sorted by fused score, descending.
        """
        rrf_scores: Dict[str, float] = {}
        item_by_id: Dict[str, Dict] = {}

        for rank, item in enumerate(dense_items):
            item_id = item.get('id', '')
            if not item_id:
                continue
            rrf_scores[item_id] = rrf_scores.get(item_id, 0.0) + 1.0 / (self.rrf_k + rank + 1)
            # Prefer the dense item (has real distance + metadata) when id collides
            item_by_id.setdefault(item_id, item)

        for rank, item in enumerate(bm25_items):
            item_id = item.get('id', '')
            if not item_id:
                continue
            rrf_scores[item_id] = rrf_scores.get(item_id, 0.0) + 1.0 / (self.rrf_k + rank + 1)
            # Fill in the item if dense didn't already surface it
            item_by_id.setdefault(item_id, item)

        fused_ids = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)
        result = []
        for item_id in fused_ids[:top_k]:
            item = dict(item_by_id[item_id])  # shallow copy — don't mutate caller's
            item['rrf_score'] = rrf_scores[item_id]
            result.append(item)
        return result

    def _hybrid_retrieve(
        self, query: str, top_k: int, rerank_k: int,
        conversation_history: Optional[List[Dict]] = None,
        query_embedding: Optional[List[float]] = None
    ) -> Tuple[List[Dict], str]:
        """
        Hybrid retrieval: BM25 + Dense + RRF fusion, then reranking.

        Replaces the old dense-only _semantic_retrieve. Catches BOTH exact
        keyword matches (BM25) and semantic similarity (Dense) and fuses them
        with RRF for more accurate retrieval than either alone.

        Query rewrite is now CONDITIONAL (see _should_rewrite): only run when
        the query actually benefits from it.

        Multi-hop DECOMPOSITION (QUERY_DECOMPOSE_ENABLED): if the query is a
        comparison/multi-entity question, it is first split into per-entity
        sub-queries (via _decompose_query). Each sub-query is then rewritten
        + retrieved independently, and results are merged. This ensures both
        entities surface their own chunks instead of one dominating the other.

        Returns (retrieved_items, context_string).
        """
        # Optional multi-hop decomposition → list of (sub)queries to retrieve.
        # When decomposition is off or N/A, this returns [query].
        retrieve_queries = self._decompose_query(query)

        all_items: List[Dict] = []
        seen_ids: set = set()

        for rq in retrieve_queries:
            # Conditional rewrite per (sub)query — only when it benefits.
            if self._should_rewrite(rq, conversation_history):
                query_variants = self._rewrite_query_llm(rq, conversation_history)
            else:
                query_variants = [rq]
                if self.use_llm_query_rewrite:
                    print(f"⏭️  Query rewrite skipped (clear query: {len(rq.split())} words)")

            for variant in query_variants[:3]:
                # Dense retrieval (cosine ANN over embeddings)
                dense_items = self.retrieve(
                    variant, top_k=self.dense_candidates,
                    query_embedding=query_embedding if variant == query else None
                )
                # BM25 retrieval (keyword) — empty list if rank_bm25 unavailable
                bm25_items = []
                if self.hybrid_search_enabled and self._ensure_bm25_index():
                    bm25_items = self._bm25_search(variant, n=self.bm25_candidates)

                if self.hybrid_search_enabled and (dense_items or bm25_items):
                    fused = self._rrf_fuse(dense_items, bm25_items, top_k=max(top_k, rerank_k))
                else:
                    # Dense-only fallback (rank_bm25 missing or hybrid disabled)
                    fused = dense_items[:max(top_k, rerank_k)]

                for item in fused:
                    item_id = item.get('id', '')
                    if item_id and item_id not in seen_ids:
                        seen_ids.add(item_id)
                        all_items.append(item)

        n_sub = len(retrieve_queries)
        print(f"✅ Hybrid retrieval: {len(all_items)} unique items "
              f"from {n_sub} sub-quer{'y' if n_sub == 1 else 'ies'} "
              f"(dense + {'BM25' if self._bm25 is not None else 'BM25-off'})")

        if not all_items:
            return [], ""

        # Rerank the merged shortlist against the ORIGINAL query (not the
        # sub-queries) so the final relevance ordering reflects what the user
        # actually asked. Backend: cosine or cross-encoder (unchanged).
        if self.use_reranking and len(all_items) > 1:
            rerank_to = min(len(all_items), max(rerank_k, 8))
            all_items = self.rerank(query, all_items, top_k=rerank_to)
        else:
            all_items.sort(key=lambda x: x.get('distance', 999.0))
            all_items = all_items[:rerank_k]

        context = self.format_context(all_items)
        return all_items, context

    def _semantic_retrieve(
        self, query: str, top_k: int, rerank_k: int,
        conversation_history: Optional[List[Dict]] = None,
        query_embedding: Optional[List[float]] = None
    ) -> Tuple[List[Dict], str]:
        """Backward-compatible wrapper around _hybrid_retrieve.

        Kept so any external caller (e.g. /chat/stream endpoint) still works.
        New code should call _hybrid_retrieve directly.
        """
        return self._hybrid_retrieve(
            query, top_k, rerank_k, conversation_history, query_embedding
        )

    # ------------------------------------------------------------------
    # FAQ cache layer (layer 1) — strict embedding-similarity FAQ lookup
    # ------------------------------------------------------------------

    def _faq_cache_lookup(
        self, query: str, query_embedding: Optional[List[float]] = None
    ) -> Optional[str]:
        """
        Layer 1 retrieval: fast FAQ exact-match + strict embedding-similarity.

        Returns the FAQ answer string on a confident hit, or None to fall
        through to the hybrid retrieval layer.

        Two paths:
          (a) Exact/normalized string match (unchanged from get_best_faq_match
              Fast Path 1/2) — catches verbatim phrasings instantly, <50ms.
              VALIDATED by embedding cosine: the string matcher is loose enough
              to false-positive on shared keywords (the "what is chikku brain"
              → leadership bug), so we require the matched FAQ's question to
              also clear a cosine bar before trusting it.
          (b) Strict FAQ-question embedding cosine >= FAQ_EMBEDDING_THRESHOLD
              (default 0.75). This catches paraphrases the string matcher
              misses, with the same strict bar.

        The trailing "Is there anything else..." prompt is appended to match
        the previous FAQ-fast-path UX.
        """
        if not self.faq_cache_enabled:
            return None

        # Ensure we have an embedding of the query and the FAQ-question embeddings
        try:
            if query_embedding is None:
                query_embedding = self.get_embedding(query)
            faq_embeddings = self.knowledge_base.get_faq_question_embeddings(self.provider.embed)
        except Exception as e:
            print(f"⚠️  FAQ embedding lookup skipped: {e}")
            return None

        # Precompute cosine of the query against EVERY FAQ question (used by
        # both path (a) validation and path (b)).
        q_to_faq: List[Tuple[str, str, float]] = []
        best_sim = -1.0
        best_answer = ""
        best_question = ""
        for question, answer, q_emb in faq_embeddings:
            sim = self._cosine_similarity(query_embedding, q_emb)
            q_to_faq.append((question, answer, sim))
            if sim > best_sim:
                best_sim = sim
                best_answer = answer
                best_question = question

        # (a) String match — but only TRUSTED if the best-matching FAQ question
        # also clears a (slightly relaxed) cosine bar. The keyword-overlap
        # matcher is allowed to find the candidate; embedding similarity
        # confirms it's actually about the same thing.
        try:
            string_answer = self.knowledge_base.get_best_faq_match(query)
        except Exception as e:
            print(f"⚠️  FAQ string match failed: {e}")
            string_answer = ""
        if string_answer and best_sim >= self.faq_embedding_threshold:
            print(f"⚡ FAQ cache hit (string+cosine={best_sim:.3f} on "
                  f"'{best_question[:40]}')")
            return f"{string_answer}\n\nIs there anything else I can help you with? 😊"
        if string_answer and best_sim < self.faq_embedding_threshold:
            # String matched but embedding disagrees — this is exactly the
            # "what is chikku brain" → leadership false-positive. Log and fall
            # through to hybrid retrieval rather than trusting the loose match.
            print(f"🔎 FAQ string match rejected by cosine "
                  f"({best_sim:.3f} < {self.faq_embedding_threshold} on "
                  f"'{best_question[:40]}') — falling through to hybrid")

        # (b) Strict FAQ-question embedding cosine (independent of string match)
        if best_answer and best_sim >= self.faq_embedding_threshold:
            print(f"⚡ FAQ cache hit (cosine={best_sim:.3f}, threshold={self.faq_embedding_threshold})")
            return f"{best_answer}\n\nIs there anything else I can help you with? 😊"
        if best_sim >= 0.0:
            print(f"🔎 FAQ cache miss (best cosine={best_sim:.3f} < {self.faq_embedding_threshold})")
        return None


    
    def _kb_enrichment(self, query: str, semantic_items: List[Dict]) -> str:
        """
        Enrich semantic search results with structured knowledge base data.

        When ChromaDB finds results about a topic, pull related structured
        data from that KB section to ensure completeness — e.g. when the
        retrieval surfaces a featured-product overview, this can add that
        product's features/benefits chunks that didn't make the shortlist.

        Selection is now SEMANTIC (cosine similarity between the query
        embedding and each KB chunk), replacing the old keyword-overlap
        scoring which was noisy and English-stemming-dependent.

        Returns additional context string from KB, or empty string.
        """
        if not semantic_items:
            return ""

        # Topics already surfaced by retrieval — only enrich those
        detected_topics = {item.get('metadata', {}).get('topic', '')
                           for item in semantic_items if item.get('metadata', {}).get('topic')}
        if not detected_topics:
            return ""

        # Collect candidate enrichment chunks across detected topics
        candidates: List[Dict] = []
        for topic in detected_topics:
            if not self.knowledge_base._data.get(topic):
                continue
            for chunk in self.knowledge_base._extract_section_content(topic):
                candidates.append(chunk)
        if not candidates:
            return ""

        # Deduplicate enrichment against what's ALREADY in the semantic
        # shortlist (by normalized text), so we only add NEW context.
        existing_texts = {
            re.sub(r'\s+', ' ', (item.get('document', '') or '').lower()).strip()
            for item in semantic_items
        }

        # Score each candidate by cosine similarity to the query.
        # One query embedding + one embedding per unique candidate text.
        try:
            query_emb = self.get_embedding(query)
        except Exception as e:
            print(f"⚠️  KB enrichment skipped (query embed failed): {e}")
            return ""

        scored: List[Tuple[float, str]] = []
        emb_cache: Dict[str, List[float]] = {}
        for chunk in candidates:
            raw_text = chunk.get('text', '')
            if not raw_text:
                continue
            norm = re.sub(r'\s+', ' ', raw_text.lower()).strip()
            if not norm or norm in existing_texts:
                continue
            # Clean "Key: " prefixes the way the old code did, for readability
            clean_text = re.sub(r'^[A-Za-z][A-Za-z0-9]*(?:\s[A-Za-z0-9]*)*:\s', '', raw_text)
            if norm in emb_cache:
                emb = emb_cache[norm]
            else:
                try:
                    emb = self.get_embedding(clean_text)
                    emb_cache[norm] = emb
                except Exception:
                    continue
            sim = self._cosine_similarity(query_emb, emb)
            scored.append((sim, clean_text))

        if not scored:
            return ""

        # Keep the top enrichment chunks above a small similarity floor so we
        # don't pad the context with loosely-related KB text. 0.35 cosine is a
        # lenient bar — well below the retrieval threshold — because enrichment
        # is supplementary, not primary. Capped at 3 chunks: hybrid retrieval
        # already broadens recall, so enrichment is a light supplement.
        scored.sort(key=lambda x: x[0], reverse=True)
        SIM_FLOOR = 0.35
        top = [text for sim, text in scored[:3] if sim >= SIM_FLOOR]
        return "\n\n".join(top)
    
    def query_stream(
        self,
        user_query: str,
        top_k: Optional[int] = None,
        rerank_k: Optional[int] = None,
        conversation_history: Optional[List[Dict]] = None
    ):
        """
        Streaming version of query() — yields pipeline events as they happen.

        This is the SINGLE SOURCE OF TRUTH for the GROUNDED-FIRST pipeline.
        query() (below) is a thin wrapper that consumes this generator and
        returns the final response dict for non-streaming callers
        (/chat/text, /query).

        Event timeline (the streaming /chat/voice endpoint forwards these to
        the frontend as Server-Sent Events):
          - Deterministic / FAQ-cache HIT (fast, <50ms):
              yield {'type': 'response', 'query', 'response', 'items',
                     'retrieved_count', 'intent', 'source'}
              yield {'type': 'done', 'intent'}
          - FAQ-cache MISS (about to enter the slow 4-6s steps):
              yield {'type': 'filler'}        # signal frontend to speak a filler
              ... 4-6s of hybrid retrieval + LLM ...
              yield {'type': 'response', ...}
              yield {'type': 'done', 'intent'}

        The filler event is emitted the instant step 3 misses, BEFORE the slow
        hybrid-retrieval + LLM-generation steps, so the frontend can start
        speaking a filler sentence within ~100ms of the request arriving.

        'source' tags where the response came from, for debugging:
          'deterministic' | 'faq_cache' | 'llm' | 'fallback'

        Flow:
          [1] Intent classification (embedding-based, shares embedding with [3])
          [2] Deterministic templates for CONVERSATIONAL / core-IDENTITY
          [3] Layer 1: FAQ cache (string + strict embedding similarity, <50ms)
          [4] Conditional query rewrite (only for short/pronoun/context queries)
          [5] Layer 2: Hybrid search (BM25 + Dense + RRF fusion)
          [6] Layer 3: Rerank (cosine or cross-encoder)
          [7] KB enrichment (light)
          [8] Context? → LLM generation | else FAQ cache retry → graceful fallback

        Grounding rule (preserved from v1): the LLM is NEVER called with empty
        context — that was the source of fabricated facts. No context → graceful
        "I don't have that detail" response.
        """
        top_k = max(1, top_k) if top_k is not None else self.top_k
        rerank_k = max(1, rerank_k) if rerank_k is not None else self.rerank_k

        # Step [1]: Classify intent. The classifier (in embedding mode) embeds
        # the query; we opportunistically reuse that embedding for retrieval so
        # we don't embed the same query twice.
        intent_result, query_embedding = self._classify_intent_with_embedding(user_query)
        print(f"📋 Intent: {intent_result.intent_type.value} ({intent_result.category.value})")

        # Step [2]: Route pure greeting / "who are you" / "what can you do" to
        # deterministic templates. Leadership/founder questions are intentionally
        # NOT routed here — they are factual KB queries that must go through
        # retrieval so the LLM synthesizes from grounded context (proper RAG).
        DETERMINISTIC_INTENTS = {
            IntentType.IDENTITY_WHO_ARE_YOU,
            IntentType.IDENTITY_WHAT_DO_YOU_DO,
            IntentType.IDENTITY_CAPABILITIES,
        }
        if (intent_result.category == IntentCategory.CONVERSATIONAL
                or (intent_result.category == IntentCategory.IDENTITY
                    and intent_result.intent_type in DETERMINISTIC_INTENTS)):
            response = self.answer_about_or_identity(user_query, conversation_history, intent_result)
            yield {
                'type': 'response', 'source': 'deterministic',
                'query': user_query, 'response': response,
                'items': [], 'retrieved_count': 0,
                'intent': intent_result.to_dict()
            }
            yield {'type': 'done', 'intent': intent_result.to_dict()}
            return

        # Step [3] — LAYER 1: FAQ cache.
        # Strict exact-string + embedding-cosine FAQ lookup. Cuts latency to
        # <50ms for verbatim / near-verbatim FAQ hits and bypasses the whole
        # retrieval + LLM-generation stack. The strict embedding bar
        # (FAQ_EMBEDDING_THRESHOLD, default 0.75) fixes the keyword-overlap
        # bug that mis-routed "what is chikku brain" → leadership FAQ.
        if self.faq_cache_enabled:
            faq_answer = self._faq_cache_lookup(user_query, query_embedding)
            if faq_answer:
                print(f"⚡ Layer 1 (FAQ cache): answered in <50ms (skipped hybrid + LLM)")
                yield {
                    'type': 'response', 'source': 'faq_cache',
                    'query': user_query, 'response': faq_answer,
                    'items': [], 'retrieved_count': 0,
                    'intent': intent_result.to_dict()
                }
                yield {'type': 'done', 'intent': intent_result.to_dict()}
                return

        # --- FAQ cache MISS: emit the filler signal NOW, before the slow
        # hybrid-retrieval + LLM-generation steps. The frontend starts
        # speaking a filler sentence immediately (~100ms after request),
        # then stops it and speaks the real response once it arrives (4-6s).
        # The frontend owns the filler text; we only send the signal.
        if self.filler_signal_enabled:
            print(f"🗣️  FAQ cache miss — emitting filler signal for frontend")
            yield {'type': 'filler'}

        # Steps [4] + [5] + [6]: conditional rewrite + hybrid retrieval + rerank.
        # _hybrid_retrieve internally applies the _should_rewrite gate, so clear
        # queries skip the LLM rewrite entirely (saves ~0.3-0.5s for the majority).
        print(f"🔍 Hybrid search (BM25 + Dense + RRF, top {top_k})...")
        semantic_items, semantic_context = self._hybrid_retrieve(
            user_query, top_k, rerank_k, conversation_history,
            query_embedding=query_embedding
        )

        # Step [7]: Light KB enrichment — only when hybrid returned a small set.
        # Hybrid retrieval already broadens recall vs. old dense-only, so
        # enrichment is no longer load-bearing; keep it small (top 3).
        if semantic_items and len(semantic_items) <= rerank_k:
            enrich = self._kb_enrichment(user_query, semantic_items)
            if enrich:
                print(f"📚 Enriched with KB structured data ({len(enrich)} chars)")
                semantic_context = (semantic_context + "\n\n" + enrich).strip() if semantic_context else enrich

        # Step [8]: If we have ANY grounded context, let the LLM synthesize from it.
        if semantic_context:
            sanitized_history = self._sanitize_conversation_history(conversation_history) if conversation_history else None
            response = self.generate_response(user_query, semantic_context, sanitized_history)

            yield {
                'type': 'response', 'source': 'llm',
                'query': user_query,
                'response': response,
                'items': [{'name': item.get('metadata', {}).get('title', item.get('id', '')),
                           'section': item.get('metadata', {}).get('doc_type', ''),
                           'content': item.get('document', '')[:200]}
                          for item in (semantic_items or [])],
                'retrieved_count': len(semantic_items),
                'intent': intent_result.to_dict()
            }
            yield {'type': 'done', 'intent': intent_result.to_dict()}
            return

        # No grounded context — Layer-1 FAQ cache retry (string-only path),
        # then graceful fallback. Never call the LLM ungrounded.
        if self.faq_cache_enabled:
            faq_answer = self._faq_cache_lookup(user_query, query_embedding)
            if faq_answer:
                print(f"✅ Answered from FAQ cache (fallback)")
                yield {
                    'type': 'response', 'source': 'faq_cache',
                    'query': user_query, 'response': faq_answer,
                    'items': [], 'retrieved_count': 0,
                    'intent': intent_result.to_dict()
                }
                yield {'type': 'done', 'intent': intent_result.to_dict()}
                return

        print(f"🤷 No grounded context found — returning graceful fallback")
        company_name = self.bot_cfg.company_name
        graceful = (
            f"I don't have that exact detail handy, but I'd love to tell you about "
            f"what {company_name} does! We build intelligent robots, AI platforms, "
            f"and industry solutions. What would you like to know? 🤖"
        )
        yield {
            'type': 'response', 'source': 'fallback',
            'query': user_query, 'response': graceful,
            'items': [], 'retrieved_count': 0,
            'intent': intent_result.to_dict()
        }
        yield {'type': 'done', 'intent': intent_result.to_dict()}

    def query(
        self,
        user_query: str,
        top_k: Optional[int] = None,
        rerank_k: Optional[int] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Complete RAG query pipeline (non-streaming) — GROUNDED-FIRST design.

        Thin wrapper over query_stream(): consumes the event generator and
        returns the final response dict for non-streaming callers
        (/chat/text, /query). The streaming /chat/voice endpoint calls
        query_stream() directly so it can forward each event (including the
        filler signal) to the frontend.

        Returns a dict shaped exactly like the legacy API for backward
        compatibility: {query, response, items, retrieved_count, intent}.
        """
        final: Optional[Dict] = None
        for event in self.query_stream(
            user_query, top_k=top_k, rerank_k=rerank_k,
            conversation_history=conversation_history
        ):
            if event.get('type') == 'response':
                # Strip the streaming-only 'type'/'source' keys so the returned
                # dict matches the legacy shape exactly.
                final = {k: v for k, v in event.items() if k not in ('type', 'source')}
        if final is None:
            # Defensive: generator produced no response event (should not happen).
            company_name = self.bot_cfg.company_name
            graceful = (
                f"I don't have that exact detail handy, but I'd love to tell you about "
                f"what {company_name} does! We build intelligent robots, AI platforms, "
                f"and industry solutions. What would you like to know? 🤖"
            )
            return {
                'query': user_query, 'response': graceful,
                'items': [], 'retrieved_count': 0,
                'intent': None
            }
        return final


def main():
    """Test RAG pipeline"""
    project_root = Path(__file__).parent.parent
    chroma_db_path = project_root / "chroma_db"
    
    # Initialize pipeline
    print("Initializing RAG pipeline...")
    rag = RAGPipeline(
        chroma_db_path=str(chroma_db_path),
        use_reranking=False  # Set to True if reranking installed
    )
    
    # Test with single query first
    print("\n" + "="*60)
    print("Testing RAG Pipeline")
    print("="*60 + "\n")
    
    query = "What vegetarian dosas do you have?"
    print(f"Query: {query}")
    print("-" * 60)
    
    try:
        result = rag.query(query, top_k=10, rerank_k=5)
        
        print(f"\nResponse:\n{result['response']}")
        print(f"\nRetrieved {result['retrieved_count']} items")
        if result['items']:
            print("\nTop items:")
            for item in result['items']:
                price_str = f"{item['price']} {item['currency']}" if item.get('price') else "N/A"
                print(f"  - {item['name']} ({item['section']}) - {price_str}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)


if __name__ == "__main__":
    main()
