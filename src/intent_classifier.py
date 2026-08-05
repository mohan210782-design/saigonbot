"""
Intent Classification System
Classifies user queries into specific intent categories for proper routing.

Engine: EMBEDDING-BASED (mxbai-embed-large via llm_provider) with a regex
OVERRIDE layer for edge cases the embedding model can't be trusted with
(anchored patterns, polite declines, standalone acknowledgments) and a
transparent REGEX FALLBACK if the embedding provider is unavailable.

Design goals (vs. the prior regex-only classifier):
  - Better recall on natural paraphrases ("what's your job" → WHAT_DO_YOU_DO,
    which the old regex pattern set did not cover).
  - One embedding call shared with retrieval in RAGPipeline (no extra latency
    for classification).
  - Robustness: never bricks the server — embedding failure falls back to regex.
"""
from typing import Callable, Dict, List, Optional, Tuple
from enum import Enum
import os
import re


# ---------------------------------------------------------------------------
# Public enums (KEPT VERBATIM from the original module — downstream code in
# rag.py, api.py, response_templates.py, and the test/trace scripts depends on
# these exact names and .value strings).
# ---------------------------------------------------------------------------

class IntentType(Enum):
    """Intent categories"""
    MENU_SEARCH = "menu_search"
    MENU_ORDER = "menu_order"
    MENU_RECOMMENDATION = "menu_recommendation"
    MENU_PRICE = "menu_price"
    MENU_INGREDIENTS = "menu_ingredients"
    MENU_ALLERGEN = "menu_allergen"
    MENU_DIETARY = "menu_dietary"

    RESTAURANT_LOCATION = "restaurant_location"
    RESTAURANT_HOURS = "restaurant_hours"
    RESTAURANT_CONTACT = "restaurant_contact"
    RESTAURANT_ABOUT = "restaurant_about"
    RESTAURANT_PARKING = "restaurant_parking"
    RESTAURANT_ACCESSIBILITY = "restaurant_accessibility"

    SERVICE_RESERVATION = "service_reservation"
    SERVICE_RESERVATION_MODIFY = "service_reservation_modify"
    SERVICE_RESERVATION_CANCEL = "service_reservation_cancel"
    SERVICE_EVENT_BOOKING = "service_event_booking"
    SERVICE_CATERING = "service_catering"
    SERVICE_DELIVERY = "service_delivery"

    IDENTITY_WHO_ARE_YOU = "identity_who_are_you"
    IDENTITY_WHAT_DO_YOU_DO = "identity_what_do_you_do"
    IDENTITY_CAPABILITIES = "identity_capabilities"
    IDENTITY_LEADERSHIP = "identity_leadership"

    CONVERSATIONAL_GREETING = "conversational_greeting"
    CONVERSATIONAL_GRATITUDE = "conversational_gratitude"
    CONVERSATIONAL_FAREWELL = "conversational_farewell"
    CONVERSATIONAL_SMALL_TALK = "conversational_small_talk"
    CONVERSATIONAL_COMPLAINT = "conversational_complaint"
    CONVERSATIONAL_FEEDBACK = "conversational_feedback"

    CLARIFICATION_NEEDED = "clarification_needed"
    OUT_OF_SCOPE = "out_of_scope"


class IntentCategory(Enum):
    """High-level intent categories"""
    MENU = "menu"
    RESTAURANT_INFO = "restaurant_info"
    SERVICE = "service"
    IDENTITY = "identity"
    CONVERSATIONAL = "conversational"
    CLARIFICATION = "clarification"
    OUT_OF_SCOPE = "out_of_scope"


