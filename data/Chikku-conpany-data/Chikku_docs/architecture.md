# Architecture

How the runtime is organised and how a single voice turn flows through it.
Read this before editing `www/js/app.js`.

> ⚠️ **Thay đổi so với bản cũ:**
> - Cập nhật **toàn bộ line number** (bản cũ lệch 50–150 dòng do code đã thêm/sửa). Mọi số dòng giờ khớp commit `6d82842`.
> - Sửa phần "Phase 1 parallel": bản cũ nói có 4 promise (health/rag/mic/stt) trong `Promise.all` → thật chỉ 3 (health/rag/mic). Moonshine preload chạy SAU `Promise.all`.
> - Sửa "optimistic preload torn down if healthy" — không có logic này (phiên bản `sttEngine:'native'` cũ).
> - Sửa phần STT dispatch: nhấn mạnh với config hiện tại (`sttEngine:'moonshine'`) thì Moonshine dùng cho cả online+l offline; Capacitor/Web Speech chỉ chạy khi `sttEngine:'native'`.
> - **Lazy Moonshine load + native fallback (mới):** `shouldUseMoonshineSTT()` giờ phân biệt rõ `sttEngine:'moonshine'` (luôn dùng) vs `sttEngine:'native'` (chỉ Moonshine khi offline HOẶC khi native fail). Moonshine không preload tại boot nếu `sttEngine:'native'` + online. Nhánh native tear down Moonshine resident trước khi start. Native start-failure (≥`NATIVE_STT_FAIL_THRESHOLD=2`) → tự fallback sang Moonshine.
> - Bổ sung các logic doc cũ không mô tả: follow-up speech floor, stitch buffer, native silence floors, weather, volume.
>
> Tất cả line number tham chiếu `www/js/app.js` (3364 dòng) tr khi ghi file khác.

## Mental model

`app.js` is a **single 3364-line vanilla-JS module** that owns a small state
machine and orchestrates five sibling modules. There is no framework and no
build step — the WebView loads it directly as `<script type="module">`.

```
                          ┌──────────────────────────────────────────┐
                          │              app.js (orchestrator)        │
                          │  state · runtime · ui · voice loop        │
                          └──┬─────────┬─────────┬─────────┬─────────┘
                             │         │         │         │
            ┌────────────────┘         │         │         └────────────────┐
            ▼                          ▼         ▼                          ▼
   avatar-manager.js          wakeword-manager.js   offline-rag/        offline-stt/
   (WebGL video renderer)     (ONNX wake word)      (BM25+MiniLM RAG)   (Moonshine)
                             │
                             ▼  all backend I/O via window.chikkuAPI
                             api-client.js  (healthCheck · chatVoice SSE)
```

Each sibling is **passive**: it exposes a class/manager and reports back through
callbacks or returned promises. **Only `app.js` mutates app state.**

---

## State objects

Three module-level objects hold everything:

### `state` (app.js:8) — conversation flags
The authoritative high-level state. Every flag flip is followed by
`syncAvatarState()` so the avatar mirrors the conversation.

| field | meaning |
|-------|---------|
| `conversationId` | backend conversation id, or `local-<ts>` offline |
| `messageCount` | turn counter, persisted to `localStorage` |
| `isRecording` / `isProcessing` / `isSpeaking` / `isWaiting` | the four active states |
| `isError` | full-screen ERROR overlay active |
| `wakewordReady` / `wakewordActive` | wakeword model loaded / this turn was wake-triggered |
| `offlineMode` | answering from local KB; STT routes to Moonshine |
| `retryCount` / `maxRetries` | ERROR retry counter (default max 5) |

### `runtime` (app.js:90) — timers, handles, transient flags
All `setTimeout`/`setInterval` IDs, Capacitor listener handles, and the TTS
interrupt mechanism. Notable groups:

- **Flow control (app.js:91-100):** `apiAbortController`, `pendingSpeakRequestId` /
  `pendingSpeakResolver` / `pendingSpeakTimer` (TTS interrupt — see [Barge-in](#barge-in--interrupt)),
  `isCancellingFlow`, `lastFlowCancelledAt`, `suppressIdleOverlay`, `manualMicOnly`.
- **Wakeword gesture (app.js:100-104):** `wakewordIgnoreUntil`, `wakewordGestureUnlocked`,
  `wakewordGestureHandler`, `wakewordActivationPromise`.
- **Capacitor STT handles (app.js:104-106):** `capacitorPartialResultsHandle`,
  `capacitorListeningStateHandle`, `nativeRecordingTimeout`.
- **Follow-up timers (app.js:107-114):** `followUpRestartTimer`, `sttStartedAt`,
  `sttRetryCount`, `followUpTimer`, `followUpStatusTimer`, `followUpExpiresAt`,
  `followUpResumeMs`, `idleNewChatTimer`.
- **Offline engines — lazy singletons (app.js:115-122):** `offlineRAG`,
  `offlineRagBuilding`, `offlineSTT`, `offlineSTTBuilding`, `offlineSTTFailedAt`
  (30s negative-cache window), `offlineSTTRetryCount` (bounded retry).
- **Misc:** `healthPollTimer`, `volume` + `volumeCollapseTimer`, `weatherPollTimer` /
  `weatherLat` / `weatherLon` / `greetingSpoken`.

### `ui` (app.js:30) — cached DOM refs
Plain `getElementById` lookups grouped by region (avatar layer, kiosk layers,
status bar, weather, text-input panel, exit dialog, chat row).

---

## State machine

Five avatar states are defined in `avatar-manager.js` (`AVATAR_STATES`,
`avatar-manager.js:1-7`): `IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `ERROR`.
Each maps to a green-screen MP4 played through a WebGL chroma-key shader. The
AvatarManager is a pure renderer — **`app.js` owns the transitions**.

### `syncAvatarState()` (app.js:150) — the single source of truth
Priority resolver (highest wins):

| condition | → state |
|-----------|---------|
| `isError` | `ERROR` |
| `isSpeaking` | `SPEAKING` |
| `isRecording` | `LISTENING` (beats `isWaiting`) |
| `isProcessing` or `isWaiting` | `THINKING` |
| otherwise | `IDLE` (or `THINKING` if `suppressIdleOverlay`) |

`syncKioskComponents(state)` (app.js:188) mirrors the same state onto the
non-avatar overlays (glow ring, barge-in button, idle overlay, action row,
error overlay).

### Transition diagram

```
                  ┌──────────────── ERROR   (backend down + no offline RAG)
                  │              ↑ applyBackendHealth() sets isError
                  │              ↓ any interaction / health restore
                  │
  (boot) ──► IDLE ─┬── wakeword "hi chikku" ──┐
                  │                           │  startWakewordConversation()
                  │                           ▼
                  │   ┌──── (greeting) ───────────► SPEAKING
                  │   │                                │
                  │   │ tap mic / tap-to-speak         │ speak() ends
                  │   │ / barge-in button              ▼
                  └──►├──► LISTENING ◄──────────── FOLLOW-UP (isWaiting, looks THINKING)
                      │      │ STT final transcript       │ 10 s window
                      │      ▼                            │ or new wake/tap
                      │   THINKING (isProcessing)         │
                      │      │ speak() starts             │
                      │      ▼                            │
                      │   SPEAKING                        │
                      │      │ TTS done                   │
                      │      └──► startFollowUpTimer ─────┘
                      │
                      └── (follow-up timeout, 2 min idle) ──► IDLE
```

Key transition helpers:

| function | role |
|----------|------|
| `beginListeningSession(triggerSource)` (app.js:601) | canonical entry to LISTENING — pauses wakeword, cancels in-flight flow, force-sets LISTENING before any `await` (anti-flicker), plays ding (if not native), starts recording |
| `setRecordingState(bool)` (app.js:1991) | sets `isRecording` + status text + `syncAvatarState()` |
| `cancelCurrentFlow(reason, options)` (app.js:551) | universal teardown — abort fetch, clear timers, stop recording + speaking, clear ERROR. Dedupes within 1 s when idle |
| `exitWaitingToIdle(reason)` (app.js:977) | leave follow-up, resume wakeword, start the 2-min idle timer |

---

## The voice loop end-to-end

One full turn, wake word → spoken answer:

### 1. Wake word detection
`initWakeword()` (app.js:1050) builds `WakewordManager` with an `onDetected`
callback. On detection it calls `getWakewordBlockReason()` (app.js:249) which
returns `null` only when wakeword-ready, off cooldown, not cancelling, not in
any active state, and the voice page is visible. If unblocked →
`startWakewordConversation()`.

> Wake word cần **user gesture** trước khi bắt đầu listen (autoplay policy).
> `attachWakewordGestureListeners` (app.js:342) gắn listener `pointerdown`/`keydown`
> trên document; lần tap đầu tiên mới `activateWakewordAfterGesture` (app.js:307).

### 2. Greeting
`startWakewordConversation()` (app.js:638) picks the online/offline greeting,
pauses the wake word, creates a conversation (`createConversation()` online,
`local-<ts>` offline), appends the greeting bubble, calls `speak(greeting)`,
then opens the follow-up window.

### Speech-to-text dispatch

`startRecording()` (app.js:1457) quyết định engine qua `shouldUseMoonshineSTT()`
(app.js:1380). Moonshine được chọn khi **bất kỳ** điều kiện nào dưới đây (và
`offlineSTT.enabled` vẫn là kill-switch):

```
shouldUseMoonshineSTT():
  if !offlineSTT.enabled        → false
  if sttEngine === 'moonshine'  → true        // Moonshine là engine cấu hình
  if state.offlineMode          → true        // native cloud STT không dùng được
  if useMoonshineFallback       → true        // native engine fail nhiều lần
  → false
```

Điều này có nghĩa:

- `sttEngine:'moonshine'` (default) → Moonshine dùng cho **cả online lẫn offline**,
  preload ngay tại boot.
- `sttEngine:'native'` + online → dùng Capacitor SpeechRecognition (cloud). Moonshine
  **không** được preload tại boot, để mic tự do cho native plugin.
- `sttEngine:'native'` + offline → Moonshine được force (cloud STT cần network),
  `applyBackendHealth()` sẽ lazy-load khi offline.
- `sttEngine:'native'` + native plugin fail start nhiều lần
  (`NATIVE_STT_FAIL_THRESHOLD = 2`) → `useMoonshineFallback` bật, chuyển sang
  Moonshine cho phần còn lại của session.

Priority trong `startRecording`:

1. **Moonshine** (`shouldUseMoonshineSTT()` true, app.js:1573) → `_startOfflineSTT()`
   (app.js:1782). Streams partials/finals qua callbacks
   `onPartial`/`onFinal`/`onSpeechStart`/`onSpeechEnd`.
2. **Capacitor native** (`CapacitorSTT`, app.js:1641) → `_startCapacitorSTT()`
   (app.js:1663). Chỉ chạy khi `sttEngine:'native'` + online + chưa fallback. Dùng
   **final-only** (`partialResults:false`), đăng ký `listeningState` listener.
   Trước khi gọi native, nhánh này **tear down Moonshine resident** (nếu có, không
   đang listen) để tránh mic contention (app.js:1641-1655).
3. **Web Speech API** (`WebSTT`, app.js:1650) → `_startWebSTT()` (app.js:1829).
   Fallback cho browser.

Transcripts accumulate in module-level `finalTranscript` (app.js:1373).

> **Native → Moonshine fallback.** Khi `_startCapacitorSTT` `.catch` nhận lỗi,
> `classifyNativeSttError()` (app.js:1427) phân loại 2 nhóm:
> - **`'no-input'`** (benign recognition outcome) — "No match" / "No speech" /
>   "Speech timeout" / aborted. Đây là tín hiệu end-of-session bình thường
>   (user im lặng / không khớp) → log ở `console.log` (không phải error), và
>   **reset** `nativeSttFailCount` để một glitch đơn lẻ không còn mang theo.
> - **`'start-failure'`** (engine không chạy được) — audio capture / recognizer
>   busy / service missing / network / server / permission.
>   `recordNativeSttStartFailure()` (app.js:1483) tăng `runtime.nativeSttFailCount`;
>   đạt `NATIVE_STT_FAIL_THRESHOLD` (2, app.js:719) → `runtime.useMoonshineFallback`
>   bật, mọi `startRecording()` tiếp theo đi nhánh Moonshine.
>
> Matcher **fail-safe**: mọi lỗi không nhận diện được (empty / unknown) →
> `'start-failure'` (kiosk phải giữ responsive). Message được normalize: strip
> prefix exception (`CapacitorException: …`), lowercase, collapse separators
> (space/underscore/hyphen) → khớp được mọi variant (`"No match"`, `no_match`,
> `nomatch`, `NO MATCH`). Bug cũ: classifier chỉ check `no_match` (underscore)
> nên message thực `"No match"` (space) bị counted → 2 lần silent = fallback sai.
> Flag reset khi user re-engage hoặc backend recover (offline→online).

> **Native STT silence floors** (app.js:860-872): `completeSilenceLengthMs:2000`,
> `possiblyCompleteSilenceLengthMs:1500`, `minimumSessionLengthMs:5000`. Follow-up
> turn mở rộng lên `FOLLOW_UP_TIMEOUT_MS` (10s).

### 4. Stop + handle transcript
`stopRecording()` (app.js:1902) tears down whichever STT engine is active,
flushes `finalTranscript`, and if non-empty calls `handleTranscript(transcript)`.

### 5. `handleTranscript(query)` (app.js:2025) — the brain
Guards against empty/re-entrant input (drops if TTS still playing), sets
`isProcessing`, appends the user bubble, then branches:

- **Offline mode** (app.js:2067) → `getOfflineRAG()` → `rag.answer(query)` →
  `speak()` → `startFollowUpTimer()`.
- **Online mode** (app.js:2120) → `createFlowAbortController()`, then
  `window.chikkuAPI.chatVoiceWithRetry(query, conversationId, { signal, onFiller })`.
  On success → adopt `conversation_id` from the `done` event, `speak()`,
  follow-up. On **non-abort** error (app.js:2156) → flip `offlineMode=true` and
  retry via offline RAG (graceful degradation). On `AbortError` → no-op (user interrupted).

### 6. Speak
`speak(text)` (app.js:1210) cleans the text (`cleanTextForSpeech` app.js:1171 —
strip markdown/emoji), bumps `pendingSpeakRequestId` (the cancel mechanism),
pauses the wake word, then:
**Priority 1** — `CapacitorTTS.speak()`; sets `isSpeaking` + SPEAKING avatar
~200 ms **before** starting audio (app.js:1261-1274) so the 4K video decoder has
a head start. **Priority 2** — Web `speechSynthesis`.

### 7. Follow-up window opens
`startFollowUpTimer()` (app.js:916) sets `isWaiting=true`, arms a 10 s timeout,
and calls `beginFollowUpListen()` (app.js:842) on the next tick so the visitor
can speak immediately without re-triggering the wake word.

### Filler bridging (online only)
Khi backend emit SSE `filler` event (FAQ cache miss, ~4–6 s LLM wait),
`onFiller` → `speakFiller()` (app.js:1146) speaks a random sentence from
`FILLER_SENTENCES` (app.js:1123). Real response's `speak()` tự cancel filler
mid-utterance qua `pendingSpeakRequestId`.

---

## Online vs offline mode

App liên tục probe backend và switch mode tự động.

### Boot health check (`runLoading`, app.js:2355)
`healthCheck()` retried up to `bootHealthRetries` (3) với `bootHealthRetryDelayMs`
(1 s) giữa các attempt, mỗi attempt fail-fast ở `bootHealthTimeoutMs` (2 s)
(app.js:2374-2385). Backend down → offline trong ~7-9 s.
`state.offlineMode = !healthy` (app.js:2412).

### Periodic poll — `startHealthPoll()` (app.js:2693)
`setInterval` mỗi `HEALTH_POLL_MS` (8 s, app.js:2691); mỗi tick gọi `healthCheck()`
rồi `applyBackendHealth(healthy)`.

### `applyBackendHealth(healthy)` (app.js:2712)
- Flip `state.offlineMode`.
- **Online → offline (app.js:2718-2753):** reset offline-STT failure cache +
  retry counter; nếu `sttEngine!=='moonshine'` thì tear down stale STT manager;
  kick `getOfflineSTT()` preload Moonshine. Lúc này `shouldUseMoonshineSTT()`
  đã true (offline mode force Moonshine) nên Moonshine lazy-load.
- **Offline → online (app.js:2763-2787):** nếu `sttEngine!=='moonshine'` VÀ
  Moonshine không đang listen (`!runtime.offlineSTT.isListening`) → tear down
  Moonshine để release mic cho native SpeechRecognition. **Lưu ý:** không cần
  chờ fully-idle như trước — Moonshine nhả mic giữa các session, nên
  speaking/processing/waiting đều an toàn; một defensive backstop cũng có sẵn
  trong `startRecording()` (tear down Moonshine resident ngay trước khi native
  start). Ngoài ra, nếu `useMoonshineFallback` đang set, clear nó +
  `nativeSttFailCount` để cho native engine cơ hội thử lại sau khi backend restore.
- **ERROR overlay rule (app.js:2779-2792):** chỉ show khi offline VÀ offline RAG
  unavailable (kể cả đang build). Otherwise app stays usable.

### `updateNetworkUI()` (app.js:2799)
Toggle status-bar dot/icon/label: green *Connected* vs amber-pulse *Offline-mode*.

> **Lazy Moonshine preload.** Boot: offline RAG KB luôn preload song song với
> health check (app.js:2390). Moonshine preload chạy SAU `Promise.all`
> (app.js:2423) **chỉ khi** `shouldUseMoonshineSTT()` — tức `sttEngine:'moonshine'`,
> HOẶC offline-mode (native cloud STT không khả dụng). Với `sttEngine:'native'` +
> backend healthy, Moonshine **không** load tại boot → mic tự do cho native
> SpeechRecognition, tránh bug mic contention khi backend cold-start chậm.

See [offline-rag.md](offline-rag.md) for the RAG internals and
[configuration.md](configuration.md) for the health-check knobs.

---

## Follow-up window

Sau mỗi `speak()` completion (greeting, online/offline response, error) mở cửa sổ
follow-up 10 s (`FOLLOW_UP_TIMEOUT_MS = 10_000`, app.js:698).

| timer / field | role |
|---------------|------|
| `followUpTimer` | the 10 s `setTimeout` (app.js:934) |
| `followUpStatusTimer` | 1 s `setInterval` updating "Listening… Ns" countdown (app.js:927) |
| `followUpExpiresAt` | epoch-ms deadline (app.js:921) |
| `followUpResumeMs` | frozen remainder when paused (app.js:737) |

| function | role |
|----------|------|
| `startFollowUpTimer()` (app.js:916) | open the window |
| `pauseFollowUpTimer()` / `resumeFollowUpTimer()` (app.js:729 / 748) | freeze/restore countdown |
| `refreshFollowUpWhileSpeaking()` (app.js:772) | top-up remainder lên `FOLLOW_UP_SPEECH_FLOOR_MS` (10 s, app.js:762) để không cắt mid-utterance. **Không doc cũ đề cập.** |
| `beginFollowUpListen()` (app.js:842) | restart STT inside the window without wake word |
| `exitWaitingToIdle()` (app.js:977) | close the window, resume wake word, start idle timer |
| `startIdleNewChatTimer()` (app.js:1009) | 2 min idle → silent new conversation (`IDLE_NEW_CHAT_TIMEOUT_MS`, app.js:699) |

> **The wake word is intentionally NOT resumed during the follow-up window**
> (`resumeWakewordListening` early-returns if `isWaiting`, app.js:389) — STT
> owns the mic for the whole window.

---

## Barge-in / interrupt

Two layers:

### Barge-in button (app.js:2994)
Visible only during `SPEAKING` (app.js:194). On `pointerdown`: set
`suppressIdleOverlay=true`, `cancelCurrentFlow('barge-in')` then
`beginListeningSession('manual')` (app.js:3004-3007).

### `cancelCurrentFlow(reason, options)` (app.js:551)
Universal teardown — aborts `runtime.apiAbortController`, clears all timers,
stops recording + speaking, clears ERROR. Dedupes a second call within 1 s
when nothing is active (app.js:560-570 — the barge-in handler chains into
`beginListeningSession`, which itself calls `cancelCurrentFlow`).

### TTS-level interrupt (`stopSpeaking`, app.js:1352)
Bumps `pendingSpeakRequestId`, resolves `pendingSpeakResolver` (which races
against `CapacitorTTS.speak()` inside `speak()`), then `CapacitorTTS.stop()`.
The id mechanism is also what lets a new `speak()` (the real response) cancel a
filler mid-utterance.

---

## Session persistence — `localStorage`

> ⚠️ **KNOWN ISSUE.** Sessions and volume persisted trong `window.localStorage`,
> **không** Capacitor Preferences. `@capacitor/preferences` có trong `package.json`
> nhưng `app.js` không dùng. Hoạt động cả 2 platform nhưng không phải approach
> cross-platform khuyến nghị (localStorage có thể bị WebView clear). Xem
> [troubleshooting.md](troubleshooting.md).

| key | shape | restored at |
|-----|-------|-------------|
| `chikku_session` | `{ conversation_id, message_count }` | boot, if online & healthy (app.js:2441-2457) |
| `chikku_volume` | integer 0–100 (default 80) | boot, before any TTS (app.js:3358) |

---

## Boot sequence

Entry point là IIFE ở cuối `app.js` (app.js:3353):

```
requestWakeLock()
runtime.volume = getStoredVolume()       // restore before TTS
ui.volumeSlider.value = runtime.volume
updateVolumeIcon(runtime.volume)
initAvatarSurface()                      // AvatarManager init (WebGL chroma-key)
await runLoading()
```

`runLoading()` (app.js:2355) có 3 phase:

**Phase 1 — parallel** (`Promise.all`, app.js:2411) — **chỉ 3 promise**:
- `healthPromise` (app.js:2372) — boot health check with retries.
- `ragPromise` (app.js:2390) — `getOfflineRAG()` + `warmUp()` (luôn, kể cả online,
  để fallback tức thì).
- `micPromise` (app.js:2407) — `requestMicWithTimeout(10000)` →
  `requestMicPermission()` (Capacitor first, `getUserMedia` fallback).

Sau `Promise.all`: `state.offlineMode = !healthy` (app.js:2412). Moonshine
preload chạy **sau** (app.js:2423) nếu `shouldUseMoonshineSTT()` — không nằm
trong `Promise.all`. Lazy: chỉ load khi Moonshine là engine thực sự dùng
(`sttEngine:'moonshine'` hoặc offline-mode). Với `sttEngine:'native'` + healthy,
Moonshine không load tại boot → tránh mic contention với native SpeechRecognition.

**Phase 2 — sequential** (app.js:2438):
- Session restore/create (online) hoặc local-id (offline/failed).
- **TTS warm-up** (app.js:2472): `CapacitorTTS.speak({ text: '.', volume: 0 })` —
  forces the 1–3 s Android TTS engine init now so the launch greeting is instant.
- `initWakeword()` (app.js:2491) — loads the ONNX model, starts listening after
  first user gesture.

**Phase 3 — voice page** (app.js:2503):
- `state.isSpeaking = true` set **before** `showPage('voice')` so the idle
  overlay never flashes.
- `startHealthPoll()` (app.js:2506), `fetchWeather()` (app.js:2507) + 30 min
  interval.
- `playLaunchGreeting()` (app.js:2516) speaks the greeting once, opens the
  follow-up window.

All button `addEventListener` calls are top-level (not inside `runLoading`).

---

## Tính năng không doc cũ nào đề cập

- **Weather** (app.js:2227-2351): Open-Meteo API (free, no key), poll mỗi 30 min.
  Default location Bengaluru (12.9716, 77.5946) nếu geolocation fail (app.js:2281-2284).
  Cập nhật status bar `weatherTemp`/`weatherDesc`/`weatherLoc` + SVG icon.
- **Volume slider** (app.js:3136-3234): dropdown từ status bar, persist
  `chikku_volume`, auto-collapse 3 s, icon mute/low/normal.
- **Exit password gate** (app.js:3016-3122): dialog centered, so khớp
  `exitPassword` config. `''` disables → exit ngay.
- **Wake-lock re-acquire** (app.js:3329-3349): `navigator.wakeLock.request('screen')`,
  re-acquire on `visibilitychange` + on release.
- **Stitch buffer** (offline-stt/index.js:93-349): gộp nhiều Moonshine final thành
  1 transcript sau `stitchTimeoutMs=1500ms` im lặng — chống early-cutoff khi user
  ngắt quãng ("uh…", "hmm…").
- **Offline STT negative cache + bounded retry** (app.js:2641, 1538-1557):
  30 s negative-cache sau load fail; bounded retry 3 lần với backoff
  `[2000,5000,10000]`.

---

## Backend contract

Frontend talk với backend CHỈ qua `window.chikkuAPI` (`api-client.js`). 3 endpoint:

| method | path | used by | notes |
|--------|------|---------|-------|
| `GET` | `/health` | `healthCheck()` (api-client.js:42) | polled mỗi 8 s |
| `POST` | `/conversation/new` | `createConversation()` (api-client.js:51) | returns `conversation_id` |
| `POST` | `/chat/voice` | `chatVoice()` (api-client.js:80) | SSE stream |

SSE event schema (`filler` / `response` / `done` / `error`) documented trong
[VOICE_FILLER_GUIDE.md](../VOICE_FILLER_GUIDE.md).

> Legacy `POST /chat/text` (one JSON blob) không còn gọi từ frontend —
> `sendMessage`/`sendMessageWithRetry` đã xoá. grep `/chat/text` trong `www/js/` = 0.
