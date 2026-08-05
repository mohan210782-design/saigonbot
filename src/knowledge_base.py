"""
Knowledge Base Module
Loads and serves structured knowledge for Chikku Robotics.
Features smart topic-aware search across all KB sections.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

from bot_config import get_bot_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic → KB Section mapping for smart query routing
# ---------------------------------------------------------------------------
TOPIC_SECTION_MAP: Dict[str, Tuple[str, List[str]]] = {
    # (section_name, [detection_keywords])
    "products":      ("products",      ["product", "products", "robot", "robots", "guidebot", "cobot", "cobots", "drone", "drones", "hardware", "software", "model", "models", "sensor", "sensors", "specification", "specs", "autonomous", "make"]),
    "services":      ("services",      ["service", "services", "consulting", "training", "maintenance", "support plan", "engineering", "deployment", "warranty", "support", "offer", "offerings"]),
    "technologies":  ("technologies",  ["technology", "technologies", "artificial intelligence", "machine learning", "deep learning", "computer vision", "nlp", "edge computing", "reinforcement learning", "generative ai", "ai platform", "chikku brain", "ai"]),
    "solutions":     ("solutions",     ["solution", "industry", "manufacturing", "healthcare", "warehousing", "logistics", "smart city", "smart cities", "agriculture", "hospitality", "retail"]),
    "partnerships":  ("partnerships",  ["partner", "partnership", "collaboration", "collaborate", "nvidia", "aws", "qualcomm", "alliance"]),
    "company_overview": ("company_overview", ["company", "overview", "mission", "vision", "headquarters", "values", "headquarter", "office", "location", "about chikku", "what is chikku", "chikku robotics", "tell me about chikku"]),
    "identity":      ("identity",      ["identity", "brand", "founder", "founded", "director", "leadership", "leader", "name origin", "chikku meaning", "mean", "introduction", "who are you", "who is chikku", "owner", "owns", "ownership"]),
}


class KnowledgeBase:
    """Manages structured knowledge (restaurant or robotics)"""
    
    def __init__(self, kb_path: Optional[Path] = None):
        """
        Initialize knowledge base
        
        Args:
            kb_path: Path to knowledge base directory. Defaults to data/knowledge_base
        """
        if kb_path is None:
            project_root = Path(__file__).parent.parent
            kb_path = project_root / "data" / "knowledge_base"
        
        self.kb_path = Path(kb_path)
        self._data = {}
        self.bot_cfg = get_bot_config()
        self._load_all()
    
    def _load_all(self):
        """Load all knowledge base files dynamically based on identity"""
        try:
            for kb_dir in self.bot_cfg.knowledge_base_dirs:
                self._load_directory(kb_dir)
            
            # Load FAQ — identity-aware: only load common_questions.json for restaurant
            # For robotics, the FAQ is already loaded via _load_directory("robotics")
            self._load_faq()
            
            logger.info(f"✅ Knowledge base loaded from {self.kb_path} (dirs: {self.bot_cfg.knowledge_base_dirs})")
        except Exception as e:
            logger.error(f"⚠️  Failed to load knowledge base: {e}")
            self._data = {}
    
    def _load_directory(self, dir_name: str):
        """Load all JSON files from a knowledge base subdirectory"""
        dir_path = self.kb_path / dir_name
        
        if not dir_path.exists():
            logger.warning(f"Knowledge base directory not found: {dir_path}")
            return
        
        for json_file in sorted(dir_path.glob("*.json")):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Use filename (without .json) as key
                key = json_file.stem
                self._data[key] = data
                logger.debug(f"  Loaded: {dir_name}/{json_file.name}")
            except Exception as e:
                logger.warning(f"  Failed to load {json_file}: {e}")
    
    def _load_restaurant_info(self):
        """Load restaurant information files"""
        restaurant_path = self.kb_path / "restaurant"
        
        if not restaurant_path.exists():
            logger.warning(f"Restaurant info directory not found: {restaurant_path}")
            return
        
        # Load location
        location_file = restaurant_path / "location.json"
        if location_file.exists():
            with open(location_file, 'r', encoding='utf-8') as f:
                self._data['location'] = json.load(f)
        
        # Load hours
        hours_file = restaurant_path / "hours.json"
        if hours_file.exists():
            with open(hours_file, 'r', encoding='utf-8') as f:
                self._data['hours'] = json.load(f)
        
        # Load contact
        contact_file = restaurant_path / "contact.json"
        if contact_file.exists():
            with open(contact_file, 'r', encoding='utf-8') as f:
                self._data['contact'] = json.load(f)
        
        # Load policies
        policies_file = restaurant_path / "policies.json"
        if policies_file.exists():
            with open(policies_file, 'r', encoding='utf-8') as f:
                self._data['policies'] = json.load(f)
        
        # Load accessibility
        accessibility_file = restaurant_path / "accessibility.json"
        if accessibility_file.exists():
            with open(accessibility_file, 'r', encoding='utf-8') as f:
                self._data['accessibility'] = json.load(f)
    
    def _load_services(self):
        """Load service information files"""
        services_path = self.kb_path / "services"
        
        if not services_path.exists():
            logger.warning(f"Services directory not found: {services_path}")
            return
        
        # Load reservations
        reservations_file = services_path / "reservations.json"
        if reservations_file.exists():
            with open(reservations_file, 'r', encoding='utf-8') as f:
                self._data['reservations'] = json.load(f)
        
        # Load events
        events_file = services_path / "events.json"
        if events_file.exists():
            with open(events_file, 'r', encoding='utf-8') as f:
                self._data['events'] = json.load(f)
        
        # Load catering
        catering_file = services_path / "catering.json"
        if catering_file.exists():
            with open(catering_file, 'r', encoding='utf-8') as f:
                self._data['catering'] = json.load(f)
        
        # Load delivery
        delivery_file = services_path / "delivery.json"
        if delivery_file.exists():
            with open(delivery_file, 'r', encoding='utf-8') as f:
                self._data['delivery'] = json.load(f)
    
    def _load_faq(self):
        """Load FAQ — identity-aware.
        
        For restaurant: loads from knowledge_base/faq/common_questions.json
        For robotics: the FAQ is already loaded via _load_directory("robotics") as self._data['faq']
                      which contains the full JSON with faq_items array.
                      We normalize it to a flat list of {question, answer} dicts.
        """
        from bot_config import is_robotics
        
        if is_robotics():
            # Robotics FAQ is already loaded by _load_directory("robotics") as self._data['faq']
            # It's a dict with 'faq_items' key — normalize it to a list for search_faq()
            faq_data = self._data.get('faq', {})
            if isinstance(faq_data, dict) and 'faq_items' in faq_data:
                self._data['faq'] = faq_data.get('faq_items', [])
                logger.info(f"✅ Loaded {len(self._data['faq'])} robotics FAQ items")
            elif isinstance(faq_data, list):
                # Already normalized
                logger.info(f"✅ Using {len(faq_data)} FAQ items (already normalized)")
            else:
                logger.warning("⚠️  Robotics FAQ has unexpected format, resetting to empty")
                self._data['faq'] = []
        else:
            # Restaurant: load from common_questions.json
            faq_path = self.kb_path / "faq" / "common_questions.json"
            if faq_path.exists():
                with open(faq_path, 'r', encoding='utf-8') as f:
                    faq_data = json.load(f)
                    self._data['faq'] = faq_data.get('faq_items', [])
                logger.info(f"✅ Loaded {len(self._data['faq'])} restaurant FAQ items")
            else:
                logger.warning(f"⚠️  FAQ file not found: {faq_path}")
    
    def get_location(self) -> Optional[Dict]:
        """Get restaurant location information"""
        return self._data.get('location')
    
    def get_hours(self) -> Optional[Dict]:
        """Get restaurant hours"""
        return self._data.get('hours')
    
    def get_contact(self) -> Optional[Dict]:
        """Get contact information"""
        return self._data.get('contact')
    
    def get_policies(self) -> Optional[Dict]:
        """Get restaurant policies"""
        return self._data.get('policies')
    
    def get_accessibility(self) -> Optional[Dict]:
        """Get accessibility information"""
        return self._data.get('accessibility')
    
    def get_reservation_info(self) -> Optional[Dict]:
        """Get reservation information"""
        return self._data.get('reservations')
    
    def get_events_info(self) -> Optional[Dict]:
        """Get events/booking information"""
        return self._data.get('events')
    
    def get_catering_info(self) -> Optional[Dict]:
        """Get catering information"""
        return self._data.get('catering')
    
    def get_delivery_info(self) -> Optional[Dict]:
        """Get delivery information"""
        return self._data.get('delivery')
    
    def get_faq(self) -> List[Dict]:
        """Get FAQ items"""
        return self._data.get('faq', [])
    
    # ------------------------------------------------------------------
    # Smart Knowledge Base Search
    # ------------------------------------------------------------------
    
    @staticmethod
    def _stem_word(word: str) -> str:
        """
        Simple English stemmer — reduces words to a common base form.
        Handles common suffixes: -s, -es, -ies, -ed, -ing, -er, -or, -ment, -tion
        Examples: directors→director, robots→robot, partners→partner, technologies→technology
        """
        word_lower = word.lower()
        if len(word_lower) <= 3:
            return word_lower
        
        # Order matters — apply longer suffixes first
        suffixes = [
            ('ologies', 'ology'),   # technologies → technology
            ('ments', 'ment'),
            ('tions', 'tion'),
            ('iness', 'y'),
            ('nesses', 'ness'),
            ('ators', 'ator'),
            ('ables', 'able'),
            ('ities', 'ity'),
            ('ives', 'ive'),
            ('ings', 'ing'),
            ('ers', 'er'),
            ('ors', 'or'),
            ('ies', 'y'),           # companies → company
            ('es', ''),             # boxes → box, services → service
            ('s', ''),              # directors → director, robots → robot
        ]
        
        for suffix, replacement in suffixes:
            if word_lower.endswith(suffix) and len(word_lower) - len(suffix) >= 3:
                return word_lower[:-len(suffix)] + replacement
        
        return word_lower
    
    def _detect_topic(self, query: str) -> Optional[str]:
        """
        Detect which KB section the query is about based on keyword matching.
        Uses word-boundary matching for short keywords (<=3 chars) to avoid
        false positives (e.g. 'ai' matching inside 'training').
        Also uses stemming for better singular/plural matching.
        """
        query_lower = query.lower()
        best_topic = None
        best_score = 0
        
        topic_priority = ["technologies", "products", "solutions", "services", 
                          "partnerships", "identity", "company_overview"]
        
        for topic in topic_priority:
            if topic not in TOPIC_SECTION_MAP:
                continue
            section, keywords = TOPIC_SECTION_MAP[topic]
            score = 0
            for kw in keywords:
                if len(kw) <= 3:
                    # Short keywords: use word boundary to avoid substring false positives
                    if re.search(r'\b' + re.escape(kw) + r'\b', query_lower):
                        score += 1
                elif kw in query_lower:
                    score += 1
                else:
                    # Multi-word: check if all words appear (not necessarily contiguous)
                    kw_words = kw.split()
                    if len(kw_words) > 1 and all(
                        re.search(r'\b' + re.escape(w) + r'\b', query_lower) if len(w) <= 3 else w in query_lower
                        for w in kw_words
                    ):
                        score += 0.5
                    # Also try stemmed matching for single-word keywords
                    elif len(kw_words) == 1 and len(kw) > 4:
                        kw_stem = self._stem_word(kw)
                        query_words = query_lower.split()
                        for qw in query_words:
                            if self._stem_word(qw) == kw_stem:
                                score += 0.7
                                break
            if score > best_score:
                best_score = score
                best_topic = topic
        
        return best_topic if best_score >= 1 else None
    
    def _flatten_json_value(self, val, max_depth: int = 3, _depth: int = 0) -> str:
        """Recursively flatten any JSON value into a readable text string.
        Avoids duplicating the name when description already starts with it."""
        if _depth > max_depth:
            return ""
        if isinstance(val, str):
            return val
        if isinstance(val, (int, float, bool)):
            return str(val)
        if isinstance(val, list):
            parts = []
            for item in val:
                flat = self._flatten_json_value(item, max_depth, _depth + 1)
                if flat:
                    parts.append(flat)
            return "; ".join(parts)
        if isinstance(val, dict):
            name = val.get("name") or val.get("title") or val.get("question") or val.get("area") or ""
            desc = val.get("description") or val.get("answer") or val.get("detail") or val.get("story") or val.get("meaning") or ""
            if name and desc:
                # Avoid "Name: Name rest of description..." when desc starts with name
                desc_lower = desc.lower().strip()
                name_lower = name.lower().strip()
                if desc_lower.startswith(name_lower):
                    return desc
                return f"{name}: {desc}"
            if name:
                return name
            if desc:
                return desc
            # Generic flatten
            parts = []
            for k, v in val.items():
                if isinstance(v, (str, int, float, bool)):
                    parts.append(f"{k}: {v}")
            return " | ".join(parts)
        return str(val)
    
    def _extract_section_content(self, section_key: str) -> List[Dict]:
        """
        Extract searchable content chunks from a KB section.
        Returns list of {text, title, subtopic} dicts.
        """
        data = self._data.get(section_key)
        if not data:
            return []
        
        chunks = []
        
        if isinstance(data, list):
            # FAQ-style: list of {question, answer}
            for item in data:
                if isinstance(item, dict):
                    q = item.get("question", "")
                    a = item.get("answer", "")
                    if q and a:
                        chunks.append({"text": f"{q}\n{a}", "title": q, "subtopic": "faq"})
        
        elif isinstance(data, dict):
            # Check if it's a FAQ wrapper
            if "faq_items" in data:
                for item in data["faq_items"]:
                    if isinstance(item, dict):
                        q = item.get("question", "")
                        a = item.get("answer", "")
                        if q and a:
                            chunks.append({"text": f"{q}\n{a}", "title": q, "subtopic": "faq"})
                return chunks
            
            # General nested structure: iterate top-level keys
            for top_key, top_val in data.items():
                if isinstance(top_val, dict):
                    title = top_val.get("title", top_key.replace("_", " ").title())
                    desc = top_val.get("description", "")
                    
                    # --- Collect direct simple fields as individual chunks ---
                    for k, v in top_val.items():
                        if k == "name":
                            continue  # Skip standalone name — never useful as an answer
                        if isinstance(v, str) and k not in ["title", "description", "tagline"]:
                            key_label = k.replace('_', ' ').title()
                            # Include key in text for scoring, _format_kb_result will clean it
                            chunks.append({
                                "text": f"{key_label}: {v}",
                                "title": key_label,
                                "subtopic": top_key,
                                "field": k
                            })
                        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
                            key_label = k.replace('_', ' ').title()
                            items_str = ", ".join(v)
                            chunks.append({
                                "text": f"{key_label}: {items_str}",
                                "title": key_label,
                                "subtopic": top_key,
                                "field": k
                            })
                    
                    # Add the section overview (lower priority — placed after direct fields and arrays)
                    if desc:
                        chunks.append({"text": f"{desc}", "title": title, "subtopic": top_key, "field": "description", "_priority": "low"})
                    
                    # Handle arrays of items (products, partners, services, etc.)
                    for array_key in ["partners", "products", "technologies", "offerings", 
                                       "programs", "applications", "capabilities", "values",
                                       "features", "highlights", "models", "platforms",
                                       "sectors", "labs", "case_studies", "faq_items",
                                       "standards", "safety_features", "priorities",
                                       "key_features", "key_patent_areas", "benefits",
                                       "key_research_areas", "specifications", "sensors"]:
                        items = top_val.get(array_key, [])
                        if isinstance(items, list):
                            for item in items:
                                flat = self._flatten_json_value(item)
                                if flat:
                                    item_title = ""
                                    if isinstance(item, dict):
                                        item_title = item.get("name") or item.get("title") or item.get("area") or item.get("question") or ""
                                    # Avoid duplicating name when flat already starts with it
                                    context = top_key.replace('_', ' ')
                                    if item_title and flat.lower().startswith(item_title.lower()):
                                        chunks.append({
                                            "text": f"{context}: {flat}",
                                            "title": item_title or title,
                                            "subtopic": top_key
                                        })
                                    else:
                                        prefix = f"{item_title}: " if item_title else ""
                                        chunks.append({
                                            "text": f"{context}: {prefix}{flat}",
                                            "title": item_title or title,
                                            "subtopic": top_key
                                        })
                    
                    # Handle nested person/detail dicts
                    for sub_key, sub_val in top_val.items():
                        if isinstance(sub_val, dict) and sub_key not in ["title", "description"] + [
                            "partners", "products", "technologies", "offerings", "programs",
                            "applications", "capabilities", "values", "features", "highlights",
                            "models", "platforms", "sectors", "labs", "case_studies",
                            "standards", "safety_features", "priorities", "key_features",
                            "key_patent_areas", "benefits", "key_research_areas",
                            "specifications", "sensors", "faq_items"
                        ]:
                            flat = self._flatten_json_value(sub_val)
                            if flat:
                                sub_title = sub_val.get("name") or sub_val.get("title") or sub_key.replace("_", " ").title()
                                # Include parent key as context for scoring (stripped in _format_kb_result)
                                context = top_key.replace('_', ' ')
                                if flat.lower().startswith(sub_title.lower()):
                                    text = f"{context}: {flat}"
                                else:
                                    text = f"{context}: {sub_title}: {flat}"
                                chunks.append({
                                    "text": text,
                                    "title": sub_title,
                                    "subtopic": top_key
                                })
        
        return chunks
    
    def search_knowledge_base(self, query: str) -> str:
        """
        Smart topic-aware search across all knowledge base sections.
        
        1. Detect the topic from the query
        2. Search the corresponding KB section for relevant content
        3. Fall back to FAQ if no KB section content found
        4. Format and return the best answer
        
        Returns empty string if nothing found.
        """
        # Step 1: Detect topic
        topic = self._detect_topic(query)
        
        # Step 2: Search the detected section
        if topic:
            section_name = TOPIC_SECTION_MAP[topic][0]
            chunks = self._extract_section_content(section_name)
            
            if chunks:
                # Score chunks by keyword relevance (with stemming)
                query_lower = query.lower()
                query_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', query_lower)
                stop_words = {'the','and','for','are','you','your','what','how','does','can',
                              'will','with','that','this','from','have','has','been','who','is','do','where','when','tell','about'}
                query_words = [w for w in query_clean.split() if len(w) > 2 and w not in stop_words]
                # Compute stemmed query words for better matching
                query_stems = [self._stem_word(w) for w in query_words] if query_words else []
                
                if not query_words:
                    # Very short / all-stop-words query — do NOT return a random
                    # chunk. Fall through to FAQ matching (handled by caller).
                    return ""
                
                # Score and find best match
                best_chunk = None
                best_score = 0
                min_score = 1 if len(query_words) <= 2 else max(2, len(query_words) * 0.3)
                
                for chunk in chunks:
                    text_lower = chunk["text"].lower()
                    text_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', text_lower)
                    score = 0
                    # Compute stemmed text words once per chunk
                    text_words = text_clean.split()
                    text_stems = set(self._stem_word(tw) for tw in text_words if len(tw) > 2)
                    
                    for i, w in enumerate(query_words):
                        if w in text_clean:
                            score += 1.0  # Exact match
                        elif i < len(query_stems) and query_stems[i] in text_stems:
                            score += 0.8  # Stemmed match (singular/plural, etc.)
                        elif len(w) > 4:
                            # Partial/stem matching: check if any text word shares a long prefix
                            # e.g. "founded" ≈ "founder", "robots" ≈ "robotics"
                            for tw in text_words:
                                if len(tw) > 3:
                                    min_len = min(len(w), len(tw))
                                    common = sum(1 for a, b in zip(w, tw) if a == b)
                                    if common >= min_len - 1 and common >= 4:
                                        score += 0.5
                                        break
                    if score > best_score and score >= min_score:
                        best_score = score
                        best_chunk = chunk
                    elif score == best_score and best_chunk:
                        # Tiebreaker: prefer non-description chunks (array items, direct fields)
                        if chunk.get("_priority") != "low" and best_chunk.get("_priority") == "low":
                            best_chunk = chunk
                        # Also prefer longer, more informative chunks
                        elif (chunk.get("_priority") == best_chunk.get("_priority") 
                              and len(chunk.get("text", "")) > len(best_chunk.get("text", ""))):
                            best_chunk = chunk
                
                if best_chunk:
                    return self._format_kb_result(section_name, best_chunk)
                
                # No chunk scored above the minimum threshold — do NOT return a
                # random "first" chunk (that was a hallucination vector). Return
                # empty so the caller falls through to FAQ matching.
                return ""
        
        # Step 3: Fallback to FAQ search
        faq_answer = self.get_best_faq_match(query)
        if faq_answer:
            return faq_answer
        
        return ""
    
    def _format_kb_result(self, section: str, chunk: Dict) -> str:
        """Format a knowledge base chunk into a natural, conversational response."""
        text = chunk.get("text", "").strip()
        title = chunk.get("title", "")
        field = chunk.get("field", "")
        
        # Strip "Key: " prefix for direct field chunks (it was added for scoring)
        if field and title:
            prefix = f"{title}: "
            if text.startswith(prefix):
                text = text[len(prefix):]
        
        # Convert to natural language based on field type
        if field == "headquarters":
            text = f"We are headquartered in {text}"
        elif field == "global_offices":
            text = f"We have global offices in {text}"
        elif field == "mission":
            clean = text.strip()
            if clean.lower().startswith('to '):
                clean = clean[3:]  # Remove leading "To " to avoid "to to make"
            text = f"Our mission is to {clean[0].lower() + clean[1:] if clean else clean}"
        elif field == "vision":
            clean = text.strip()
            text = f"Our vision is {clean[0].lower() + clean[1:] if clean else clean}"
        elif field == "inspiration":
            text = f"The name Chikku is inspired by the {text}"
        elif field == "greeting":
            pass  # skip greeting in KB responses
        
        # For products/services lists, add natural framing
        if title and field not in ["headquarters", "global_offices", "mission", "vision", 
                                      "inspiration", "meaning", "greeting", "description"]:
            if ', ' in text and len(text.split(', ')) >= 2 and ': ' not in text:
                text = f"Our {title.lower()} include {text}"
        
        # Strip any remaining "Key: " or "context: " patterns from text
        text = re.sub(r'^[A-Za-z][A-Za-z0-9]*(?:\s[A-Za-z][A-Za-z0-9]*)*:\s', '', text)
        
        # Ensure text ends with proper punctuation
        text = text.strip()
        if text and not text[-1] in '.!?':
            text += '.'
        
        return f"{text}\n\nIs there anything else you'd like to know?"
    
    # ------------------------------------------------------------------
    # FAQ search (topic-specific keyword search)
    # ------------------------------------------------------------------
    
    def _search_faq_for_topic(self, keywords: list) -> str:
        """
        Search the FAQ for an answer matching given topic keywords.
        Returns the answer string if found, empty string otherwise.
        """
        import re
        faq_items = self.get_faq()
        if not faq_items:
            return ""
        
        for item in faq_items:
            if not isinstance(item, dict):
                continue
            question = item.get('question', '').lower()
            question_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', question)
            answer = item.get('answer', '')
            # Check if any keyword matches the question (punctuation-stripped)
            if any(kw.lower() in question_clean for kw in keywords):
                return answer
        
        return ""
    
    def get_best_faq_match(self, query: str) -> str:
        """
        Find the best matching FAQ answer for a user query.
        Uses a FAST exact/near-exact match first, then falls back to
        stemmed multi-word scoring with singular/plural normalization.
        
        Returns empty string if no good match found.
        """
        faq_items = self.get_faq()
        if not faq_items:
            return ""
        
        query_lower = query.lower().strip()
        # Strip common punctuation from the query for cleaner word matching
        import re
        query_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', query_lower)
        query_clean = re.sub(r'\s+', ' ', query_clean).strip()
        
        # -----------------------------------------------------------------
        # FAST PATH 1: Exact/near-exact match (O(n), no embedding needed).
        # Normalizes both query and FAQ question, then checks for:
        #   (a) exact string match
        #   (b) query is fully contained in question
        #   (c) question is fully contained in query
        # This catches "Who is your owner" ↔ "Who is your owner?" instantly.
        # -----------------------------------------------------------------
        for item in faq_items:
            if not isinstance(item, dict):
                continue
            question = item.get('question', '').lower()
            question_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', question)
            question_clean = re.sub(r'\s+', ' ', question_clean).strip()
            answer = item.get('answer', '')
            
            # (a) Exact match after normalization
            if query_clean == question_clean:
                return answer
            # (b) Query is fully contained in the question (e.g. "your owner" inside "who is your owner")
            if len(query_clean) >= 8 and query_clean in question_clean:
                return answer
            # (c) Question is fully contained in the query (user typed extra words)
            if len(question_clean) >= 8 and question_clean in query_clean:
                return answer
        
        # -----------------------------------------------------------------
        # FAST PATH 2: Significant word overlap (e.g. "owner" + "who").
        # If 80%+ of the meaningful query words appear in a question, it's
        # almost certainly the same intent. This is cheaper than the full
        # scoring loop below and catches phrasing variations.
        # -----------------------------------------------------------------
        stop_words = {'the', 'and', 'for', 'are', 'you', 'your', 'what', 'how', 'does', 
                      'can', 'will', 'with', 'that', 'this', 'from', 'have', 'has', 'been',
                      'who', 'is', 'do', 'where', 'when', 'tell', 'about', 'me', 'a', 'an',
                      'it', 'to', 'of', 'in', 'on', 'at', 'or', 'be', 'so', 'if', 'no'}
        query_words = [w for w in query_clean.split() if w not in stop_words]
        
        for item in faq_items:
            if not isinstance(item, dict):
                continue
            question = item.get('question', '').lower()
            question_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', question)
            question_clean = re.sub(r'\s+', ' ', question_clean).strip()
            answer = item.get('answer', '')
            
            if not query_words:
                continue
            matched = sum(1 for w in query_words if w in question_clean)
            ratio = matched / len(query_words)
            if ratio >= 0.8 and matched >= 1:
                return answer
        
        # -----------------------------------------------------------------
        # FULL SCORING: Stemmed multi-word scoring with singular/plural
        # normalization. Used as fallback for longer or more complex queries.
        # -----------------------------------------------------------------
        query_words = [w for w in query_clean.split() if len(w) > 2 and w not in stop_words]
        # Also compute stemmed versions
        query_stems = [self._stem_word(w) for w in query_words]
        
        if not query_words:
            return ""
        
        best_score = 0
        best_answer = ""
        # Dynamic threshold: at least 1 for short queries, higher for longer
        if len(query_words) <= 2:
            min_score = 1
        else:
            min_score = max(2, len(query_words) * 0.3)
        
        for item in faq_items:
            if not isinstance(item, dict):
                continue
            question = item.get('question', '').lower()
            question_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', question)
            answer = item.get('answer', '')
            
            # Compute stemmed question words
            question_words = [w for w in question_clean.split() if len(w) > 2]
            question_stems = set(self._stem_word(w) for w in question_words)
            
            # Score: exact match + stemmed match
            score = 0
            for i, w in enumerate(query_words):
                if w in question_clean:
                    score += 1.0  # Exact match
                elif i < len(query_stems) and query_stems[i] in question_stems:
                    score += 0.8  # Stemmed match (singular/plural, etc.)
            
            # Bonus: if the question is a near-exact match to the query
            if query_clean in question_clean or question_clean in query_clean:
                score += 10
            
            if score > best_score and score >= min_score:
                best_score = score
                best_answer = answer
        
        return best_answer
    
    def search_faq(self, query: str) -> List[Dict]:
        """
        Search FAQ for relevant questions
        
        Args:
            query: Search query
            
        Returns:
            List of matching FAQ items
        """
        query_lower = query.lower()
        faq_items = self.get_faq()
        
        matches = []
        for item in faq_items:
            question = item.get('question', '').lower()
            answer = item.get('answer', '').lower()
            
            # Simple keyword matching
            if any(word in question or word in answer for word in query_lower.split() if len(word) > 2):
                matches.append(item)
        
        return matches
    
    def format_location(self) -> str:
        """Format location as human-readable text (identity-aware)."""
        from bot_config import is_robotics
        
        if is_robotics():
            # For robotics, search FAQ for location-related answer
            answer = self._search_faq_for_topic(['location', 'located', 'headquarters', 'office', 'where are you'])
            if answer:
                return f"📍 **{self.bot_cfg.company_name} — Location**\n\n{answer}\n\nIs there anything else you'd like to know about our locations? 🌍"
            # Fallback: try company_overview data
            overview = self._data.get('company_overview', {})
            company = overview.get('company', {})
            if company:
                hq = company.get('headquarters', '')
                offices = company.get('global_offices', [])
                if hq or offices:
                    parts = [f"📍 **{self.bot_cfg.company_name} — Location**\n"]
                    if hq:
                        parts.append(f"🏢 Headquarters: {hq}")
                    if offices:
                        parts.append("🌍 Global Offices:")
                        for office in offices:
                            parts.append(f"   • {office}")
                    parts.append("\nWe serve customers globally through our direct sales team and partner network. 🌐")
                    return "\n".join(parts)
            return ""
        
        # Restaurant path (original)
        location = self.get_location()
        if not location:
            return ""
        
        addr = location.get('address', {})
        return f"""📍 **{location.get('restaurant_name', 'Saigon Indian Restaurant')}**

