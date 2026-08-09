# Project structure & file reference

> ⚠️ **Thay đổi so với bản cũ:**
> - Sửa line count `app.js` ~3370 → **3364**, `config.js` 149 → **156**.
> - Thêm note về **10 file wakeword model thừa** trong `assets/model/` (alexa/jarvis/mycroft/rhasspy/timer/weather) — không dùng, tăng APK. Xem [TECH_DEBT 3.1](../TECH_DEBT.md#31--file-asset-tha-c-trong-disk-app-khong-load).
> - Còn lại đã verify đúng (đây là doc chính xác thứ 2 sau offline-rag.md).

A complete map of the repository: every directory, the code/model/config files inside it, and the role each one plays. Use this as the lookup table when you need to find *where* something lives before reading the topical docs
([architecture](architecture.md), [offline-rag](offline-rag.md), [native](native.md), [configuration](configuration.md)).

> **Conventions reminder.** There is **no build step** — `www/` is plain ES
> modules loaded directly by the WebView. Edit a `.js` file, run `npm run sync`,
> and it is in the app. Filenames are **case-sensitive on Android** (the APK
> filesystem is ext4, not case-insensitive like iOS HFS+).

---

## Top-level overview

```
chikku_mobile/
├── www/                     ← THE app (ships inside the APK/IPA WebView)
├── android/                 ← Capacitor-generated Android project
├── ios/                     ← Capacitor-generated iOS project
├── scripts/                 ← asset/model prep + tests (npm run …)
├── docs/                    ← this folder (long-form developer docs)
├── capacitor.config.json    ← Capacitor config (appId, webDir=www, scheme)
├── package.json             ← npm scripts + Capacitor plugin dependencies
├── package-lock.json
├── README.md                ← project overview + quick start
├── SETUP.md                 ← first-build walkthrough
├── VOICE_FILLER_GUIDE.md    ← backend SSE /chat/voice contract (VN/EN mixed)
├── .gitignore               ← ignores node_modules/, .zcode/, base.apk
└── .zcode/                  ← local agent config (gitignored)
```

The split that matters: **`www/` is the product** (the voice kiosk app);
**`android/` + `ios/` are the Capacitor shells** that wrap it and provide native capabilities (TTS, mic, the custom Moonshine STT plugin). Everything under `www/` is identical across platforms — the platform-specific differences live entirely in `android/` and `ios/`.

---

## The three source layers

| Layer | Where | Runs as | Edited how |
|-------|-------|---------|------------|
| **Web app** | `www/` | JS inside the system WebView | edit file → `npm run sync` |
| **Native shell** | `android/`, `ios/` | Java/Kotlin/Swift, native APIs | edit + rebuild in Android Studio / Xcode |
| **Asset prep** | `scripts/` | Node.js (build-time only, not shipped) | `npm run <script>` |

---

## `www/` — the web application

This is the directory Capacitor serves as `webDir`. Every file here is loaded verbatim by the WebView — no transpiler, bundler, or framework.

### `www/` layout

```
www/
├── index.html               ← page shells: every DOM node the JS hooks onto
├── styles.css               ← all styling (single file, no preprocessor)
├── js/                      ← application code (ES modules)
│   ├── app.js               ← THE orchestrator (~3300 lines): state machine + voice loop
│   ├── api-client.js        ← window.chikkuAPI: health/conversation/chat-voice SSE
│   ├── config.js            ← window.CHIKKU_CONFIG (see configuration.md)
│   ├── avatar-manager.js    ← AvatarManager: WebGL green-screen video renderer
│   ├── wakeword-manager.js  ← WakewordManager: ONNX + AudioWorklet wake word
│   ├── offline-rag/         ← on-device RAG pipeline (10 files)
│   └── offline-stt/         ← Moonshine STT manager + native bridge
├── assets/                  ← images, video, audio, KB JSON, ONNX models, WASM
└── vendor/                  ← vendored libraries (onnxruntime, openwakeword, transformers)
```

### `www/js/` — application modules

| File | Lines | Role |
|------|------:|------|
| `app.js` | 3364 | **The orchestrator — the source of truth.** Owns the `state`/`runtime`/`ui` objects, the five-state avatar machine, and the entire voice loop (wake word → greeting → STT → transcript handling → speak → follow-up). The only module that mutates app state. |
| `api-client.js` | 249 | `APIClient` → `window.chikkuAPI`. All backend I/O. `healthCheck()`, `createConversation()`, `chatVoice()` (SSE stream parser), `chatVoiceWithRetry()` (abortable, retrying wrapper). Fetch-based, no external deps. |
| `config.js` | 156 | `window.CHIKKU_CONFIG` — every tunable knob (API, boot health, avatar, wakeword, offlineRAG, offlineSTT, voiceFiller, sttEngine). See [configuration.md](configuration.md). |
| `avatar-manager.js` | 645 | `AvatarManager` + `AVATAR_STATES`. Pure WebGL renderer: two `<video>` slots crossfaded through a chroma-key (green-screen) fragment shader. `IDLE/LISTENING/THINKING/SPEAKING/ERROR` each map to a green-screen MP4. Does **not** own transitions — `app.js` drives them. |
| `wakeword-manager.js` | 476 | `WakewordManager`. Wraps the vendored openWakeWord engine (`vendor/openwakeword/`) + ONNX Runtime Web. Runs an AudioWorklet at 16 kHz, computes melspectrogram features, scores the wake word ONNX model, applies VAD + a sliding-window detector, reports detections via `onDetected`. |

### `www/js/offline-rag/` — on-device RAG pipeline

Used in offline mode (backend unreachable). Full pipeline in
[offline-rag.md](offline-rag.md); this is the file map.

| File | Lines | Role |
|------|------:|------|
| `index.js` | 299 | **Orchestrator** — `RAGPipeline.answer(query)` entry point. Runs normalize → classify intent → template route → hybrid retrieval → confidence. Async. |
| `text-normalizer.js` | 131 | `normalizeQuery()` — ASR cleanup: lowercase, strip filler words, expand contractions, number-words → digits, trim. |
| `intent.js` | 342 | Two-stage intent classifier. `classifyIntent()` (regex fast-pass over IDENTITY/INFO/CONVERSATIONAL patterns, first-match-wins) + `classifyIntentSemantic()` (dense fallback against precomputed `INTENT_EXAMPLES` vectors). Also defines `IntentType` / `IntentCategory`. |
| `retriever.js` | 226 | `HybridRetriever` — BM25 + MiniLM dense cosine → Reciprocal Rank Fusion → top-K → linear rerank → confidence label (`high`/`low`). |
| `bm25.js` | 119 | Okapi BM25 lexical index (`k1=1.5`, `b=0.75`). Tokenize → stop-word strip → stem → score. |
| `embedder.js` | 115 | On-device MiniLM wrapper (transformers.js). Lazy race-safe singleton `init()`, `embed(text)` → `Float32Array(384)`, `cosineSim()`. Shares the wake word's ORT wasm binaries. |
| `knowledge-base.js` | 509 | KB loader + `extractSectionContent()` chunker (shared with the build script) + legacy `searchKnowledgeBase()` keyword matcher + `getBestFaqMatch()`. |
| `stemmer.js` | 49 | Lightweight suffix-stripping stemmer used by BM25. |
| `templates.js` | 199 | Canned identity/conversational/info/error responses (`ROBOTICS_*_RESPONSES`), `getTemplate()`, `gracefulFallback()`, `getErrorResponse()`. Info templates (COMPANY_LOCATION/CONTACT/HOURS/ABOUT) are routed via the matching intents (TECH_DEBT 2.1 fix). |
| `config.js` | 14 | Identity constants: `botName`, `companyName`, `companyTagline`, `fallbackEmail`. Mirrors the backend's `bot_config`. |

### `www/js/offline-stt/` — Moonshine offline speech-to-text

| File | Lines | Role |
|------|------:|------|
| `index.js` | 350 | `OfflineSTTManager`. Manages the Moonshine lifecycle (load/start/stop/destroy), stitches partial transcripts into finals (anti-early-cutoff), and forwards `onPartial`/`onFinal`/`onSpeechStart`/`onSpeechEnd`/`onError` callbacks to match the online STT contract. |
| `moonshine-native.js` | 254 | JS bridge to the custom `MoonshineStt` Capacitor plugin. Wraps `window.Capacitor.Plugins.MoonshineStt.{loadModel,start,stop,destroy}` and the `moonshine:partial`/`moonshine:final`/`moonshine:error` events. |

### `www/assets/` — runtime assets

```
www/assets/
├── logo.png                 ← brand logo (loading page + status bar)
├── chat-bg.jpg              ← chat background texture
├── city-bg.png              ← idle/kiosk background
├── audio/
│   └── ding.mp3             ← wake-word detection sound (wakeword.dingUrl)
├── videos/                  ← avatar green-screen MP4s (WebGL chroma-keyed)
│   ├── idle-state-green.mp4 ← IDLE / LISTENING / THINKING loops
│   └── speaking-state-green.mp4 ← SPEAKING loop
├── knowledge_base/          ← RAG knowledge base (8 source JSONs + embeddings)
│   ├── company_overview.json
│   ├── identity.json
│   ├── products.json
│   ├── services.json
│   ├── solutions.json
│   ├── technologies.json
│   ├── partnerships.json
│   ├── faq.json
│   └── embeddings.json      ← GENERATED (build:kb-embeddings) — precomputed vectors
├── model/                   ← openWakeWord ONNX weights (single-thread build)
│   ├── .gitkeep
│   ├── Hi_chikku.onnx       ← custom "hi chikku" wake word model (~200 KB) — ĐANG DÙNG
│   ├── embedding_model.onnx ← openWakeWord embedding model (~1.3 MB) — ĐANG DÙNG
│   ├── melspectrogram.onnx  ← melspectrogram feature extractor (~1.1 MB) — ĐANG DÙNG
│   ├── silero_vad.onnx      ← Silero voice-activity detection (~1.8 MB) — ĐANG DÙNG
│   └── ⚠️ + 10 file thừa (alexa/hey_jarvis/hey_mycroft/hey_rhasspy/timer/weather × .onnx/.tflite)
│         không reference, tăng APK. Xem [TECH_DEBT 3.1](../TECH_DEBT.md#31--file-asset-tha-c-trong-disk-app-khong-load).
├── models/                  ← transformers.js sentence-embedding model
│   └── Xenova/all-MiniLM-L6-v2/
│       ├── config.json
│       ├── tokenizer.json
│       ├── tokenizer_config.json
│       ├── special_tokens_map.json
│       ├── vocab.txt
│       └── onnx/
│           ├── model.onnx           ← full-precision (~23 MB)
│           └── model_quantized.onnx ← int8 quantized (~23 MB) — used at runtime
└── ort/                     ← ONNX Runtime WASM binaries (GENERATED by prepare:wakeword-assets)
    ├── ort-wasm.mjs         ← aliased single-thread ORT loader (patched)
    ├── ort-wasm.wasm        ← single-thread ORT binary
    ├── ort-wasm-simd-threaded.mjs ← SIMD+threaded source (aliased from)
    └── ort-wasm-simd-threaded.wasm
```

#### Model file roles

| Model | File(s) | Used by | Purpose |
|-------|---------|---------|---------|
| Wake word | `model/Hi_chikku.onnx` | `wakeword-manager.js` | Scores the "hi chikku" phrase. Custom-trained. |
| Wake word features | `model/melspectrogram.onnx` | `wakeword-manager.js` | Audio → 16 kHz melspectrogram input for the wake word model. |
| Wake word VAD | `model/silero_vad.onnx` | `wakeword-manager.js` | Voice-activity gating before accepting a detection. |
| Wake word embedder | `model/embedding_model.onnx` | `wakeword-manager.js` | openWakeWord's internal embedding model. |
| RAG embeddings | `models/Xenova/all-MiniLM-L6-v2/onnx/model_quantized.onnx` | `offline-rag/embedder.js` | 384-dim sentence embeddings for dense retrieval (int8). |
| RAG vectors | `knowledge_base/embeddings.json` | `offline-rag/retriever.js` | Precomputed chunk + intent-example vectors (~1.7 MB). |

> **Generated vs committed.** `assets/ort/*` and `assets/models/**` are
> produced by `npm run prepare:assets` (via `scripts/copy-wakeword-assets.mjs`
> and `scripts/download-minilm-model.mjs`) but **are committed to git** so a
> fresh clone builds without re-downloading. `embeddings.json` is committed too
> (generated by `scripts/build-kb-embeddings.mjs`). Re-run the scripts when the
> KB or model versions change.

### `www/vendor/` — vendored third-party libraries

Copied from `node_modules/` by `scripts/copy-wakeword-assets.mjs` (the
`transformers` bundle is committed as-is). The WebView cannot use bare
`node_modules/` imports, so these are vendored and imported by relative path.

| Path | Source package | Used by | Role |
|------|----------------|---------|------|
| `vendor/onnxruntime/ort.wasm.min.mjs` | `onnxruntime-web` | `wakeword-manager.js` (and indirectly the RAG embedder) | ONNX Runtime Web ESM loader. |
| `vendor/openwakeword/index.js` | `openwakeword-wasm-browser` | `wakeword-manager.js` | Re-export barrel. |
| `vendor/openwakeword/WakeWordEngine.js` | `openwakeword-wasm-browser` | `wakeword-manager.js` | `WakeWordEngine` class (AudioWorklet + melspec + scoring). Patched to import the vendored ORT. |
| `vendor/transformers/transformers.min.mjs` | `@huggingface/transformers` | `offline-rag/embedder.js` | Transformers.js — loads the MiniLM model for RAG embeddings. |

---

## `scripts/` — build-time asset preparation & tests

Plain Node ESM (`.mjs`), run via the `npm run` scripts in `package.json`.
None of these ship in the app.

| File | npm script | Role |
|------|------------|------|
| `copy-wakeword-assets.mjs` | `prepare:wakeword-assets` | Copies openWakeWord models → `www/assets/model/`, ORT wasm → `www/assets/ort/`, vendored libs → `www/vendor/`. Also mirrors `www/assets/ort` into the native asset trees. |
| `download-moonshine-models.mjs` | `prepare:moonshine-models` | Downloads a Moonshine model's 3 files (`encoder_model.ort`, `decoder_model_merged.ort`, `tokenizer.bin`) into staging. |
| `copy-moonshine-to-android-assets.mjs` | `prepare:moonshine-assets` | Copies the staged Moonshine model → `android/app/src/main/assets/moonshine/<model>/`. Native-side only. |
| `download-minilm-model.mjs` | `prepare:minilm-model` | Downloads `Xenova/all-MiniLM-L6-v2` → `www/assets/models/Xenova/all-MiniLM-L6-v2/`. |
| `build-kb-embeddings.mjs` | `build:kb-embeddings` | Reads the 8 KB JSONs, extracts chunks with the **same** `extractSectionContent()` as runtime, embeds each with MiniLM, writes `www/assets/knowledge_base/embeddings.json`. |
| `test-offline-rag.mjs` | `test:offline-rag` | 15-query RAG smoke test (Node). Must be 15/15 pass. |
| `playwright-mic-test.mjs` | `test:web:mic` | Playwright-driven mic capture test against `www/` in Chromium. |

#### Script composition (from `package.json`)

| Composite script | Runs |
|------------------|------|
| `prepare:moonshine` | `prepare:moonshine-models` + `prepare:moonshine-assets` |
| `prepare:rag` | `prepare:minilm-model` + `build:kb-embeddings` |
| `prepare:assets` | `prepare:wakeword-assets` + `prepare:moonshine` + `prepare:rag` |
| `sync` | `prepare:assets` + `npx cap sync` |
| `build:android` | `prepare:assets` + `npx cap build android` |
| `build:ios` | `prepare:assets` + `npx cap build ios` |

> Run `npm run sync` after **any** change under `www/` or to any model asset —
> it re-stages assets and re-syncs into both native projects.

---

## `android/` — Capacitor Android project

```
android/
├── build.gradle                    ← root build (AGP 8.13.2, google-services classpath)
├── variables.gradle                ← SDK versions (minSdk 26 forced by Moonshine)
├── settings.gradle                 ← module includes
├── capacitor.settings.gradle       ← GENERATED (cap sync) — plugin modules
├── gradle.properties
├── local.properties                ← SDK path (gitignored)
├── gradlew / gradlew.bat           ← wrapper scripts
├── gradle/wrapper/
│   ├── gradle-wrapper.jar
│   └── gradle-wrapper.properties
├── capacitor-cordova-android-plugins/  ← GENERATED Cordova-plugin bridge module
└── app/
    ├── build.gradle                ← app module config (appId, deps, Moonshine AAR)
    ├── capacitor.build.gradle      ← GENERATED — plugin dependencies
    ├── proguard-rules.pro          ← empty (minify disabled)
    └── src/
        ├── main/
        │   ├── AndroidManifest.xml ← permissions + kiosk activity config
        │   ├── assets/             ← native-side assets
        │   ├── java/com/chikkurobotics/chikku/  ← native source
        │   └── res/                ← resources (icons, splash, themes, XML config)
        ├── androidTest/            ← instrumented test stub
        └── test/                   ← unit test stub
```

### `android/app/src/main/java/com/chikkurobotics/chikku/` — native source

The package matches the `applicationId` (`com.chikkurobotics.chikku`). Only two
Java files — the rest is Capacitor-generated.

| File | Role |
|------|------|
| `MainActivity.java` | `BridgeActivity` entry point. Registers `MoonshineSttPlugin` **before** `super.onCreate()` (Capacitor 5 gotcha), enables kiosk mode (`FLAG_KEEP_SCREEN_ON` + immersive sticky UI). |
| `MoonshineSttPlugin.java` | Custom `@CapacitorPlugin(name="MoonshineStt")`. Wraps the Moonshine Voice SDK (`ai.moonshine:moonshine-voice:0.0.69`) for streaming on-device STT. Exposes `loadModel`/`start`/`stop`/`destroy`; emits `moonshine:partial`/`moonshine:final`/`moonshine:error`. **Android only.** |

### `android/app/src/main/assets/` — native-side assets

| Path | Role |
|------|------|
| `capacitor.config.json` | GENERATED — copy of the root config consumed by the bridge. |
| `capacitor.plugins.json` | GENERATED — lists npm-installed plugins (SpeechRecognition, TextToSpeech, App, Preferences). Custom plugins are **not** listed here. |
| `moonshine/base-en/` | Native-only Moonshine model (`encoder_model.ort`, `decoder_model_merged.ort`, `tokenizer.bin`). Staged by `prepare:moonshine-assets`. **Not git-tracked** — run `npm run prepare:moonshine` to stage. |
| `public/` | A mirror of `www/` — this is what the WebView actually loads on Android. Regenerated by `cap sync`. |

### `android/app/src/main/res/` — Android resources

| Path | Role |
|------|------|
| `values/strings.xml` | `app_name`="Chikku", package/url-scheme strings. |
| `values/styles.xml` | App themes (splash, NoActionBar). |
| `values/ic_launcher_background.xml` | Launcher background color. |
| `xml/AndroidManifest.xml` refs | — |
| `xml/network_security_config.xml` | Allows cleartext HTTP (LAN backend). |
| `xml/file_paths.xml` | FileProvider paths. |
| `xml/config.xml` | Cordova compatibility config. |
| `mipmap-*/ic_launcher*.png` | App icons (all densities). |
| `drawable-*/splash.png` | Splash screens (portrait + landscape, all densities). |
| `layout/activity_main.xml` | Bridge layout (single Capacitor WebView). |

### Android permissions (`AndroidManifest.xml`)

| Permission | Purpose |
|------------|---------|
| `INTERNET` | Backend calls + online Web Speech. |
| `RECORD_AUDIO` | Mic for wake word / Moonshine / SpeechRecognition. |
| `MODIFY_AUDIO_SETTINGS` | Mic configuration (volume / silent mode). |

---

## `ios/` — Capacitor iOS project

Standard Capacitor iOS scaffold. `App/App/public/` (the `www/` mirror) and
`capacitor-cordova-ios-plugins/` are gitignored (regenerated by `cap sync`).

```
ios/
├── .gitignore                   ← ignores public/, Pods/, output/, cordova plugins
└── App/
    ├── Podfile                  ← CocoaPods deps (run `pod install` first time)
    ├── App.xcodeproj/           ← Xcode project
    ├── App.xcworkspace/         ← open this in Xcode (not the .xcodeproj)
    └── App/
        ├── AppDelegate.swift    ← app lifecycle entry point
        ├── Info.plist           ← ⚠️ MISSING mic/SpeechRecognition usage strings — see troubleshooting.md
        ├── capacitor.config.json← GENERATED copy of root config
        ├── config.xml           ← Cordova compatibility
        ├── Assets.xcassets/     ← AppIcon + Splash image sets
        ├── Base.lproj/          ← LaunchScreen.storyboard + Main.storyboard
        └── public/              ← mirror of www/ (gitignored, regenerated by cap sync)
```

> **iOS is not yet production-ready** — see the known issues in
> [troubleshooting.md](troubleshooting.md) (missing `Info.plist` permission
> strings) and [native.md](native.md) (no Moonshine equivalent plugin, so
> offline STT is unavailable; offline mode shows the text-input panel instead).

---

## Configuration & metadata files (root)

| File | Role |
|------|------|
| `capacitor.config.json` | Source of truth for app identity: `appId`=`com.chikkurobotics.chikku`, `appName`=`Chikku`, `webDir`=`www`, `androidScheme`=`http` (cleartext, needed for LAN backend). |
| `package.json` | npm scripts (sync/build/prepare/test) + Capacitor plugin dependencies (`speech-recognition`, `text-to-speech`, `app`, `preferences`) + ML libs (`onnxruntime-web`, `openwakeword-wasm-browser`, `@huggingface/transformers`). |
| `package-lock.json` | Pinned dependency versions. |
| `.gitignore` | Ignores `node_modules/`, `.zcode/`, `base.apk`. |

---

## Documentation files

| File | Audience / topic |
|------|------------------|
| `README.md` (root) | Project overview, quick start, tech stack, doc index. |
| `SETUP.md` | First-build walkthrough (prerequisites, config, APK/IPA output). |
| `VOICE_FILLER_GUIDE.md` | Backend `POST /chat/voice` SSE contract (`filler`/`response`/`done`/`error`). |
| `docs/README.md` | Index of the `docs/` folder + repo-structure summary + quick-lookup table. |
| `docs/architecture.md` | Runtime architecture, state machine, voice loop end-to-end. |
| `docs/offline-rag.md` | On-device RAG pipeline (intent → retrieval → confidence → tuning). |
| `docs/native.md` | Android/iOS native layer, Capacitor plugins, build steps, the Moonshine plugin. |
| `docs/configuration.md` | `CHIKKU_CONFIG` reference (every knob explained). |
| `docs/troubleshooting.md` | Debug cheatsheet + known issues. |
| `docs/project-structure.md` | **This file** — directory & file reference. |

---

## "Where do I edit…?" quick lookup

| Task | File(s) |
|------|---------|
| Change what the bot says about itself | `www/js/offline-rag/templates.js`, `offline-rag/config.js` |
| Edit knowledge base content | `www/assets/knowledge_base/*.json` → `npm run build:kb-embeddings` |
| Tune RAG relevance / confidence | `www/js/config.js` → `offlineRAG.*` ([configuration.md](configuration.md)) |
| Change the wake word phrase/model | `www/js/config.js` → `wakeword.*` + retrain `assets/model/Hi_chikku.onnx` |
| Swap avatar videos | drop MP4s in `www/assets/videos/` + `config.js` → `avatar.videoSources` |
| Point at a different backend | `www/js/config.js` → `apiBaseUrl` |
| Change the offline STT model | `config.js` → `offlineSTT.moonshineModel` + `MOONSHINE_MODEL=<n> npm run prepare:moonshine` |
| Add/modify a backend endpoint | `www/js/api-client.js` |
| Change app permissions | `android/app/src/main/AndroidManifest.xml`, `ios/App/App/Info.plist` |
| Edit native Moonshine plugin | `android/.../MoonshineSttPlugin.java` + `www/js/offline-stt/moonshine-native.js` |
| Update staged models (wake word / MiniLM / ORT wasm) | `scripts/copy-wakeword-assets.mjs`, `scripts/download-minilm-model.mjs` → `npm run prepare:wakeword-assets` / `prepare:minilm-model` |
| Regenerate RAG embeddings | `scripts/build-kb-embeddings.mjs` → `npm run build:kb-embeddings` |
| Change build/version SDK | `android/variables.gradle`, `android/app/build.gradle` |

---

## Generated / gitignored files (do not edit by hand)

These are produced by tooling and either committed (so fresh clones build
without re-downloading) or gitignored (regenerated every build). Editing them
directly is wasted work — change the **source** and re-run the script.

| Path | Generated by | Committed? |
|------|--------------|------------|
| `www/assets/ort/*` | `prepare:wakeword-assets` | ✅ yes |
| `www/assets/model/*.onnx` | `prepare:wakeword-assets` | ✅ yes (except `Hi_chikku.onnx` — custom) |
| `www/vendor/**` | `prepare:wakeword-assets` (transformers committed) | ✅ yes |
| `www/assets/models/Xenova/all-MiniLM-L6-v2/**` | `prepare:minilm-model` | ✅ yes |
| `www/assets/knowledge_base/embeddings.json` | `build:kb-embeddings` | ✅ yes |
| `android/app/src/main/assets/public/**` | `cap sync` (mirror of `www/`) | ❌ no (regenerated) |
| `android/app/src/main/assets/moonshine/**` | `prepare:moonshine-assets` | ❌ no |
| `android/app/src/main/assets/capacitor.{config.json,plugins.json}` | `cap sync` | ❌ no |
| `android/capacitor.settings.gradle`, `capacitor.build.gradle` | `cap sync` | ❌ no |
| `android/app/build/`, `*/build/` | Gradle build | ❌ no |
| `android/hs_err_pid*.log`, `replay_pid*.log` | JVM crash dumps | ❌ no (safe to delete) |
| `ios/App/App/public/**` | `cap sync` (mirror of `www/`) | ❌ no |
| `ios/App/Pods/` | `pod install` | ❌ no |
| `node_modules/` | `npm install` | ❌ no |

> If the wake word fails to initialise after a clean checkout, the most likely
> cause is a missing/mismatched file under `www/assets/ort/` or
> `www/assets/model/` — re-run `npm run prepare:wakeword-assets`.
