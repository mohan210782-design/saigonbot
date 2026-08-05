"""
Ingest Chikku Robotics knowledge into ChromaDB.

Reads structured JSON data from data/knowledge_base/robotics/ and
about text from data/processed/about_robotics.txt, then indexes
everything into the 'chikku_robotics' ChromaDB collection.

Safe to re-run — existing docs with same IDs are updated (upsert).

=== Contextual Retrieval (Anthropic technique) ===
Each chunk is prefixed with 1-2 sentences of LLM-generated context
("this chunk is from <doc>, describing <X>") BEFORE embedding. This makes
each chunk self-contained so the embedding captures its provenance, not
just its isolated content. Anthropic reports this cuts retrieval failures
by ~49% (and ~67% when combined with reranking).

The LLM context is generated via OpenAI (cheap, fast) and CACHED to
data/context_cache.json keyed by (chunk_id, text_hash) so re-ingestion
of unchanged chunks costs nothing. Gated by CONTEXTUAL_EMBEDDINGS_ENABLED
(default true); when off, chunks are embedded as-is.

=== Entity alias injection ===
Canonical product names from data/entity_glossary.json are injected into
chunk text (as a hidden "Also known as: ..." line) so that STT-mangled
variants ("s robot", "watch guards") still match the canonical embedding.
This is critical for voice input where "S-Robot" is often heard as
"EST robot", "es robot", etc.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import chromadb
from tqdm import tqdm

# Ensure project src is on path
sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

from bot_config import get_bot_config
from llm_provider import get_provider


# ---------------------------------------------------------------------------
# Contextual Retrieval helpers (Anthropic technique)
# ---------------------------------------------------------------------------

def _contextual_enabled() -> bool:
    """Whether LLM-generated chunk context is prepended before embedding."""
    return os.getenv("CONTEXTUAL_EMBEDDINGS_ENABLED", "true").lower() == "true"


def _context_cache_path() -> Path:
    """Path to the JSON cache file storing LLM-generated chunk contexts."""
    project_root = Path(__file__).parent.parent
    return project_root / "data" / "context_cache.json"


def _load_context_cache() -> dict:
    """Load the persistent chunk-context cache. Returns {} if missing/corrupt."""
    p = _context_cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  Context cache corrupt, starting fresh: {e}")
        return {}


def _save_context_cache(cache: dict) -> None:
    """Persist the chunk-context cache to disk."""
    p = _context_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_openai_context_client():
    """Return a dedicated OpenAI client for context generation.

    Context generation ALWAYS uses OpenAI (cheap, fast) regardless of the
    main LLM_PROVIDER, so that re-running ingestion on a local-only setup
    still produces consistent Anthropic-style contexts. Returns None if
    OpenAI is unavailable (no key) — caller falls back to no context.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except Exception as e:
        print(f"⚠️  OpenAI context client unavailable: {e}")
        return None


def _generate_chunk_context(
    openai_client,
    model: str,
    chunk_text: str,
    metadata: dict,
) -> str:
    """Ask the LLM for a 1-2 sentence context prefix for this chunk.

    The context states which document/section the chunk comes from and what
    it is about, so the chunk can stand alone when embedded. Returns the
    context string (no enclosing markup). On any error, returns "" and the
    caller embeds the chunk as-is.
    """
    # Build a short provenance hint from metadata so the LLM doesn't have
    # to guess. E.g. "source: robotics/products.json, topic: products,
    # subtopic: featured_products, chunk_type: product_features"
    hints = []
    for key in ("source", "topic", "subtopic", "chunk_type", "title", "category"):
        val = metadata.get(key)
        if val:
            hints.append(f"{key}: {val}")
    provenance = "; ".join(hints) if hints else "Chikku Robotics knowledge base"

    system = (
        "You are preparing a chunk of text for embedding in a RAG system "
        "for Chikku Robotics (an AI & robotics company). Your job is to write "
        "a SHORT context sentence (1-2 sentences, max 40 words) that explains "
        "WHERE this chunk sits in the knowledge base and WHAT it is about, so "
        "the chunk can be understood in isolation when embedded.\n\n"
        "Rules:\n"
        "1. Output ONLY the context sentence(s). No preamble, no labels, no quotes.\n"
        "2. Start with 'This chunk is from...' or similar.\n"
        "3. Mention the canonical entity/product name if one appears (e.g. "
        "'S-Robot', 'WatchGuard6S', 'Chikku Voice AI Kiosk').\n"
        "4. Do NOT restate the chunk's content verbatim — summarize its ROLE.\n"
        "5. Be concrete and factual. Do not invent facts not inferable from "
        "the provenance hint or the chunk itself."
    )
    user = (
        f"Provenance: {provenance}\n\n"
        f"Chunk content:\n\"\"\"\n{chunk_text[:1500]}\n\"\"\"\n\n"
        "Write the 1-2 sentence context prefix:"
    )
    try:
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=80,
            temperature=0.0,
        )
        ctx = (resp.choices[0].message.content or "").strip().strip('"').strip()
        # Strip any leading label the model may have added despite instructions
        ctx = re.sub(r'^(context|prefix|note)\s*:\s*', '', ctx, flags=re.IGNORECASE)
        return ctx
    except Exception as e:
        print(f"⚠️  Context generation failed for chunk: {e}")
        return ""


