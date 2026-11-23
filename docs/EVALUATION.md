# LOKI — Evaluation and observability

Two complementary views of quality:

- **Live metrics.** Every chat and voice turn is traced (timings and counts only, never content). The **Analytics**
  page shows them for the last 24 h, 7 days or 30 days.
- **Offline evaluations.** Fixed test sets run against the real models in a separate database. They give numbers
  you can compare across changes. Reports are saved in `backend/eval/results/` and also appear on the Analytics page.

## Running the evaluations

Needs LOKI's Ollama (`scripts/start-ollama.ps1`) and Postgres (`docker compose up -d postgres`).

```powershell
cd backend
.\.venv\Scripts\python.exe -m eval.run rag --answers   # retrieval benchmark + answer quality (≈2 min)
.\.venv\Scripts\python.exe -m eval.run agent --repeat 3 # 14 scenarios × 3 runs (≈3 min)
.\.venv\Scripts\python.exe -m eval.run voice            # recognition, latency, barge-in (≈1 min)
```

- Each run wipes and uses the `loki_eval` database; change it with `EVAL_DATABASE_URL`, which must end in `_eval`.
- Your own data is never read or written.
- Eval traffic is not recorded as usage.

## What is measured, and how

### Knowledge retrieval (`eval/datasets/rag/`)

- **Corpus:** a fictional project, "Meridian", with 7 files: a handbook, a deploy guide, an HTML API reference,
  Python and TypeScript code, meeting notes and a PDF security policy. It is indexed by LOKI's real ingestion
  pipeline (20 chunks).
- **38 queries:**
  - factual (23)
  - paraphrased with no shared keywords (6)
  - code (2)
  - PDF (2)
  - conversational, with the question buried in filler (2)
  - not answerable from the documents (3)
- **Labels are evidence phrases, not chunk ids.** A passage counts as relevant if it contains one, so the benchmark
  survives changes to chunking.
- **Metrics:** Precision@K, Recall@K (the evidence is in the top K), NDCG@5 and MRR, for five search modes: vector
  only, keyword only, hybrid (reciprocal-rank fusion), hybrid + reranker, and production (what chat uses).
- **With `--answers`,** each question is asked in a temporary chat with the real model, and the reply is scored on:
  - **answer correct**: the expected facts appear in the reply
  - **citation precision**: cited passages are relevant
  - **citation validity**: `[n]` markers point at passages that were shown
  - **context relevance**: passages shown to the model are relevant
  - **faithfulness**: an LLM judge checks every claim against the passages
  - **abstention**: unanswerable questions get "the documents don't cover this"

### Agent (`eval/datasets/agent_scenarios.py`)

- **14 scenarios:**
  - creating tasks, reminders, notes and events with natural-language dates
  - listing and completing tasks
  - deletion with approval given and refused
  - questions that need no tool
  - a document question
  - a multi-step request
  - two recovery scenarios, where the tool's first call fails with a temporary error
- **Pass = the resulting state is right,** checked through the API (the task exists with tomorrow 09:00 in the
  user's timezone). The wording of the reply doesn't decide it.
- **Metrics:**
  - task completion
  - tool selection accuracy (the required tools succeeded and nothing outside the expected or allowed set was
    called)
  - tool execution success
  - failure recovery
  - unnecessary calls
  - latency

### Voice (`eval/voice.py`)

- **Recognition:** 10 phrases × 2 voices are synthesised with Kokoro, then transcribed by Whisper. Reported as
  word error rate (normalised for "ten"/"10" and British/American spelling; the raw figure is reported too) and
  recognition latency.
- **End to end:** 5 spoken questions over the WebSocket, exactly as the browser sends them: time to transcript,
  first word, first audio and done.
- **Barge-in:** a long spoken answer is interrupted as soon as audio starts, and the time until LOKI is silent is
  measured.
- **Limitation:** the speech is synthetic and clean, so WER is a lower bound. Real rooms and microphones are
  covered by [USER_TESTING.md](USER_TESTING.md).

## Current results (2026-11-22, RTX 5060 laptop, qwen3:4b-instruct)

### Retrieval

| Search mode | Recall@5 | P@1 | NDCG@5 | MRR | p50 latency |
|---|---|---|---|---|---|
| Vector only | 1.000 | 0.800 | 0.917 | 0.888 | 38 ms |
| Keyword only | 0.971 | 0.714 | 0.855 | 0.822 | 40 ms |
| Hybrid (RRF) | 1.000 | 0.857 | 0.934 | 0.915 | 38 ms |
| Hybrid + reranker | 0.971 | 0.971 | 0.945 | 0.971 | 587 ms |
| **Production** | **0.971** | **0.971** | **0.945** | **0.971** | **597 ms** |

- The reranker lifts top-1 precision from 0.86 to 0.97.
- The one miss ("How quickly do I have to respond when I get paged?") is found by search, but the reranker scores
  it under the threshold. A threshold of 0.10 recovers it, but every unanswerable question then gets passages and
  prompts carry about 50% more passages, so the threshold stays at 0.25.
- Precision@5 is 0.20 by construction: most queries have exactly one relevant passage in a 20-chunk corpus.

### Answers

| Metric | Result |
|---|---|
| Answer correct | 0.971 |
| Citation precision | 0.939 |
| Citation validity | 0.971 |
| Context relevance | 0.714 |
| Faithfulness (judge) | 0.912 |
| Declined unanswerable questions | 3/3 |
| p50 first word / total | 2.06 s / 2.93 s |

- The judge is the same 4B model, and it is noisy: it flagged "Invoices are kept for 7 years" as unsupported next
  to a passage stating exactly that. Treat faithfulness as a lower bound.

### Agent

42 runs (14 scenarios × 3):

| Metric | Result |
|---|---|
| Task completion | 1.000 |
| Tool selection | 1.000 |
| Failure recovery | 1.000 |
| Unnecessary calls | 0 |
| Tool execution success | 0.882 (the failures are the injected ones) |
| p50 / p95 turn | 2.6 s / 4.3 s |

### Voice

| Metric | Result |
|---|---|
| WER (normalised) | 0.000 (20/20 exact) |
| WER (raw) | 0.025 |
| Recognition p50 / p95 | 188 / 213 ms |
| First audio p50 / p95 | 1.48 / 3.39 s |
| Turn total p50 | 2.22 s |
| Barge-in stop p50 | 15 ms |
| Errors | 0 |

## Findings the evaluations led to (fixed in Phase 7)

| Finding | Fix | Effect |
|---|---|---|
| Reranking took 1.1 s per query on CPU | Passages are batched by length (each batch is padded to its longest member) | ~600 ms, identical scores |
| "I called the bank, mark that task as done" failed 3/3: the model said "I don't have access to your task list" and asked for an id, even after being told it has the tools | "mark … done" counts as a request for `complete_task`. When the model falsely says it can't see the user's data, the read-only list tool is called on its behalf (a real, audited step shown to the user) | 0/3 → 3/3; agent suite 0.929 → 1.000 |
| The model writes ’ (curly apostrophe), which slipped past the check | Apostrophes are normalised before guards run | — |

## Live metrics (Analytics page)

| Area | Metrics |
|---|---|
| Responses | turns, errors, time to first word and full reply (p50/p95), tokens in/out, model cost (from `MODEL_PRICES`; local models cost $0), cloud fallbacks |
| Voice | recognition latency, time to first audio, voice turn total, recognition errors and rate, no-speech, interruptions and spoken "stop", synthesis failures |
| Knowledge & memory | document search latency, turns using documents, citation validity (invented `[n]` markers), passages cited/shown, memory recall latency, extraction latency/errors |
| Agent | tool calls, success rate, declined by you, failure recovery (a failed call followed by a successful one in the same turn), safety-net interventions (retries, corrections, repetition stops, false "no access"), per-tool calls/success/p50 |
| System | API requests and p50/p95, slowest endpoints, server errors, logged errors with recent messages, open sessions now/peak, your 👍/👎 ratings |
| Traces | the last 25 turns, each with a waterfall: memory recall, retrieval, model, each tool call, guard events |

Retention is 30 days (`METRICS_RETENTION_DAYS`). `METRICS_ENABLED=false` turns recording off.

Langfuse was considered and not used: self-hosting it needs ClickHouse, Redis and MinIO (2–4 GB of RAM), and Langfuse
Cloud would receive prompts and replies. Traces live in LOKI's own Postgres, and the data model (traces with spans)
maps onto OpenTelemetry/Langfuse if an export is wanted later.
