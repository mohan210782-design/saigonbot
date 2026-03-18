# Fine-Tuning Analysis - Critical Issues Found

## 🔴 Critical Problems Identified

### 1. **LLM Completely Ignoring Query Intent**
The LLM is generating responses that don't match the query at all:

- ❌ **Query**: "Show me vegetarian options"  
  **Current**: Talks about "spiciest non-veg dish"  
  **Expected**: Lists vegetarian dishes

- ❌ **Query**: "Any spicy veg starters?"  
  **Current**: Talks about "spiciest non-vegetarian dish"  
  **Expected**: Lists spicy vegetarian starters

- ❌ **Query**: "What non-veg starters do you have?"  
  **Current**: Talks about "Vegetable Pulao" (vegetarian!)  
  **Expected**: Lists non-vegetarian starters

- ❌ **Query**: "Do you have egg dishes?"  
  **Current**: Talks about "spiciest non-vegetarian dish"  
  **Expected**: Lists egg dishes

- ❌ **Query**: "Any seafood options?"  
  **Current**: Talks about "spiciest non-veg dish"  
  **Expected**: Lists seafood dishes

- ❌ **Query**: "Is this dish vegetarian?"  
  **Current**: Talks about "spiciest non-veg dish"  
  **Expected**: Asks for clarification (which dish?)

### 2. **LLM Copying Wrong Examples**
First query response includes: `"Query: \"What's your spiciest non-veg dish?\"\nResponse:"`  
This suggests the LLM is copying from conversation history or examples instead of using retrieved items.

### 3. **Retrieved Items Are Correct, But LLM Ignores Them**
- Retrieved items match the query correctly
- But LLM generates responses about completely different dishes
- LLM is hallucinating instead of using provided context

### 4. **Price Formatting Inconsistencies**
- Some prices formatted correctly: "164,000 VND"
- Others wrong: "164000 VND", "154000VND" (no comma, no space)

## 🔧 Root Causes

1. **Prompt Not Strong Enough**: LLM is not forced to use retrieved items
2. **No Post-Processing Validation**: No check if response matches query intent
3. **Retrieved Items Not Filtered**: Non-veg items shown for veg queries, etc.
4. **Conversation History Contamination**: Previous queries bleeding into current response
5. **No Deterministic Formatters**: Should use templates for specific query types

## ✅ Fixes I Will Implement

### Fix 1: Filter Retrieved Items by Query Intent
- For "vegetarian" queries → filter out non-veg items
- For "non-veg" queries → filter out vegetarian items  
- For "spicy" queries → prioritize spicy items
- For "starter" queries → prioritize starter items

### Fix 2: Strengthen Prompt with Query-Specific Instructions
- Add explicit instructions based on query type
- Force LLM to mention ONLY items from retrieved list
- Add query-specific examples

### Fix 3: Add Post-Processing Validation
- Check if response mentions items from retrieved list
- Check if response matches query intent (veg vs non-veg)
- Regenerate if validation fails

### Fix 4: Clear Conversation History for Menu Queries
- Don't use conversation history for menu queries (causes contamination)
- Only use history for conversational queries

### Fix 5: Deterministic Formatters for Common Patterns
- Create formatters for: vegetarian queries, non-veg queries, spicy queries, etc.
- Use templates when possible instead of LLM

### Fix 6: Improve Context Formatting
- Make it clearer which items match the query
- Add query-specific headers in context

## 📋 Implementation Plan

1. ✅ Add `filter_items_by_intent()` method
2. ✅ Update `generate_response()` to filter items before formatting context
3. ✅ Strengthen user prompt with query-specific instructions
4. ✅ Add response validation (check if items mentioned match retrieved items)
5. ✅ Clear conversation history for menu queries
6. ✅ Add deterministic formatters for common query patterns