{addr.get('full_address', '')}

We're located in the heart of District 1, making it convenient for both locals and visitors. Need directions or more information? Just ask! 😊"""
    
    def format_hours(self) -> str:
        """Format hours as human-readable text (identity-aware)."""
        from bot_config import is_robotics
        
        if is_robotics():
            # For robotics, there's no specific hours — use FAQ or company info
            # Try searching FAQ for business hours / operating hours specifically
            answer = self._search_faq_for_topic(['business hours', 'operating hours', 'opening hours', 'what time', 'office hours', 'working hours'])
            if answer:
                return f"🕒 **{self.bot_cfg.company_name} — Availability**\n\n{answer}"
            # Fallback: generic business hours response
            return f"""🕒 **{self.bot_cfg.company_name} — Business Hours**

Our offices and R&D labs operate during standard business hours (Monday–Friday, 9:00 AM – 6:00 PM local time).

For specific inquiries, please reach out to us at {self.bot_cfg.fallback_email}. We're happy to help! 😊"""
        
        # Restaurant path (original)
        hours = self.get_hours()
        if not hours:
            return ""
        
        return f"""🕒 **Opening Hours**

{hours.get('summary', 'Monday – Sunday: 7:30 AM – 10:30 PM')}

{hours.get('note', 'We serve Breakfast, Lunch & Dinner throughout the day!')}

Whether you're looking for an early morning dosa or a late-night curry, we're here for you! 😊"""
    
    def format_contact(self) -> str:
        """Format contact info as human-readable text (identity-aware)."""
        from bot_config import is_robotics
        
        if is_robotics():
            # For robotics, search FAQ for contact-related answer
            answer = self._search_faq_for_topic(['contact', 'email', 'phone', 'reach', 'get started', 'consultation'])
            if answer:
                return f"📞 **{self.bot_cfg.company_name} — Contact**\n\n{answer}"
            # Fallback
            email = self.bot_cfg.fallback_email
            return f"""📞 **{self.bot_cfg.company_name} — Contact**

✉️ Email: {email}

Feel free to reach out to us! We're happy to help with any questions about our AI and robotics solutions. 🤖"""
        
        # Restaurant path (original)
        contact = self.get_contact()
        if not contact:
            return ""
        
        phone = contact.get('phone', {})
        return f"""📞 **Contact Information**

Phone: {phone.get('formatted', '')}

✉️ Email: {contact.get('email', '')}

Feel free to call us for reservations, inquiries, or any questions! We're happy to help! 😊"""
    
    def get_restaurant_info_text(self) -> str:
        """Get full restaurant information as formatted text"""
        parts = []

        location_text = self.format_location()
        if location_text:
            parts.append(location_text)

        hours_text = self.format_hours()
        if hours_text:
            parts.append(hours_text)

        contact_text = self.format_contact()
        if contact_text:
            parts.append(contact_text)

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # FAQ question embedding cache (used by RAG's FAQ cache layer 1)
    # ------------------------------------------------------------------

    def get_faq_question_embeddings(
        self, embed_fn
    ) -> List[Tuple[str, str, List[float]]]:
        """Return [(question, answer, embedding)] for every FAQ question.

        Embeddings are computed lazily ONCE on first call and cached on this
        singleton (self._faq_q_emb_cache). The cache is invalidated if the FAQ
        list length changes (e.g. after a KB reload).

        The caller (RAGPipeline._faq_cache_lookup) computes cosine similarity
        between the query embedding and each question embedding to decide a
        strict FAQ hit, replacing the keyword-overlap matcher that
        mis-routed "what is chikku brain" → leadership FAQ.
        """
        faq_items = self.get_faq()
        # (re)build cache if missing or stale
        cache = getattr(self, "_faq_q_emb_cache", None)
        if cache is None or cache.get("_count") != len(faq_items):
            cache = None
        if cache is not None:
            return cache["items"]

        items: List[Tuple[str, str, List[float]]] = []
        for item in faq_items:
            if not isinstance(item, dict):
                continue
            question = (item.get("question") or "").strip()
            answer = (item.get("answer") or "").strip()
            if not question or not answer:
                continue
            try:
                vec = embed_fn(question)
            except Exception as e:
                logger.warning(f"FAQ embedding failed for '{question[:40]}...': {e}")
                continue
            if vec:
                items.append((question, answer, list(vec)))
        self._faq_q_emb_cache = {"_count": len(faq_items), "items": items}
        logger.info(f"✅ Cached {len(items)} FAQ question embeddings")
        return items

    def invalidate_faq_question_embeddings(self) -> None:
        """Drop the cached FAQ question embeddings (call after KB reload)."""
        if hasattr(self, "_faq_q_emb_cache"):
            del self._faq_q_emb_cache


# Global knowledge base instance
_kb_instance = None


def get_knowledge_base() -> KnowledgeBase:
    """Get or create global knowledge base instance"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance
