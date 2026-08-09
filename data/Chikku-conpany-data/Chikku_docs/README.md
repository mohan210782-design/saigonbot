# Developer Documentation Index

This folder is the long-form reference for maintaining and extending the app.
For a first-build walkthrough see [`../SETUP.md`](../SETUP.md).

| Doc | Audience |
|-----|----------|
| **[../AUDIT_REPORT.md](../AUDIT_REPORT.md)** | ⚠️ Đọc TRƯỚC — đối chiếu doc cũ vs code thật (commit `6d82842`) |
| **[../TECH_DEBT.md](../TECH_DEBT.md)** | Chủ dự án — danh sách dead code / config chết để dọn dẹp |
| [project-structure.md](project-structure.md) | Anyone new to the repo — directory & file reference |
| [architecture.md](architecture.md) | Anyone touching `www/js/app.js` or the voice loop |
| [offline-rag.md](offline-rag.md) | Anyone tuning the offline knowledge-base / retrieval |
| [native.md](native.md) | Anyone building APK/IPA or editing native plugins |
| [configuration.md](configuration.md) | Anyone changing behaviour via `CHIKKU_CONFIG` |
| [troubleshooting.md](troubleshooting.md) | Debugging, known issues, FAQ |

---

## Repository structure

```
chikku_mobile/
├── README.md                  ← start here
├── SETUP.md                   ← first-build walkthrough
├── VOICE_FILLER_GUIDE.md      ← backend SSE /chat/voice contract
├── capacitor.config.json      ← webDir=www, appId, plugin config
├── package.json               ← npm scripts (sync, build, prepare:assets)
│
├── docs/                      ← this folder
│
├── www/                       ← the web app (this is what ships in the APK/IPA)
│   ├── index.html             ← page shells, DOM the JS hooks onto
│   ├── styles.css             ← all styling
│   └── js/
│       ├── app.js             ← THE app: 3364 lines, the entire voice loop
│       ├── api-client.js      ← window.chikkuAPI: healthCheck, createConversation,
│       │                        chatVoiceWithRetry (SSE)
│       ├── config.js          ← window.CHIKKU_CONFIG (see configuration.md)
│       ├── avatar-manager.js  ← AvatarManager: WebGL green-screen video renderer
│       ├── wakeword-manager.js← WakewordManager: ONNX + AudioWorklet wake word
│       ├── offline-rag/       ← on-device RAG (10 files) — see offline-rag.md
│       └── offline-stt/       ← Moonshine STT manager + native bridge
│   ├── assets/                ← images, video, KB JSON, ONNX models, WASM
│   │   ├── model/             ← openWakeWord weights (Hi_chikku, melspec, VAD…)
│   │   ├── models/            ← transformers.js MiniLM model for RAG
│   │   ├── ort/               ← ONNX Runtime WASM binaries
│   │   ├── videos/            ← avatar green-screen MP4s (idle / speaking)
│   │   ├── audio/             ← ding.mp3
│   │   └── knowledge_base/    ← 8 KB JSON files + embeddings.json
│   └── vendor/                ← vendored libraries (onnxruntime, openwakeword, transformers)
│
├── scripts/                   ← asset/model prep + tests (run via npm scripts)
│   ├── copy-wakeword-assets.mjs
│   ├── download-moonshine-models.mjs
│   ├── copy-moonshine-to-android-assets.mjs
│   ├── download-minilm-model.mjs
│   ├── build-kb-embeddings.mjs      ← generates embeddings.json
│   ├── test-offline-rag.mjs         ← npm run test:offline-rag
│   └── playwright-mic-test.mjs      ← npm run test:web:mic
│
├── android/                   ← Capacitor-generated Android project
│   └── app/src/main/java/com/chikkurobotics/chikku/
│       ├── MainActivity.java
│       └── MoonshineSttPlugin.java  ← custom Capacitor plugin (offline STT)
│
└── ios/                       ← Capacitor-generated iOS project
```

## Where things live — quick lookup

| I want to… | Look at |
|------------|---------|
| Change what the bot says about itself | `www/js/offline-rag/templates.js`, `config.js` |
| Edit the knowledge base | `www/assets/knowledge_base/*.json` then `npm run build:kb-embeddings` |
| Tune RAG relevance | `www/js/config.js` → `offlineRAG.*` (see [configuration.md](configuration.md)) |
| Change the wake word | `www/js/config.js` → `wakeword.*` + retrain ONNX model |
| Change the avatar videos | `www/js/config.js` → `avatar.videoSources` + drop MP4s in `assets/videos/` |
| Point at a different backend | `www/js/config.js` → `apiBaseUrl` |
| Add a Capacitor plugin | see [native.md](native.md#adding-a-capacitor-plugin) |
| Change permissions | `android/app/src/main/AndroidManifest.xml`, `ios/App/App/Info.plist` |

## Conventions

- **No build step.** `www/` is plain ES modules loaded directly by the WebView.
  Edit a `.js` file, run `npm run sync`, and it's in the app. There is no
  transpiler, bundler, or framework to satisfy.
- **`app.js` is the source of truth.** It owns the state machine and orchestrates
  every other module. Sibling modules (`avatar-manager.js`, `wakeword-manager.js`,
  `offline-rag/`, `offline-stt/`) are passive — they expose classes/managers and
  call back via callbacks/promise resolvers, they don't mutate app state.
- **Config over code.** Tunable behaviour lives in `CHIKKU_CONFIG`
  (`www/js/config.js`), not hardcoded. See [configuration.md](configuration.md).
- **Backend contract.** The frontend talks to the backend only through
  `window.chikkuAPI` (`api-client.js`). The SSE event schema is documented in
  [VOICE_FILLER_GUIDE.md](../VOICE_FILLER_GUIDE.md).
