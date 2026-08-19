#!/usr/bin/env python3
"""
Tests for multilingual support (src/language.py + the pipeline boundaries).

Runs without Ollama, OpenAI or ChromaDB: the LLM is a stub that records what it
was asked, which is enough to check the translation boundaries and the answer
directive. Run with:

    python test_language.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import language as L  # noqa: E402
from response_validator import ResponseValidator  # noqa: E402

TAMIL_Q = "உங்கள் தயாரிப்புகள் என்ன?"          # "what are your products?"
TAMIL_A = "எங்கள் தயாரிப்புகள் S-Robot மற்றும் WatchGuard6S ஆகியவை."

failures = []


def check(label, actual, expected):
    if actual == expected:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}\n     expected: {expected!r}\n     actual:   {actual!r}")
        failures.append(label)


def check_true(label, value):
    check(label, bool(value), True)


class StubProvider:
    """Records every chat() call and replies with a canned translation."""

    def __init__(self, reply="what are your products?"):
        self.reply = reply
        self.calls = []

    def chat(self, messages, options):
        self.calls.append({"messages": messages, "options": options})
        return self.reply


# ── normalisation ────────────────────────────────────────────────────────────
print("\nLanguage tags")
check("ta-IN normalises to ta", L.normalize_language("ta-IN"), "ta")
check("uppercase TA normalises", L.normalize_language("TA"), "ta")
check("underscore form normalises", L.normalize_language("ta_IN"), "ta")
check("'auto' is not a language", L.normalize_language("auto"), None)
check("unsupported code rejected", L.normalize_language("fr"), None)
check("empty rejected", L.normalize_language(""), None)
check("None rejected", L.normalize_language(None), None)
check_true("en counts as English", L.is_english("en"))
check_true("unknown code treated as English", L.is_english("zz"))
check("ta is not English", L.is_english("ta"), False)


# ── script detection ─────────────────────────────────────────────────────────
print("\nScript detection")
check("Tamil detected", L.detect_language(TAMIL_Q), "ta")
check("English detected", L.detect_language("what are your products"), "en")
check("mixed script counts as Tamil", L.detect_language("Chikku பற்றி சொல்லுங்கள்"), "ta")
check("Telugu detected", L.detect_language("నమస్కారం"), "te")
check("Kannada detected", L.detect_language("ನಮಸ್ಕಾರ"), "kn")
check("Malayalam detected", L.detect_language("നമസ്കാരം"), "ml")
check("Devanagari reported as Hindi", L.detect_language("नमस्ते"), "hi")
check("empty string is English", L.detect_language(""), "en")
check("digits only is English", L.detect_language("123 456"), "en")

print("\nDeclared language wins over detection")
check("declared ta-IN honoured", L.resolve_language("hello there", "ta-IN"), "ta")
check("no declaration falls back to script", L.resolve_language(TAMIL_Q, None), "ta")
check("'auto' falls back to script", L.resolve_language(TAMIL_Q, "auto"), "ta")


# ── translation ──────────────────────────────────────────────────────────────
print("\nTranslation in")
provider = StubProvider()
out = L.translate_to_english(provider, TAMIL_Q, "ta")
check("Tamil query translated", out, "what are your products?")
check("one LLM call made", len(provider.calls), 1)
check("temperature pinned at 0", provider.calls[0]["options"]["temperature"], 0.0)

L.translate_to_english(provider, TAMIL_Q, "ta")
check("repeat query served from cache", len(provider.calls), 1)

provider_en = StubProvider()
same = L.translate_to_english(provider_en, "what are your products?", "en")
check("English query untouched", same, "what are your products?")
check("English query makes no LLM call", len(provider_en.calls), 0)


print("\nTranslation failure is survivable")


class ExplodingProvider:
    def chat(self, messages, options):
        raise RuntimeError("ollama is down")


kept = L.translate_to_english(ExplodingProvider(), "வணக்கம் நண்பரே", "ta")
check("failed translation returns input unchanged", kept, "வணக்கம் நண்பரே")


print("\nReply scaffolding is stripped")
check(
    "reasoning block removed",
    L._strip_translation_noise("<think>hmm, the user wants…</think>\nwhat are your products?"),
    "what are your products?",
)
check(
    "'Translation:' label removed",
    L._strip_translation_noise("Translation: what are your products?"),
    "what are your products?",
)
check(
    "wrapping quotes removed",
    L._strip_translation_noise('"what are your products?"'),
    "what are your products?",
)
check(
    "inner quotes kept",
    L._strip_translation_noise('he said "hello" to me'),
    'he said "hello" to me',
)


# ── the outgoing boundary ────────────────────────────────────────────────────
print("\nlocalize() is idempotent")
native = StubProvider(reply="SHOULD NOT BE CALLED")
check("already-Tamil reply passes through", L.localize(native, TAMIL_A, "ta"), TAMIL_A)
check("no LLM call for a native reply", len(native.calls), 0)

canned = StubProvider(reply=TAMIL_A)
check("English template gets translated", L.localize(canned, "Our products are…", "ta"), TAMIL_A)
check("one LLM call for a template", len(canned.calls), 1)

en_only = StubProvider(reply="SHOULD NOT BE CALLED")
check("English target is a no-op", L.localize(en_only, "Our products are…", "en"), "Our products are…")
check("English target makes no LLM call", len(en_only.calls), 0)


# ── the answer directive ─────────────────────────────────────────────────────
print("\nAnswer directive")
directive = L.answer_language_directive("ta-IN")
check_true("names the language", "Tamil" in directive)
check_true("names the native script", "தமிழ்" in directive)
check_true("bans transliteration", "transliterate" in directive)
check("English gets no directive", L.answer_language_directive("en"), "")
check("unknown code gets no directive", L.answer_language_directive("fr"), "")


# ── validator ────────────────────────────────────────────────────────────────
print("\nValidator skips English-only rules on non-English replies")
validator = ResponseValidator(enabled=True)

leak = "As an AI model, I can tell you about our robots and what they do today."
english_result = validator.validate(leak, language="en")
check("English persona leak still caught", english_result["issues"] != [], True)

tamil_result = validator.validate(TAMIL_A, language="ta")
check("Tamil reply reports no phrase issues", tamil_result["issues"], [])
check("Tamil reply returned unmodified", tamil_result["cleaned_response"], TAMIL_A)
check("Tamil reply is valid", tamil_result["valid"], True)

short = validator.validate("சரி.", language="ta")
check("truncation/length checks still run", "Response too short" in short["issues"], True)


# ── summary ──────────────────────────────────────────────────────────────────
print()
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ All multilingual checks passed")
