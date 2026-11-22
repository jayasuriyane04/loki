# LOKI — Roadmap and status

Status key: ✅ done and tested · 🚧 in progress · ⏳ not started.

| Phase | Deliverable | Status |
|---|---|---|
| 1 Foundation | Text assistant: auth, conversations, streaming chat, model abstraction (Ollama + Gemini), command-centre UI | ✅ see below |
| 2 Voice | STT/TTS providers, WebSocket audio, VAD, barge-in, real amplitude visualiser | ✅ see below |
| 3 Memory | Postgres + pgvector, Alembic, memory extraction/retrieval, memory manager UI, temporary chats | ✅ see below |
| 4 RAG | Ingestion worker, hybrid search, rerank, citations, knowledge-base UI | ✅ see below |
| 5 Agent + tools | LangGraph orchestrator, tool registry + permissions, reminders/tasks/notes, web research | ✅ see below |
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

## Phase 5 — agent and tools (2026-11-22) ✅

Architecture
- **LangGraph agent** (`app/agent/graph.py`): `model → approve → tools → model …` (up to 12 model steps).
  - The model step streams its text to the user and collects tool calls.
  - The approve step pauses with `interrupt()` for actions that need confirmation; it has no side effects, so
    resuming is safe.
  - The tools step runs the calls.
  - Live objects travel in the run context, never in checkpoints.
- **29 tools** (`app/tools/builtin/`), each with a Pydantic input schema, timeout, permission level and audit-log entry:
  - **Time and information:** time, weather (Open-Meteo), web search (**SearXNG** in Docker, no API key), reading web
    pages (refuses private and local addresses at every redirect; content is wrapped as untrusted).
  - **Productivity:** tasks, reminders, notes (embedded so they're searchable), calendar events, notifications.
  - **Your knowledge:** document and code search, reading uploaded project files, memory search.
  - **System:** LOKI's own logs, system info, allowlisted dev commands, apps and workflows
    (`backend/config/automation.json`), opening websites.
- **Permissions:**
  - *read* tools run automatically.
  - *reversible* tools run automatically unless you set them to "ask me first" or "off".
  - *confirm* tools always ask: deleting tasks, notes or events, running commands, opening URLs. That can't be
    switched off.
  - The executor enforces all of this whatever the model asks.
  - Commands are allowlisted ids only: no shell, and the argv comes from config.
- **Approvals name the target:** before asking, a check finds the item and describes exactly what will happen
  ("Permanently delete task “buy groceries” (due Mon 23 Nov 09:00)"). An impossible request is rejected without
  asking you.
- **Reminders:** a scheduler (15 s poll) delivers them as stored notifications, pushed live to every open tab (toast,
  bell, optional desktop notification). Reminders that fell due while LOKI was off are delivered at start-up.
- **Timezone:** the browser reports its IANA timezone. The prompt shows local time plus a 7-day date table.

Guards added because of failures seen in live runs with `qwen3:4b-instruct`
| Live failure | Fix |
|---|---|
| Later turns said "Task created/deleted" **without calling tools**, copying earlier text-only replies | History replays past tool calls and results; firmer prompt; **unbacked-claim check** (each claim must be backed by a matching successful tool this turn or earlier on the same item), otherwise a visible correction and one retry |
| "Friday" → Thursday; "tomorrow" → day after | Date fields accept the user's own words ("Friday 10am", "in 2 hours", "27 Nov 18:00"), resolved exactly in code (20 tested cases) |
| Invented ids (`task-7c2a…`), and you were asked to approve deleting them | Tools accept titles; targets are checked before approval |
| A 72 s / 4k-token loop repeating "I'll now list your open tasks." | Repetition guard (third identical sentence ends the step); detection of promises without action |
| A recap of an earlier deletion was flagged as a false claim | Claims are matched against earlier successful steps by item title |
| Ran out of steps and narrated "Creating note… Notification set" | Steps raised to 12; the final step tells the model it has no tools; claims made then get a visible correction |
| Silently skipped "save as a note" / "notify me" | Completion check: explicitly requested actions (note, notify, remind, task, event) must succeed before the turn ends; one targeted retry |
| Repeated a false claim after the retry | A false claim never stands: a visible correction names what was **not** done |
| Windows has no timezone database (`zoneinfo` failed even for UTC) | `tzdata` dependency |
| Ollama silently truncated prompts at 4,096 tokens (also affected Phase 4) | `num_ctx` set to 12,288 for chat and warm-up |

Verified
- **156 backend tests** pass on SQLite and on Postgres (agent loop, approvals, denial, pre-approval rejection,
  invalid args, unknown tools, step limit, switched-off tools, preference locks, reminders → notifications,
  CRUD and isolation, SSRF refusal, untrusted wrapping, allowlisted command runs after approval, all guards above).
- **Live with the real model**, all six scenarios from the brief:
  - reminder "tomorrow at 10 AM" → Mon 23 Nov 10:00
  - tasks for Friday and tomorrow → correct dates
  - weather (umbrella question answered from Open-Meteo)
  - web research with 3 cited bullets from real SearXNG results
  - delete with approval, and a refusal respected
  - the **multi-step workflow** (search → recover from 403 → read 3 sources → save a structured note → notify):
    done in about 30 s, with a correction shown for one premature claim
- **Browser:** tool steps under replies; an approval card naming the target, then deletion; a reminder delivered
  as a toast and bell badge (≈19 s after due, within the 15 s poll); Planner tabs; Tools page with locked settings
  and the activity log.

Limits
- 4B model quality: research content can be loose (it once called a closed-source product "open-source", and
  included non-voice platforms). Corrections can appear mid-reply when the model claims something early.
- Claim and request detection is pattern-based (English phrasing); unusual wording can slip past.
- Calendar is LOKI's own (no Google or Outlook sync yet); notifications only reach open LOKI tabs or the desktop (no
  phone push yet).