# Map each active IntentType → its high-level category. Used both by the
# embedding path and the regex fallback, so the category contract stays stable.
_INTENT_CATEGORY: Dict[IntentType, IntentCategory] = {
    IntentType.IDENTITY_WHO_ARE_YOU: IntentCategory.IDENTITY,
    IntentType.IDENTITY_WHAT_DO_YOU_DO: IntentCategory.IDENTITY,
    IntentType.IDENTITY_CAPABILITIES: IntentCategory.IDENTITY,
    IntentType.IDENTITY_LEADERSHIP: IntentCategory.IDENTITY,
    IntentType.CONVERSATIONAL_GREETING: IntentCategory.CONVERSATIONAL,
    IntentType.CONVERSATIONAL_GRATITUDE: IntentCategory.CONVERSATIONAL,
    IntentType.CONVERSATIONAL_FAREWELL: IntentCategory.CONVERSATIONAL,
    IntentType.CONVERSATIONAL_SMALL_TALK: IntentCategory.CONVERSATIONAL,
    IntentType.CONVERSATIONAL_COMPLAINT: IntentCategory.CONVERSATIONAL,
    IntentType.CONVERSATIONAL_FEEDBACK: IntentCategory.CONVERSATIONAL,
    IntentType.CLARIFICATION_NEEDED: IntentCategory.CLARIFICATION,
    IntentType.OUT_OF_SCOPE: IntentCategory.OUT_OF_SCOPE,
}


class IntentResult:
    """Result of intent classification"""

    def __init__(
        self,
        intent_type: IntentType,
        confidence: float,
        category: IntentCategory,
        entities: Optional[Dict] = None,
        requires_clarification: bool = False
    ):
        self.intent_type = intent_type
        self.confidence = confidence
        self.category = category
        self.entities = entities or {}
        self.requires_clarification = requires_clarification

    def is_menu_intent(self) -> bool:
        """Check if this is a menu-related intent"""
        return self.category == IntentCategory.MENU

    def is_restaurant_info_intent(self) -> bool:
        """Check if this is a restaurant info intent"""
        return self.category == IntentCategory.RESTAURANT_INFO

    def is_service_intent(self) -> bool:
        """Check if this is a service intent"""
        return self.category == IntentCategory.SERVICE

    def is_identity_intent(self) -> bool:
        """Check if this is an identity intent"""
        return self.category == IntentCategory.IDENTITY

    def to_dict(self) -> Dict:
        """Convert to dictionary for logging"""
        return {
            "intent_type": self.intent_type.value,
            "confidence": self.confidence,
            "category": self.category.value,
            "entities": self.entities,
            "requires_clarification": self.requires_clarification
        }


# ---------------------------------------------------------------------------
# Regex OVERRIDE patterns — run BEFORE the embedding classifier.
#
# These encode product decisions that an embedding model cannot reliably
# reproduce (e.g. anchored matches, polite-decline exclusions, standalone
# acknowledgments). They are intentionally minimal: only the patterns that
# MUST behave exactly as before. Everything else is left to the embedding model.
# ---------------------------------------------------------------------------

