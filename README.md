# LOKI

A voice-first, memory-backed, tool-using personal AI assistant, built in phases.

**Current status: Phases 1–2 done.** LOKI is a working text **and voice** assistant: accounts, persistent
conversations, streaming replies, hands-free voice with interruption (barge-in), all running locally:
Whisper speech recognition on the GPU, Kokoro speech synthesis, Ollama for the model.
Memory, documents and tools are **not built yet**. See [docs/ROADMAP.md](docs/ROADMAP.md).

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

Prerequisites: Python 3.12+, Node 20+, [Ollama](https://ollama.com).

LOKI's model server, in its own terminal (pins Ollama to the NVIDIA GPU on port 11435; keep it open):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-ollama.ps1
```
First time only, in another terminal, pull the model (2.5 GB):
```powershell
$env:OLLAMA_HOST="127.0.0.1:11435"; ollama pull qwen3:4b-instruct
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

**Talking to LOKI:** click the mic button next to Send. The top bar shows a red **Mic live** badge while the
microphone is on. Just speak; LOKI answers out loud, and you can interrupt it by talking (or say "stop").
Voice, speed and "read typed replies aloud" are in the **Voice** menu in the top bar. Use headphones so
LOKI doesn't hear itself.

## Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
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
