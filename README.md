# LOKI

A voice-first, memory-backed, tool-using personal AI assistant, built in phases.

**Current status: all seven phases done.** LOKI is a text **and voice** assistant with long-term memory, a personal
knowledge base with cited answers, and an agent that uses tools. It can search the web and read pages, check the
weather, manage tasks, reminders, notes and a calendar, search your files and code, and run approved dev commands and
apps. Anything destructive asks you first. Everything runs locally: Whisper on the GPU, Kokoro speech, Ollama for the
chat and embedding models, an ONNX reranker, PostgreSQL + pgvector and SearXNG in Docker. Phase 6 adds settings
(reply style, your own instructions, voice on the account), projects LOKI recognises in conversation, dated
conversation summaries, and opt-in background features: deadline and event alerts, a daily briefing, quiet hours and
watched project folders. Phase 7 adds an Analytics page (live traces and metrics), offline evaluation suites for
retrieval, the agent and voice, and a Docker deployment. See [docs/ROADMAP.md](docs/ROADMAP.md).

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, the eight subsystems, trust boundaries, limitations, required credentials |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema (implemented and planned) |
| [docs/API.md](docs/API.md) | REST + WebSocket contracts |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phase plan and status |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Evaluation suites, current results, live metrics |
| [docs/USER_TESTING.md](docs/USER_TESTING.md) | Real-user testing protocol |

## Stack
- **Backend**: Python 3.13, FastAPI, Pydantic, SQLAlchemy 2 (async), WebSockets, Argon2id
- **Frontend**: Next.js 16, React 19, TypeScript, Tailwind CSS 4, Framer Motion, Zustand
- **Models**: Ollama (local, default `qwen3:4b`) with optional Gemini fallback
- **Database**: SQLite in Phase 1 → PostgreSQL + pgvector from Phase 3

## Run locally (Windows / PowerShell)