- Gemini tool calling is implemented but untested (no API key).

## Phase 4 — knowledge base / RAG (2026-11-22) ✅

Pipeline
1. **Upload** (`POST /api/documents`, multipart; files, folders and drag and drop): path traversal refused; secrets files
   (`.env`, `*.pem`, `id_rsa`, `credentials*.json`…), dependency/build folders and binaries skipped; 20 MB per
   file, 200 per request. Identity = (user, project, path): re-uploading unchanged content is a no-op, changed
   content is re-indexed in place.
2. **Background ingestion** (in-process queue, one worker, unfinished jobs re-queued at start-up; Celery has no
   Windows support): extract (pypdf per page; Markdown, text, HTML with scripts and styles stripped, 30+ code languages)
   → clean (PDF hyphenation, whitespace) → **structure-aware chunks** (Markdown by heading path, PDF by page,
   code by top-level definition; about 1,200 characters with about 150 characters of overlap; heading-only sections dropped) →
   embeddings (`qwen3-embedding`, batched) → old chunks replaced in one transaction.
3. **Hybrid search**: pgvector cosine plus Postgres full-text search (generated `tsvector`, headings weighted, GIN index),
   fused with reciprocal-rank fusion → **cross-encoder rerank** (`mxbai-rerank-xsmall-v1`, ONNX on CPU, ~0.2 s for
   30 passages) → passages scoring at least 0.25 are kept. Also kept: passages that both searches rank top 2, if
   the reranker gives at least 60% of the threshold, because the reranker under-scores code.
4. **Grounded answer**: up to 6 numbered passages go in `<documents>` (labelled as data; any `</documents>`,
   `<system>` and similar tags inside them are neutralised). Rules in the system prompt separate what the user said,
   their documents (cite [n]), general knowledge and LOKI's own suggestions.
5. **Citations**: after the reply, `[n]` markers are matched against the passages actually shown. Invented numbers
   never become citations. The source list (title, heading, page or line range, snippet, score, cited?) is saved
   with the message and shown as clickable chips. `[n]` markers are not spoken in voice replies.

Verified
- 105 backend tests pass on **both SQLite and Postgres**: extraction (Markdown, code, real PDF, HTML), chunking with
  overlap, unsafe-path and secret-file refusal, upload/update/delete lifecycle, privacy between users, failed-PDF
  reporting, grounded answers with citation validation, no injection for unrelated questions, prompt-injection
  neutralisation, temporary chats using documents.
- Live (real models, a Markdown design doc + Python module + 2-page PDF): indexed in about 1 s; 5 of 5 questions handled
  correctly. Answers came from the right file with the right location (Markdown section + lines, PDF page 2, the code's
  line range), and the off-topic poem used no documents. First token in 0.1–0.35 s.
- Browser: upload through the page (the `.env` was skipped), status badges, the search tester, inline citation
  chips with tooltips, the expandable Sources list, and citations still shown after a reload.

