# Troubleshooting & known issues

> ⚠️ **Thay đổi so với bản cũ:**
> - Sửa "Android online should use Web Speech" + "offlineSTT.enabled:false" — sai với config hiện tại (`sttEngine:'moonshine'` + `enabled:true`).
> - Sửa log prefix `[NETWORK]` → `[HEALTH]` (code dùng `[HEALTH]` cho online/offline transitions).
> - Bổ sung log prefixes thiếu: `[SESSION]`, `[EXIT]`, `[MIC]`, `[FILLER]`, `[FLOW]`, `[BARGE-IN]`, `[WAKE-LOCK]`.
> - Các known issues (iOS plist, release signing, localStorage, 'base' model) đã verify vẫn còn đúng.

Debug cheatsheet plus the gaps flagged during the docs review.

## Known issues

These are real discrepancies between the code and the (intended) documented
behaviour. They don't block the Android production build but should be tracked.

### iOS missing permission strings

`ios/App/App/Info.plist` is missing `NSMicrophoneUsageDescription` and
`NSSpeechRecognitionUsageDescription`. iOS will **crash** the moment the mic or
SpeechRecognition is accessed. `SETUP.md` claims they are added automatically —
they are not.

**Fix:** add to `Info.plist` before any iOS build:
```xml
<key>NSMicrophoneUsageDescription</key>
<string>Chikku listens to your voice to answer questions.</string>
<key>NSSpeechRecognitionUsageDescription</key>
<string>Chikku transcribes your speech to answer questions.</string>
```

### Android release signing

`android/app/build.gradle` has no `signingConfigs { release {…} }` block, so
`./gradlew assembleRelease` falls back to the **debug keystore**. Fine for
internal testing; not for Play Store / production distribution.

**Fix:** add a release signing config and reference it from `buildTypes.release`:
```gradle
android {
    signingConfigs {
        release {
            storeFile file(System.env.KEYSTORE_PATH ?: "release.keystore")
            storePassword System.env.KEYSTORE_PASSWORD
            keyAlias System.env.KEY_ALIAS
            keyPassword System.env.KEY_PASSWORD
        }
    }
    buildTypes {
        release {
            signingConfig signingConfigs.release
            // ...
        }
    }
}
```
(Keep keystore credentials out of git — env vars or a gitignored properties file.)

### Session storage uses `localStorage`, not Capacitor Preferences

`@capacitor/preferences` is declared in `package.json` but `app.js` persists
session/volume to `window.localStorage` instead. This works on both platforms
but isn't the recommended cross-platform approach (localStorage can be cleared
by the WebView under storage pressure; Preferences is more durable).

**Affected:** `chikku_session`, `chikku_volume` keys.
**To migrate:** swap `getSession`/`saveSession`/`getStoredVolume`/`persistVolume`
in `app.js` to use `Preferences.get`/`set` (async — boot restore would need to
await). Low priority until a durability bug is observed.

### Moonshine model mismatch with config comment

`CHIKKU_CONFIG.offlineSTT.moonshineModel` defaults to `'base'`, which is the
**non-streaming** model (transcribes a finished buffer). If you want the
real-time streaming experience the docs describe, switch to `'tiny'`, `'small'`,
or `'medium'` and re-stage with `MOONSHINE_MODEL=<name> npm run prepare:moonshine`.

---

## Debug cheatsheet

### App stuck in ERROR overlay
- Backend unreachable **and** offline RAG failed to build. Check:
  - `config.js:apiBaseUrl` reachable from the device?
  - `embeddings.json` + KB JSONs present in `assets/knowledge_base/`?
  - Console logs: `[BOOT]`, `[OFFLINE-RAG]`.
- The overlay clears automatically when health returns (8 s poll) **and** RAG
  is ready.

### Wake word never fires
- `wakeword.enabled` true? `keywordModelFile` case matches the on-disk file
  exactly on Android (`Hi_chikku.onnx`, lowercase `c`)?
- ORT wasm present at `assets/ort/`? Model at `assets/model/`?
- Wake word needs a **user gesture** before it starts listening (autoplay
  policy). Tap the screen once after boot.
- Wakeword is **paused** during TTS and the follow-up window — that's intended.
- Bump `wakeword.debug: true` and watch `[WAKEWORD]` score logs.

