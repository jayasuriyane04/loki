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

## Phase 3 — Memory ⏳
- **memories**: `id, user_id, kind (profile|episodic|semantic), content, importance (0–1),
  source_message_id, project_id null, valid_from, valid_to null, superseded_by null,
  embedding vector(N), created_at, updated_at`. HNSW index on embedding.
- **user_settings**: `user_id pk, memory_enabled, preferences jsonb`.

## Phase 4 — Knowledge base ⏳
- **documents**: `id, user_id, project_id null, title, source, file_type, sha256, size_bytes,
  status (pending|processing|ready|failed), error, uploaded_at, updated_at`.
- **chunks**: `id, document_id cascade, user_id, ordinal, content, heading_path, page,
  token_count, embedding vector(N), tsv tsvector (generated), created_at`.
  HNSW on embedding, GIN on tsv. Re-upload with a new sha256 deletes the old chunks in the same transaction.

## Phase 5 — Tools and tasks ⏳
- **tool_executions**: `id, user_id, conversation_id, tool_name, arguments jsonb, status,
  result jsonb, error, permission_level, approved_by_user, duration_ms, created_at`.
- **tasks**: `id, user_id, project_id null, title, notes, status, due_at, completed_at`.
- **reminders**: `id, user_id, text, remind_at, delivered_at, channel`.
- **notes**: `id, user_id, project_id null, title, body, embedding vector(N)`.

## Phase 6 — Personalisation and proactive ⏳
- **projects**: `id, user_id, name, summary, status`.
- **schedules**: `id, user_id, kind, cron, enabled, config jsonb, last_run_at`.
- **notifications**: `id, user_id, title, body, read_at, created_at`.

## Migrations
Phase 1 creates tables on startup (`create_all`). Alembic is introduced together with the move to
Postgres in Phase 3, starting from a baseline of the Phase 1 schema.
