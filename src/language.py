"""
Multilingual input/output support.

Every retrieval component in this project is English: the ChromaDB index was
embedded with an English-trained model, the intent taxonomies are English regex
patterns, and the chunk metadata (doc_type, audience, section names) is English.
Re-embedding the corpus per language would mean a separate index and a separate
intent taxonomy for every language added.

So the pipeline keeps one English index and moves the language boundary to the
edges instead:

    Tamil question  ->  translate to English  ->  retrieve / classify (English)
                    ->  LLM told to answer in Tamil  ->  Tamil answer

The caller (kiosk) supplies the language it detected during speech recognition.
When it does not, `detect_language` guesses from the script, which is exact for
the Indic languages this serves — they have their own Unicode blocks, so there
is nothing probabilistic about it.

Canned strings (welcome message, "I couldn't find that") never reach the LLM, so
they are translated here and cached; the same handful of strings is translated
once per process, not once per turn.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# Language spoken when nothing else is known. The kiosk chrome is English, so
# this stays "en" unless a site is deployed monolingual in something else.
DEFAULT_LANGUAGE = (os.getenv("DEFAULT_LANGUAGE", "en") or "en").strip().lower()

# Turn off to force English-only behaviour (no translation, no directives) — a
# useful kill switch if a site sees translation latency it does not need.
MULTILINGUAL_ENABLED = os.getenv("MULTILINGUAL_ENABLED", "true").lower() == "true"

# Languages the pipeline will translate and answer in. Codes are ISO 639-1.
# `native` is what the answer directive shows the LLM — naming the language in
# its own script measurably reduces the "answers in English anyway" failure.
LANGUAGES: Dict[str, Dict[str, str]] = {
    "en": {"name": "English",    "native": "English"},
    "hi": {"name": "Hindi",      "native": "हिन्दी"},
    "ta": {"name": "Tamil",      "native": "தமிழ்"},
    "bn": {"name": "Bengali",    "native": "বাংলা"},
    "gu": {"name": "Gujarati",   "native": "ગુજરાતી"},
    "ml": {"name": "Malayalam",  "native": "മലയാളം"},
    "kn": {"name": "Kannada",    "native": "ಕನ್ನಡ"},
    "te": {"name": "Telugu",     "native": "తెలుగు"},
    "pa": {"name": "Punjabi",    "native": "ਪੰਜਾਬੀ"},
    "vi": {"name": "Vietnamese", "native": "Tiếng Việt"},
}

# Unicode blocks that identify a language unambiguously. Ordered because the
# first match wins; these blocks do not overlap, so order is not significant
# beyond determinism.
# Each Indic language below owns its Unicode block outright, so a hit is proof
# rather than a guess. Two blocks serve more than one language — Devanagari is
# also Marathi/Nepali and Bengali is also Assamese — and are reported as the
# majority language, which is the best a script test can do.
_SCRIPT_RANGES: Tuple[Tuple[str, str], ...] = (
    ("ta", r"[஀-௿]"),   # Tamil
    ("te", r"[ఀ-౿]"),   # Telugu
    ("kn", r"[ಀ-೿]"),   # Kannada
    ("ml", r"[ഀ-ൿ]"),   # Malayalam
    ("bn", r"[ঀ-৿]"),   # Bengali (also Assamese — reported as Bengali)
    ("gu", r"[઀-૿]"),   # Gujarati
    ("pa", r"[਀-੿]"),   # Gurmukhi (Punjabi)
    ("hi", r"[ऀ-ॿ]"),   # Devanagari (Hindi/Marathi — reported as Hindi)
)

_SCRIPT_RES: Tuple[Tuple[str, "re.Pattern"], ...] = tuple(
    (code, re.compile(pattern)) for code, pattern in _SCRIPT_RANGES
)

# A short mixed-script query ("Chikku பற்றி சொல்லுங்கள்") is still a Tamil
# query. Anything above this share of non-Latin characters counts as that
# script rather than as English with a loanword.
_SCRIPT_THRESHOLD = 0.15

# Names that must survive translation with their exact spelling. A question
# asked in Tamil script has no Latin spelling to preserve, so the translator
# transliterates by ear — "சிக்கு ரோபோட்டிக்ஸ்" came back as "Siku Robotics",
# which then has to match "Chikku Robotics" in the index. For a company kiosk the
# brand name often IS the query, so the mapping cannot be left to chance.
#
# Format: pipe-separated names, e.g. "Chikku Robotics|S-Robot|WatchGuard6S".
TRANSLATION_GLOSSARY = tuple(
    term.strip()
    for term in (os.getenv("TRANSLATION_GLOSSARY", "") or "").split("|")
    if term.strip()
)

_TRANSLATION_CACHE_MAX = max(20, int(os.getenv("TRANSLATION_CACHE_MAX_SIZE", "300")))
# key: (direction, language, text) -> translated text
_translation_cache: "OrderedDict[Tuple[str, str, str], str]" = OrderedDict()


# ---------------------------------------------------------------- normalising


def normalize_language(code: Optional[str]) -> Optional[str]:
    """Reduce a tag like 'ta-IN' or 'TA' to a supported code, else None.

    Whisper reports bare ISO 639-1 codes, but browsers and OS locales send
    region-tagged ones, so both have to resolve to the same entry.
    """
    if not code:
        return None
    base = str(code).strip().lower().replace("_", "-").split("-")[0]
    if not base or base == "auto":
        return None
    return base if base in LANGUAGES else None


def is_english(code: Optional[str]) -> bool:
    """True when no translation is needed. Unknown codes are treated as English."""
    return normalize_language(code) in (None, "en")


def language_name(code: Optional[str]) -> str:
    entry = LANGUAGES.get(normalize_language(code) or "en", LANGUAGES["en"])
    return entry["name"]


def native_name(code: Optional[str]) -> str:
    entry = LANGUAGES.get(normalize_language(code) or "en", LANGUAGES["en"])
    return entry["native"]


def detect_language(text: str) -> str:
    """Identify the language of `text` from its script.

    Only used as a fallback: the kiosk already knows what Whisper detected, and
    passes it. Typed queries have no such signal, which is what this covers.
    """
    if not text:
        return "en"

    stripped = [c for c in text if not c.isspace() and not c.isdigit()]
    if not stripped:
        return "en"

    for code, pattern in _SCRIPT_RES:
        hits = sum(1 for c in stripped if pattern.match(c))
        if hits / len(stripped) >= _SCRIPT_THRESHOLD:
            return code

    return "en"


def resolve_language(text: str, declared: Optional[str] = None) -> str:
    """The language of this turn: what the caller declared, else the script."""
    if not MULTILINGUAL_ENABLED:
        return "en"
    known = normalize_language(declared)
    if known:
        return known
    return detect_language(text)


# ---------------------------------------------------------------- translation


def _cache_get(direction: str, lang: str, text: str) -> Optional[str]:
    key = (direction, lang, text)
    if key in _translation_cache:
        value = _translation_cache.pop(key)
        _translation_cache[key] = value       # refresh LRU position
        return value
    return None


def _cache_put(direction: str, lang: str, text: str, value: str) -> None:
    _translation_cache[(direction, lang, text)] = value
    while len(_translation_cache) > _TRANSLATION_CACHE_MAX:
        _translation_cache.popitem(last=False)


def _translate(provider, text: str, system_prompt: str, direction: str, lang: str) -> str:
    """One translation round-trip. Returns `text` unchanged on any failure.

    Failing open matters: a translation outage should degrade retrieval quality,
    not take the kiosk down. The untranslated query still returns *something*.
    """
    cached = _cache_get(direction, lang, text)
    if cached is not None:
        return cached

    try:
        result = provider.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            {
                # Translation must not paraphrase or continue the text, so
                # temperature is pinned at 0. The budget allows for Indic
                # scripts, which tokenize to roughly 3x English.
                "max_tokens": 400,
                "temperature": 0.0,
                "top_p": 1.0,
                "num_ctx": 2048,
            },
        )
    except Exception as e:                       # noqa: BLE001 - fail open
        print(f"⚠️  Translation failed ({direction}, {lang}): {e}")
        return text

    cleaned = _strip_translation_noise(result)
    if not cleaned:
        return text

    _cache_put(direction, lang, text, cleaned)
    return cleaned


def _strip_translation_noise(result: Optional[str]) -> str:
    """Remove the scaffolding small models wrap translations in.

    Seen in practice: reasoning blocks from deepseek-r1, a leading
    'Translation:' label, and the whole thing quoted.
    """
    if not result:
        return ""

    text = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL | re.IGNORECASE)
    text = text.strip()
    text = re.sub(r"^(translation|translated text|english)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip()

    # Only unwrap when the quotes enclose the whole string — a translation may
    # legitimately contain a quoted phrase.
    if len(text) >= 2 and text[0] in "\"'“‘" and text[-1] in "\"'”’":
        text = text[1:-1].strip()

    return text


def translate_to_english(provider, text: str, source_language: str) -> str:
    """Translate a user question into English for retrieval and intent matching."""
    if not text or not text.strip() or is_english(source_language):
        return text

    name = language_name(source_language)
    glossary = ""
    if TRANSLATION_GLOSSARY:
        glossary = (
            "- These names may appear mangled by the recogniser. When a word plausibly "
            "sounds like one of them, treat it as that name and spell it EXACTLY "
            "like this: " + ", ".join(TRANSLATION_GLOSSARY) + "\n"
        )
    # The input is speech-recognition output, not typed text, and saying so is
    # worth real accuracy. Questions arrive with words garbled by transliteration
    # — a speaker mixing English into Tamil says "service", which comes back as
    # "சாவல்" — and a translator told to expect that recovers the intent far more
    # often than one treating the text as authoritative.
    system_prompt = (
        f"You are a translation engine. The {name} text comes from a speech "
        f"recogniser at a public kiosk, so it may contain mis-transcribed words.\n"
        "Translate it into English.\n"
        "Rules:\n"
        "- Output ONLY the English translation. No preamble, no notes, no quotes.\n"
        "- Preserve proper nouns, product names, and numbers.\n"
        f"{glossary}"
        "- Speakers often mix English words into their own language, and those come "
        "back transliterated or garbled. If a word is not a real word in "
        f"{name} but sounds like an English one, translate it as that English word.\n"
        "- Recover the most likely intended question. Do not invent a topic that "
        "nothing in the text points to; if it is truly unintelligible, translate it "
        "literally.\n"
        "- Keep it a question if the input is a question.\n"
        "- If the text is already English, repeat it unchanged."
    )
    translated = _translate(provider, text.strip(), system_prompt, "to_en", source_language)
    if translated != text:
        print(f"🌐 {name} → English: {translated!r}")
    return translated


def translate_from_english(provider, text: str, target_language: str) -> str:
    """Translate a canned English string into the user's language.

    For LLM-generated answers use `answer_language_directive` instead — having
    the model answer natively is both faster and better than a second pass over
    its English output.
    """
    if not text or not text.strip() or is_english(target_language):
        return text

    name = language_name(target_language)
    system_prompt = (
        f"You are a translation engine. Translate the user's English text into {name}.\n"
        "Rules:\n"
        f"- Output ONLY the {name} translation. No preamble, no notes, no quotes.\n"
        "- Keep Markdown formatting (**bold**, bullet lists) and emoji exactly where they are.\n"
        "- Leave brand and product names in their original spelling."
    )
    return _translate(provider, text.strip(), system_prompt, "from_en", target_language)


def localize(provider, text: str, target_language: str) -> str:
    """Make sure an outgoing reply is in the user's language.

    Applied at the single point where a reply leaves the pipeline, which is why
    it has to be idempotent: most replies are LLM output that already came back
    in the right language (see `answer_language_directive`), while the rest are
    the hardcoded templates and error strings scattered through the restaurant
    path. Script detection separates the two exactly, so a native reply passes
    through untouched and only the English ones cost a translation call.
    """
    if not text or not text.strip() or is_english(target_language):
        return text

    target = normalize_language(target_language)
    if detect_language(text) == target:
        return text                       # already answered natively

    return translate_from_english(provider, text, target)


# -------------------------------------------------------------- LLM directives


def answer_language_directive(code: Optional[str]) -> str:
    """Prompt block that makes the model answer in the user's language.

    Empty for English so English turns keep the exact prompt they had before.
    Appended last in the user message because instructions closest to the end
    of the prompt are the ones models follow most reliably.
    """
    lang = normalize_language(code)
    if not lang or lang == "en":
        return ""

    name = language_name(lang)
    native = native_name(lang)
    return (
        f"\n\nLANGUAGE REQUIREMENT (overrides the formatting notes above):\n"
        f"- The customer asked in {name} ({native}). Write your ENTIRE reply in {name}.\n"
        f"- Do not reply in English, and do not repeat the answer in English.\n"
        f"- Do not transliterate {name} into the Latin alphabet — use {native} script.\n"
        f"- Keep brand, product, and person names in their original spelling "
        f"(for example: Chikku Robotics, NVIDIA Jetson).\n"
        f"- Numbers, prices, and units stay in digits."
    )