Prerequisites: Python 3.12+, Node 20+, [Ollama](https://ollama.com), Docker Desktop.

Database and web search, once (they restart with Docker Desktop afterwards):
```powershell
docker compose up -d postgres searxng
```

LOKI's model server, in its own terminal (pins Ollama to the NVIDIA GPU on port 11435; keep it open):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-ollama.ps1
```
First time only, in another terminal, pull the chat model (2.5 GB) and the memory embedding model (640 MB):
```powershell
$env:OLLAMA_HOST="127.0.0.1:11435"; ollama pull qwen3:4b-instruct; ollama pull qwen3-embedding:0.6b
```

Backend, in one terminal:
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Voice model files (one-time, about 350 MB, run from the LOKI folder). Whisper's `small` model (about 480 MB) downloads automatically on first start:
```powershell
New-Item -ItemType Directory -Force backend\models\kokoro
```
```powershell
curl.exe -L -o backend\models\kokoro\kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
```
```powershell
curl.exe -L -o backend\models\kokoro\voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```
Document reranker (one-time, about 280 MB; without it, search still works but ranks less precisely):
```powershell
$d="backend\models\reranker\mxbai-rerank-xsmall-v1"; New-Item -ItemType Directory -Force "$d\onnx" | Out-Null; foreach ($f in "tokenizer.json","onnx/model.onnx") { curl.exe -L -o "$d\$f" "https://huggingface.co/mixedbread-ai/mxbai-rerank-xsmall-v1/resolve/main/$f" }
```
No NVIDIA GPU? Set `STT_DEVICE=cpu` and `STT_COMPUTE_TYPE=int8` in `backend/.env`. To run without voice, set `VOICE_ENABLED=false`.

Frontend, in a second terminal:
```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Open http://localhost:3000 and create an account. API docs: http://localhost:8000/docs.

**Memory:** LOKI saves useful facts you mention ("Saved: …" appears under its reply) and shows which
memories it used for each answer. Open **Memory** in the side panel to search, edit, delete or switch memory
off. Temporary chats never read or write memory. Passwords and other secrets are never stored.

**Documents:** open **Knowledge base** in the side panel and add files or a whole project folder (optionally tagged
with a project). When an answer uses them, it cites passages as numbered chips. Click one to see the exact text,
page or lines. The search box there shows exactly which passages LOKI would use for a question.

**Getting things done:** just ask ("remind me tomorrow at 10 to submit the application", "add renew passport for
Friday", "do I need an umbrella in Chennai?", "research X, save a summary as a note and notify me"). Each tool LOKI
uses appears as a step above its answer. Deleting things, running commands and opening websites show an
**approval card** first. **Planner** (side panel) lists tasks, reminders, events and notes. **Tools** lets you set each
tool to automatic, "ask me first" or off, and shows the activity log. Allowed commands, apps and workflows are in
`backend/config/automation.json`.

**Talking to LOKI:** click the mic button next to Send. The top bar shows a red **Mic live** badge while the
microphone is on. Just speak; LOKI answers out loud, and you can interrupt it by talking (or say "stop").
Voice, speed and "read typed replies aloud" are in the **Voice** menu in the top bar. Use headphones so
LOKI doesn't hear itself.

## Run in Docker (Phase 7)

Everything except Ollama in containers: backend on http://localhost:8100, UI on http://localhost:3100. Ollama stays on
the host (start it with `scripts\start-ollama.ps1`). The backend container uses the NVIDIA GPU for speech recognition
and the model files you already downloaded (`backend/models`, and Whisper from your Hugging Face cache).
```powershell
docker compose --profile app up -d --build
```
**One click:** `scripts\install-shortcuts.ps1` puts **LOKI** and **Stop LOKI** on your desktop.
- **LOKI** starts the model server, Docker Desktop if needed, and the containers, then opens LOKI in the browser:
  about 30 s from cold, 16 s when Docker is already running, 4 s when LOKI is already up.
- **Stop LOKI** stops the app containers and the model server, which frees the GPU. The database keeps running.
- Logs are in `%LOCALAPPDATA%\LOKI\logs`.
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-shortcuts.ps1
```
- Uses the same database as running from source. Run one backend at a time: stop the source backend first, or
  reminders can be delivered twice.
- In the container, the desktop tools (run a command, open an app or website, workflows) are switched off
  (`DESKTOP_TOOLS=false`), because they would act inside the container rather than on your PC.
- Documents uploaded from source are stored under `backend/data/uploads`. The container keeps uploads in its own
  volume: search works for everything already indexed, but re-indexing an older document needs a fresh upload.
- The browser talks to the backend directly. To serve LOKI from another host, rebuild the frontend with
  `--build-arg NEXT_PUBLIC_API_URL=https://your-host`, and set `CORS_ORIGINS` and `COOKIE_SECURE=true` (HTTPS).
- Stop with `docker compose --profile app down` (your data stays in the `pgdata` volume).

## Evaluations and analytics
Open **Analytics** in the side panel for live latency, tokens, tool success, citation validity, errors and per-turn
traces. Offline benchmarks with the real models (separate `loki_eval` database):
```powershell
cd backend; .\.venv\Scripts\python.exe -m eval.run rag --answers
```
```powershell
cd backend; .\.venv\Scripts\python.exe -m eval.run agent --repeat 3
```
```powershell
cd backend; .\.venv\Scripts\python.exe -m eval.run voice
```
Methods and current results: [docs/EVALUATION.md](docs/EVALUATION.md).

## Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```
The default run uses a throwaway SQLite file. To run the same suite on Postgres + pgvector, first create the test database once:
```powershell
docker compose exec -T postgres psql -U loki -d loki -c "create database loki_test;"
```
```powershell
cd backend; $env:TEST_DATABASE_URL="postgresql+asyncpg://loki:loki@127.0.0.1:5432/loki_test"; .\.venv\Scripts\python.exe -m pytest -q
```
```powershell
cd frontend
npx tsc --noEmit
npx eslint src
npm run build
```

## Configuration
All settings are environment variables. See [backend/.env.example](backend/.env.example) and
[frontend/.env.example](frontend/.env.example). No keys are hard-coded, and `.env` files are git-ignored.

Changing models needs no code change, e.g. a cloud fallback:
```
LLM_FALLBACK_PROVIDER=gemini
LLM_FALLBACK_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...
```

## Performance note (this machine)
A plain `ollama serve` on this laptop picks the **AMD Radeon 880M** integrated GPU (23 tokens/s) instead of the
RTX 5060 (83–94 tokens/s), because the integrated GPU reports more memory. That's why LOKI uses
`scripts\start-ollama.ps1`. With it and `qwen3:4b-instruct`, LOKI starts speaking about 1.6–1.9 s after you stop
talking. Thinking models such as `qwen3:4b` still work, but they reason before every answer (seconds to a minute).
