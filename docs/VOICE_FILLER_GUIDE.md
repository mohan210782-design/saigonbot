# Voice Filler Signal — Hướng dẫn tích hợp Frontend

Backend đã thêm endpoint **`POST /chat/voice`** (SSE streaming). Khi **FAQ cache miss** (step 3 trong pipeline RAG), backend bắn ngay event `filler` để frontend speak câu đệm trong lúc chờ response thật (4-6 giây).

Filler text do **frontend tự giữ** — backend chỉ gửi signal `{"type":"filler"}` (không kèm text).

---

## 1. Tại sao dùng `/chat/voice` thay vì `/chat/text`?

| Endpoint | Khi nào | Hành vi |
|----------|---------|---------|
| `/chat/text` (cũ) | Không cần filler | Trả 1 JSON blob ở cuối (4-6s chờ) → user im lặng |
| **`/chat/voice`** (mới) | **Voice AI, cần filler** | Stream events: `filler` → `response` → `done`. User nghe câu đệm ngay (<100ms), rồi nghe response |

Endpoint cũ **vẫn hoạt động** — bạn có thể chạy song song, hoặc chuyển hẳn sang `/chat/voice`.

---

## 2. Event schema (SSE)

Mỗi event là 1 dòng `data: {json}\n\n`. Parse JSON để lấy object.

| `type` | Khi nào | Payload | Frontend làm gì |
|--------|---------|---------|-----------------|
| **`filler`** | FAQ cache MISS (sắp chờ 4-6s) | `{}` (chỉ có type) | **Speak câu đệm ngay** (chọn random từ list filler) |
| **`response`** | Response sẵn sàng | `{query, response, items, retrieved_count, intent, source}` | **Stop filler** → **speak response** |
| **`done`** | Stream kết thúc | `{conversation_id, intent}` | Đóng kết nối, lưu `conversation_id` cho turn sau |
| **`error`** | Pipeline lỗi | `{message}` | Hiển thị / log lỗi, đóng kết nối |

**`source`** trong event `response` (debug/telemetry): `deterministic` \| `faq_cache` \| `llm` \| `fallback`.
- `deterministic` / `faq_cache` = response nhanh (KHÔNG có filler event trước đó).
- `llm` / `fallback` = response chậm (CÓ filler event trước đó).

---

## 3. Cách gọi endpoint (fetch + ReadableStream)

> ⚠️ **Không dùng `EventSource`.** `EventSource` chỉ hỗ trợ GET, mà `/chat/voice` là POST (có body JSON). Phải dùng `fetch()` + đọc stream thủ công.

### 3.1. Code mẫu (JavaScript / TypeScript)

```javascript
const API_BASE = 'http://localhost:8000';

/**
 * Gọi /chat/voice, xử lý filler + response qua SSE.
 *
 * @param {string} query          - Câu hỏi của user (từ STT)
 * @param {string|null} conversationId - ID từ turn trước (null nếu turn đầu)
 * @param {object} handlers
 * @param {function} handlers.onFiller   - gọi khi nhận event filler → speak câu đệm
 * @param {function} handlers.onResponse - gọi khi nhận response → stop filler, speak response
 * @param {function} handlers.onError    - gọi khi lỗi
 * @param {function} handlers.onDone     - gọi khi stream kết thúc (nhận conversationId)
 * @param {AbortSignal} [signal]         - để cancel (user interrupt)
 * @returns {Promise<void>}
 */
async function chatVoice(query, conversationId, handlers, signal) {
  const resp = await fetch(`${API_BASE}/chat/voice`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, conversation_id: conversationId }),
    signal,  // cho phép abort
  });

  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE events phân tách bằng \n\n
    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const rawEvent = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      // Mỗi event có dạng: "data: {json}"
      const dataLine = rawEvent.split('\n').find(l => l.startsWith('data: '));
      if (!dataLine) continue;

      const event = JSON.parse(dataLine.slice(6));

      switch (event.type) {
        case 'filler':
          handlers.onFiller?.();
          break;
        case 'response':
          handlers.onResponse?.(event.response, event);
          break;
        case 'done':
          handlers.onDone?.(event.conversation_id, event);
          break;
        case 'error':
          handlers.onError?.(event.message);
          break;
      }
    }
  }
}
```

### 3.2. Cách dùng

