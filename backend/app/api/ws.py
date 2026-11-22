import asyncio
import json
import logging
import time
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from app.api.deps import resolve_session
from app.core.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal
from app.schemas import WSAudioUtterance, WSControl, WSUserMessage, WSVoiceConfig
from app.services.chat import ChatService, TurnError
from app.voice.base import VoiceError
from app.voice.manager import Speaker, VoiceManager
from app.voice.speech_text import is_stop_command

router = APIRouter()
log = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    settings = get_settings()
    origin = ws.headers.get("origin")
    # Browsers always send Origin; reject cross-site pages (cookie-auth WebSocket CSRF).
    if origin is not None and origin not in settings.cors_origins:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with SessionLocal() as db:
        sess = await resolve_session(db, ws.cookies.get(settings.session_cookie_name))
        user_id = sess.user_id if sess else None
    if user_id is None:
        await ws.close(code=4401)
        return

    await ws.accept()
    service = ChatService(ws.app.state.llm, settings)
    voice: VoiceManager = ws.app.state.voice
    voice_cfg = WSVoiceConfig(type="voice_config", voice=settings.tts_voice, speed=settings.tts_speed)
    send_lock = asyncio.Lock()
    current: asyncio.Task[None] | None = None
    pending_audio: WSAudioUtterance | None = None
    max_audio_bytes = int(settings.stt_max_utterance_s * 16000 * 2)

    async def send(event: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_json(event)

    async def send_audio(header: dict[str, Any], pcm: bytes) -> None:
        # Header and its binary frame must stay adjacent on the wire.
        async with send_lock:
            await ws.send_json(header)
            await ws.send_bytes(pcm)

    async def transcribe(meta: WSAudioUtterance, pcm: bytes) -> WSUserMessage | None:
        await send({"type": "state", "state": "transcribing"})
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        try:
            tr = await voice.stt.transcribe(audio, meta.sample_rate)  # type: ignore[union-attr]
        except VoiceError as e:
            raise TurnError("stt_failed", str(e)) from e
        log.info("stt", extra={"audio_s": round(tr.duration_s, 2), "stt_ms": tr.latency_ms, "lang": tr.language, "chars": len(tr.text)})
        await send({"type": "stt_final", "text": tr.text, "language": tr.language, "latency_ms": tr.latency_ms, "audio_s": round(tr.duration_s, 2)})
        if not tr.text:
            await send({"type": "error", "code": "no_speech", "message": "I didn't catch that."})
            return None
        if is_stop_command(tr.text):
            # The client already stopped playback on barge-in; nothing to save or answer.
            await send({"type": "stt_command", "command": "stop"})
            return None
        return WSUserMessage(
            type="user_message", conversation_id=meta.conversation_id, content=tr.text,
            temporary=meta.temporary, input_mode="voice",
        )

    async def run(msg: WSUserMessage | None, audio: tuple[WSAudioUtterance, bytes] | None = None) -> None:
        started = time.perf_counter()
        speaker: Speaker | None = None
        try:
            if audio is not None:
                msg = await transcribe(*audio)
                if msg is None:
                    return
            assert msg is not None
            wants_speech = voice_cfg.speak_replies if msg.input_mode == "voice" else voice_cfg.speak_text_replies
            if wants_speech and voice.tts_ready and voice.tts is not None:
                speaker = Speaker(
                    voice.tts, voice=voice_cfg.voice or settings.tts_voice, speed=voice_cfg.speed,
                    send=send, send_audio=send_audio, turn_started=started,
                )
            async with SessionLocal() as db:
                user = await db.get(User, user_id)
                if user is None or not user.is_active:
                    await send({"type": "error", "code": "unauthorized", "message": "Session no longer valid."})
                    return
                await service.run_turn(db, user, msg, send, on_delta=speaker.feed if speaker else None)
            if speaker:
                await speaker.finish()
        except TurnError as e:
            await _safe(send, {"type": "error", "code": e.code, "message": e.message})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("turn failed")
            await _safe(send, {"type": "error", "code": "internal", "message": "Something went wrong on LOKI's side."})
        finally:
            if speaker:
                await speaker.close()
            await _safe(send, {"type": "state", "state": "idle"})

    async def stop_current() -> None:
        if current and not current.done():
            current.cancel()
            await asyncio.gather(current, return_exceptions=True)

    def busy() -> bool:
        return current is not None and not current.done()

    try:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                break

            if frame.get("bytes") is not None:
                data = frame["bytes"]
                meta, pending_audio = pending_audio, None
                if meta is None:
                    await send({"type": "error", "code": "bad_request", "message": "Audio frame without audio_utterance header."})
                elif not voice.stt_ready:
                    await send({"type": "error", "code": "stt_unavailable", "message": _stt_unavailable(voice)})
                elif len(data) == 0 or len(data) % 2 or len(data) > max_audio_bytes:
                    await send({"type": "error", "code": "bad_request", "message": "Audio must be 16-bit PCM and at most "
                                f"{settings.stt_max_utterance_s:.0f} s long."})
                elif busy():
                    await send({"type": "error", "code": "busy", "message": "LOKI is still responding."})
                else:
                    current = asyncio.create_task(run(None, (meta, data)))
                continue

            try:
                data = json.loads(frame.get("text") or "")
                kind = data.get("type") if isinstance(data, dict) else None
                if kind == "user_message":
                    msg = WSUserMessage.model_validate(data)
                    if busy():
                        await send({"type": "error", "code": "busy", "message": "LOKI is still responding."})
                        continue
                    current = asyncio.create_task(run(msg))
                elif kind == "audio_utterance":
                    pending_audio = WSAudioUtterance.model_validate(data)
                elif kind == "voice_config":
                    voice_cfg = WSVoiceConfig.model_validate(data)
                    if voice_cfg.voice and voice.tts_ready and voice.tts and voice_cfg.voice not in voice.tts.voices():
                        voice_cfg.voice = settings.tts_voice
                else:
                    ctl = WSControl.model_validate(data)
                    if ctl.type == "ping":
                        await send({"type": "pong"})
                    elif ctl.type == "cancel":
                        # Await the cancelled turn so an utterance sent right after a barge-in isn't rejected as busy.
                        await stop_current()
            except (json.JSONDecodeError, ValidationError) as e:
                detail = e.errors()[0]["msg"] if isinstance(e, ValidationError) else "Invalid JSON"
                await send({"type": "error", "code": "bad_request", "message": detail})
    except WebSocketDisconnect:
        pass
    finally:
        await stop_current()


def _stt_unavailable(voice: VoiceManager) -> str:
    st = voice.stt_status
    if st.state == "loading":
        return "Speech recognition is still starting up."
    if st.state == "error":
        return f"Speech recognition failed to load: {st.error}"
    return "Speech recognition is turned off."


async def _safe(send: Any, event: dict[str, Any]) -> None:
    try:
        await send(event)
    except Exception:
        pass