### Wrong STT backend active
- **Cấu hình mặc định:** `sttEngine:'moonshine'` + `offlineSTT.enabled:true` →
  app dùng **Moonshine cho cả online + offline**. Nếu bạn thấy log
  `[STT] using offline Moonshine streaming` khi online → đó là đúng, không phải bug.
- Nếu muốn online dùng SpeechRecognition plugin (Google cloud) → set
  `sttEngine:'native'` trong `config.js`. Khi đó:
  - Online healthy → native plugin dùng, Moonshine **không** load tại boot.
  - Offline → Moonshine lazy-load (cloud STT cần network).
  - Native plugin fail start nhiều lần → auto fallback sang Moonshine (xem bên dưới).
- **iOS** chưa build được do thiếu permission strings (xem known issue trên).
- `offlineSTT.enabled:false` → Moonshine **không** load trong mọi trường hợp;
  offline mode sẽ fallback text-input panel. (Hiện đang `true`.)

### Native STT can't acquire mic / "Moonshine chiếm mic" (FIXED)
**Triệu chứng:** `sttEngine:'native'`, nhưng native SpeechRecognition lỗi
(`audio_capture`/`recognizer_busy`), hoặc Moonshine vẫn log
`[moonshine] streaming started` dù đang online.

**Nguyên nhân gốc (đã fix):** Boot detect offline tạm thời (backend cold-start) →
Moonshine preload → giữ native AudioRecord → khi backend lên lại, teardown bị
skip vì không "fully idle" → native STT không lấy được mic.

**Fix:**
1. `shouldUseMoonshineSTT()` giờ chỉ force Moonshine khi **thực sự** offline, không
   phải "offline-mode boot tạm thời" nếu `sttEngine:'native'` + online.
2. Nhánh native trong `startRecording()` tear down Moonshine resident (nếu không
   đang listen) ngay trước khi native plugin start.
3. `applyBackendHealth()` offline→online teardown điều kiện nới lỏng: chỉ cần
   Moonshine **không đang listen** (không cần fully-idle).
4. Native STT start-failure ≥ `NATIVE_STT_FAIL_THRESHOLD` (2) → auto fallback
   sang Moonshine (`useMoonshineFallback`).

**Debug:** bật `debug:true` trong config, theo dõi log `[STT] native start failure`,
`[STT] releasing resident Moonshine manager`, `[HEALTH] online again — releasing
offline STT manager`.

### `[STT] native recognition error: CapacitorException: No match` (FIXED)
**Triệu chứng:** Console spam `console.error` với `CapacitorException: No match`
khi user im lặng hoặc nói không rõ. Có thể kèm auto-fallback **sai** sang
Moonshine sau 2 lần.

**Đây là behavior bình thường bị log sai + phân loại sai.** `"No match"` là
Android `ERROR_NO_MATCH` — recognizer chạy xong nhưng không khớp gì, tương đương
user im lặng. KHÔNG phải lỗi nghiêm trọng.

**Nguyên nhân gốc (đã fix):**
1. `.catch` log `console.error` cho mọi rejection → kết quả bình thường trông
   như crash. Giờ `classifyNativeSttError()` phân loại trước; `'no-input'` →
   `console.log`, `'start-failure'` → `console.error`.
2. **Bug nghiêm trọng trong classifier cũ:** chỉ check `no_match` (underscore)
   nhưng message thực là `"No match"` (dấu cách, mixed case) → không khớp → bị
   fail-safe thành `'start-failure'` → tăng counter → 2 lần silent = fallback
   sai sang Moonshine.
3. Classifier mới: strip prefix `CapacitorException: `, lowercase, collapse
   separators (space/underscore/hyphen), search thay vì anchor → khớp mọi
   variant (`"No match"`, `no_match`, `nomatch`, `NO MATCH`, …). Unknown /
   empty vẫn fail-safe `'start-failure'` (kiosk phải responsive).
4. `'no-input'` outcome giờ **reset** counter (1 glitch + 1 silent không tích lũy).

**Debug:** log giờ sẽ hiện `[STT] native no-input outcome: No match` (info, không
phải error). Nếu vẫn thấy `[STT] native start failure` cho message `"No match"` →
classifier bị regress, kiểm tra `classifyNativeSttError` (app.js:1427).

