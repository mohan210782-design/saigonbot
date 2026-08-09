# Configuration reference

> ⚠️ **Thay đổi so với bản cũ:**
> - Sửa `offlineSTT.enabled` default từ `false` → **`true`** (thật sự trong code, bản cũ sai).
> - Sửa `detectionMinFrames` từ `2` → **`3`**.
> - Đánh dấu `splashDurationMs` là **config chết** (không chỗ đọc) — xem [TECH_DEBT.md](../TECH_DEBT.md#11-).
> - Bổ sung `sttEngine` (field quan trọng bản cũ không có trong bảng Top-level).
> - Mọi default đều dẫn `config.js:line` để re-verify.

All runtime behaviour is driven by `window.CHIKKU_CONFIG` in
[`www/js/config.js`](../www/js/config.js). This is a complete reference; the
file itself is heavily commented, so this doc focuses on *what each knob does
and how to tune it*.

Edit the file, then `npm run sync` (no rebuild needed — the WebView loads it
directly).

## Top-level

| Field | Default | config.js | Purpose |
|-------|---------|-----------|---------|
| `apiBaseUrl` | `http://100.79.75.31:8000` | L8 | Backend URL. Device must be on the same network. |
| `apiTimeoutMs` | `180000` | L9 | Per-request timeout (read in `api-client.js:9`). LLM turns are slow — keep high. |
| `apiRetryAttempts` | `3` | L10 | Retry count for `chatVoiceWithRetry`. |
| `apiRetryDelayMs` | `2000` | L11 | Backoff between retries. |
| `bootHealthRetries` | `3` | L17 | Fast boot attempts before offline fallback. |
| `bootHealthRetryDelayMs` | `1000` | L18 | Delay between boot health attempts. |
| `bootHealthTimeoutMs` | `2000` | L19 | Per-attempt fetch timeout. Read in `app.js:2376`. |
| `splashDurationMs` | `3000` | L20 | ⚠️ **CONFIG CHẾT** — không có chỗ đọc (xem [TECH_DEBT 1.1](../TECH_DEBT.md#11-)). Loading screen chờ `Promise.all` health/rag/mic, không sleep theo biến này. |
| `exitPassword` | `'chikku'` | L23 | Password to exit the kiosk (`app.js:3016`). `''` disables the gate. |
| `ttsLang` | `en-US` | L24 | TTS language (`app.js:1215`). |
| `ttsRate` | `1.0` | L25 | TTS speed 0.1–10 (`app.js:1216`). |
| `ttsPitch` | `1.0` | L26 | TTS pitch 0–2 (`app.js:1217`). |
| `sttEngine` | **`'moonshine'`** | L33 | STT engine cho **online** mode. `'moonshine'` = Moonshine on-device; `'native'` = Capacitor SpeechRecognition (Google cloud). Quyết định logic ở `shouldUseMoonshineSTT()` (`app.js:1380`). |
| `debug` | `false` | L37 | Master console-suppression flag (xem `index.html:294-298`). `false` = quiet logs. |

> **Bảng thật (`shouldUseMoonshineSTT()`):**
>
> | `sttEngine` | online | offline | native fail | → engine dùng |
> |-------------|--------|---------|-------------|---------------|
> | `'moonshine'` | ✓ | ✓ | n/a | **Moonshine** (luôn, preload tại boot) |
> | `'native'` | ✓ | — | — | **Capacitor SpeechRecognition** (Moonshine không load) |
> | `'native'` | — | ✓ | — | **Moonshine** (offline force; lazy-load) |
> | `'native'` | ✓ | — | ≥2 fail | **Moonshine** (auto fallback, see `NATIVE_STT_FAIL_THRESHOLD`) |
>
> Với `sttEngine:'native'` + online healthy, Moonshine **không** preload tại boot →
> mic tự do cho native plugin. Khi backend rớt (`applyBackendHealth`), Moonshine
> lazy-load; khi backend lên lại, Moonshine bị tear down (nếu không đang listen)
> để nhả mic. Xem [architecture.md → STT dispatch](architecture.md#speech-to-text-dispatch).

## Boot health check

| Field | Default | config.js | Purpose |
|-------|---------|-----------|---------|
| `bootHealthRetries` | `3` | L17 | Number of fast attempts before falling back to offline. |
| `bootHealthRetryDelayMs` | `1000` | L18 | Delay between attempts. |
| `bootHealthTimeoutMs` | `2000` | L19 | Per-attempt fetch timeout. A truly-down backend resolves to offline in ~7–9 s. |

> If your backend has a slow cold-start, **raise** `bootHealthTimeoutMs` or
> `bootHealthRetries` rather than lowering the timeout.

## `avatar`

Controls the WebGL green-screen video renderer. See `avatar-manager.js`.

| Field | Default | config.js | Purpose |
|-------|---------|-----------|---------|
| `transitionMs` | `400` | L39 | Crossfade duration (`avatar-manager.js:133`). |
| `renderMode` | `canvas` | L42 | `canvas` = WebGL chroma-key; `video` = native `<video>` (alpha only). |
| `videoSources.IDLE` | `assets/videos/idle-state-green.mp4` | L44 | Idle loop. |
| `videoSources.LISTENING` | `assets/videos/idle-state-green.mp4` | L45 | Listening loop (reuses idle). |
| `videoSources.THINKING` | `assets/videos/idle-state-green.mp4` | L46 | Thinking loop (reuses idle). |
| `videoSources.SPEAKING` | `assets/videos/speaking-state-green.mp4` | L47 | Speaking loop. |

To swap avatar videos, drop new MP4s in `www/assets/videos/` and update the
paths. Filenames must be **lowercase** on Android (filesystem is case-sensitive).

## `wakeword`

The openWakeWord ONNX engine. Config được spread nguyên (`...wakewordConfig`) vào `WakewordManager` (`app.js:1059`), nên mọi field đều dùng được.

| Field | Default | config.js | Purpose |
|-------|---------|-----------|---------|
| `enabled` | `true` | L51 | Master switch (`app.js:1052`). |
| `phrase` | `'hi chikku'` | L52 | Display phrase. |
| `keywordName` | `'chikku'` | L53 | openWakeWord model name. |
| `keywordModelFile` | `'Hi_chikku.onnx'` | L58 | Model file under `assets/model/`. **Case-sensitive on Android**. |
| `baseAssetUrl` | `./assets/model` | L59 | Where the ONNX models live. |
| `ortWasmPath` | `./assets/ort/` | L60 | ONNX Runtime WASM location. |
| `ortThreadCount` | `1` | L61 | Threads (http scheme → no crossOriginIsolated). |
| `ortProxy` | `false` | L62 | Run ORT on the main thread. |
| `mediaTrackConstraints` | see file | L63-74 | Mic constraints. AEC/NS/AGC all `false` — native preprocessing distorts speech. |
| `melspecInputScale` / `melspecInputClamp` | `32767` | L75-76 | Mel-spectrogram input scaling. |
| `gain` | `1` | L77 | Input gain. |
| `agc.*` | see file | L78-85 | Software AGC (currently `enabled: false`). |
| `vadThreshold` | `0.35` | L86 | Voice activity detection threshold. |
| `vadDetectionGraceMs` | `800` | L87 | Grace period after VAD fires. |
| `detectionThreshold` | `0.25` | L88 | Min keyword score (with VAD active). |
| `detectionScoreOverride` | `0.45` | L91 | Accept above this score even without VAD. `0` disables. |
| `detectionWindowFrames` | `8` | L92 | Sliding window length. |
| `detectionMinFrames` | **`3`** | L93 | Min frames above threshold within window. *(Bản cũ ghi 2 — sai.)* |
| `scoreEventIntervalMs` | `250` | L94 | UI score-update throttle. |
| `cooldownMs` | `2000` | L95 | Cooldown after a detection. |
| `dingUrl` | `assets/audio/ding.mp3` | L96 | Sound played on detection (`app.js:538`). |
| `speechEndSilenceMs` | `1400` | L97 | Silence that ends a speech segment (`app.js:408`). |
| `startupIgnoreMs` | `0` | L98 | Ignore detections right after listening starts. |
| `retriggerCooldownMs` | `2000` | L99 | Cooldown between consecutive triggers (`app.js:246`). |
| `debug` | `false` | L100 | Verbose wakeword logs (separate from top-level `debug`). |
| `debugLogIntervalMs` | `400` | L101 | Verbose log interval. |

## `offlineRAG`

The on-device RAG pipeline. See [offline-rag.md](offline-rag.md) for the full
pipeline. Các field được spread qua `embedded.opts` vào `HybridRetriever` (`index.js:123` → `retriever.js:66`).

| Field | Default | config.js | Purpose |
|-------|---------|-----------|---------|
| `semantic` | `true` | L113 | Master switch for the dense (MiniLM) channel (`app.js:2582`). `false` → keyword/BM25-only. |
| `rrfK` | `60` | L115 | Reciprocal Rank Fusion constant (`retriever.js:147`). Standard TREC value. |
| `topK` | `10` | L116 | Candidates to rerank after fusion (`retriever.js:147`). |
| `cosineThreshold` | `0.40` | L117 | Min dense cosine for a HIGH-confidence answer (`retriever.js:208`). |
| `bm25OnlyThreshold` | `8` | L118 | Min BM25 score when the dense channel is unavailable (`retriever.js:212`). |
| `intentCosineThreshold` | `0.60` | L119 | Min cosine for semantic intent reclassification (`index.js:118`). |

**Tuning impact:**
- Lower `cosineThreshold` → more confident answers (risk: false matches).
  Higher → safer but more clarifications. MiniLM: related ≈ 0.55, unrelated ≈ 0.05 *(giá trị tham khảo, chưa benchmark)*.
- Lower `intentCosineThreshold` → more paraphrases reclassify as
  identity/conversational (risk: routing product queries to a template).
- BM25 scores scale with corpus length — tune `bm25OnlyThreshold` empirically.

Rerank weights (`wFused`, `wTitle`, `wLexOverlap`, `lowPriorityPenalty`) and BM25
params (`k1`, `b`) are **not** in config — change them in
`retriever.js:DEFAULTS` (L44-54) / `bm25.js` (L52-53).

## `offlineSTT`

On-device Moonshine Voice streaming STT. See [native.md → MoonshineStt](native.md#custom-plugin-moonshinestt-android-only).

| Field | Default | config.js | Purpose |
|-------|---------|-----------|---------|
| `enabled` | **`true`** | L139 | Master switch. Read trong `shouldUseMoonshineSTT()` (`app.js:1381`). *(Bản cũ ghi `false` — sai.)* |
| `moonshineModel` | `base` | L142 | Model short-name. `tiny \| small \| medium` (streaming) hoặc `base` (non-streaming). Stage với `MOONSHINE_MODEL=<name> npm run prepare:moonshine`. |
| `maxRecordingMs` | `30000` | L145 | Hard cap on a single listening session (`offline-stt/index.js:308`). |
| `debug` | `false` | L146 | ⚠️ Hiện không tác động — manager hardcode `debug:true` default (`offline-stt/index.js:72`) và không gate log. Xem [TECH_DEBT 1.2](../TECH_DEBT.md#12-). |

> ⚠️ **Cấu hình hiện tại mâu thuẫn:** `moonshineModel:'base'` là **non-streaming** (transcribe buffer xong), trong khi `sttEngine:'moonshine'` + `enabled:true` nghĩa là app dùng nó cho cả online. Nếu muốn streaming thật (partials real-time), set `'tiny'`/`'small'`/`'medium'` + re-stage. Xem [TECH_DEBT 6.4](../TECH_DEBT.md#64-).

> Moonshine offline STT là **Android only**. iOS không có plugin tương đương — offline mode trên iOS hiện text-input panel (nếu build được, hiện chưa build do thiếu permission strings).

## `voiceFiller`

Bridging sentence while the LLM thinks. See [VOICE_FILLER_GUIDE.md](../VOICE_FILLER_GUIDE.md).

| Field | Default | config.js | Purpose |
|-------|---------|-----------|---------|
| `enabled` | `true` | L154 | Khi `true`, frontend speaks a filler sentence on SSE `filler` event (`app.js:1147`). Stream vẫn chạy nếu `false` — chỉ không có bridging speech. |

The actual filler sentences live in `FILLER_SENTENCES` in `app.js:1123` (hiện 1
câu: `"Chikku is thinking, just a moment."`), not in config. Backend-side toggle
is `FILLER_SIGNAL_ENABLED` in the backend `.env`.

---

## Other constants (in `app.js`, not config)

Hardcoded constants in `app.js`, documented for completeness:

| Constant | Value | app.js | Purpose |
|----------|-------|--------|---------|
| `FOLLOW_UP_TIMEOUT_MS` | `10000` | L698 | Follow-up window after speaking. |
| `IDLE_NEW_CHAT_TIMEOUT_MS` | `120000` | L699 | 2 min idle → silent new conversation. |
| `OFFLINE_STT_MAX_RETRIES` | `3` | L705 | Bounded auto-retry after offline STT load failure. |
| `OFFLINE_STT_RETRY_BACKOFF` | `[2000, 5000, 10000]` | L706 | Backoff table (ms). |
| `NATIVE_STT_FAIL_THRESHOLD` | `2` | L712 | Số native STT **start** failure liên tiếp trước khi auto-fallback sang Moonshine (`recordNativeSttStartFailure` → `classifyNativeSttError`, app.js:1483). Benign outcomes (`no_match`/`speech_timeout`/`no_speech`/aborted) được phân loại `'no-input'` → **không** tính và **reset** counter. Unknown errors → `'start-failure'` fail-safe (kiosk phải responsive). |
| `FOLLOW_UP_SPEECH_FLOOR_MS` | `10000` | L762 | Min follow-up time guaranteed while user is speaking (không có doc cũ đề cập). |
| `HEALTH_POLL_MS` | `8000` | L2691 | Backend health poll interval. |
| `WEATHER_POLL_MS` | `1800000` | L2244 | Weather refresh (30 min). |
| `NATIVE_STT_SILENCE_FLOOR` | `{complete:2000, possibly:1500, minSession:5000}` | L860-872 | Silence floors cho native STT (không có doc cũ đề cập). |
| `SESSION_KEY` | `'chikku_session'` | L1103 | localStorage key for session. |
| `VOLUME_KEY` | `'chikku_volume'` | L3138 | localStorage key for volume. |
| `TEXT_MAX_CHARS` / `TEXT_WARN_THRESHOLD` | `500` / `400` | L3238-3239 | Text-input panel limits. |

To make any of these configurable, move them into `CHIKKU_CONFIG` and read via
`window.CHIKKU_CONFIG.*` with the listed value as default.
