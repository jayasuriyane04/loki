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

## Planned
- Phase 3: `/api/memories` (list, search, PATCH, DELETE), `/api/settings` (memory toggle).
- Phase 4: `/api/documents` (multipart upload, list, delete, reindex), citations on `assistant_end`.
- Phase 5: `/api/tools`, `/api/tool-executions`, `/api/tasks`, `/api/reminders`, WS `tool_call`, `tool_result`, `confirmation_required` / `confirm`.
- Phase 7: `/api/metrics`.