Found and fixed during live testing
- The reranker (prose-trained) scored a code passage 0.21, under the cut-off, so a "where is the login endpoint"
  question got no code. Fixed with definition-level code chunks, path + language labels for code passages, and
  the both-searches-agree rule.

Limits
- The 4B model sometimes cites a passage that only partly supports a sentence: the citation number is valid, but the claim is broader.
  Citations are checked for existence, not entailment.
- Scanned PDFs (images) aren't read (no OCR). DOCX isn't supported yet.
- The reranker is English-oriented; other languages still retrieve via embeddings and keywords, but rank less precisely.
- Ingestion runs inside the API process; a separate worker (and Redis queue) is planned with scheduled jobs in Phase 6.

## Phase 3 — memory (2026-11-22) ✅

How it works
- **Recall** (before each reply): embed the message (`qwen3-embedding:0.6b`, instruction-prefixed query) →
  nearest memories, ranked by similarity plus small importance and recency boosts → plus always-on core profile
  facts (importance ≥ 0.7) → plus dated events when the message says "yesterday", "last week", etc. "What do you
  remember about me" recalls broadly, and the reply is told to answer only from the notes. Memories go into the
  system prompt inside `<memory>`, labelled as data, not instructions.
- **Extraction** (after each reply, in the background): the model proposes add/update/delete operations as
  schema-constrained JSON, using the 10 most related existing memories (shown with short ids m1…m10). Then code-level guards
  check them, because a 4B model does not reliably follow the rules on its own:
  - secrets are redacted before the model sees the message, and rejected if they appear in a memory (regex + Luhn + entropy);
  - a memory's new facts must come from the user's own *statements*: not from questions, and never from LOKI's reply;
  - pure questions skip extraction entirely;
  - an "update" that is really a different fact, drops details the user never mentioned, or just appends a new fact
    to an old sentence is turned into a separate new memory. Nothing gets overwritten;
  - near-duplicates (cosine ≥ 0.92) are not stored twice; identical rewrites are ignored.
- **Working memory**: once a conversation exceeds about 75% of the context budget, older turns are summarised into
  `conversations.summary`; the last 6 turns stay verbatim.
- **Control**: Memory page (list, semantic search, add, edit, delete, delete all, on/off switch). Under each reply,
  "Used N memories" shows what was recalled and "Saved/Updated/Forgot" chips show what changed. Temporary chats
  neither read nor write memory; neither does a user who turned memory off.

Verified
- 83 backend tests pass, including the migrations and the exact failures seen in live runs as regression tests.
- Live with the real models: across a 6-message introduction, LOKI stored 4 correct memories (profile, project, preference,
  dated decision), skipped small talk ("I'm hungry") and the password, and correctly answered "what do you
  remember", "what stack does Tarka use" and "what did we decide today" in new conversations. Guards rejected or
  re-routed every bad operation the model proposed during those runs.
- Browser: Saved/Used chips, Memory page listing, semantic search ("which programming language does my habit app
  use" finds the Go/SQLite memories), editing, and secret rejection in the add form.

PostgreSQL + pgvector (Docker, `pgvector/pgvector:pg16`: PostgreSQL 16.16, pgvector 0.8.7)
- All 83 tests also pass on Postgres (`TEST_DATABASE_URL=…/loki_test`). The migrations create the HNSW cosine index.
- Existing development data was copied from SQLite with `backend/scripts/sqlite_to_postgres.py`. Row counts were identical for
  every table, and all 24 memories kept 1024-dim normalised vectors. `loki.db` is kept as a backup.
- The live memory check was repeated on Postgres: same correct memories, and all three recall questions answered correctly.
- Query plan: memory search filters by user first and sorts exactly (per-user sets are small). The HNSW index is
  there for when memory counts grow; pgvector 0.8's iterative scans make filtered ANN searches work then.
- Use `127.0.0.1` in `DATABASE_URL`: on this machine `localhost` tried IPv6 first and made every new connection
  about 5× slower (test suite 4 min 19 s vs 47 s).

Not done / limits
- The 4B model can still blend separate facts in its *answer* (it once said Tarka uses Docker; the memory says
  LOKI does) and embellish broad "what do you remember" answers. The stored memories stay correct.
- Contradictions phrased without naming the old value ("I moved to Bengaluru", when Chennai is stored) are saved
  as a second memory rather than replacing the first. That's safer than losing data, but needs manual tidying.
- Embedding changes need a migration + re-embed; no admin tool for that yet.

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
