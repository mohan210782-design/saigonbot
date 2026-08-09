# Software Requirements Specification (SRS)

## Chikku Mobile — Voice AI Kiosk Application

**Version:** 1.0.0  
**Date:** 2026-07-28  
**Company:** Chikku Robotics  

---

## Table of Contents

1. [Introduction](#1-introduction)
   - [1.1 Purpose](#11-purpose)
   - [1.2 Scope](#12-scope)
   - [1.3 Definitions & Glossary](#13-definitions--glossary)
   - [1.4 References](#14-references)
2. [Overall Description](#2-overall-description)
   - [2.1 Product Perspective](#21-product-perspective)
   - [2.2 Product Functions](#22-product-functions)
   - [2.3 User Characteristics](#23-user-characteristics)
   - [2.4 Operating Environment](#24-operating-environment)
   - [2.5 Design & Implementation Constraints](#25-design--implementation-constraints)
   - [2.6 Assumptions & Dependencies](#26-assumptions--dependencies)
3. [Specific Requirements](#3-specific-requirements)
   - [3.1 External Interface Requirements](#31-external-interface-requirements)
   - [3.2 Functional Requirements](#32-functional-requirements)
   - [3.3 Performance Requirements](#33-performance-requirements)
   - [3.4 Non-functional Requirements](#34-non-functional-requirements)
   - [3.5 Platform-specific Requirements](#35-platform-specific-requirements)

---

## 1. Introduction

### 1.1 Purpose

This Software Requirements Specification (SRS) defines the functional and non-functional requirements for the **Chikku Mobile** application — a voice-activated AI kiosk developed by Chikku Robotics. The application serves as the front-end conversational interface for the Chikku service robot, providing natural voice interaction to visitors at exhibitions, lobbies, and public spaces.

This document is intended for:
- **Developers** — as the authoritative reference for implementation.
- **QA Engineers** — as the basis for test planning and verification.
- **Project Stakeholders** — as the agreed-upon scope of delivered functionality.

### 1.2 Scope

Chikku Mobile is a **hybrid mobile application** built with Capacitor 5, wrapping a vanilla JavaScript web application inside a native Android/iOS shell. The system provides:

- **Always-on wake word detection** — listens for "hi chikku" using an on-device ONNX model (openWakeWord).
- **Multi-backend speech-to-text (STT)** — Moonshine Voice SDK (Android, on-device — default engine for both online & offline; also the auto-fallback when the native cloud STT fails) and `@capacitor-community/speech-recognition` (Google cloud, when `sttEngine:'native'` + online healthy). Web Speech API is the browser fallback. Engine selection is centralized in `shouldUseMoonshineSTT()`.
- **Conversational AI with hybrid retrieval** — queries a remote backend (`POST /chat/voice` SSE) when online, and falls back to an on-device Retrieval-Augmented Generation (RAG) pipeline (BM25 + MiniLM dense embeddings + Reciprocal Rank Fusion) when offline.
- **Avatar rendering** — a WebGL green-screen video avatar with five states (idle, listening, thinking, speaking, error).
- **Native text-to-speech (TTS)** — with barge-in support and filler bridging.
- **Kiosk mode** — lockdown UX with password-gated exit, preventing visitors from leaving the app.

The offline RAG knowledge base covers the company's identity, products, services, solutions, partnerships, technologies, and frequently asked questions.

### 1.3 Definitions & Glossary

| Term | Definition |
|------|------------|
| **Wake Word** | The spoken phrase "hi chikku" that activates the voice assistant from idle. |
| **STT** | Speech-to-Text — converting spoken audio into text. |
| **TTS** | Text-to-Speech — synthesizing spoken audio from text. |
| **RAG** | Retrieval-Augmented Generation — retrieving relevant knowledge chunks and using them to generate or select an answer. |
| **SSE** | Server-Sent Events — a unidirectional streaming protocol used by the backend `/chat/voice` endpoint. |
| **BM25** | Okapi BM25 — a bag-of-words lexical retrieval function (k1=1.5, b=0.75). |
| **MiniLM** | `all-MiniLM-L6-v2` — a sentence-transformer model (384-dim embeddings) used for dense semantic retrieval. |
| **RRF** | Reciprocal Rank Fusion — a rank-aggregation method combining BM25 and dense results (k=60). |
| **Moonshine** | The Useful Sensors Moonshine Voice SDK — an on-device streaming STT engine for Android. |
| **openWakeWord** | An open-source ONNX-based wake word detection library. |
| **Filler** | A bridging sentence spoken by TTS while waiting for a slow LLM response from the backend. |
| **Follow-up Window** | A ~10 s period after each answer during which the mic stays open for a follow-up question without re-triggering the wake word. |
| **Barge-in** | The ability to interrupt the current TTS utterance (via button or new speech) and immediately begin a new voice turn. |
| **Capacitor** | A cross-platform native runtime that wraps a web application inside a WebView with access to native device APIs. |
| **Chroma-key** | A compositing technique (green-screen removal) used by the WebGL shader to render the avatar video with transparent background. |
| **VAD** | Voice Activity Detection — determines whether a segment of audio contains speech. |
| **Kiosk Mode** | A locked-down UX preventing the user from navigating away from the application. |

### 1.4 References

| Document | Location |
|----------|----------|
| Project README | `README.md` |
| Setup Guide | `SETUP.md` |
| Architecture Documentation | `docs/architecture.md` |
| Project Structure Reference | `docs/project-structure.md` |
| Offline RAG Pipeline | `docs/offline-rag.md` |
| Native Layer & Plugins | `docs/native.md` |
| Configuration Reference | `docs/configuration.md` |
| Troubleshooting Guide | `docs/troubleshooting.md` |
| Voice Filler SSE Contract | `VOICE_FILLER_GUIDE.md` |
| Capacitor Configuration | `capacitor.config.json` |
| App Configuration | `www/js/config.js` |

---

## 2. Overall Description

### 2.1 Product Perspective

Chikku Mobile is the client-side component of the larger Chikku Robotics ecosystem. The system architecture comprises:

```
┌──────────────────────┐     HTTP/SSE      ┌──────────────────────┐
│   Chikku Mobile App   │ ◄──────────────► │   Saigonbot Backend   │
│  (Capacitor + WebView) │                   │  (RAG + LLM Server)   │
│                       │                   │  POST /chat/voice      │
│  ┌─────────────────┐ │                   │  GET /health            │
│  │ On-device RAG    │ │                   └──────────────────────┘
│  │ On-device STT    │ │
│  │ Wake Word Engine │ │
│  └─────────────────┘ │
└──────────────────────┘
```

The app is designed to function **both online and offline**. When the backend is reachable, the app delegates answering to the server. When unreachable, it degrades gracefully to on-device STT and RAG with no user-visible disruption beyond a status indicator change.

### 2.2 Product Functions

At a high level, the application provides the following capabilities:

| ID | Function | Priority |
|----|----------|----------|
| F-01 | Always-on wake word detection ("hi chikku") | Essential |
| F-02 | Speech-to-text transcription (online & offline) | Essential |
| F-03 | Conversational question answering via backend SSE | Essential |
| F-04 | On-device offline RAG fallback | Essential |
| F-05 | Text-to-speech response delivery with interrupt | Essential |
| F-06 | Avatar rendering with 5-state visual feedback | Essential |
| F-07 | 10-second follow-up conversation window | High |
| F-08 | Kiosk mode with password-gated exit | High |
| F-09 | Backend health monitoring & auto mode switching | High |
| F-10 | Weather information display | Medium |
| F-11 | Text-input panel as fallback for STT | Medium |
| F-12 | Filler bridging during LLM wait | Medium |

### 2.3 User Characteristics

The target users are **visitors at exhibitions, trade shows, and public venues** who interact with the Chikku robot. Users are expected to:

- Have no technical training.
- Interact primarily through **natural spoken English**.
- Stand within conversational distance of the device (~1–3 meters).
- May have varying accents, speech patterns, and background noise conditions.

A secondary user is the **booth operator** who sets up and monitors the device. This user needs the exit password and may configure the backend URL.

### 2.4 Operating Environment

| Parameter | Requirement |
|-----------|-------------|
| **Platform** | Android 8.0+ (API 26), iOS 13+ |
| **Android WebView** | Chrome WebView (system-provided, version ≥ 80) |
| **iOS WebView** | WKWebView (system-provided) |
| **Network** | Wi-Fi (same LAN as backend), or offline |
| **Screen** | Tablet-sized display (recommended 10"+) in landscape or portrait |
| **Audio** | Built-in microphone (mono, 16 kHz), built-in speaker |
| **Architecture** | arm64-v8a (Android), arm64 (iOS); x86_64 supported for emulator testing |
| **Orientation** | Landscape primary (kiosk mount); portrait supported |

### 2.5 Design & Implementation Constraints

| ID | Constraint |
|----|------------|
| C-01 | **No build step.** The web app (`www/`) must be plain ES modules loaded directly by the WebView — no transpiler, bundler, or framework (React/Vue/Angular). |
| C-02 | **Capacitor 5** is the only allowed native bridge. No Cordova plugins. |
| C-03 | **HTTP scheme on Android.** `androidScheme: "http"` is required for LAN backend access (cleartext traffic). |
| C-04 | **Single-threaded ORT.** ONNX Runtime Web runs on the main thread (`ortProxy: false`) because the app is served over `http` (no `crossOriginIsolated` for SharedArrayBuffer). |
| C-05 | **Case-sensitive filenames on Android.** All asset filenames must match exactly, including case (Android uses ext4 filesystem). |
| C-06 | **No COOP/COEP headers.** The app runs on the `capacitor://` or `http://` scheme without cross-origin isolation. |
| C-07 | **Mic constraints.** Echo cancellation, noise suppression, and auto-gain control must be `false` — native preprocessing distorts speech without a reference signal from native TTS. Software AGC inside the AudioWorklet handles normalization. |
| C-08 | **App ID** is `com.chikkurobotics.chikku` and must not change after initial release. |
| C-09 | **Offline STT is Android-only.** Moonshine Voice SDK has no iOS equivalent. iOS offline mode shows the text-input panel. |

### 2.6 Assumptions & Dependencies

| ID | Assumption / Dependency |
|----|--------------------------|
| A-01 | The backend server (`saigonbot`) is available at the configured `apiBaseUrl` on the same LAN. |
| A-02 | The backend exposes `GET /health` and `POST /chat/voice` endpoints conforming to the SSE contract in `VOICE_FILLER_GUIDE.md`. |
| A-03 | The Android device has Google Chrome WebView installed (part of Google Play Services / system image). |
| A-04 | ONNX Runtime Web WASM binaries are present at `www/assets/ort/`. |
| A-05 | openWakeWord models are present at `www/assets/model/`. |
| A-06 | Knowledge base JSON files and embeddings are present at `www/assets/knowledge_base/`. |
| A-07 | Moonshine Voice SDK models are present in `android/app/src/main/assets/moonshine/` for offline STT builds. |
| A-08 | The user grants microphone permission on first launch. |
| A-09 | A user gesture (tap) occurs before wake word detection can start (browser autoplay policy). |

---

## 3. Specific Requirements

### 3.1 External Interface Requirements

#### 3.1.1 User Interface

The UI is a full-screen kiosk interface with the following layers (bottom to top):

| Layer | Description |
|-------|-------------|
| **Avatar layer** | WebGL canvas rendering a green-screen video avatar with chroma-key compositing. Occupies the full viewport as the background. |
| **Status bar** | Top bar showing: network status indicator (green dot = online, amber pulse = offline), weather icon + temperature, volume slider, exit button. |
| **Kiosk overlays** | Glow ring around the avatar, barge-in button (visible during speaking), idle overlay (semi-transparent with "Say 'Hi Chikku'" or "Tap to Speak"), error overlay (full-screen with message). |
| **Chat transcript** | Scrollable text area showing user messages (right-aligned) and bot responses (left-aligned) with conversation bubbles. |
| **Text-input panel** | Shown when offline STT is unavailable — a text field with send button for typed queries. |
| **Exit dialog** | Password prompt shown when the exit button is tapped. |

#### 3.1.2 Avatar States

The avatar renders in exactly **five** states, each mapped to a green-screen MP4 video:

| State | Video | Trigger |
|-------|-------|---------|
| `IDLE` | `idle-state-green.mp4` | No active interaction. |
| `LISTENING` | `idle-state-green.mp4` (reuses idle) | Microphone is recording user speech. |
| `THINKING` | `idle-state-green.mp4` (reuses idle) | Processing transcript, waiting for backend response, or in follow-up window. |
| `SPEAKING` | `speaking-state-green.mp4` | TTS is actively playing audio. |
| `ERROR` | (overlay, not video) | Backend unreachable AND offline RAG unavailable. |

Transitions between states use a 400 ms crossfade between two video slots rendered through a WebGL chroma-key fragment shader.

#### 3.1.3 Backend API Contract

The app communicates with the backend exclusively through `window.chikkuAPI`:

**`GET /health`**
- Returns `{ status: "ok" }` on success.
- Used for boot health check and periodic polling (8 s interval).
- Timeout: 2 s per attempt (boot), 5 s (periodic).

**`POST /chat/voice`** (SSE stream)
- Request body: `{ query: string, conversation_id: string | null }`
- Events (SSE `data:` lines):
  - `{"type":"filler"}` — FAQ cache miss; frontend should speak a filler sentence immediately.
  - `{"type":"response", "query":..., "response":..., "source":...}` — final answer ready.
  - `{"type":"done", "conversation_id":...}` — stream complete.
  - `{"type":"error", "message":...}` — pipeline error.
- See `VOICE_FILLER_GUIDE.md` for the full contract.

#### 3.1.4 Hardware Interfaces

| Interface | Usage |
|-----------|-------|
| **Microphone** | 16 kHz mono audio capture for wake word and STT. Accessed via `getUserMedia` (WebView) or Capacitor SpeechRecognition plugin. |
| **Speaker** | Audio output for TTS and the wake word detection ding. |
| **Touchscreen** | Tap-to-speak activation, barge-in button, exit button, volume slider, text input. |
| **Wi-Fi** | LAN connectivity to the backend server. |

### 3.2 Functional Requirements

---

#### FR-01: Wake Word Detection

**Priority:** Essential  
**Module:** `wakeword-manager.js`

The system shall continuously listen for the spoken phrase "hi chikku" using an on-device openWakeWord ONNX model.

| ID | Requirement |
|----|-------------|
| FR-01.1 | The wake word engine shall load the ONNX model `Hi_chikku.onnx` from `assets/model/` at boot. |
| FR-01.2 | Audio shall be captured at 16 kHz mono via an `AudioWorklet` node. |
| FR-01.3 | Mel-spectrogram features shall be computed in the AudioWorklet and scored by the ONNX model on the main thread. |
| FR-01.4 | A sliding-window detector (8 frames, min 2 above threshold) shall be applied to reduce false positives. |
| FR-01.5 | The detection threshold shall be 0.25 with VAD active, or 0.45 as an override when VAD is inactive. |
| FR-01.6 | A VAD threshold of 0.35 with 800 ms grace period shall gate detections. |
| FR-01.7 | A 2-second cooldown shall be enforced after each detection to prevent double-triggers. |
| FR-01.8 | A "ding" sound (`assets/audio/ding.mp3`) shall be played on detection as audible feedback. |
| FR-01.9 | The wake word engine shall be automatically **paused** during TTS playback and the follow-up window. |
| FR-01.10 | The wake word engine shall be **resumed** when the follow-up window closes or the user exits to idle. |
| FR-01.11 | Wake word detection requires a prior user gesture (tap) due to browser autoplay restrictions. The UI shall prompt "Tap to Start" until this occurs. |

---

#### FR-02: Speech-to-Text (STT)

**Priority:** Essential  
**Modules:** `app.js`, `offline-stt/`, `MoonshineSttPlugin.java`

The system shall transcribe user speech to text using the best available STT backend for the current mode and platform.

**STT Backend Selection Priority** (decided by `shouldUseMoonshineSTT()`, `app.js:1380`):

| Condition | Platform | Backend |
|-----------|----------|---------|
| `sttEngine:'moonshine'` (default) | Android | Moonshine Voice SDK (both online & offline) |
| `sttEngine:'native'` + online healthy | Android/iOS | `@capacitor-community/speech-recognition` plugin (Google cloud) |
| `sttEngine:'native'` + offline | Android | Moonshine Voice SDK (offline forces it — cloud STT needs network) |
| `sttEngine:'native'` + native failed ≥ threshold | Android | Moonshine Voice SDK (auto fallback) |
| Browser (no Capacitor) | any | Web Speech API (continuous + interim) |
| Offline + no Moonshine (iOS) | iOS | None — text-input panel shown |

| ID | Requirement |
|----|-------------|
| FR-02.1 | The Moonshine STT plugin shall load a model (tiny/small/medium/base) from `android/app/src/main/assets/moonshine/`. Loading is **lazy**: the model is loaded only when `shouldUseMoonshineSTT()` is true (i.e. `sttEngine:'moonshine'`, OR offline mode, OR native STT fallback), NOT eagerly at boot when `sttEngine:'native'` + online. |
| FR-02.2 | Moonshine shall emit `partial` (interim) and `final` (completed utterance) events to the JS layer. |
| FR-02.3 | Web Speech API shall be configured for continuous recognition with interim results and auto-restart on `onend`. |
| FR-02.4 | The Capacitor SpeechRecognition plugin shall register `partialResults` and `listeningState` listeners. |
| FR-02.5 | All STT backends shall accumulate partial transcripts into `finalTranscript` and deliver the complete transcript on stop. |
| FR-02.6 | Speech end shall be detected after 1,400 ms of silence (configurable via `wakeword.speechEndSilenceMs`). |
| FR-02.7 | If offline STT is disabled (`offlineSTT.enabled: false`) or unavailable (iOS), the text-input panel shall be displayed in offline mode. |
| FR-02.8 | STT backend switching (online ↔ offline) shall be seamless — the current recording is stopped, the engine is torn down, and the new engine is initialized without requiring user action. |
| FR-02.9 | Before the native SpeechRecognition plugin starts, any resident Moonshine manager that is NOT actively listening shall be destroyed (`startRecording()` native branch) to free the native microphone. This prevents mic contention when Moonshine was loaded during a prior offline state and the backend has since recovered. |
| FR-02.10 | A native SpeechRecognition error shall be classified by `classifyNativeSttError()` as either `'no-input'` (benign recognition outcome: silence / no-match / timeout / aborted — the recognizer RAN but produced no usable transcript) or `'start-failure'` (the recognizer could NOT run: audio capture, recognizer busy, service missing, network/server/client error, permission denied). Classification shall normalize the error message — strip an exception-class prefix (e.g. `CapacitorException: `), lowercase, and collapse separators (space/underscore/hyphen) — so message wording/casing changes across plugin versions cannot misclassify a benign outcome as a failure. Unknown / empty errors shall default to `'start-failure'` (fail-safe: a kiosk must keep responding). After `NATIVE_STT_FAIL_THRESHOLD` (2) consecutive `'start-failure'` outcomes, the app shall flip `runtime.useMoonshineFallback` and route all subsequent `startRecording()` calls to the Moonshine engine. A `'no-input'` outcome shall RESET the failure counter (a single glitch followed by a normal silent turn must not accumulate). The fallback flag is cleared when the backend recovers (offline→online transition in `applyBackendHealth`). |

---

#### FR-03: Conversational AI — Online Mode

**Priority:** Essential  
**Modules:** `app.js`, `api-client.js`

When the backend is reachable, the system shall delegate question answering to the remote `/chat/voice` SSE endpoint.

| ID | Requirement |
|----|-------------|
| FR-03.1 | The app shall send the user's transcript and current `conversation_id` via `POST /chat/voice`. |
| FR-03.2 | The app shall parse the SSE stream and handle `filler`, `response`, `done`, and `error` events. |
| FR-03.3 | On receiving a `filler` event, the app shall immediately speak a random filler sentence (from `FILLER_SENTENCES`) to bridge the LLM wait time (~4–6 s). |
| FR-03.4 | On receiving a `response` event, the app shall cancel any in-progress filler and speak the real response via TTS. |
| FR-03.5 | On receiving a `done` event, the app shall adopt the returned `conversation_id` for the next turn. |
| FR-03.6 | The request shall be **abortable** via `AbortController` to support barge-in and flow cancellation. |
| FR-03.7 | Failed requests shall be retried up to 3 times with 2 s exponential backoff (`apiRetryAttempts`, `apiRetryDelayMs`). |
| FR-03.8 | On non-abort failure (network error, HTTP 5xx), the app shall automatically switch to offline mode and retry the query via the on-device RAG pipeline. |

---

#### FR-04: Conversational AI — Offline Mode

**Priority:** Essential  
**Modules:** `www/js/offline-rag/` (10 files)

When the backend is unreachable, the system shall answer questions using an on-device hybrid RAG pipeline.

**Pipeline stages:**

```
Normalize → Classify Intent → Template Route → Hybrid Retrieval (BM25 + MiniLM) → Confidence → Format Response
```

| ID | Requirement |
|----|-------------|
| FR-04.1 | **Normalization** — The query shall be lowercased, stripped of filler words, have contractions expanded, number-words converted to digits, and whitespace trimmed. |
| FR-04.2 | **Intent Classification** — A two-stage classifier shall determine intent: (1) regex fast-pass (first-match-wins), (2) semantic fallback using MiniLM cosine similarity against precomputed `INTENT_EXAMPLES` vectors (threshold: 0.60). |
| FR-04.3 | **Template Routing** — Conversational intents (greeting, gratitude, small talk, complaint, feedback), company-info intents (location, contact, business hours, about), and select identity intents (who are you, what do you do, capabilities) shall be answered via deterministic templates from `templates.js`. |
| FR-04.4 | **Hybrid Retrieval** — BM25 (lexical) and MiniLM dense cosine similarity (semantic) scores shall be combined via Reciprocal Rank Fusion (k=60) to produce a fused top-10 ranking. |
| FR-04.5 | **Reranking** — The top-10 candidates shall be linearly reranked using weighted BM25 + cosine scores. |
| FR-04.6 | **Confidence Labeling** — A cosine threshold of 0.40 shall define HIGH confidence; below that, the best FAQ match (keyword-based) shall be attempted; if no FAQ match, a clarification prompt shall be returned. |
| FR-04.7 | When the MiniLM embedder is unavailable (semantic disabled or not loaded), the system shall fall back to BM25-only retrieval with a score threshold of 8. |
| FR-04.8 | If no result meets any threshold, a graceful fallback response shall be returned ("I'm not sure about that…"). |
| FR-04.9 | The offline RAG shall be preloaded and warmed up at boot (in parallel with the health check) so the first offline query is fast. |

---

#### FR-05: Text-to-Speech (TTS)

**Priority:** Essential  
**Module:** `app.js` (`speak()` function)

The system shall speak responses aloud using the best available TTS engine.

| ID | Requirement |
|----|-------------|
| FR-05.1 | TTS shall use `@capacitor-community/text-to-speech` (native TTS) as the primary engine. |
| FR-05.2 | Web `SpeechSynthesis` API shall serve as a fallback if Capacitor TTS is unavailable (e.g., running in a desktop browser during development). |
| FR-05.3 | TTS language shall default to `en-US` with configurable rate (0.1–10) and pitch (0–2). |
| FR-05.4 | The avatar state shall transition to `SPEAKING` ~200 ms **before** TTS audio begins, allowing the 4K video decoder a head start. |
| FR-05.5 | Response text shall be cleaned before speaking: Markdown formatting, emoji, and special characters shall be stripped. |
| FR-05.6 | **Barge-in support:** A `pendingSpeakRequestId` mechanism shall allow a new `speak()` call to cancel an in-progress utterance via `CapacitorTTS.stop()`. |
| FR-05.7 | A silent TTS warm-up (speaking `'.'` at volume 0) shall run at boot to initialize the Android TTS engine (~1–3 s), ensuring the launch greeting is instant. |
| FR-05.8 | The wake word engine shall be paused during all TTS playback and resumed afterward. |

---

#### FR-06: Follow-up Conversation Window

**Priority:** High  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-06.1 | After every TTS response completes, a 10-second follow-up window shall open (`FOLLOW_UP_TIMEOUT_MS = 10_000`). |
| FR-06.2 | During the follow-up window, the mic shall remain open for STT without requiring the wake word. |
| FR-06.3 | The wake word engine shall remain paused during the follow-up window. |
| FR-06.4 | A countdown timer shall display "Listening… Ns" in the status area, updating every 1 second. |
| FR-06.5 | The follow-up timer shall **pause** when the user begins speaking (to prevent expiration mid-utterance) and **resume** when speech ends. |
| FR-06.6 | If the follow-up timer expires with no speech, the app shall return to IDLE, resume the wake word, and start a 2-minute idle conversation timer. |
| FR-06.7 | After 2 minutes of idle, a new conversation shall be silently created (resetting `conversation_id`) without any user-visible notification. |

---

#### FR-07: Kiosk Mode & Access Control

**Priority:** High  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-07.1 | The app shall run in full-screen kiosk mode, preventing the user from navigating away. |
| FR-07.2 | An exit button shall be visible in the status bar. |
| FR-07.3 | Tapping the exit button shall show a password prompt dialog. |
| FR-07.4 | The exit password shall be configurable via `CHIKKU_CONFIG.exitPassword` (default: `'chikku'`). |
| FR-07.5 | Setting `exitPassword` to an empty string shall disable the password gate (exit with a single tap). |
| FR-07.6 | The app shall request a wake lock to prevent the screen from sleeping during operation. |

---

#### FR-08: Avatar Rendering

**Priority:** Essential  
**Module:** `avatar-manager.js`

| ID | Requirement |
|----|-------------|
| FR-08.1 | The avatar shall be rendered via a WebGL canvas with a chroma-key (green-screen) fragment shader. |
| FR-08.2 | Two `<video>` elements shall be maintained as texture sources, allowing crossfade transitions. |
| FR-08.3 | State transitions shall crossfade over 400 ms (configurable via `avatar.transitionMs`). |
| FR-08.4 | Each of the five avatar states (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `ERROR`) shall map to a green-screen MP4 video. |
| FR-08.5 | `app.js` shall own all state transitions — `AvatarManager` is a pure renderer that does not mutate app state. |
| FR-08.6 | A `video` render mode shall be supported as an alternative (native `<video>` element for videos with alpha channel), selectable via `avatar.renderMode`. |

---

#### FR-09: Health Monitoring & Mode Switching

**Priority:** High  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-09.1 | At boot, a health check shall be retried up to 3 times with 1 s delays between attempts (2 s per-attempt timeout). A truly-down backend shall resolve to offline mode within ~7–9 s. |
| FR-09.2 | A periodic health poll shall run every 8 seconds (`HEALTH_POLL_MS`). |
| FR-09.3 | On each health poll result, `applyBackendHealth(healthy)` shall determine the mode transition. |
| FR-09.4 | **Online → Offline:** The offline-STT failure cache shall be reset; any stale cached STT manager (when `sttEngine!=='moonshine'`) shall be destroyed; Moonshine shall be lazy-loaded via `getOfflineSTT()`. |
| FR-09.5 | **Offline → Online:** When `sttEngine!=='moonshine'`, any resident Moonshine manager that is NOT actively listening shall be destroyed to release the mic for the native speech recognition plugin. (No need to wait for fully-idle — Moonshine releases the mic between sessions.) Additionally, if `runtime.useMoonshineFallback` is set, it shall be cleared alongside `runtime.nativeSttFailCount` to give the native engine a fresh chance now that the backend has recovered. |
| FR-09.5a | When `sttEngine:'moonshine'`, the Moonshine manager is retained across the offline→online transition because online mode still uses it (no teardown). |
| FR-09.6 | The ERROR overlay shall only be shown when **both** the backend is unreachable **and** the offline RAG is unavailable (not even building). |
| FR-09.7 | A status bar indicator shall toggle between a green "Connected" dot and an amber-pulse "Offline-mode" dot based on current mode. |

---

#### FR-10: Weather Display

**Priority:** Medium  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-10.1 | The app shall fetch and display current weather (icon + temperature) in the status bar. |
| FR-10.2 | Weather shall be fetched at boot and refreshed every 30 minutes. |
| FR-10.3 | Weather fetch failure shall be silent — a missing weather display shall not block any other functionality. |

---

#### FR-11: Text Input Fallback

**Priority:** Medium  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-11.1 | When offline STT is unavailable (iOS offline mode, or `offlineSTT.enabled: false`), a text-input panel shall be shown. |
| FR-11.2 | The text-input panel shall include a text field and a send button. |
| FR-11.3 | Text submitted via the panel shall follow the same `handleTranscript()` processing pipeline as voice input. |

---

#### FR-12: Filler Bridging (Online Only)

**Priority:** Medium  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-12.1 | When the backend sends an SSE `filler` event, a random sentence from a predefined `FILLER_SENTENCES` list shall be spoken immediately via TTS. |
| FR-12.2 | Filler sentences shall be short, natural bridging phrases (e.g., "Let me think about that…", "One moment please…"). |
| FR-12.3 | When the real `response` arrives, the filler shall be cancelled mid-utterance via the `pendingSpeakRequestId` mechanism. |
| FR-12.4 | Fillers shall only be used in online mode (offline RAG responses are deterministic and fast). |

---

#### FR-13: Session Persistence

**Priority:** Medium  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-13.1 | The active `conversation_id` and message count shall be persisted to `localStorage` under the key `chikku_session`. |
| FR-13.2 | The audio volume setting (0–100) shall be persisted to `localStorage` under the key `chikku_volume`. |
| FR-13.3 | Session data shall be restored at boot if the backend is healthy and online. |
| FR-13.4 | Volume shall be restored at boot before any TTS playback. |

---

#### FR-14: Barge-in / Interrupt

**Priority:** High  
**Module:** `app.js`

| ID | Requirement |
|----|-------------|
| FR-14.1 | A barge-in button shall be visible only during the `SPEAKING` state. |
| FR-14.2 | Tapping the barge-in button shall immediately cancel all current flow: abort any in-flight SSE request, stop recording, stop speaking, clear error state. |
| FR-14.3 | After cancellation, a new listening session shall begin immediately. |
| FR-14.4 | `cancelCurrentFlow()` shall be idempotent — a second call within 1 second when nothing is active shall be a no-op (prevents double `stopSpeaking()`). |

---

### 3.3 Performance Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| PR-01 | Wake word detection latency (audio onset → detection callback) | < 500 ms |
| PR-02 | Ding sound playback latency (detection → audio start) | < 100 ms |
| PR-03 | Avatar state change latency (state set → video crossfade start) | < 50 ms |
| PR-04 | Filler sentence TTS start latency (filler event → audio start) | < 100 ms |
| PR-05 | Real response TTS start latency (response event → filler cancel + audio start) | < 200 ms |
| PR-06 | Offline RAG answer latency (query → response text, cold KB) | < 2,000 ms |
| PR-07 | Offline RAG answer latency (query → response text, warm KB) | < 500 ms |
| PR-08 | Boot-to-ready time (app start → wake word active with health resolved) | < 15 s |
| PR-09 | Offline → online switch latency (health returns → STT engine swapped) | < 3 s |
| PR-10 | Online → offline switch latency (health lost → offline RAG available) | Instant (preloaded) |
| PR-11 | TTS warm-up time (silent utterance → TTS engine ready) | < 3 s |
| PR-12 | Moonshine model load time (model bytes → ready for streaming) | < 5 s. With `sttEngine:'native'` + online, the load is deferred to first offline/fallback use (lazy), so it does not count toward boot time. |
| PR-13 | MiniLM embedder initialization time | < 5 s |
| PR-14 | ONNX wake word model load time | < 3 s |
| PR-15 | Memory usage (app in IDLE, wake word active, no conversation) | < 300 MB |
| PR-16 | Memory usage (app during active conversation with Moonshine + RAG loaded) | < 600 MB |
| PR-17 | APK size (all models bundled) | < 250 MB |
| PR-18 | Frame rate — avatar video playback | ≥ 24 FPS |
| PR-19 | Frame rate — WebGL canvas rendering | ≥ 30 FPS |

---

### 3.4 Non-functional Requirements

#### 3.4.1 Reliability

| ID | Requirement |
|----|-------------|
| NFR-01 | The app shall gracefully degrade from online to offline mode without user-visible errors or restarts. |
| NFR-02 | The app shall automatically recover from offline to online mode when the backend becomes reachable. |
| NFR-03 | A single failed backend request shall not crash the app — it shall be retried or fall back to offline RAG. |
| NFR-04 | The app shall survive WebView process death (Android memory pressure) and restore session state from `localStorage`. |
| NFR-05 | The app shall handle `getUserMedia` permission denial gracefully, falling back to text input. |
| NFR-06 | All `setTimeout`/`setInterval` timers shall be tracked in `runtime` and cleared on flow cancellation. |

#### 3.4.2 Usability

| ID | Requirement |
|----|-------------|
| NFR-07 | The app shall require **zero training** for visitors — natural speech interaction only. |
| NFR-08 | Visual feedback shall be immediate for every interaction: ding on wake word, avatar state change on listening/speaking, countdown during follow-up. |
| NFR-09 | Error states shall display a clear, friendly message, not a technical stack trace. |
| NFR-10 | The avatar shall provide continuous visual presence — it shall never show a blank/black screen. |
| NFR-11 | Text in the UI shall be large enough to read from 1–3 meters (kiosk-appropriate font sizes). |

#### 3.4.3 Maintainability

| ID | Requirement |
|----|-------------|
| NFR-12 | All tunable behavior shall be configured in `www/js/config.js` (`window.CHIKKU_CONFIG`), not hardcoded. |
| NFR-13 | `app.js` shall be the single source of truth for app state. Sibling modules shall be passive — they expose classes/managers and report via callbacks; they shall not mutate app state. |
| NFR-14 | The knowledge base shall be stored as structured JSON files; embeddings shall be regenerated via `npm run build:kb-embeddings`. |
| NFR-15 | All asset preparation shall be scripted via `npm run` commands; there shall be no manual file-copy steps. |
| NFR-16 | The codebase shall have no build step (no transpiler, bundler, or framework) to minimize toolchain complexity. |

#### 3.4.4 Security

| ID | Requirement |
|----|-------------|
| NFR-17 | The kiosk exit shall be gated by a configurable password. |
| NFR-18 | The app shall not transmit audio data to any third-party service (all wake word and offline STT processing is on-device). |
| NFR-19 | Backend communication shall be limited to the configured `apiBaseUrl` only. |
| NFR-20 | The Android build shall use a release signing configuration (not the debug keystore) for production distribution. |
| NFR-21 | Keystore credentials shall not be stored in version control — they shall be provided via environment variables or a gitignored properties file. |

#### 3.4.5 Compatibility

| ID | Requirement |
|----|-------------|
| NFR-22 | The app shall run on Android 8.0 (API 26) and above. |
| NFR-23 | The app shall run on iOS 13 and above. |
| NFR-24 | The web app (`www/`) shall be identical across Android and iOS — platform differences shall exist only in `android/` and `ios/`. |
| NFR-25 | Asset filenames shall be case-sensitive-correct for Android's ext4 filesystem. |

---

### 3.5 Platform-specific Requirements

#### 3.5.1 Android

| ID | Requirement |
|----|-------------|
| PS-01 | The Android app shall use Chrome WebView (system-provided). |
| PS-02 | The Android manifest shall declare permissions: `INTERNET`, `RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS`, `WAKE_LOCK`. |
| PS-03 | Cleartext HTTP traffic shall be permitted for LAN backend access (`android:usesCleartextTraffic="true"`). |
| PS-04 | `minSdkVersion` shall be 26 (required by Moonshine Voice SDK). |
| PS-05 | The custom `MoonshineSttPlugin` shall be registered in `MainActivity.onCreate()` **before** `super.onCreate()`. |
| PS-06 | The Moonshine Voice SDK dependency (`ai.moonshine:moonshine-voice:0.0.69`) shall be resolved from Maven Central. |
| PS-07 | Native libraries (`libmoonshine.so`, `libonnxruntime.so`) shall be bundled for `arm64-v8a`, `armeabi-v7a`, and `x86_64` architectures. |

#### 3.5.2 iOS

| ID | Requirement |
|----|-------------|
| PS-08 | `Info.plist` shall include `NSMicrophoneUsageDescription` with a user-facing explanation. |
| PS-09 | `Info.plist` shall include `NSSpeechRecognitionUsageDescription` with a user-facing explanation. |
| PS-10 | The Capacitor SpeechRecognition plugin shall be used for online STT (iOS Safari lacks Web Speech API). |
| PS-11 | Offline STT (Moonshine) is **not available** on iOS; the text-input panel shall be the fallback in offline mode. |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-07-28 | — | Initial SRS document. |
