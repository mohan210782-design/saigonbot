# Quick API Test Guide

## Step 1: Start the API Server

In one terminal, run:
```bash
cd /Users/mohan/Documents/mtech/hotel/saigonbot
python3 run_api.py
```

Wait for: `Application startup complete`

## Step 2: Test the API

### Option A: Use the test script (recommended)
In another terminal:
```bash
cd /Users/mohan/Documents/mtech/hotel/saigonbot
python3 test_api.py
```

### Option B: Manual testing with curl

#### Test 1: Identity Query
```bash
curl -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"query": "who are you"}'
```

Expected: Welcome message (template), no menu items, intent: identity_who_are_you

#### Test 2: Restaurant Info Query
```bash
curl -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"query": "where are you located"}'
```

Expected: Location info (template), no menu items, intent: restaurant_location

#### Test 3: Menu Query
```bash
curl -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"query": "biryani options"}'
```

Expected: Menu items returned, intent: menu_search

#### Test 4: Service Query
```bash
curl -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"query": "book a table"}'
```

Expected: Reservation info (template), intent: service_reservation

#### Test 5: Conversation Persistence
```bash
# First message
curl -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"query": "hello", "conversation_id": "test-123"}'

# Second message (same conversation_id)
curl -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"query": "what do you do", "conversation_id": "test-123"}'
```

Expected: Both messages stored in same conversation

## What to Check

✅ **Intent Classification**: Check `intent.intent_type` in response
✅ **Templates**: Identity/restaurant/service queries should use templates (no AI disclaimers)
✅ **Menu Queries**: Should return menu items with `retrieved_count > 0`
✅ **Error Handling**: Invalid queries should return user-friendly errors
✅ **Persistence**: Same `conversation_id` should maintain context

## Common Issues

1. **"API not running"**: Make sure `run_api.py` is running
2. **Import errors**: Check that all dependencies are installed (`pip install -r requirements.txt`)
3. **Database errors**: Check that `conversations.db` is created (should happen automatically)
4. **No menu items**: Make sure menu items are ingested (`python3 src/ingestion.py`)