### TTS silent / choppy on first answer
- Boot warm-up (`CapacitorTTS.speak({text:'.',volume:0})`) forces the 1–3 s
  Android TTS engine init. If the launch greeting is choppy, the warm-up may
  have been skipped — check `runLoading` phase 2 ran.
- `speak()` flips the avatar to SPEAKING ~200 ms **before** starting audio to
  avoid video stutter. If you reorder this, the 4K decoder starves.

### Offline RAG answers are wrong / too generic
See [offline-rag.md → Tuning cheatsheet](offline-rag.md#tuning-cheatsheet).
Most common: `cosineThreshold` too low (confident wrong answers) or too high
(too many clarifications).

### `INTENT_EXAMPLES` drift
If a paraphrase that should match an identity intent doesn't, and you recently
edited `intent.js:INTENT_EXAMPLES`, you forgot the matching edit in
`scripts/build-kb-embeddings.mjs` + rebuild. Run:
```bash
npm run build:kb-embeddings && npm run test:offline-rag
```

### Avatar video not appearing
- `renderMode: 'canvas'` requires the videos to be **green-screen** MP4s (the
  WebGL shader chroma-keys green to transparent). Plain videos won't work.
- Filenames are **case-sensitive on Android**. Verify the path in
  `avatar.videoSources.*` matches exactly.

### Moonshine loads but never emits finals
- `moonshineModel: 'base'` is **non-streaming** — it transcribes a finished
  buffer, so partials are rare. Use a streaming model (`tiny`/`small`/`medium`)
  for real-time behaviour.
- Very noisy environment? `maxRecordingMs` (30 s) is the safety auto-stop.

### Build fails after adding a plugin
- Run `npm run sync` (not just `cap sync`) — it regenerates
  `capacitor.plugins.json` and `capacitor.settings.gradle`.
- Custom Android plugin not visible in JS? It must be `registerPlugin()`-ed in
  `MainActivity.onCreate()` **before** `super.onCreate()` (Capacitor 5 gotcha).

---

## Useful log prefixes

grep these in `adb logcat` (Android) or Safari Web Inspector (iOS):

| Prefix | Source |
|--------|--------|
| `[BOOT]` | boot sequence, health check (app.js runLoading) |
| `[WAKEWORD]` | wake word engine (wakeword-manager + app.js) |
| `[TTS]` | speech output (app.js speak/stopSpeaking) |
| `[STT]` | speech recognition (app.js + offline-stt) |
| `[OFFLINE-RAG]` | offline RAG pipeline (app.js getOfflineRAG + offline-rag/) |
| `[OFFLINE-STT]` | Moonshine STT manager lifecycle (offline-stt/index.js) |
| `[moonshine]` | Moonshine native bridge (moonshine-native.js) |
| `[VOICE]` | voice stream SSE (api-client.js chatVoice) |
| `[FILLER]` | filler bridging speech (app.js speakFiller) |
| `[WEATHER]` | weather poll (app.js fetchWeather) |
| `[HEALTH]` | online/offline transitions (app.js applyBackendHealth) |
| `[SESSION]` | conversation session timers (app.js follow-up/idle) |
| `[MIC]` | mic permission + start/stopRecording (app.js) |
| `[FLOW]` | cancelCurrentFlow teardown (app.js) |
| `[BARGE-IN]` | barge-in button (app.js) |
| `[EXIT]` | app exit cleanup (app.js performExit) |
| `[WAKE-LOCK]` | screen wake lock (app.js) |

> *(Bản cũ ghi `[NETWORK]` cho online/offline transitions — sai, code dùng `[HEALTH]`.)*

Set `CHIKKU_CONFIG.debug: true` to unsuppress non-prefixed logs.

---

## Testing locally

| Command | What it does |
|---------|--------------|
| `npm run test:offline-rag` | 15-query RAG smoke test (Node). Must be 15/15 pass. |
| `npm run test:web:mic` | Playwright-driven mic test against `www/` in Chromium. |
| `npm run sync` | Re-stage all assets + `cap sync` — run after any `www/` edit. |

For live device debugging, `adb logcat | grep -E "WAKEWORD\|TTS\|STT\|BOOT"`
covers most of the voice loop.
