# LOKI

A voice-first, memory-backed, tool-using personal AI assistant, built in phases.

**Current status: Phases 1–3 done.** LOKI is a text **and voice** assistant with long-term memory: it learns
useful facts about you as you talk, recalls them in later conversations, and shows you exactly what it saved and
used. Everything runs locally: Whisper on the GPU, Kokoro speech, Ollama for the chat and embedding models,
PostgreSQL + pgvector in Docker. Documents and tools are **not built yet**. See [docs/ROADMAP.md](docs/ROADMAP.md).

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, the eight subsystems, trust boundaries, limitations, required credentials |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema (implemented and planned) |
| [docs/API.md](docs/API.md) | REST + WebSocket contracts |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phase plan and status |

## Stack
- **Backend**: Python 3.13, FastAPI, Pydantic, SQLAlchemy 2 (async), WebSockets, Argon2id
- **Frontend**: Next.js 16, React 19, TypeScript, Tailwind CSS 4, Framer Motion, Zustand
- **Models**: Ollama (local, default `qwen3:4b`) with optional Gemini fallback
- **Database**: SQLite in Phase 1 → PostgreSQL + pgvector from Phase 3

## Run locally (Windows / PowerShell)

Prerequisites: Python 3.12+, Node 20+, [Ollama](https://ollama.com), Docker Desktop.

Database, once (it restarts with Docker Desktop afterwards):
```powershell
docker compose up -d postgres
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

**Talking to LOKI:** click the mic button next to Send. The top bar shows a red **Mic live** badge while the
microphone is on. Just speak; LOKI answers out loud, and you can interrupt it by talking (or say "stop").
Voice, speed and "read typed replies aloud" are in the **Voice** menu in the top bar. Use headphones so
LOKI doesn't hear itself.

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
