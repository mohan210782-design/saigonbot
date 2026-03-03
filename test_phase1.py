"""
Test script for Phase 1 improvements
Tests intent classification, templates, error handling, and database
"""
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from intent_classifier import get_intent_classifier, IntentType, IntentCategory
from response_templates import get_template, get_welcome_message
from errors import handle_error, RetrievalError, LLMError
from database import get_db
from chat import ConversationManager


def test_intent_classification():
    """Test intent classification"""
    print("\n" + "="*60)
    print("TEST 1: Intent Classification")
    print("="*60)
    
    classifier = get_intent_classifier()
    
    test_cases = [
        ("who are you", IntentType.IDENTITY_WHO_ARE_YOU),
        ("what do you do", IntentType.IDENTITY_WHAT_DO_YOU_DO),
        ("what can you help with", IntentType.IDENTITY_CAPABILITIES),
        ("where are you located", IntentType.RESTAURANT_LOCATION),
        ("what are your hours", IntentType.RESTAURANT_HOURS),
        ("book a table", IntentType.SERVICE_RESERVATION),
        ("biryani options", IntentType.MENU_SEARCH),
        ("hello", IntentType.CONVERSATIONAL_GREETING),
        ("thank you", IntentType.CONVERSATIONAL_GRATITUDE),
    ]
    
    passed = 0
    failed = 0
    
    for query, expected_intent in test_cases:
        result = classifier.classify_intent(query)
        if result.intent_type == expected_intent:
            print(f"✅ '{query}' → {result.intent_type.value} (confidence: {result.confidence:.2f})")
            passed += 1
        else:
            print(f"❌ '{query}' → Expected {expected_intent.value}, got {result.intent_type.value}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_response_templates():
    """Test response templates"""
    print("\n" + "="*60)
    print("TEST 2: Response Templates")
    print("="*60)
    
    test_intents = [
        IntentType.IDENTITY_WHO_ARE_YOU,
        IntentType.IDENTITY_WHAT_DO_YOU_DO,
        IntentType.RESTAURANT_LOCATION,
        IntentType.RESTAURANT_HOURS,
        IntentType.SERVICE_RESERVATION,
    ]
    
    passed = 0
    failed = 0
    
    for intent in test_intents:
        template = get_template(intent)
        if template:
            print(f"✅ Template exists for {intent.value}")
            print(f"   Preview: {template[:80]}...")
            passed += 1
        else:
            print(f"❌ No template for {intent.value}")
            failed += 1
    
    # Test welcome message
    welcome = get_welcome_message()
    if welcome and len(welcome) > 100:
        print(f"✅ Welcome message exists ({len(welcome)} chars)")
        passed += 1
    else:
        print(f"❌ Welcome message missing or too short")
        failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_error_handling():
    """Test error handling"""
    print("\n" + "="*60)
    print("TEST 3: Error Handling")
    print("="*60)
    
    passed = 0
    failed = 0
    
    # Test RetrievalError
    try:
        error = RetrievalError("Test retrieval error", query="test query")
        msg = handle_error(error)
        if "menu" in msg.lower() or "suggest" in msg.lower():
            print(f"✅ RetrievalError handled correctly")
            print(f"   Message: {msg[:80]}...")
            passed += 1
        else:
            print(f"❌ RetrievalError message not user-friendly")
            failed += 1
    except Exception as e:
        print(f"❌ RetrievalError test failed: {e}")
        failed += 1
    
    # Test LLMError
    try:
        error = LLMError("Test LLM error", model="test-model")
        msg = handle_error(error)
        if len(msg) > 20 and "😊" in msg:
            print(f"✅ LLMError handled correctly")
            print(f"   Message: {msg[:80]}...")
            passed += 1
        else:
            print(f"❌ LLMError message not user-friendly")
            failed += 1
    except Exception as e:
        print(f"❌ LLMError test failed: {e}")
        failed += 1
    
    # Test generic exception
    try:
        msg = handle_error(ValueError("Test error"))
        if len(msg) > 20:
            print(f"✅ Generic exception handled correctly")
            passed += 1
        else:
            print(f"❌ Generic exception message too short")
            failed += 1
    except Exception as e:
        print(f"❌ Generic exception test failed: {e}")
        failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_database():
    """Test database operations"""
    print("\n" + "="*60)
    print("TEST 4: Database Operations")
    print("="*60)
    
    passed = 0
    failed = 0
    
    try:
        db = get_db()
        
        # Test create conversation
        conv_id = db.create_conversation(session_id="test_session_123")
        if conv_id:
            print(f"✅ Conversation created: {conv_id[:20]}...")
            passed += 1
        else:
            print(f"❌ Failed to create conversation")
            failed += 1
        
        # Test add message
        msg_id = db.add_message(conv_id, "user", "test query", intent="test_intent")
        if msg_id:
            print(f"✅ Message added: {msg_id[:20]}...")
            passed += 1
        else:
            print(f"❌ Failed to add message")
            failed += 1
        
        # Test get messages
        messages = db.get_messages(conv_id, max_messages=10)
        if len(messages) == 1 and messages[0]['content'] == "test query":
            print(f"✅ Messages retrieved correctly")
            passed += 1
        else:
            print(f"❌ Failed to retrieve messages")
            failed += 1
        
        # Test get conversation by session
        conv = db.get_conversation_by_session("test_session_123")
        if conv and conv['id'] == conv_id:
            print(f"✅ Conversation retrieved by session ID")
            passed += 1
        else:
            print(f"❌ Failed to retrieve conversation by session")
            failed += 1
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()
        failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_conversation_manager():
    """Test conversation manager"""
    print("\n" + "="*60)
    print("TEST 5: Conversation Manager")
    print("="*60)
    
    passed = 0
    failed = 0
    
    try:
        manager = ConversationManager()
        
        # Test create/get conversation
        session_id = "test_session_456"
        conv_id1 = manager.get_or_create_conversation(session_id)
        conv_id2 = manager.get_or_create_conversation(session_id)
        
        if conv_id1 == conv_id2:
            print(f"✅ Same session returns same conversation ID")
            passed += 1
        else:
            print(f"❌ Same session returned different conversation IDs")
            failed += 1
        
        # Test add/get messages
        manager.add_message(conv_id1, "user", "test message 1")
        manager.add_message(conv_id1, "assistant", "test response 1")
        
        history = manager.get_history(conv_id1, max_messages=10)
        if len(history) == 2:
            print(f"✅ Conversation history retrieved correctly")
            print(f"   Messages: {len(history)}")
            passed += 1
        else:
            print(f"❌ Failed to retrieve conversation history")
            failed += 1
        
    except Exception as e:
        print(f"❌ Conversation manager test failed: {e}")
        import traceback
        traceback.print_exc()
        failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("PHASE 1 TEST SUITE")
    print("="*60)
    
    results = []
    
    # Run tests
    results.append(("Intent Classification", test_intent_classification()))
    results.append(("Response Templates", test_response_templates()))
    results.append(("Error Handling", test_error_handling()))
    results.append(("Database Operations", test_database()))
    results.append(("Conversation Manager", test_conversation_manager()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed_count = sum(1 for _, result in results if result)
    total_count = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed! Phase 1 is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total_count - passed_count} test(s) failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