```javascript
// Giữ conversationId giữa các turn
let conversationId = null;

// Track filler đang speak để có thể cancel
let currentFillerUtterance = null;

async function handleUserQuery(query) {
  await chatVoice(
    query,
    conversationId,
    {
      onFiller: () => {
        // Chọn câu đệm random, speak ngay
        const filler = pickRandomFiller();
        currentFillerUtterance = speak(filler);  // trả về utterance để cancel
      },
      onResponse: (responseText, event) => {
        // Stop filler ngay khi response đến
        if (currentFillerUtterance) {
          cancelSpeech(currentFillerUtterance);
          currentFillerUtterance = null;
        }
        // Speak response thật
        speak(responseText);
      },
      onDone: (convId) => {
        conversationId = convId;  // lưu cho turn sau
      },
      onError: (msg) => {
        console.error('Voice stream error:', msg);
        if (currentFillerUtterance) cancelSpeech(currentFillerUtterance);
      },
    },
    abortController.signal  // optional: để user có thể ngắt
  );
}
```

---

## 4. Filler sentences (frontend tự giữ)

Backend chỉ gửi signal, bạn tự định nghĩa list filler. Gợi ý các câu đệm phù hợp voice AI của robot:

```javascript
const FILLER_SENTENCES = [
  "Let me look that up for you.",
  "Great question, let me think about that.",
  "Hmm, let me find the right information.",
  "Just a moment while I check.",
  "Good question! Let me pull that up.",
  "Let me get those details for you.",
  "One second, I want to give you the best answer.",
  "Sure, let me find that out for you.",
];

// Chọn random, KHÔNG lặp lại câu vừa dùng (tránh lặp nhàm)
let lastFillerIndex = -1;
function pickRandomFiller() {
  let idx;
  do {
    idx = Math.floor(Math.random() * FILLER_SENTENCES.length);
  } while (idx === lastFillerIndex && FILLER_SENTENCES.length > 1);
  lastFillerIndex = idx;
  return FILLER_SENTENCES[idx];
}
```

> **Mẹo:** Giữ filler **ngắn** (3-6 từ). Filler chỉ cần đủ dài để phủ kín khoảng chờ ~4-6s. Nếu response đến trước khi filler đọc xong → cancel filler và speak response ngay (xem `onResponse` ở trên).

---

## 5. Xử lý cancel / user interrupt

Khi user nói lại trong lúc đang chờ / đang speak filler:

```javascript
let abortController = null;

function startQuery(query) {
  // Abort query cũ nếu còn đang chạy
  if (abortController) abortController.abort();

  abortController = new AbortController();

  // Cancel speech đang phát (filler hoặc response)
  cancelAllSpeech();

  handleUserQuery(query);  // truyền abortController.signal vào
}
```

Khi `abort()` được gọi, `fetch` sẽ throw `AbortError` — bắt nó để không báo lỗi:

```javascript
async function chatVoice(...) {
  try {
    // ... fetch + read loop ...
  } catch (err) {
    if (err.name === 'AbortError') return;  // user interrupt, im lặng
    throw err;
  }
}
```

---

## 6. Test bằng curl

```bash
# Test nhanh endpoint (thấy 3 events: filler, response, done)
curl -N -X POST http://localhost:8000/chat/voice \
  -H "Content-Type: application/json" \
  -d '{"query": "tell me about your kiosk robots"}'
```

Output kỳ vọng (FAQ miss → có filler):
```
data: {"type":"filler"}

data: {"type":"response","source":"llm","query":"tell me about your kiosk robots","response":"...","items":[...],"retrieved_count":3,"intent":{...}}

data: {"type":"done","intent":{...},"conversation_id":"abc-123"}
```

Test câu FAQ hit (KHÔNG có filler):
```bash
curl -N -X POST http://localhost:8000/chat/voice \
  -H "Content-Type: application/json" \
  -d '{"query": "who is your owner"}'
```

---

## 7. Migration checklist (từ `/chat/text` sang `/chat/voice`)

1. [ ] Thay `fetch('/chat/text')` bằng hàm `chatVoice()` ở Section 3.1.
2. [ ] Thêm list `FILLER_SENTENCES` (Section 4).
3. [ ] Implement `speak()` / `cancelSpeech()` (Web Speech API hoặc TTS engine của bạn).
4. [ ] Xử lý `conversation_id` từ event `done` (giữ qua các turn).
5. [ ] Thêm `AbortController` cho user interrupt (Section 5).
6. [ ] Test: câu FAQ hit (không filler) vs câu miss (có filler).
7. [ ] Tắt filler nếu cần: set `FILLER_SIGNAL_ENABLED=false` trong `.env` (backend skip event filler, stream vẫn chạy).

---

## 8. Backend config

Trong `.env` (hoặc `config.env`):

```env
# Bật/tắt filler signal (default: true)
# false → endpoint vẫn SSE nhưng KHÔNG gửi event filler
FILLER_SIGNAL_ENABLED=true
```
