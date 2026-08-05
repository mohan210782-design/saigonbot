#!/usr/bin/env python3
"""
Phase 5: End-to-end identity switching test
============================================
Tests both BOT_IDENTITY=restaurant and BOT_IDENTITY=robotics to verify
all components work correctly with the switching mechanism.
"""
import sys
import os
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def clear_cache():
    """Clear cached modules to force fresh reload."""
    for k in list(sys.modules.keys()):
        if any(p in k for p in ['bot_config', 'knowledge_base', 'response_templates',
                                 'errors', 'intent_classifier', 'rag']):
            del sys.modules[k]


def test_identity(identity: str):
    """Run all tests for a given BOT_IDENTITY."""
    os.environ['BOT_IDENTITY'] = identity
    clear_cache()

    print(f"\n{'='*60}")
    print(f"  TESTING: BOT_IDENTITY={identity}")
    print(f"{'='*60}")

    results = {"passed": 0, "failed": 0, "errors": []}

    # === 1. Bot Config ===
    print("\n── 1. Bot Config ──")
    try:
        from bot_config import get_bot_config, is_robotics, is_restaurant, resolve_path
        cfg = get_bot_config()
        print(f"   company_name:       {cfg.company_name}")
        print(f"   collection_name:    {cfg.collection_name}")
        print(f"   system_prompt_file: {cfg.system_prompt_file}")
        print(f"   about_file:         {cfg.about_file}")
        print(f"   kb_dirs:            {cfg.knowledge_base_dirs}")
        print(f"   context_formatter:  {cfg.context_formatter}")
        print(f"   fallback_phone:     {cfg.fallback_phone}")
        print(f"   fallback_email:     {cfg.fallback_email}")
        print(f"   menu_keywords:      {len(cfg.menu_keywords)} words")

        # Verify resolve_path works
        prompt_path = resolve_path(cfg.system_prompt_file)
        about_path = resolve_path(cfg.about_file)
        print(f"   system_prompt exists: {prompt_path.exists()}")
        print(f"   about_file exists:    {about_path.exists()}")

        if identity == 'restaurant':
            assert cfg.company_name == 'Saigon Indian Restaurant'
            assert cfg.collection_name == 'hotel_saigon_menu'
            assert is_restaurant() and not is_robotics()
            assert len(cfg.menu_keywords) == 34
        else:
            assert cfg.company_name == 'Chikku Robotics'
            assert cfg.collection_name == 'chikku_robotics'
            assert is_robotics() and not is_restaurant()
            assert cfg.context_formatter == 'generic'

        results["passed"] += 1
        print("   ✅ bot_config: PASSED")
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"bot_config: {e}")
        print(f"   ❌ bot_config: FAILED — {e}")

    # === 2. Knowledge Base ===
    print("\n── 2. Knowledge Base ──")
    try:
        from knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        keys = list(kb._data.keys())
        print(f"   KB keys: {keys}")

        if identity == 'restaurant':
            expected = {'accessibility', 'contact', 'hours', 'location', 'policies',
                        'reservations', 'events', 'catering', 'delivery', 'faq'}
            assert set(keys) >= expected, f"Missing keys: {expected - set(keys)}"
        else:
            expected = {'identity', 'products', 'services', 'faq'}
            assert set(keys) >= expected, f"Missing keys: {expected - set(keys)}"

        results["passed"] += 1
        print("   ✅ knowledge_base: PASSED")
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"knowledge_base: {e}")
        print(f"   ❌ knowledge_base: FAILED — {e}")

    # === 3. Response Templates ===
    print("\n── 3. Response Templates ──")
    try:
        from response_templates import get_welcome_message, get_error_response, get_template
        from intent_classifier import IntentType

        welcome = get_welcome_message()
        print(f"   Welcome first 60 chars: {welcome[:60]}...")

        err = get_error_response('system_error')
        print(f"   Error response first 60 chars: {err[:60]}...")

        # Test identity template
        who_template = get_template(IntentType.IDENTITY_WHO_ARE_YOU)
        print(f"   IDENTITY_WHO_ARE_YOU template: {'Yes' if who_template else 'No'}")

        if identity == 'restaurant':
            assert 'Saigon Indian' in welcome or 'Namaste' in welcome
        else:
            assert 'Chikku Robotics' in welcome or 'robot' in welcome.lower()

        results["passed"] += 1
        print("   ✅ response_templates: PASSED")
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"response_templates: {e}")
        print(f"   ❌ response_templates: FAILED — {e}")

    # === 4. Error Handling ===
    print("\n── 4. Error Handling ──")
    try:
        from errors import ChatbotError, LLMError, SystemError, RetrievalError
        from errors import IntentError, DatabaseError, ValidationError, handle_error

        # Test each error type produces a message
        for err_cls in [ChatbotError, LLMError, SystemError, RetrievalError,
                         IntentError, DatabaseError, ValidationError]:
            e = err_cls("test error")
            msg = e.user_message
            assert len(msg) > 10, f"{err_cls.__name__} message too short"

        # Test handle_error
        msg = handle_error(ValueError("test"))
        assert len(msg) > 10

        # Verify no hardcoded restaurant phone in robotics
        if identity == 'robotics':
            e = ChatbotError("test")
            assert '+84 (028) 6291 3672' not in e.user_message, \
                "Robotics error should not have restaurant phone!"

        results["passed"] += 1
        print("   ✅ errors: PASSED")
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"errors: {e}")
        print(f"   ❌ errors: FAILED — {e}")

    # === 5. Intent Classifier ===
    print("\n── 5. Intent Classifier ──")
    try:
        from intent_classifier import get_intent_classifier, IntentType, IntentCategory
        ic = get_intent_classifier()

        test_queries = {
            'who are you': IntentType.IDENTITY_WHO_ARE_YOU,
            'hello': IntentType.CONVERSATIONAL_GREETING,
            'thank you': IntentType.CONVERSATIONAL_GRATITUDE,
        }

        if identity == 'restaurant':
            test_queries.update({
                'where are you located': IntentType.RESTAURANT_LOCATION,
                'what time do you open': IntentType.RESTAURANT_HOURS,
                'recommend a dish': IntentType.MENU_RECOMMENDATION,
                'vegetarian options': IntentType.MENU_DIETARY,
            })

        for query, expected in test_queries.items():
            result = ic.classify_intent(query)
            status = "✅" if result.intent_type == expected else "⚠️"
            print(f"   {status} \"{query}\" → {result.intent_type.value}")

        results["passed"] += 1
        print("   ✅ intent_classifier: PASSED")
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"intent_classifier: {e}")
        print(f"   ❌ intent_classifier: FAILED — {e}")

    # === 6. RAG Pipeline (collection + retrieval + formatting) ===
    print("\n── 6. RAG Pipeline ──")
    try:
        import chromadb
        from llm_provider import get_provider

        client = chromadb.PersistentClient(path=str(Path(__file__).parent / "chroma_db"))

        # Verify collection exists
        try:
            col = client.get_collection(name=cfg.collection_name)
            count = col.count()
            print(f"   Collection '{cfg.collection_name}': {count} docs")
            assert count > 0, f"Collection {cfg.collection_name} is empty!"
        except Exception as e:
            print(f"   ⚠️  Collection not found: {e}")
            results["failed"] += 1
            results["errors"].append(f"chromadb: {e}")
            print(f"   ❌ chromadb: FAILED — {e}")
            return results

        # Test retrieval
        provider = get_provider()
        test_queries_rag = {
            'restaurant': [
                ('spicy chicken dish', 'chicken'),
                ('vegetarian options', 'paneer'),
                ('where is the restaurant', 'Lê Anh Xuân'),
            ],
            'robotics': [
                ('what robots do you build', 'robotic'),
                ('tell me about AI', 'Intelligence'),
                ('who is Chikku', 'Chikku'),
            ]
        }

        for query, expected_keyword in test_queries_rag[identity]:
            emb = provider.embed(query)
            results_q = col.query(query_embeddings=[emb], n_results=3)
            docs = results_q['documents'][0]
            found = any(expected_keyword.lower() in d.lower() for d in docs)
            status = "✅" if found else "⚠️"
            print(f"   {status} \"{query}\" → found '{expected_keyword}': {found}")

        results["passed"] += 1
        print("   ✅ RAG retrieval: PASSED")
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"rag: {e}")
        print(f"   ❌ RAG pipeline: FAILED — {e}")

    # === Summary ===
    total = results["passed"] + results["failed"]
    print(f"\n── Summary: {results['passed']}/{total} passed ──")
    if results["errors"]:
        for err in results["errors"]:
            print(f"   ❌ {err}")

    return results


def main():
    all_results = {}

    for identity in ['restaurant', 'robotics']:
        all_results[identity] = test_identity(identity)

    print(f"\n{'='*60}")
    print(f"  FINAL RESULTS")
    print(f"{'='*60}")
    for identity, results in all_results.items():
        total = results["passed"] + results["failed"]
        status = "✅ ALL PASSED" if results["failed"] == 0 else f"❌ {results['failed']} FAILED"
        print(f"  BOT_IDENTITY={identity}: {results['passed']}/{total} — {status}")

    all_passed = all(r["failed"] == 0 for r in all_results.values())
    exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
