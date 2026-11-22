# LOKI — Roadmap and status

Status key: ✅ done and tested · 🚧 in progress · ⏳ not started.

| Phase | Deliverable | Status |
|---|---|---|
| 1 Foundation | Text assistant: auth, conversations, streaming chat, model abstraction (Ollama + Gemini), command-centre UI | ✅ see below |
| 2 Voice | STT/TTS providers, WebSocket audio, VAD, barge-in, real amplitude visualiser | ✅ see below |
| 3 Memory | Postgres + pgvector, Alembic, memory extraction/retrieval, memory manager UI, temporary chats | ⏳ |
| 4 RAG | Ingestion worker, hybrid search, rerank, citations, knowledge-base UI | ⏳ |
| 5 Agent + tools | LangGraph orchestrator, tool registry + permissions, reminders/tasks/notes, web research | ⏳ |
| 6 Personalisation | Preferences, projects, schedules, proactive notifications | ⏳ |
| 7 Eval + deploy | Langfuse, eval datasets, metrics dashboard, Docker deployment | ⏳ |

## Phase 1 — scope
Backend
- FastAPI app, structured JSON logging, request ids, CORS, global error handling
- SQLAlchemy 2 async models (users, sessions, conversations, messages); SQLite locally, Postgres via env
- Register / login / logout / me with Argon2id hashes and revocable server-side sessions
- Login rate limiting (in-memory; moves to Redis in Phase 3)
- `LLMProvider` abstraction: Ollama and Gemini, health checks, timeouts, retry on connect errors, primary → fallback
- WebSocket streaming chat with cancel (barge-in primitive) and per-message usage/latency records
- Tests (pytest) with a fake provider

Frontend
- Next.js + TypeScript + Tailwind + Framer Motion + Zustand
- Login / register, assistant screen with central visualiser (state-driven; no fake audio reactivity),
  streaming conversation, history side panel, top bar with assistant/model status
- Side-panel entries for later phases are shown as disabled with their phase number

## Phase 1 — verification (2026-11-22)
- Backend: 27 pytest tests pass (auth, sessions, rate limit, ownership isolation, WS streaming, history context,
  cancel → `interrupted`, fallback, all-providers-down, empty reply, Ollama reasoning separation).
- Live against Ollama `qwen3:4b`: streaming replies, honest refusal of unavailable abilities (reminders),
  token/latency metrics stored, Stop propagates to Ollama (it logs `cancel task`).
- Frontend: `tsc`, ESLint and `next build` clean. Tested in a browser: register, sign-in, streaming states
  (processing → reasoning → idle), stop, history list, reload of a saved conversation, mobile drawer.
- Not covered: login rate limiting is per-process (in-memory); `docker-compose.yml` is untested (no Docker here).

## Phase 2 — voice (2026-11-22)
Design: fully local. Browser Silero VAD (`@ricky0123/vad-web`) → finished utterance over the WebSocket →
faster-whisper `small` on the RTX 5060 (CUDA float16) → same chat turn as text → reply split into sentences
while it streams → Kokoro TTS (CPU) → int16 PCM chunks → Web Audio playback. Providers sit behind
`STTProvider` / `TTSProvider`, so Deepgram / ElevenLabs etc. can be added without touching the chat flow.

Done and verified
- 43 backend tests pass (adds: voice turn order, header/binary pairing, voice + speed settings, typed replies
  silent unless enabled, silence → `no_speech`, bad/oversized audio, STT still loading, barge-in then immediate
  new utterance, spoken "stop" starts no turn, sentence chunking incl. code blocks, Markdown and first-chunk split).
- Real engines: Whisper transcribes a 4–5 s utterance in 0.2–0.5 s on the RTX 5060; Kokoro synthesises at about 0.3× real time
  on CPU. Kokoro → Whisper round trip is word-perfect. Models load in about 4 s at start-up and are warmed up then.
- In the browser (mic replaced by recorded speech fed through a fake `getUserMedia`; everything after the mic
  was real): Listening → Hearing → Transcribing → Reasoning → Speaking states; LOKI started speaking 1.6 s after
  its first token; barge-in stopped playback within about 0.7 s and the new question was answered in context; spoken
  "Stop." just silenced LOKI.
- Visualiser is driven by real levels: microphone RMS while listening, analyser on LOKI's audio output while speaking.
- Clear indicators: red "Mic live" badge in the top bar and a red mic button while the microphone is on.

Not verified / limitations
- Not tested with a physical microphone or speakers (this test browser has neither). Echo: browser echo
  cancellation is on, but without headphones LOKI may hear itself and interrupt its own reply. Test this.
- Transcription is per utterance (Whisper is not a streaming model): there are no live partial captions.
- Voice and speed settings are stored in the browser (localStorage), not per account. That moves into user settings in Phase 6.
- Only English Kokoro voices are offered in the picker; Whisper auto-detects other languages.

## Model speed fix (2026-11-22) ✅
Cause: Ollama saw both GPUs and picked the AMD Radeon 880M, because it borrows system RAM and reports 12 GB.
It ran at 23 tok/s. The model was also `qwen3:4b`, a thinking-only build that reasoned for 200–2,000 hidden
tokens before every answer.

Fix:
- `scripts/start-ollama.ps1` runs LOKI's own Ollama on port 11435 with the AMD GPU hidden (process-only
  environment variables, no system changes). The RTX 5060 gives 83–94 tok/s.
- Default model is `qwen3:4b-instruct` (no reasoning step, tool-calling capable): about 0.2–0.4 s to the first token.
- LOKI preloads the model at start-up (`LLM_WARMUP`), so the first question doesn't pay about 3.5 s of loading.
- Voice turns get a "you are being spoken aloud" instruction: short, conversational, no Markdown.
- The first spoken chunk also breaks at conjunctions, so a long opening sentence starts playing sooner.

Measured end to end (spoken question → LOKI's voice starts): **1.6–1.9 s**, previously 35–90 s.
Breakdown: transcription about 0.4 s, model about 0.2 s, first Kokoro chunk about 1 s.
Further headroom: run Kokoro on the GPU, or use a smaller Whisper model.

GPU memory with everything loaded: about 3.9 GB of 8 GB (Whisper small plus qwen3:4b-instruct).

## Later-phase notes
- Phase 2 needs a decision between Deepgram (cloud, lowest latency) and faster-whisper on the RTX 5060 (local, free).
- Phase 3 requires Docker Desktop or a native PostgreSQL + pgvector install.
