# Native layer (Android & iOS)

> ⚠️ **Thay đổi so với bản cũ:**
> - Sửa bảng Capacitor plugins: SpeechRecognition + Web Speech giờ là **dead path** với config mặc định (`sttEngine:'moonshine'`). Moonshine dùng cho cả online + offline.
> - Thêm cảnh báo `moonshineModel:'base'` là non-streaming (mâu thuẫn mô tả "streaming").
> - Xác nhận iOS `Info.plist` thiếu usage strings (code thật, chưa fix).
> - Các claim build/SDK/permission đã verify đúng (xem AUDIT_REPORT.md).

The Capacitor shell, native plugins, permissions, and build steps.
The web app lives in `www/` and is identical across platforms — the differences
are all in `android/` and `ios/`.

For asset preparation (wake word / Moonshine / MiniLM models) see the `npm run`
scripts in [the root README](../README.md#quick-start) and `package.json`.

## App identity

| | Value |
|--|-------|
| appId | `com.chikkurobotics.chikku` |
| appName | `Chikku` |
| webDir | `www` |
| androidScheme | `http` (cleartext — needed for LAN backend) |

`capacitor.config.json` is the source of truth.

---

## Capacitor plugins

| Plugin | package.json | Used for | Platform |
|--------|--------------|----------|----------|
| SpeechRecognition | `@capacitor-community/speech-recognition ^5` | Online STT (cloud) — chạy khi `CHIKKU_CONFIG.sttEngine==='native'` + online healthy + chưa fallback. | Android + iOS |
| TextToSpeech | `@capacitor-community/text-to-speech ^3` | Speaking answers (app.js:1167) | Android + iOS |
| App | `@capacitor/app ^5` | Lifecycle, `exitApp()` (app.js:3095) | Android + iOS |
| Preferences | `@capacitor/preferences ^5` | (declared, **not currently used** — app dùng `localStorage`. Xem [architecture.md → Session persistence](architecture.md#session-persistence--localstorage)) | Android + iOS |
| **MoonshineStt** (custom) | *no npm package* | On-device streaming STT — engine chính khi `sttEngine:'moonshine'` (mặc định), hoặc khi offline, hoặc khi native STT fail. Xem bên dưới. | **Android only** |

> ⚠️ **Lazy load + native fallback (mới).** Moonshine giờ chỉ load khi thực sự cần
> (`shouldUseMoonshineSTT()`, app.js:1380):
> - `sttEngine:'moonshine'` (default) → Moonshine dùng cho cả online + offline, preload tại boot.
> - `sttEngine:'native'` + online healthy → Moonshine **không** load, mic tự do cho SpeechRecognition.
> - `sttEngine:'native'` + offline → Moonshine lazy-load (cloud STT cần network).
> - `sttEngine:'native'` + native plugin fail start ≥ `NATIVE_STT_FAIL_THRESHOLD` (2) lần → auto fallback sang Moonshine (`runtime.useMoonshineFallback`).
>
> Trước khi native SpeechRecognition start, nhánh native trong `startRecording()`
> tear down bất kỳ Moonshine manager nào còn resident (không đang listen) để tránh
> mic contention — đây là fix cho bug "native STT không hoạt động vì Moonshine
> chiếm mic" khi boot detect offline tạm thời rồi backend lên lại.

---

## Custom plugin: `MoonshineStt` (Android only)

The only custom native code in the repo. A Capacitor plugin wrapping the
[Moonshine Voice SDK](https://github.com/UsefulSensors/moonshine) for on-device
streaming speech-to-text, used in offline mode.

| File | Role |
|------|------|
| `android/app/src/main/java/com/chikkurobotics/chikku/MoonshineSttPlugin.java` | `@CapacitorPlugin(name="MoonshineStt")` — load/start/stop/destroy |
| `android/app/src/main/java/com/chikkurobotics/chikku/MainActivity.java` | BridgeActivity; registers `MoonshineSttPlugin` |
| `www/js/offline-stt/moonshine-native.js` | JS bridge — calls `Capacitor.Plugins.MoonshineStt.*` |
| `www/js/offline-stt/index.js` | `OfflineSTTManager` (stitching partials → finals) |

### JS methods exposed
| Method | Role |
|--------|------|
| `loadModel({ model })` | Load model from `assets/moonshine/<model>/` (`encoder_model.ort`, `decoder_model_merged.ort`, `tokenizer.bin`). Accepts `tiny \| small \| medium \| base`. **Lazy:** chỉ gọi khi `shouldUseMoonshineSTT()` true (xem callout ở trên). |
| `start()` | Begin streaming transcription (requests `RECORD_AUDIO` first) |
| `stop()` | Stop, keep mic |
| `destroy()` | Full teardown, release mic — used when switching offline → online, hoặc trước khi native SpeechRecognition start, hoặc khi native fallback được clear |

### Events sent to JS (`notifyListeners`)
| Event | Payload | Meaning |
|-------|---------|---------|
| `moonshine:partial` | `{ text }` | interim transcript |
| `moonshine:final` | `{ text }` | completed utterance |
| `moonshine:error` | `{ message }` | failure |

### Gotcha — register order
In `MainActivity.onCreate()`, `registerPlugin(MoonshineSttPlugin.class)` must
be called **before** `super.onCreate()`. Capacitor 5 consumes the builder inside
`super.onCreate()`, so registering after means `window.Capacitor.Plugins.MoonshineStt`
is `undefined` in the WebView. See the comment in `MainActivity.java`.

### Model selection
| model | arch | mode |
|-------|------|------|
| `tiny`, `small`, `medium` | streaming | real-time partials + finals |
| `base` | non-streaming | transcribes a finished buffer (partials hiếm) |

Set via `CHIKKU_CONFIG.offlineSTT.moonshineModel`. The matching model dir must
be staged by `MOONSHINE_MODEL=<name> npm run prepare:moonshine`.

> ⚠️ **Cấu hình hiện tại = `'base'`** (`config.js:142`) — non-streaming. Kết hợp
> `sttEngine:'moonshine'` (dùng cho cả online) nghĩa là app đang chạy model
> non-streaming cho mọi turn. Nếu muốn streaming thật (partials real-time), set
> `'tiny'`/`'small'`/`'medium'` + re-stage. Xem [TECH_DEBT 6.4](../TECH_DEBT.md#64-).

### Moonshine SDK integration
- Dependency: `ai.moonshine:moonshine-voice:0.0.69` (Maven Central AAR — no
  local `.aar` in `app/libs/`).
- Bundles native libs `libmoonshine.so` + `libonnxruntime.so` for `arm64-v8a`,
  `armeabi-v7a`, `x86_64`. No NDK/CMake needed.
- Forces `minSdkVersion = 26`.
- `MicTranscriber` owns the mic (16 kHz mono) and segments speech itself — no
  external VAD.

> iOS has **no equivalent** plugin, so offline STT is unavailable there. In
> offline mode on iOS the app shows the text-input panel instead.

---

## Permissions

### Android — `android/app/src/main/AndroidManifest.xml`
| Permission | Purpose |
|------------|---------|
| `INTERNET` | backend calls + online Web Speech |
| `RECORD_AUDIO` | mic for Moonshine / SpeechRecognition / wake word |
| `MODIFY_AUDIO_SETTINGS` | mic configuration (volume / silent mode) |

Notable app config:
- `usesCleartextTraffic="true"` + `network_security_config` — allows HTTP to
  the LAN backend (`res/xml/network_security_config.xml`).
- `MainActivity` is `singleTask`, full-screen, hardware-accelerated, with
  `FLAG_KEEP_SCREEN_ON` + immersive sticky UI (kiosk mode).

### iOS — `ios/App/App/Info.plist`

> ⚠️ **KNOWN ISSUE.** `Info.plist` is currently missing
> `NSMicrophoneUsageDescription` and `NSSpeechRecognitionUsageDescription`.
> The app will crash on iOS the moment the mic or SpeechRecognition is
> accessed. These must be added before any iOS build/test. See
> [troubleshooting.md](troubleshooting.md#ios-missing-permission-strings).

---

## Build steps

### Prerequisites
- Node 18+
- Android Studio + JDK 17 (Android)
- Xcode 15+ and Apple Developer account (iOS, Mac only)

### 0. Sync web assets + models into native projects
```bash
npm install
npm run sync          # = prepare:assets + cap sync
```
Run this every time you change files under `www/` or any model asset.

### Android — debug APK
```bash
cd android && ./gradlew assembleDebug
# output: android/app/build/outputs/apk/debug/app-debug.apk
```

### Android — release APK
> ⚠️ **KNOWN ISSUE.** `app/build.gradle` has no `signingConfigs { release {…} }`
> block, so `assembleRelease` falls back to the **debug keystore**. Add a
> release signing config before producing a production-signed APK. See
> [troubleshooting.md](troubleshooting.md#android-release-signing).

```bash
cd android && ./gradlew assembleRelease
# output: android/app/build/outputs/apk/release/app-release.apk  (debug-signed today)
```

Or via Android Studio: `npm run open:android` → Build → Generate Signed
Bundle / APK.

### iOS
```bash
npm run sync
cd ios/App && pod install     # first time only
npm run open:ios              # = cap open ios → Xcode
# In Xcode: Signing & Capabilities → choose Team → Product → Archive
```
> Add the missing permission strings to `Info.plist` first (see KNOWN ISSUE
> above). `Podfile.lock` is not currently committed.

### Full build (one shot)
```bash
npm run build:android   # = prepare:assets + cap build android
npm run build:ios       # = prepare:assets + cap build ios
```

---

## Android build config reference

| | Value | Source |
|--|-------|--------|
| applicationId | `com.chikkurobotics.chikku` | `app/build.gradle` |
| compileSdk | 34 | `app/build.gradle` (overrides variables.gradle's 33) |
| minSdkVersion | 26 | `variables.gradle` (forced by Moonshine AAR) |
| targetSdkVersion | 33 | `variables.gradle` |
| versionCode / versionName | 1 / `1.0` | `app/build.gradle` |
| Java source/target | 17 | `app/capacitor.build.gradle` |
| AGP | 8.13.2 | `android/build.gradle` |
| minify / ProGuard | disabled / empty rules | `app/build.gradle`, `app/proguard-rules.pro` |

> **google-services.json is not present** — Firebase/push notifications are not
> wired up. Adding it requires the `google-services` plugin (already in the
> classpath at `android/build.gradle:11`).

---

## Adding a Capacitor plugin

### From npm (cross-platform plugin)
```bash
npm install @capacitor-community/some-plugin
npm run sync
```
`cap sync` regenerates `android/app/src/main/assets/capacitor.plugins.json`
and `android/capacitor.settings.gradle` — do not edit those by hand.

### Custom Android-only plugin (like MoonshineStt)
1. Write `YourPlugin.java` annotated `@CapacitorPlugin(name="YourPlugin")` under
   `android/app/src/main/java/com/chikkurobotics/chikku/`.
2. In `MainActivity.onCreate()`, **before** `super.onCreate()`:
   ```java
   this.registerPlugin(YourPlugin.class);
   ```
3. Call from JS via `window.Capacitor.Plugins.YourPlugin`.
4. The plugin will not appear in `capacitor.plugins.json` (that file only lists
   npm plugins) — that's expected for custom plugins.

---

## Asset staging for native

The `prepare:*` npm scripts stage assets into both the web layer (for WebView
JS) and the native layer (for native code that reads assets directly):

| Script | Web target | Native target |
|--------|-----------|---------------|
| `prepare:wakeword-assets` | `www/assets/model`, `www/assets/ort`, `www/vendor/*` | — (WebView only) |
| `prepare:moonshine-models` | — | (downloads into staging) |
| `prepare:moonshine-assets` | — | `android/app/src/main/assets/moonshine/<model>/` |
| `prepare:minilm-model` | `www/assets/models/Xenova/all-MiniLM-L6-v2/` | — (WebView only) |
| `build:kb-embeddings` | `www/assets/knowledge_base/embeddings.json` | — (WebView only) |

Moonshine models are native-side only (the SDK runs in Java, not the WebView);
everything else runs inside the WebView.