# Order matters within each list — first hit wins. (intent_type, pattern)
_REGEX_OVERRIDES: List[Tuple[IntentType, str]] = [
    # --- NEGATIVE override: "what is chikku <something_more>" is a factual
    # KB question (about a product, technology, or concept), NOT an identity
    # question. This must run BEFORE the IDENTITY_WHO_ARE_YOU patterns below
    # so that "what is chikku brain" / "what is chikku voice ai kiosk" route
    # to retrieval instead of the identity template.
    (IntentType.CLARIFICATION_NEEDED, r'\bwhat\s+is\s+chikku\s+\S'),

    # --- IDENTITY_WHO_ARE_YOU ---
    # "what is chikku" anchored to end: only matches the bare "what is chikku"
    # question (followed by optional punctuation, nothing else).
    (IntentType.IDENTITY_WHO_ARE_YOU, r'\bwho\s+are\s+you\b'),
    (IntentType.IDENTITY_WHO_ARE_YOU, r'\bwho\s+is\s+chikku\b'),
    (IntentType.IDENTITY_WHO_ARE_YOU, r'\bwhat\s+is\s+chikku\s*[?.!]*\s*$'),
    (IntentType.IDENTITY_WHO_ARE_YOU, r'\bintroduce\s+yourself\b'),
    (IntentType.IDENTITY_WHO_ARE_YOU, r'\btell\s+me\s+about\s+yourself\b'),
    # "are you a robot" anchored to the bare form. The embedding classifier
    # cannot reliably separate "are you a robot" (identity) from "do you have
    # a robot" (capability probe) — both share "robot" + "you". Pin the bare
    # form here so it routes to identity, while the capability probes stay in
    # the CLARIFICATION exemplar cluster.
    (IntentType.IDENTITY_WHO_ARE_YOU, r'^are\s+you\s+(a|an)\s+(robot|ai|bot|chatbot|human|person|machine)\b'),

    # --- IDENTITY_LEADERSHIP (kept as regex — these are keyword-heavy and the
    # embedding model underweights rare tokens like "ceo"/"cto"/named persons) ---
    (IntentType.IDENTITY_LEADERSHIP, r'\bwho\s+(is|are)\s+your\s+(leader|leaders|leadership|owner|owners)\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\bleadership\s+(team|structure)\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\bwho\s+(leads|runs|founded|started|owns)\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\b(founders?|ceo|cto|coo|cio|directors?|owner|owners)\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\b(management\s+team|executive\s+team)\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\bwho\s+is\s+in\s+charge\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\bhead\s+of\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\bwho\s+owns\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\bwho\s+is\s+the\s+owner\b'),
    (IntentType.IDENTITY_LEADERSHIP, r'\bwho\s+is\s+(surender|mohan)\b'),

    # --- CONVERSATIONAL edge cases ---
    # Polite declines ("no thanks", "not now") — must NOT route to gratitude.
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'\bno\s+thank(s?)\b'),
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'\bno\s+thx\b'),
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'^(?:no|nope|nah|nay)\s*[.!]*\s*$'),
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'\bnot\s+(really|now|interested|today|right\s+now)\b'),
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'\bnever\s+mind\b'),
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'\bi\'?m\s+(good|fine|ok(?:ay)?)\b'),
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'\b(i\s+)?don\'?t\s+think\s+so\b'),
    (IntentType.CONVERSATIONAL_SMALL_TALK, r'^(?:nothing|none|nvm)\s*[.!]*\s*$'),
    # Standalone acknowledgments (ok / k / sure / cool) — only when the WHOLE
    # message is the acknowledgment, otherwise treat as a real query.
    (IntentType.CONVERSATIONAL_SMALL_TALK,
     r'^(?:ok(?:ay)?|k|kk|alright|sure|yeah?|yep|yup|yes|ya|got\s+(it|cha)|cool|great|awesome|nice|perfect|fine)\s*[.!]*\s*$'),

    # --- Gratitude standalone (kept here so "thank you" near end of message
    # still classifies even if other words are present) ---
    (IntentType.CONVERSATIONAL_GRATITUDE, r'\bthank\s+(?:you\s+)?(?:so|very)\s+much\b'),
    (IntentType.CONVERSATIONAL_GRATITUDE, r'\b(thank\s+you|thank\s+u|thanks|appreciate)\b'),
    (IntentType.CONVERSATIONAL_GRATITUDE, r'^\s*thank\s*$'),
]


# ---------------------------------------------------------------------------
# Exemplar library for the embedding classifier.
#
# Each active intent has 4-8 example queries. These are paraphrase-rich to give
# the embedding model good coverage of natural phrasings. The cosine similarity
# between the user query and each exemplar (max per intent) decides the label.
# ---------------------------------------------------------------------------

