# Fine-Tuning Fixes Applied

## 🔴 Critical Issues Found

1. **LLM Completely Ignoring Query Intent**: Responses didn't match queries (e.g., "vegetarian options" → talked about "spiciest non-veg dish")
2. **LLM Copying Wrong Examples**: First query response included `"Query: \"What's your spiciest non-veg dish?\"\nResponse:"` - copying from conversation history
3. **Retrieved Items Correct But Ignored**: LLM hallucinated instead of using provided context
4. **Price Formatting Inconsistencies**: Some prices formatted correctly, others wrong

## ✅ Fixes Applied

### Fix 1: Added Intent-Based Item Filtering (`filter_by_intent`)
- Filters items by dietary preference (vegetarian vs non-vegetarian)
- Filters by protein type (chicken, mutton, fish, prawn, egg, seafood)
- Filters by taste preference (spicy)
- Filters by course type (starter)
- **Location**: `src/rag.py` lines ~695-760

### Fix 2: Removed Conversation History for Menu Queries
- **Root Cause**: Conversation history was causing contamination - LLM copied responses from previous queries
- **Fix**: Set `menu_conversation_history = None` before calling `generate_response()` for menu queries
- **Location**: `src/rag.py` line ~1255
- **Also**: Removed conversation history addition in `generate_response()` method (line ~616)

### Fix 3: Strengthened Prompt with Query-Specific Instructions
- Added query-specific warnings based on query type:
  - "⚠️ CRITICAL: The user asked for VEGETARIAN options. ONLY mention vegetarian items..."
  - "⚠️ CRITICAL: The user asked for NON-VEGETARIAN options. ONLY mention non-vegetarian items..."
  - "⚠️ CRITICAL: The user asked for SPICY options. Prioritize spicy items..."
  - "⚠️ CRITICAL: The user asked for STARTERS. Focus on starter/appetizer items..."
- **Location**: `src/rag.py` lines ~625-642

### Fix 4: Enhanced User Prompt
- Added explicit instruction: "Answer the EXACT question asked"
- Added query-specific emoji guidance (🌿 for vegetarian, 🍗 for non-veg, etc.)
- Made instructions more explicit: "USE ONLY THESE" instead of just "Menu Items Available"
- **Location**: `src/rag.py` lines ~644-665

### Fix 5: Updated Filtering Pipeline
- Added `filter_by_intent()` call before `filter_by_relevance()`
- Both filters now run sequentially for better accuracy
- **Location**: `src/rag.py` lines ~1235-1245

## 📊 Expected Improvements

1. **Vegetarian Queries**: Will only show vegetarian items, no non-veg contamination
2. **Non-Veg Queries**: Will only show non-vegetarian items, no veg contamination
3. **Protein-Specific Queries**: Will filter by protein type (chicken, mutton, fish, etc.)
4. **No More Hallucination**: LLM won't copy from conversation history
5. **Better Price Formatting**: Consistent "X,XXX VND" format

## 🧪 Testing Recommendations

Test these queries from `fine_tuning_quries1.json`:
1. "Show me vegetarian options." → Should list ONLY vegetarian items
2. "Any spicy veg starters?" → Should list ONLY spicy vegetarian starters
3. "What non-veg starters do you have?" → Should list ONLY non-vegetarian starters
4. "Do you have egg dishes?" → Should list ONLY egg dishes
5. "What's good in mutton?" → Should list ONLY mutton dishes
6. "Any seafood options?" → Should list ONLY seafood dishes
7. "Is this dish vegetarian?" → Should ask for clarification (which dish?)

## 📝 Next Steps

1. Test the queries above
2. If issues remain, add response validation (check if response mentions items from retrieved list)
3. Consider deterministic formatters for very common query patterns
