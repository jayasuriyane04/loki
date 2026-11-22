# LOKI — Database schema

Target: PostgreSQL 16 + pgvector. Phase 1 runs the same SQLAlchemy models on SQLite for local
development; nothing in Phase 1 uses Postgres-only features. All ids are UUIDs, all timestamps
are UTC. Every user-owned table has `user_id` and every query filters on it.

Legend: ✅ implemented · ⏳ planned (phase).

## Phase 1 ✅

### users
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| email | varchar(320) unique | lower-cased |
| display_name | varchar(100) | |
| password_hash | varchar(255) | Argon2id |
| is_active | bool | |
| created_at, updated_at | timestamptz | |

### sessions
Server-side sessions so logout / revoke actually work (cookie holds an opaque token; only its SHA-256 is stored).
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| user_id | uuid fk → users, cascade | |
| token_hash | char(64) unique | sha256 of cookie token |
| user_agent | varchar(255) | |
| created_at, expires_at, last_seen_at | timestamptz | |
| revoked_at | timestamptz null | |

### conversations
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| user_id | uuid fk → users, cascade | indexed |
| title | varchar(200) | |
| is_temporary | bool | temporary chats are excluded from memory extraction (Phase 3) and hidden from history |
| created_at, updated_at | timestamptz | `updated_at` indexed for history ordering |

### messages
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| conversation_id | uuid fk → conversations, cascade | indexed |
| role | varchar(16) | `user` · `assistant` · `system` · `tool` |
| content | text | |
| status | varchar(16) | `complete` · `interrupted` · `error` |
| input_mode | varchar(8) | `text` · `voice` |
| provider, model | varchar | which LLM answered (assistant rows) |
| prompt_tokens, completion_tokens | int null | |
| latency_ms, first_token_ms | int null | total and time-to-first-token |
| created_at | timestamptz | |

## Phase 3 — Memory ✅ (migration `0002`)

### memories
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| user_id | uuid fk → users, cascade | indexed; every query filters on it |
| kind | varchar(16) | `profile` (about the user) · `semantic` (projects/facts) · `episodic` (dated events/decisions) |
| content | text | one standalone third-person sentence, ≤ 400 chars, secret-free |
| importance | float 0–1 | ≥ 0.7 profile memories are always in context |
| project | varchar(100) null | project tag, e.g. "Tarka" |
| source | varchar(24) | `extracted` · `user_edited` |
| source_conversation_id | uuid fk → conversations, SET NULL | where it was learned |
| event_at | timestamptz null | when an episodic event happened (time-aware recall) |
| created_at, updated_at, last_used_at | timestamptz | |
| use_count | int | times recalled into a reply |
| embedding | vector(1024) | `qwen3-embedding:0.6b`, L2-normalised. **HNSW** index (`vector_cosine_ops`) on Postgres |
| embedding_model | varchar(100) | which model produced the vector (needed to re-embed after a model change) |

### user_settings
`user_id pk/fk cascade, memory_enabled bool, updated_at`. Missing row = memory on.

### conversations (added columns)
`summary text null`, `summary_until timestamptz null`: working-memory compression. Turns at or before
`summary_until` are represented by `summary` instead of being sent verbatim.

On SQLite (dev/tests) the vector is stored as text and similarity is computed in Python; on Postgres it is
computed in SQL with pgvector (`<=>` cosine distance).

## Phase 4 — Knowledge base ✅ (migration `0003`)

### documents
`id, user_id (cascade), project ("" = none), title, source (relative path), file_type (pdf|markdown|text|html|code),
language, sha256, size_bytes, status (pending|processing|ready|failed), error, chunk_count, page_count,
storage_path, created_at, updated_at, indexed_at`. Unique `(user_id, project, source)`, so re-uploading the same
path updates the document. The original file is kept under `UPLOAD_DIR/<user_id>/<document_id>.bin` (for re-indexing),
and deleted with the document.

### chunks
`id, document_id (cascade), user_id (cascade, indexed), ordinal, content, heading_path, page, line_start,
line_end, embedding vector(1024)`. On Postgres also
`tsv tsvector GENERATED ALWAYS AS (setweight(to_tsvector('english', heading_path), 'A') || setweight(to_tsvector('english', content), 'B')) STORED`
with a **GIN** index, and an **HNSW** cosine index on `embedding`. Re-indexing replaces a document's chunks in one
transaction.

### messages (added column)
`citations json null`: the passages shown to the model for that reply, each with `cited` true/false.

## Phase 5 — Agent, tools, productivity ✅ (migration `0004`)
All user-owned (`user_id` cascade, indexed); every row records `created_by` = `user` or `loki`.
- **tasks**: `title, notes, project, priority (low|normal|high), status (open|done), due_at, completed_at, created_at, updated_at`.
- **reminders**: `text, remind_at (indexed), status (scheduled|delivered|cancelled), delivered_at, created_at`.
- **notes**: `title, body (Markdown), project, embedding vector(1024), created_at, updated_at`.
- **events**: `title, starts_at (indexed), ends_at, location, notes, created_at` (LOKI's own calendar).
- **notifications**: `kind (reminder|agent|system), title, body, read_at, created_at (indexed)`.
- **tool_executions** (audit log): `conversation_id (SET NULL), tool, arguments json, permission (read|reversible|confirm),
  status (ok|error|denied|timeout|invalid|disabled), approved (null = no approval needed), summary, result
  (truncated, success only), error, duration_ms, created_at`.
- **user_settings** + `timezone` (IANA, from the browser), `tool_prefs json` (`{tool: "confirm"|"off"}`).
- **messages** + `tool_steps json`: the tool calls behind a reply (replayed into later context).

## Phase 6 — Personalisation and proactive ⏳
- **projects**: `id, user_id, name, summary, status`.
- **schedules**: `id, user_id, kind, cron, enabled, config jsonb, last_run_at`.
- **notifications**: `id, user_id, title, body, read_at, created_at`.

## Migrations
Alembic, in `backend/migrations/` (`0001` = Phase 1 baseline, `0002` = memory, `0003` = knowledge base, `0004` = agent and tools). They run automatically
at start-up (`AUTO_MIGRATE=true`) or manually:
```powershell
cd backend; .\.venv\Scripts\python.exe -m alembic upgrade head
```
A database created by Phase 1's `create_all` (no `alembic_version` table) is stamped `0001` first, so
existing data is kept. Changing `EMBEDDING_DIM` requires a new migration and re-embedding all memories.
