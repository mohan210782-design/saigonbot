# Conversation History Solution - Smart Approach

## 🎯 Problem Statement

**Original Issue**: Removing conversation history completely broke contextual queries like:
- "tell me more about that dish"
- "what's the price of the biryani you mentioned?"
- "is that vegetarian?"

**But**: Including full conversation history caused LLM to copy wrong responses from previous queries.

## ✅ Smart Solution Implemented

### 1. **Query Enhancement** (`_enhance_query_with_history`)
- **Purpose**: Enhance retrieval query using conversation history
- **How it works**:
  - Detects contextual keywords: "that", "this", "it", "the", "previous", "mentioned"
  - Extracts dish keywords from previous user queries (biryani, curry, chicken, etc.)
  - Enhances query: `"tell me more about that"` → `"tell me more about that biryani"`
- **Location**: `src/rag.py` lines ~301-340
- **Benefit**: Better retrieval for contextual queries without passing full history to LLM

### 2. **History Sanitization** (`_sanitize_conversation_history`)
- **Purpose**: Include only user queries, exclude assistant responses
- **How it works**:
  - Filters conversation history to include only `role == 'user'` messages
  - Skips assistant responses that could cause contamination
  - Limits to last 6 messages (3 turns) to keep context focused
- **Location**: `src/rag.py` lines ~342-360
- **Benefit**: Contextual understanding without copying wrong responses

### 3. **Enhanced Prompt Instructions**
- **Added explicit instruction**: "Do NOT copy responses from previous conversations"
- **Added contextual guidance**: "If the customer refers to a previous dish, use the menu items above to answer"
- **Location**: `src/rag.py` lines ~665-670
- **Benefit**: LLM knows to use retrieved items, not history

## 🔄 How It Works Now

### Example Flow:

**Turn 1:**
- User: "Show me biryani options"
- System: Retrieves biryani items, responds with list
- History: `[{"role": "user", "content": "Show me biryani options"}]`

**Turn 2:**
- User: "Tell me more about that dish"
- System:
  1. **Query Enhancement**: Detects "that" → extracts "biryani" from history → enhances query to "Tell me more about that dish biryani"
  2. **Retrieval**: Retrieves biryani items (better match due to enhanced query)
  3. **History Sanitization**: Only includes `[{"role": "user", "content": "Show me biryani options"}]` (no assistant response)
  4. **LLM Prompt**: Includes sanitized history + retrieved items + explicit instruction to use retrieved items
  5. **Response**: Uses retrieved biryani items, not copying from previous response

## 📊 Benefits

1. ✅ **Contextual Understanding**: System understands references to previous dishes
2. ✅ **Better Retrieval**: Enhanced queries improve retrieval accuracy
3. ✅ **No Hallucination**: Sanitized history prevents copying wrong responses
4. ✅ **Focused Context**: Limited to last 3 turns keeps context relevant
5. ✅ **Explicit Instructions**: LLM knows to use retrieved items, not history

## 🧪 Testing Scenarios

### Scenario 1: Contextual Reference
```
User: "Show me vegetarian options"
Bot: [Lists vegetarian dishes]
User: "Tell me more about that paneer dish"
Expected: Should retrieve and describe paneer dishes, not copy previous response
```

### Scenario 2: Price Query
```
User: "What biryanis do you have?"
Bot: [Lists biryanis]
User: "What's the price of that mutton biryani?"
Expected: Should retrieve mutton biryani and show price, not copy previous response
```

### Scenario 3: Dietary Check
```
User: "Show me spicy dishes"
Bot: [Lists spicy dishes]
User: "Is that vegetarian?"
Expected: Should ask for clarification or check if retrieved items are vegetarian
```

## 🔧 Configuration

- **History Limit**: Last 6 messages (3 turns) - configurable in `_sanitize_conversation_history`
- **Contextual Keywords**: Defined in `_enhance_query_with_history` - can be extended
- **Dish Keywords**: Extracted from history - can be expanded for better matching

## 📝 Next Steps

1. Test contextual queries to verify enhancement works
2. Monitor for any hallucination issues
3. Fine-tune dish keyword extraction if needed
4. Consider adding entity extraction from assistant responses (dish names only, not full text)
