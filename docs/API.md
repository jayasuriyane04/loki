# LOKI — API contracts

Base URL: `http://localhost:8000`. Interactive OpenAPI docs: `/docs`.
Authentication: `loki_session` httpOnly cookie (opaque token, SameSite=Lax) set by login/register.
All bodies are JSON. Errors use `{"detail": "<message>"}` with a proper status code.

## Auth — Phase 1 ✅
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/auth/register` | `{email, password (≥10 chars), display_name}` | `201 User` + cookie |
| POST | `/api/auth/login` | `{email, password}` | `200 User` + cookie. Rate limited: 10 / 5 min per IP+email |
| POST | `/api/auth/logout` | — | `204`, session revoked |
| GET | `/api/auth/me` | — | `200 User` · `401` |

`User = {id, email, display_name, created_at}`

## Conversations — Phase 1 ✅
| Method | Path | Notes |
|---|---|---|
| GET | `/api/conversations?limit=50&offset=0` | Non-temporary, newest first → `[ConversationSummary]` |
| POST | `/api/conversations` | `{title?, is_temporary?}` → `201 ConversationSummary` |
| GET | `/api/conversations/{id}` | → `ConversationDetail` (with messages) |
| PATCH | `/api/conversations/{id}` | `{title}` |
| DELETE | `/api/conversations/{id}` | `204`, cascades messages |

`ConversationSummary = {id, title, is_temporary, created_at, updated_at}`
`Message = {id, role, content, status, input_mode, provider, model, prompt_tokens, completion_tokens, latency_ms, first_token_ms, created_at}`

## System — Phase 1 ✅
| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Liveness + DB check |
| GET | `/api/models` | Configured primary/fallback with live health: `{primary: ProviderStatus, fallback: ProviderStatus \| null}` |

`ProviderStatus = {provider, model, ok, latency_ms, error}`

## WebSocket `/ws` — Phase 1 ✅
Authenticated by cookie; connections from origins not in `CORS_ORIGINS` are rejected.

Client → server
```jsonc
{"type": "user_message", "conversation_id": "uuid | null", "content": "text", "temporary": false, "input_mode": "text"}
{"type": "cancel"}                       // stop current generation (barge-in)
{"type": "ping"}
```

Server → client
```jsonc
{"type": "conversation", "conversation": ConversationSummary}       // sent when a new conversation is created
{"type": "message_saved", "message": Message}                         // the stored user message
{"type": "state", "state": "processing" | "thinking" | "idle"}         // drives the visualiser; "thinking" = model is reasoning privately
{"type": "assistant_start", "message_id": "uuid", "provider": "...", "model": "..."}
{"type": "token", "message_id": "uuid", "delta": "text"}
{"type": "assistant_end", "message": Message}                          // final stored message (status may be "interrupted")
{"type": "error", "code": "llm_unavailable" | "llm_stream_failed" | "empty_reply" | "bad_request" | "not_found" | "busy" | "internal", "message": "..."}
{"type": "pong"}
```
Only one generation runs per connection; a second `user_message` while busy returns `error/busy`.

## Voice — Phase 2 ✅

`GET /api/voice` → `{stt: {provider, model, state, error}, tts: {provider, state, error, voices[], default_voice, default_speed}}`.
`state` is `loading` (models load in the background after start-up), `ready`, `error` or `disabled`.

WebSocket additions. Audio is mono 16-bit little-endian PCM. A binary frame always directly follows its JSON header.

Client → server
```jsonc
{"type": "voice_config", "speak_replies": true, "speak_text_replies": false, "voice": "bm_george", "speed": 1.0}
{"type": "audio_utterance", "conversation_id": "uuid | null", "temporary": false, "sample_rate": 16000}
<binary: one finished utterance, 16 kHz, ≤ 60 s>
{"type": "cancel"}   // barge-in: also stops speech synthesis; the server finishes cancelling before reading the next frame
```

Server → client
```jsonc
{"type": "state", "state": "transcribing"}
{"type": "stt_final", "text": "...", "language": "en", "latency_ms": 296, "audio_s": 3.3}
{"type": "stt_command", "command": "stop"}            // utterance was just "stop" / "never mind": no turn is started
{"type": "tts_chunk", "message_id": "uuid", "seq": 0, "sample_rate": 24000, "duration_s": 2.1, "text": "spoken sentence"}
<binary: int16 PCM for that chunk>
{"type": "tts_end", "message_id": "uuid", "first_audio_ms": 1600}
{"type": "error", "code": "no_speech" | "stt_unavailable" | "stt_failed" | "tts_failed", "message": "..."}
```
After `stt_final`, a voice turn continues exactly like a typed one (`message_saved` with `input_mode: "voice"`, `assistant_start`, `token`…).

## Memory — Phase 3 ✅
| Method | Path | Notes |
|---|---|---|
| GET | `/api/memories?kind=&q=&limit=` | Newest first; with `q`, a semantic search (each result has `similarity`) |
| GET | `/api/memories/stats` | `{total, by_kind: {profile, semantic, episodic}}` |
| POST | `/api/memories` | `{content, kind, importance, project?}` → `201 Memory`. `422` if it contains a secret |
| PATCH | `/api/memories/{id}` | Any of `content, kind, importance, project`; content changes are re-embedded. `422` on secrets |
| DELETE | `/api/memories/{id}` | `204` |
| DELETE | `/api/memories?confirm=true` | Deletes all of the user's memories → `{deleted}`; `400` without `confirm=true` |
| GET / PATCH | `/api/settings` | `{memory_enabled}`. Off = no recall and no extraction |

`Memory = {id, kind, content, importance, project, source, source_conversation_id, event_at, created_at, updated_at, last_used_at, use_count, similarity}`.
Memories of other users are always `404`.

WebSocket events
```jsonc
{"type": "state", "state": "retrieving"}                                          // recalling memories
{"type": "memories_used", "conversation_id": "…", "memories": [{"id","kind","content"}]}  // sent before assistant_start
{"type": "memory_updated", "conversation_id": "…", "operations": [{"action": "add|update|delete", "id", "kind", "content"}]}
```
`memory_updated` arrives after the reply (extraction runs in the background) and only when something changed.

## Knowledge base — Phase 4 ✅
| Method | Path | Notes |
|---|---|---|
| POST | `/api/documents` | multipart: `files[]`, optional `paths[]` (relative path per file, for folders), `project`. → `[UploadResult]` with `status: queued \| unchanged \| rejected` and `reason`. Indexing happens in the background |
| GET | `/api/documents?project=` | `[Document]` with `status: pending \| processing \| ready \| failed`, `error`, `chunk_count`, `page_count` |
| GET | `/api/documents/{id}` | `Document` + `chunks[]` (content, heading_path, page, line_start/line_end) |
| DELETE | `/api/documents/{id}` | `204`; removes passages and the stored file |
| POST | `/api/documents/{id}/reindex` | re-queue indexing |
| GET | `/api/knowledge/search?q=&project=&limit=` | Exactly what chat retrieval returns: passages with `score`, `rerank`, `vector_rank`, `keyword_rank` |
| GET | `/api/knowledge/status` | counts by status, passage count, embedding model, reranker `{model, state, error}` |
| GET | `/api/projects` | project names used by documents and memories |

Documents of other users are always `404`. `assistant_end.message.citations` (also stored on the message):
`[{n, document_id, chunk_id, title, source, project, heading, page, line_start, line_end, score, snippet, cited}]`.

## Agent, tools and productivity — Phase 5 ✅
| Method | Path | Notes |
|---|---|---|
| GET/POST | `/api/tasks?status=open\|done\|all` | `{title, due_at (ISO with offset), priority, project, notes}` |
| PATCH/DELETE | `/api/tasks/{id}` | PATCH any field incl. `status` (sets/clears `completed_at`) |
| GET/POST | `/api/reminders?include_past=` | `{text, remind_at}`; past times are refused (`422`) |
| POST | `/api/reminders/{id}/cancel` · DELETE `/api/reminders/{id}` | |
| GET/POST | `/api/notes` · PATCH/DELETE `/api/notes/{id}` | notes are embedded for `search_notes` |
| GET/POST | `/api/events?start=&end=` · DELETE `/api/events/{id}` | |
| GET | `/api/notifications?unread=` | POST `/api/notifications/read` `{ids?}` (omit = all) |
| GET | `/api/tools` | every tool: `{name, description, category, permission, always_confirm, setting, parameters}` |
| PATCH | `/api/tools/{name}` | `{setting: auto\|confirm\|off}`; `422` when setting a confirm-required tool to `auto` |
| GET | `/api/tool-executions?limit=&tool=` | audit log `{tool, arguments, permission, status, approved, summary, error, duration_ms}` |

Naive datetimes are rejected (`422`); everything is stored in UTC. `assistant_end.message.tool_steps` holds the
steps of that reply: `[{id, tool, args, status, summary, approved, duration_ms, data}]`.

WebSocket additions
```jsonc
// client → server
{"type": "client_info", "timezone": "Asia/Kolkata"}                 // sent on connect
{"type": "approval", "approval_id": "call_…", "approved": true}     // answer to approval_required
// server → client
{"type": "state", "state": "executing"}
{"type": "tool_call", "id": "call_…", "tool": "create_task", "args": {…}}
{"type": "tool_result", "id": "call_…", "tool": "…", "status": "ok|error|denied|timeout|invalid|disabled",
 "summary": "Added task “…”", "approved": null, "duration_ms": 12, "data": {…}}
{"type": "approval_required", "approval_id": "call_…", "tool": "delete_task", "args": {…},
 "call": "Permanently delete task “buy groceries” (due Mon 23 Nov 09:00)", "description": "…", "always_confirm": true}
{"type": "approval_resolved", "approval_id": "call_…", "approved": false}   // also after 5 min timeout (= denied)
{"type": "notification", "notification": {"id", "kind": "reminder|agent|system", "title", "body", "created_at"}}
```

## Planned
- Phase 7: `/api/metrics`.