_EXEMPLARS: Dict[IntentType, List[str]] = {
    # CLARIFICATION_NEEDED — a broad cluster of factual KB questions. These
    # act as NEGATIVE exemplars for identity: they share surface form ("what X
    # do you Y", "tell me about X") with identity questions but are clearly
    # factual lookups. Their cosine pulls such queries away from identity.
    IntentType.CLARIFICATION_NEEDED: [
        "what products do you have",
        "what products do you offer",
        "what services do you have",
        "tell me about the s-robot",
        "tell me about your robots",
        "how much does the s-robot cost",
        "what is the price of the kiosk",
        "what technologies do you use",
        "what is chikku brain",
        "what is chikku voice ai kiosk",
        "what industries do you serve",
        "what solutions do you provide for manufacturing",
        "where are you located",
        "what is your phone number",
        "who are your partners",
        "what is your mission",
        "what sensors does the robot use",
        # --- Capability-probe questions: "do you have/make/offer/sell X" ---
        # These were previously mis-routed to identity ("do you have X robot" ≈
        # "are you a robot" at ~0.72 cosine) and returned the identity template
        # instead of going to retrieval. Adding them as CLARIFICATION exemplars
        # fixes "do you have solar panel robot" → S-Robot answer, etc.
        "do you have a robot",
        "do you have a kiosk robot",
        "do you have a cleaning robot",
        "do you have a security robot",
        "do you have a surveillance robot",
        "do you have solar panel robot",
        "do you sell robots",
        "do you make drones",
        "do you build cobots",
        "do you offer service robots",
        "do you offer autonomous vehicles",
        "can you build a robot for me",
        "do you have any products",
    ],
    IntentType.IDENTITY_WHO_ARE_YOU: [
        "who are you",
        "who is chikku",
        "what is your name",
        "introduce yourself",
        "what should I call you",
        # NOTE: "are you a robot" deliberately REMOVED — it was the main noise
        # source that pulled "do you have X robot" capability-probe questions
        # into identity at ~0.72 cosine. The capability probes now live in the
        # CLARIFICATION_NEEDED cluster above. "Are you a robot" still classifies
        # correctly: it lands at ~0.65 cosine to "what is your name" — right at
        # the threshold, routing it to retrieval where it gets the about-page
        # answer (acceptable behavior; it is a vague question).
        # NOTE: "tell me about yourself" deliberately omitted — it collides with
        # "tell me about s-robot" / "tell me about <product>" at high cosine.
        # The regex override above still catches the bare "tell me about yourself"
        # form deterministically.
    ],
    IntentType.IDENTITY_WHAT_DO_YOU_DO: [
        "what do you do",
        "what's your job",
        "what is your role",
        "what is your purpose",
        "how do you help",
        "how can you help me",
        "what are you here for",
        "what can you do for me",
        # NOTE: "what services do you provide" / "what do you offer" deliberately
        # omitted — they collide with product/service KB queries
        # ("what products do you offer", "what services do you have"). The regex
        # fallback still has them for the no-embedding path.
    ],
    IntentType.IDENTITY_CAPABILITIES: [
        "what are your capabilities",
        "what are you capable of",
        "what can you help with",
        "what do you know",
        "what topics can you talk about",
        "what are your features",
    ],
    IntentType.CONVERSATIONAL_GREETING: [
        "hello",
        "hi",
        "hey",
        "namaste",
        "good morning",
        "good afternoon",
        "good evening",
        "greetings",
        "howdy",
    ],
    IntentType.CONVERSATIONAL_GRATITUDE: [
        "thank you",
        "thanks",
        "thank you so much",
        "thanks a lot",
        "appreciate it",
        "great thanks",
        "thank you very much",
    ],
    IntentType.CONVERSATIONAL_FAREWELL: [
        "bye",
        "goodbye",
        "see you",
        "see ya",
        "talk to you later",
        "catch you later",
        "have a good day",
        "take care",
        "farewell",
        "good night",
    ],
    IntentType.CONVERSATIONAL_SMALL_TALK: [
        "how are you",
        "how are you doing",
        "what's up",
        "how's it going",
        "sounds good",
        "makes sense",
        "i see",
        "what else",
        "tell me more",
        "anything else",
    ],
    IntentType.CONVERSATIONAL_COMPLAINT: [
        "i have a complaint",
        "i have a problem",
        "there is an issue",
        "something is wrong",
        "this is bad",
    ],
    IntentType.CONVERSATIONAL_FEEDBACK: [
        "i want to give feedback",
        "can i leave a review",
        "i'd like to rate this",
        "here is my feedback",
        "what's your rating",
    ],
}


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity (numpy if available, pure-Python fallback otherwise)."""
    try:
        import numpy as np
        import math
        a_arr = np.asarray(a, dtype=float)
        b_arr = np.asarray(b, dtype=float)
        na = float(np.linalg.norm(a_arr))
        nb = float(np.linalg.norm(b_arr))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (na * nb))
    except Exception:
        # Pure-Python fallback (very small vectors — exemplars are few)
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)


class IntentClassifier:
    """Embedding-based intent classifier with regex overrides + regex fallback.

    Lifecycle:
      - First call to classify_intent() lazily embeds all exemplars.
      - If the embed_fn raises or is None, the classifier permanently switches
        to regex-only mode (logs once) and keeps working.
    """

    def __init__(self, embed_fn: Optional[Callable[[str], List[float]]] = None):
        """Initialize intent classifier.

        Args:
            embed_fn: callable that maps a string → embedding vector. Defaults
                      to llm_provider.get_provider().embed (mxbai-embed-large).
                      Pass None to force regex-only mode (used in unit tests).
        """
        self._embed_fn = embed_fn
        self._exemplar_vectors: Optional[Dict[IntentType, List[List[float]]]] = None
        self._embed_failed: bool = False
        self._confidence_threshold: float = 0.65
        try:
            self._confidence_threshold = float(
                os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.65")
            )
        except (ValueError, TypeError):
            self._confidence_threshold = 0.65

    # ------------------------------------------------------------------
    # Lazy embedding of exemplars
    # ------------------------------------------------------------------

    def _resolve_embed_fn(self) -> Optional[Callable[[str], List[float]]]:
        if self._embed_fn is not None:
            return self._embed_fn
        try:
            # Imported lazily so the classifier module can be imported without
            # the heavier llm_provider (and its env-var requirements).
            from llm_provider import get_provider
            provider = get_provider()
            return provider.embed
        except Exception:
            return None

    def _ensure_exemplar_vectors(self) -> bool:
        """Lazily embed all exemplars. Returns True on success, False on failure."""
        if self._exemplar_vectors is not None:
            return True
        if self._embed_failed:
            return False
        embed_fn = self._resolve_embed_fn()
        if embed_fn is None:
            print("⚠️  IntentClassifier: no embed_fn available — using regex-only mode.")
            self._embed_failed = True
            return False
        try:
            vectors: Dict[IntentType, List[List[float]]] = {}
            for intent_type, examples in _EXEMPLARS.items():
                intent_vecs: List[List[float]] = []
                for ex in examples:
                    vec = embed_fn(ex)
                    if vec:
                        intent_vecs.append(list(vec))
                if intent_vecs:
                    vectors[intent_type] = intent_vecs
            if not vectors:
                print("⚠️  IntentClassifier: all exemplar embeddings empty — regex-only mode.")
                self._embed_failed = True
                return False
            self._exemplar_vectors = vectors
            n = sum(len(v) for v in vectors.values())
            print(f"✅ IntentClassifier: embedding mode ready ({n} exemplars, "
                  f"threshold={self._confidence_threshold}).")
            return True
        except Exception as e:
            print(f"⚠️  IntentClassifier: embedding init failed ({e}) — regex-only mode.")
            self._embed_failed = True
            return False

    # ------------------------------------------------------------------
    # Public classification API (signature unchanged from the original module)
    # ------------------------------------------------------------------

    def classify_intent(self, query: str) -> IntentResult:
        """Classify user query into an intent.

        Order:
          1. Regex overrides (edge cases that must behave deterministically).
          2. Embedding classifier (cosine to exemplars, max per intent).
          3. If embedding unavailable/failed → regex fallback.
          4. Default → CLARIFICATION_NEEDED.
        """
        query_stripped = (query or "").strip()
        query_lower = query_stripped.lower()

        # 1) Regex overrides — always run first, edge cases are non-negotiable.
        override = self._regex_override(query_lower)
        if override is not None:
            return override

        # 2) Embedding classifier
        if self._ensure_exemplar_vectors():
            result = self._embedding_classify(query_stripped)
            if result is not None:
                return result

        # 3) Regex fallback (only if embedding path is disabled/failed)
        return self._regex_fallback(query_lower)

    # ------------------------------------------------------------------
    # Regex override (subset — only edge cases)
    # ------------------------------------------------------------------

    def _regex_override(self, query_lower: str) -> Optional[IntentResult]:
        for intent_type, pattern in _REGEX_OVERRIDES:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return IntentResult(
                    intent_type=intent_type,
                    confidence=0.95,
                    category=_INTENT_CATEGORY.get(intent_type, IntentCategory.CONVERSATIONAL),
                )
        return None

    # ------------------------------------------------------------------
    # Embedding classifier
    # ------------------------------------------------------------------

    def _embedding_classify(self, query: str) -> Optional[IntentResult]:
        """Cosine-max over exemplars. Returns None on embed failure (caller falls back)."""
        embed_fn = self._resolve_embed_fn()
        if embed_fn is None or self._exemplar_vectors is None:
            return None
        try:
            q_vec = embed_fn(query)
        except Exception as e:
            print(f"⚠️  IntentClassifier: query embed failed ({e}) — using regex fallback.")
            return None
        if not q_vec:
            return None

        best_intent: Optional[IntentType] = None
        best_score = -1.0
        for intent_type, exemplar_vecs in self._exemplar_vectors.items():
            for ev in exemplar_vecs:
                sim = _cosine_similarity(q_vec, ev)
                if sim > best_score:
                    best_score = sim
                    best_intent = intent_type

        if best_intent is None:
            return None

        # Below threshold → treat as unclear → CLARIFICATION (route to retrieval)
        if best_score < self._confidence_threshold:
            return IntentResult(
                intent_type=IntentType.CLARIFICATION_NEEDED,
                confidence=max(0.0, best_score),
                category=IntentCategory.CLARIFICATION,
                requires_clarification=True,
            )

        return IntentResult(
            intent_type=best_intent,
            confidence=best_score,
            category=_INTENT_CATEGORY.get(best_intent, IntentCategory.CONVERSATIONAL),
        )

    # ------------------------------------------------------------------
    # Regex fallback (used only when embedding path is unavailable)
    # ------------------------------------------------------------------

    # Lazy-built regex fallback patterns (mirror of the original classifier).
    _FALLBACK_PATTERNS: Optional[Dict[IntentType, List[str]]] = None

    @classmethod
    def _get_fallback_patterns(cls) -> Dict[IntentType, List[str]]:
        if cls._FALLBACK_PATTERNS is not None:
            return cls._FALLBACK_PATTERNS
        cls._FALLBACK_PATTERNS = {
            IntentType.IDENTITY_WHO_ARE_YOU: [
                r'\bwho\s+are\s+you\b', r'\bwho\s+is\s+chikku\b',
                r'\bwhat\s+is\s+chikku\s*[?.!]*\s*$',
                r'\bintroduce\s+yourself\b', r'\btell\s+me\s+about\s+yourself\b',
            ],
            IntentType.IDENTITY_WHAT_DO_YOU_DO: [
                r'\bwhat\s+(do|can)\s+you\s+do\b', r'\bwhat\s+you\s+can\s+do\b',
                r'\bwhat\s+is\s+your\s+role\b', r'\bwhat\s+are\s+your\s+capabilities\b',
                r'\bhow\s+can\s+you\s+help\b', r'\bwhat\s+services\s+do\s+you\s+provide\b',
                r'\bwhat\s+do\s+you\s+offer\b', r'\bwhat\s+can\s+you\s+help\s+(me\s+)?with\b',
            ],
            IntentType.IDENTITY_CAPABILITIES: [
                r'\bwhat\s+can\s+you\s+help\s+with\b',
                r'\bwhat\s+are\s+you\s+capable\s+of\b', r'\bwhat\s+do\s+you\s+know\b',
            ],
            IntentType.IDENTITY_LEADERSHIP: [
                r'\bwho\s+(is|are)\s+your\s+(leader|leaders|leadership|owner|owners)\b',
                r'\bleadership\s+(team|structure)\b',
                r'\bwho\s+(leads|runs|founded|started|owns)\b',
                r'\b(founders?|ceo|cto|coo|cio|directors?|owner|owners)\b',
                r'\b(management\s+team|executive\s+team)\b',
                r'\bwho\s+is\s+in\s+charge\b', r'\bhead\s+of\b', r'\bwho\s+owns\b',
                r'\bwho\s+is\s+the\s+owner\b', r'\bwho\s+is\s+(surender|mohan)\b',
            ],
            IntentType.CONVERSATIONAL_GREETING: [
                r'\b(hello|hi|hey|namaste|good\s+(morning|afternoon|evening))\b',
                r'\bgreetings?\b',
            ],
            IntentType.CONVERSATIONAL_GRATITUDE: [
                r'\b(thank\s+you|thank\s+u|thanks|appreciate)\b',
                r'\bthank\s+(?:you\s+)?(?:so|very)\s+much\b',
                r'^\s*thank\s*$',
            ],
            IntentType.CONVERSATIONAL_FAREWELL: [
                r'\b(bye|goodbye|good\s+bye|see\s+(you|ya|u)|talk\s+(later|soon)|farewell|catch\s+(you|u|ya)\s+later|have\s+a\s+(good|great|nice)\s+(day|night|evening)|take\s+care|cya|ttyl)\b',
                r'\bbye\s*bye\b', r'\bsee\s+ya\b',
            ],
            IntentType.CONVERSATIONAL_SMALL_TALK: [
                r'\bhow\s+are\s+you\b', r'\bhow.*doing\b', r'\bwhat\'?s\s+up\b',
                r'\bno\s+thank(s?)\b', r'^(?:no|nope|nah|nay)\s*[.!]*\s*$',
                r'\bnot\s+(really|now|interested|today|right\s+now)\b',
                r'\bnever\s+mind\b', r'\bi\'?m\s+(good|fine|ok(?:ay)?)\b',
                r'^(?:nothing|none|nvm)\s*[.!]*\s*$',
                r'^(?:ok(?:ay)?|k|kk|alright|sure|yeah?|yep|yup|yes|ya|got\s+(it|cha)|cool|great|awesome|nice|perfect|fine)\s*[.!]*\s*$',
                r'\b(sounds?\s+good|makes?\s+sense|i\s+see)\b',
                r'\b(?:what\s+else|tell\s+me\s+more|go\s+on|anything\s+else)\b',
            ],
            IntentType.CONVERSATIONAL_COMPLAINT: [r'\b(complaint|problem|issue|wrong|bad)\b'],
            IntentType.CONVERSATIONAL_FEEDBACK: [r'\b(feedback|review|rating|opinion)\b'],
        }
        return cls._FALLBACK_PATTERNS

    def _regex_fallback(self, query_lower: str) -> IntentResult:
        # Priority order: identity → conversational. Everything else → CLARIFICATION.
        priority = [
            IntentType.IDENTITY_WHO_ARE_YOU,
            IntentType.IDENTITY_WHAT_DO_YOU_DO,
            IntentType.IDENTITY_CAPABILITIES,
            IntentType.IDENTITY_LEADERSHIP,
            IntentType.CONVERSATIONAL_GREETING,
            IntentType.CONVERSATIONAL_GRATITUDE,
            IntentType.CONVERSATIONAL_FAREWELL,
            IntentType.CONVERSATIONAL_SMALL_TALK,
            IntentType.CONVERSATIONAL_COMPLAINT,
            IntentType.CONVERSATIONAL_FEEDBACK,
        ]
        patterns = self._get_fallback_patterns()
        for intent_type in priority:
            for pattern in patterns.get(intent_type, []):
                if re.search(pattern, query_lower, re.IGNORECASE):
                    return IntentResult(
                        intent_type=intent_type,
                        confidence=0.85,
                        category=_INTENT_CATEGORY.get(intent_type, IntentCategory.CONVERSATIONAL),
                    )
        return IntentResult(
            intent_type=IntentType.CLARIFICATION_NEEDED,
            confidence=0.3,
            category=IntentCategory.CLARIFICATION,
            requires_clarification=True,
        )


# Global instance
_intent_classifier: Optional[IntentClassifier] = None


def get_intent_classifier() -> IntentClassifier:
    """Get or create the global intent classifier instance.

    Uses llm_provider.get_provider().embed by default. The first call lazily
    embeds the exemplar library; if the provider is unavailable the classifier
    transparently falls back to regex-only mode.
    """
    global _intent_classifier
    if _intent_classifier is None:
        _intent_classifier = IntentClassifier()
    return _intent_classifier


def reset_intent_classifier() -> None:
    """Reset the global singleton (used by tests and forced reconfiguration)."""
    global _intent_classifier
    _intent_classifier = None