def _contextualize_chunk(
    chunk_id: str,
    chunk_text: str,
    metadata: dict,
    openai_client,
    model: str,
    cache: dict,
    stats: dict,
) -> str:
    """Return the text to embed: optional context prefix + original text.

    Uses the persistent cache (keyed by chunk_id + sha1(text)) so unchanged
    chunks never re-call the LLM. Updates `cache` in place and increments
    `stats` counters for logging.
    """
    if not _contextual_enabled() or openai_client is None:
        stats["skipped"] += 1
        return chunk_text

    text_hash = hashlib.sha1(chunk_text.encode("utf-8")).hexdigest()[:16]
    cache_key = f"{chunk_id}:{text_hash}"
    cached = cache.get(cache_key)
    if cached is not None:
        stats["cached"] += 1
        ctx = cached
    else:
        ctx = _generate_chunk_context(openai_client, model, chunk_text, metadata)
        cache[cache_key] = ctx
        stats["generated"] += 1
        if not ctx:
            # Generation failed — embed as-is. Don't cache the failure so a
            # later retry (e.g. transient network error) can succeed.
            return chunk_text

    # Wrap the context in angle-bracket markers so a human inspecting the
    # stored document can distinguish it from the chunk's own content. The
    # embedding model sees it as natural-language context.
    return f"<Context: {ctx}>\n{chunk_text}"


# ---------------------------------------------------------------------------
# Entity glossary loading (for alias injection into chunk text)
# ---------------------------------------------------------------------------

def _load_entity_glossary() -> dict:
    """Load data/entity_glossary.json. Returns {} if missing/corrupt.

    The glossary maps canonical names → {aliases, category, description}.
    Used to inject 'Also known as: ...' aliases into chunk text so STT-
    mangled queries ("s robot", "watch guards") still hit the canonical
    embedding.
    """
    project_root = Path(__file__).parent.parent
    glossary_path = project_root / "data" / "entity_glossary.json"
    if not glossary_path.exists():
        return {}
    try:
        return json.loads(glossary_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  Entity glossary corrupt, skipping alias injection: {e}")
        return {}


def _find_chunk_entities(chunk_text: str, glossary: dict) -> list:
    """Return canonical entity names mentioned in the chunk text.

    Matches case-insensitively against both the canonical name and its
    aliases using WORD-BOUNDARY regex (not bare substring), so short aliases
    like 's robot' do NOT match inside 'AWS Robotics'. Used to (a) inject
    remaining aliases into the embed text and (b) record entity_names in
    chunk metadata for later filtering.
    """
    if not glossary:
        return []
    found = []
    products = glossary.get("products", {})
    for canonical, info in products.items():
        names_to_check = [canonical] + [a for a in info.get("aliases", []) if a]
        matched = False
        for name in names_to_check:
            # Word-boundary match prevents 's robot' matching inside
            # 'AWS Robotics'. re.escape handles hyphens etc. safely.
            pattern = r'\b' + re.escape(name.lower()) + r'\b'
            if re.search(pattern, chunk_text.lower()):
                matched = True
                break
        if matched:
            found.append(canonical)
    return found


def _inject_aliases(chunk_text: str, entities: list, glossary: dict) -> str:
    """Append an 'Also known as:' line listing aliases not already in the text.

    This expands the chunk's keyword surface area so BM25 and dense retrieval
    both catch STT variants. Only injects aliases that are NOT already present
    (avoid redundancy). Returns the original text if no aliases to add.
    """
    if not entities or not glossary:
        return chunk_text
    products = glossary.get("products", {})
    text_lower = chunk_text.lower()
    extra_aliases = []
    for entity in entities:
        info = products.get(entity)
        if not info:
            continue
        for alias in info.get("aliases", []):
            if alias and alias.lower() not in text_lower:
                extra_aliases.append(alias)
    if not extra_aliases:
        return chunk_text
    # Cap the alias list to avoid bloating the chunk
    alias_line = "Also known as: " + ", ".join(extra_aliases[:8]) + "."
    return f"{chunk_text}\n{alias_line}"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _flatten_value(val, indent: int = 0) -> str:
    """Recursively flatten any JSON value into a readable string."""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, list):
        parts = []
        for item in val:
            flat = _flatten_value(item, indent + 1)
            if flat:
                parts.append(flat)
        return "; ".join(parts)
    if isinstance(val, dict):
        name = val.get("name") or val.get("title") or val.get("area") or val.get("question") or ""
        desc = val.get("description") or val.get("detail") or val.get("answer") or val.get("story") or ""
        # Preserve extra structured fields (type, collaboration, specs, etc.) so they
        # become retrievable text. Previously these were silently dropped when a
        # name+description was present, hiding facts like a partner's "type" or
        # "collaboration" details from semantic search.
        reserved = {"name", "title", "area", "question", "description", "detail", "answer", "story"}
        extras = []
        for k, v in val.items():
            if k in reserved:
                continue
            if isinstance(v, str) and v.strip():
                extras.append(f"{k.replace('_', ' ').title()}: {v.strip()}")
            elif isinstance(v, list) and all(isinstance(x, str) for x in v) and v:
                extras.append(f"{k.replace('_', ' ').title()}: {', '.join(v)}")
        if extras:
            extra_text = ". ".join(extras)
            desc = f"{desc}. {extra_text}" if desc else extra_text
        if name and desc:
            return f"{name}: {desc}"
        if name:
            return name
        if desc:
            return desc
        parts = []
        for k, v in val.items():
            if isinstance(v, (str, int, float, bool)):
                parts.append(f"{k}: {v}")
        return " | ".join(parts)
    return str(val)


# Keys at the top level of a JSON file whose value is a LIST of structured
# objects, rather than a nested dict. The generic section loop (below) only
# handles dict sections and `continue`s past anything else, so these list
# sections would otherwise be silently dropped during ingestion.
#
# Each entry maps the list key -> a loader function that knows how to turn
# each list item into one or more fine-grained chunks. Add new entries here
# when a knowledge-base file introduces another top-level list section.
_LIST_SECTION_LOADERS: dict[str, callable] = {}  # populated below (fwd-decl)


def _slugify(name: str) -> str:
    """Turn a product/person name into a URL/ID-friendly slug.
    e.g. "Chikku Voice AI Kiosk" -> "chikku-voice-ai-kiosk"
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _load_featured_products(
    featured_list: list,
    file_topic: str,
    json_file: Path,
) -> list[dict]:
    """
    Turn the `featured_products` list into fine-grained semantic chunks.

    Each product produces up to 4 chunks so retrieval is sharp:
      - product_overview     : name + category + tagline + description
      - product_features     : key_features
      - product_benefits     : key_benefits / use_cases (if present)
      - product_technologies : core_technologies + target_environments

    Short embeddings of focused text beat one giant embedding that dilutes
    every signal — this is why we split instead of stuffing one chunk.

    Metadata uses topic="products" so it lives with other product data and
    is still discoverable by the products topic router, and a dedicated
    subtopic="featured_products" + product_name for filtering.
    """
    chunks: list[dict] = []

    for product in featured_list:
        if not isinstance(product, dict):
            continue

        name = product.get("name", "").strip()
        if not name:
            continue  # nothing to index without a name

        category = product.get("category", "").strip()
        tagline = product.get("tagline", "").strip()
        description = product.get("description", "").strip()
        slug = _slugify(name)

        base_meta = {
            "doc_type": "robotics",
            "source": f"robotics/{json_file.name}",
            "topic": file_topic,
            "subtopic": "featured_products",
            "title": name,
            "product_name": name,
            "category": category,
        }

        # ---- 1. Overview chunk ----
        overview_parts = [f"[{name}]"]
        if category:
            overview_parts.append(f"Category: {category}")
        if tagline:
            overview_parts.append(f"Tagline: {tagline}")
        if description:
            overview_parts.append(description)
        overview_text = " | ".join(overview_parts)
        if len(overview_parts) > 1:  # has substance beyond the bare name
            chunks.append({
                "id": f"robotics:{file_topic}:featured_products:{slug}:overview",
                "text": overview_text,
                "metadata": {**base_meta, "chunk_type": "product_overview"},
            })

        # ---- 2. Features chunk ----
        key_features = product.get("key_features", [])
        if isinstance(key_features, list) and key_features:
            feat_lines = [f"{name} — key features:"]
            for feat in key_features:
                if isinstance(feat, str) and feat.strip():
                    feat_lines.append(f"• {feat.strip()}")
            chunks.append({
                "id": f"robotics:{file_topic}:featured_products:{slug}:features",
                "text": "\n".join(feat_lines),
                "metadata": {**base_meta, "chunk_type": "product_features"},
            })

        # ---- 3. Benefits / use-cases chunk ----
        # `key_benefits` (S-Robot) is a dict of aspect -> text;
        # `use_cases` (Kiosk) is a dict of environment -> list of strings.
        benefits_parts: list[str] = []
        key_benefits = product.get("key_benefits")
        if isinstance(key_benefits, dict) and key_benefits:
            for aspect, text in key_benefits.items():
                label = aspect.replace("_", " ").title()
                if isinstance(text, str) and text.strip():
                    benefits_parts.append(f"{label}: {text.strip()}")
        use_cases = product.get("use_cases")
        if isinstance(use_cases, dict) and use_cases:
            for env, items in use_cases.items():
                label = env.replace("_", " ").title()
                if isinstance(items, list) and items:
                    items_str = "; ".join(str(i).strip() for i in items if str(i).strip())
                    if items_str:
                        benefits_parts.append(f"{label}: {items_str}")
                elif isinstance(items, str) and items.strip():
                    benefits_parts.append(f"{label}: {items.strip()}")
        # WatchGuard6S has a top-level `mission` field — fold it in here so
        # "what is the mission of WatchGuard6S?" hits a benefits-style chunk.
        mission = product.get("mission")
        if isinstance(mission, str) and mission.strip():
            benefits_parts.append(f"Mission: {mission.strip()}")

        if benefits_parts:
            chunks.append({
                "id": f"robotics:{file_topic}:featured_products:{slug}:benefits",
                "text": f"{name} — value & use cases:\n" + "\n".join(benefits_parts),
                "metadata": {**base_meta, "chunk_type": "product_benefits"},
            })

        # ---- 4. Technologies & target environments chunk ----
        tech_parts: list[str] = []
        core_tech = product.get("core_technologies", [])
        if isinstance(core_tech, list) and core_tech:
            tech_parts.append("Core technologies: " + ", ".join(
                str(t).strip() for t in core_tech if str(t).strip()
            ))
        target_envs = product.get("target_environments", [])
        if isinstance(target_envs, list) and target_envs:
            tech_parts.append("Target environments: " + ", ".join(
                str(e).strip() for e in target_envs if str(e).strip()
            ))
        if tech_parts:
            chunks.append({
                "id": f"robotics:{file_topic}:featured_products:{slug}:technologies",
                "text": f"{name} — technologies & deployment:\n" + "\n".join(tech_parts),
                "metadata": {**base_meta, "chunk_type": "product_technologies"},
            })

    return chunks


# Register the featured_products loader. Done after definition so the name
# is in scope.
_LIST_SECTION_LOADERS["featured_products"] = _load_featured_products


def load_json_data(kb_dir: Path) -> list[dict]:
    """
    Load all JSON files from the robotics knowledge base directory.
    Creates FINE-GRAINED chunks for better semantic search:
    - FAQ items get individual chunks (question + answer)
    - Leadership/person entries get individual chunks
    - Array items (products, partners, etc.) get individual chunks
    - Top-level sections still get overview chunks
    - Top-level LIST sections (e.g. featured_products) get multi-chunk
      treatment via dedicated loaders in _LIST_SECTION_LOADERS
    """
    chunks: list[dict] = []

    # Fields that should produce individual chunks per array item.
    # NOTE: "faq_items" is intentionally excluded — it already has dedicated
    # handling above (lines ~110) that builds clean "Q: ...\nA: ..." chunks.
    # Including it here would double-index every FAQ with different text/ids,
    # skewing retrieval rankings.
    ITEM_ARRAY_KEYS = [
        "products", "technologies", "sectors", "highlights",
        "offerings", "programs", "models", "platforms",
        "capabilities", "applications", "features", "partners",
        "labs", "case_studies", "standards",
        "safety_features", "priorities", "values",
        "key_features", "key_patent_areas", "benefits",
        "key_research_areas", "specifications", "sensors",
        "safety_certifications", "global_offices", "jurisdictions",
        "conferences", "timeline",
    ]

    # Fields representing individual people — always create separate chunks
    PERSON_SUBKEYS = ["founder_director", "director", "founder", "ceo", "cto", "coo",
                      "leadership", "management", "team"]

    for json_file in sorted(kb_dir.glob("*.json")):
        # Skip files marked as not needed
        if "_no_need" in json_file.name:
            print(f"   ⏭️  Skipping {json_file.name} (marked _no_need)")
            continue

        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        file_topic = json_file.stem

        # ---- TOP-LEVEL faq_items ----
        # faq.json (and possibly other files) puts `faq_items` at the root
        # of the JSON, not nested inside a section. The section loop below
        # only scans dict sections, so without this block every top-level
        # FAQ would be silently dropped (which is why "how much does a
        # Chikku robot cost?" used to fail — the answer lived only in FAQ).
        top_faq = data.get("faq_items")
        if isinstance(top_faq, list) and top_faq:
            for i, faq in enumerate(top_faq):
                if isinstance(faq, dict):
                    q = faq.get("question", "").strip()
                    a = faq.get("answer", "").strip()
                    if q and a:
                        chunks.append({
                            "id": f"robotics:{file_topic}:top:faq_{i}",
                            "text": f"Q: {q}\nA: {a}",
                            "metadata": {
                                "doc_type": "robotics",
                                "source": f"robotics/{json_file.name}",
                                "topic": file_topic,
                                "subtopic": "faq_items",
                                "title": q,
                                "chunk_type": "faq_item",
                            }
                        })

        for section_key, section_value in data.items():
            # ---- Top-level LIST sections (e.g. featured_products) ----
            # These are not dict sections, so the generic loop below skips them.
            # Dispatch to a dedicated loader when one is registered for this key.
            if isinstance(section_value, list):
                loader = _LIST_SECTION_LOADERS.get(section_key)
                if loader:
                    new_chunks = loader(section_value, file_topic, json_file)
                    chunks.extend(new_chunks)
                # Unknown list sections are intentionally ignored — add a loader
                # to _LIST_SECTION_LOADERS if you want to index a new one.
                continue

            if not isinstance(section_value, dict):
                continue

            title = section_value.get("title", section_key.replace("_", " ").title())
            description = section_value.get("description", "")

            # ---- Handle FAQ items: ONE CHUNK PER FAQ ----
            faq_items = section_value.get("faq_items", [])
            if isinstance(faq_items, list) and faq_items:
                for i, faq in enumerate(faq_items):
                    if isinstance(faq, dict):
                        q = faq.get("question", "")
                        a = faq.get("answer", "")
                        if q and a:
                            chunks.append({
                                "id": f"robotics:{file_topic}:{section_key}:faq_{i}",
                                "text": f"Q: {q}\nA: {a}",
                                "metadata": {
                                    "doc_type": "robotics",
                                    "source": f"robotics/{json_file.name}",
                                    "topic": file_topic,
                                    "subtopic": section_key,
                                    "title": q,
                                    "chunk_type": "faq_item",
                                }
                            })

            # ---- Handle PERSON entries: ONE CHUNK PER PERSON ----
            # Look for sub-dicts that represent individual people (with name + title/description)
            person_chunks_created = False
            for sub_key, sub_val in section_value.items():
                if isinstance(sub_val, dict):
                    # Check if this looks like a person entry
                    has_name = sub_val.get("name")
                    has_title = sub_val.get("title")
                    has_desc = sub_val.get("description")
                    is_person = has_name and (has_title or has_desc)
                    is_person_subkey = any(pk in sub_key.lower() for pk in PERSON_SUBKEYS)

                    if is_person or is_person_subkey:
                        person_name = has_name or sub_key.replace("_", " ").title()
                        person_title = has_title or ""
                        person_desc = has_desc or ""
                        # Build a rich, searchable text chunk for this person
                        section_context = section_key.replace("_", " ")
                        person_text = f"{section_context}: {person_name}"
                        if person_title:
                            person_text += f" — {person_title}"
                        if person_desc:
                            person_text += f". {person_desc}"
                        chunks.append({
                            "id": f"robotics:{file_topic}:{section_key}:{sub_key}",
                            "text": person_text,
                            "metadata": {
                                "doc_type": "robotics",
                                "source": f"robotics/{json_file.name}",
                                "topic": file_topic,
                                "subtopic": section_key,
                                "title": f"{person_name} ({person_title})" if person_title else person_name,
                                "chunk_type": "person",
                                "person_name": person_name,
                                "person_title": person_title,
                            }
                        })
                        person_chunks_created = True

            # ---- Handle ITEM ARRAYS: ONE CHUNK PER ITEM ----
            for list_key in ITEM_ARRAY_KEYS:
                items = section_value.get(list_key)
                if items and isinstance(items, list):
                    for i, item in enumerate(items):
                        flat = _flatten_value(item)
                        if flat:
                            item_title = ""
                            if isinstance(item, dict):
                                item_title = item.get("name") or item.get("title") or item.get("area") or item.get("question") or ""
                            
                            # Prefix with section context for better semantic matching
                            section_context = section_key.replace("_", " ")
                            if item_title:
                                prefix = f"{section_context}: {item_title}: "
                            else:
                                prefix = f"{section_context}: "
                            
                            chunks.append({
                                "id": f"robotics:{file_topic}:{section_key}:{list_key}_{i}",
                                "text": f"{prefix}{flat}",
                                "metadata": {
                                    "doc_type": "robotics",
                                    "source": f"robotics/{json_file.name}",
                                    "topic": file_topic,
                                    "subtopic": section_key,
                                    "title": item_title or f"{list_key} #{i+1}",
                                    "chunk_type": list_key if list_key != "faq_items" else "faq_item",
                                }
                            })

            # ---- Section overview chunk (lower priority but good for general queries) ----
            # Only create if we didn't already create person chunks (which are more granular)
            text_parts = [f"[{title}]"]
            if description:
                text_parts.append(description)

            # Handle special string fields at this level
            for str_key in ["meaning", "mission", "tagline", "greeting",
                           "inspiration", "vision", "story", "pronunciation",
                           "name", "founded", "headquarters", "employees"]:
                val = section_value.get(str_key)
                if isinstance(val, str) and val:
                    text_parts.append(f"{str_key.replace('_', ' ').title()}: {val}")

            if len(text_parts) > 1:  # Only create overview if there's substance
                text = " | ".join(text_parts)
                chunks.append({
                    "id": f"robotics:{file_topic}:{section_key}:overview",
                    "text": text,
                    "metadata": {
                        "doc_type": "robotics",
                        "source": f"robotics/{json_file.name}",
                        "topic": file_topic,
                        "subtopic": section_key,
                        "title": title,
                        "chunk_type": "section_overview",
                    }
                })

    # ---- Post-processing: inject entity aliases + record entity_names ----
    # For every chunk, detect which canonical products it mentions (via the
    # entity glossary) and (a) append a hidden 'Also known as:' line of STT
    # variants to the embed text, and (b) store entity_names in metadata for
    # later filtering. This is what makes 's robot' / 'watch guards' queries
    # hit the canonical S-Robot / WatchGuard6S chunks despite STT mangling.
    _inject_glossary_aliases(chunks)

    return chunks


def _inject_glossary_aliases(chunks: list[dict]) -> None:
    """Mutate chunks in place: append alias line + add entity_names metadata.

    Idempotent: if a chunk already has an 'Also known as:' line (from a prior
    run on the same data), it is not duplicated.
    """
    glossary = _load_entity_glossary()
    if not glossary:
        return
    touched = 0
    for chunk in chunks:
        text = chunk.get("text", "")
        if not text or "Also known as:" in text:
            # Already enriched (or empty) — just record entities in metadata
            entities = _find_chunk_entities(text, glossary)
            if entities:
                chunk.setdefault("metadata", {})["entity_names"] = entities
            continue
        entities = _find_chunk_entities(text, glossary)
        if entities:
            new_text = _inject_aliases(text, entities, glossary)
            if new_text != text:
                chunk["text"] = new_text
                touched += 1
            chunk.setdefault("metadata", {})["entity_names"] = entities
    if touched:
        print(f"   🔖 Injected entity aliases into {touched} chunk(s)")


def load_about_chunks(about_path: Path) -> list[dict]:
    """
    Load about_robotics.txt and split into paragraph-level chunks.
    """
    if not about_path.exists():
        print(f"⚠️  about file not found: {about_path}")
        return []

    text = about_path.read_text(encoding="utf-8").strip()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[dict] = []
    for i, para in enumerate(paragraphs):
        # Derive a rough topic from the first line
        first_line = para.split("\n")[0].strip()
        topic = first_line.lower().replace(" ", "_").replace("&", "and")

        chunks.append({
            "id": f"robotics:about:{i}",
            "text": para,
            "metadata": {
                "doc_type": "about",
                "source": "about_robotics.txt",
                "topic": "about",
                "subtopic": topic,
                "title": first_line,
            }
        })

    # Apply the same entity-alias injection used by load_json_data so that
    # about-paragraphs mentioning products (e.g. "service robots") also pick
    # up their STT aliases and entity_names metadata.
    _inject_glossary_aliases(chunks)

    return chunks


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def ingest_robotics(
    chroma_dir: str | Path,
    kb_dir: str | Path | None = None,
    about_path: str | Path | None = None,
):
    """
    Main ingestion routine.

    Args:
        chroma_dir: Path to ChromaDB persistent directory.
        kb_dir: Path to robotics knowledge_base directory (JSON files).
        about_path: Path to about_robotics.txt.
    """
    project_root = Path(__file__).parent.parent
    chroma_dir = Path(chroma_dir)

    if kb_dir is None:
        kb_dir = project_root / "data" / "knowledge_base" / "robotics"
    kb_dir = Path(kb_dir)

    if about_path is None:
        about_path = project_root / "data" / "processed" / "about_robotics.txt"
    about_path = Path(about_path)

    # --- Load chunks ---
    print("📦 Loading robotics knowledge base...")
    json_chunks = load_json_data(kb_dir)
    print(f"   JSON chunks: {len(json_chunks)}")

    about_chunks = load_about_chunks(about_path)
    print(f"   About chunks: {len(about_chunks)}")

    all_chunks = json_chunks + about_chunks
    if not all_chunks:
        print("⚠️  No chunks to ingest — aborting.")
        return

    print(f"   Total chunks: {len(all_chunks)}")

    # --- Connect to ChromaDB ---
    cfg = get_bot_config()
    collection_name = cfg.collection_name  # "chikku_robotics"

    client = chromadb.PersistentClient(path=str(chroma_dir))

    try:
        collection = client.get_collection(name=collection_name)
        # Warn if the existing collection was built with the wrong distance metric.
        # mxbai-embed-large is designed for cosine similarity; ChromaDB defaults to L2.
        col_meta = collection.metadata or {}
        if col_meta.get("hnsw:space", "l2") != "cosine":
            print(
                f"⚠️  Existing collection '{collection_name}' uses distance "
                f"'{col_meta.get('hnsw:space', 'l2')}' but embeddings require 'cosine'.\n"
                f"   Delete chroma_db/ and re-run ingestion to rebuild with the correct metric."
            )
        print(f"📂 Using existing collection: {collection_name} ({collection.count()} docs)")
    except Exception:
        # mxbai-embed-large is a cosine-similarity model, so we force hnsw:space=cosine.
        # ChromaDB's default metric (l2) produces poor rankings for these embeddings.
        collection = client.create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
                "description": f"{cfg.company_name} knowledge base",
            }
        )
        print(f"✅ Created collection: {collection_name} (cosine distance)")

    # --- Generate embeddings ---
    provider = get_provider()
    print(f"🔄 Generating embeddings via {provider.embedding_model}...")

    # --- Contextual Retrieval setup ---
    # Each chunk may be prefixed with 1-2 sentences of LLM-generated context
    # (Anthropic technique) before embedding. Contexts are cached to
    # data/context_cache.json keyed by (chunk_id, text_hash) so unchanged
    # chunks are free on re-ingest. Gated by CONTEXTUAL_EMBEDDINGS_ENABLED.
    contextual_on = _contextual_enabled()
    openai_client = _get_openai_context_client() if contextual_on else None
    context_model = os.getenv("OPENAI_CONTEXT_MODEL", "gpt-4o-mini")
    if contextual_on and openai_client is None:
        print(
            "ℹ️  Contextual Retrieval enabled but OPENAI_API_KEY missing — "
            "embedding chunks WITHOUT context prefix. Set OPENAI_API_KEY to enable."
        )
        contextual_on = False
    elif contextual_on:
        print(f"🧠 Contextual Retrieval: ON (model={context_model}, cached to data/context_cache.json)")

    context_cache = _load_context_cache() if contextual_on else {}
    ctx_stats = {"generated": 0, "cached": 0, "skipped": 0}

    ids = [c["id"] for c in all_chunks]
    raw_texts = [c["text"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    # Build embeddings, SKIPPING any chunk that fails to embed.
    # Previously a failed embed produced a zero vector that silently poisoned
    # retrieval (zero vectors match spuriously under cosine similarity).
    #
    # NOTE on storage: ChromaDB stores the DOCUMENT (text) alongside the
    # embedding. We store the CONTEXTUALIZED text (context + body + aliases)
    # so retrieval, reranking, and the LLM context window all see the rich
    # version — the context prefix also helps the LLM ground its answer.
    valid_ids, valid_texts, valid_metadatas, embeddings = [], [], [], []
    skipped = 0
    embed_desc = "Embedding chunks" + (" (with context)" if contextual_on else "")
    for i in tqdm(range(len(raw_texts)), desc=embed_desc):
        chunk_id = ids[i]
        # Decide the text to embed: optionally context-prefix the raw chunk.
        if contextual_on:
            embed_text = _contextualize_chunk(
                chunk_id, raw_texts[i], metadatas[i],
                openai_client, context_model, context_cache, ctx_stats,
            )
        else:
            embed_text = raw_texts[i]
        try:
            emb = provider.embed(embed_text)
        except Exception as e:
            print(f"⚠️  Embed error, SKIPPING chunk '{chunk_id}': {e}")
            skipped += 1
            continue
        valid_ids.append(chunk_id)
        valid_texts.append(embed_text)
        valid_metadatas.append(metadatas[i])
        embeddings.append(emb)

    # Persist the context cache (even partial) so a later re-run reuses it.
    if contextual_on:
        _save_context_cache(context_cache)
        print(
            f"   🧠 Context: {ctx_stats['generated']} generated, "
            f"{ctx_stats['cached']} cached, {ctx_stats['skipped']} skipped"
        )

    if not valid_ids:
        print("❌ No chunks were embedded successfully — aborting.")
        return
    if skipped:
        print(f"   Skipped {skipped} chunk(s) that failed to embed.")

    # --- Store in ChromaDB (upsert: remove old then add) ---
    print(f"\n💾 Storing {len(valid_ids)} chunks in ChromaDB...")

    # Remove old robotics docs to avoid duplicates
    try:
        existing = collection.get(ids=valid_ids)
        if existing and existing.get("ids"):
            collection.delete(ids=existing["ids"])
            print(f"   Removed {len(existing['ids'])} existing robotics docs")
    except Exception:
        pass

    collection.add(
        ids=valid_ids,
        embeddings=embeddings,
        documents=valid_texts,
        metadatas=valid_metadatas,
    )

    print(f"\n✅ Robotics ingestion complete!")
    print(f"   Collection: {collection_name}")
    print(f"   Total docs: {collection.count()}")
    print(f"   Topics: {sorted(set(m['topic'] for m in valid_metadatas))}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Chikku Robotics data into ChromaDB"
    )
    parser.add_argument(
        "--chroma-dir",
        default=None,
        help="Path to chroma_db directory (default: <project_root>/chroma_db)",
    )
    parser.add_argument(
        "--kb-dir",
        default=None,
        help="Path to robotics KB directory (default: data/knowledge_base/robotics)",
    )
    parser.add_argument(
        "--about-path",
        default=None,
        help="Path to about_robotics.txt (default: data/processed/about_robotics.txt)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    chroma_dir = Path(args.chroma_dir) if args.chroma_dir else (project_root / "chroma_db")

    ingest_robotics(
        chroma_dir=str(chroma_dir),
        kb_dir=args.kb_dir,
        about_path=args.about_path,
    )


if __name__ == "__main__":
    main()
