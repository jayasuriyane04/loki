import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import Settings
from app.voice.base import STTProvider, TTSProvider, VoiceError
from app.voice.speech_text import SentenceChunker

log = logging.getLogger(__name__)

State = Literal["disabled", "loading", "ready", "error"]


@dataclass
class ComponentStatus:
    state: State = "disabled"
    error: str | None = None


class VoiceManager:
    """Owns the STT/TTS providers and their background loading."""

    def __init__(self, stt: STTProvider | None, tts: TTSProvider | None, settings: Settings) -> None:
        self.stt = stt
        self.tts = tts
        self.settings = settings
        self.stt_status = ComponentStatus("loading" if stt else "disabled")
        self.tts_status = ComponentStatus("loading" if tts else "disabled")
        self._tasks: list[asyncio.Task[None]] = []

    @classmethod
    def from_settings(cls, s: Settings) -> "VoiceManager":
        stt = tts = None
        if s.voice_enabled:
            from app.voice.whisper_stt import FasterWhisperSTT

            device = s.stt_device
            stt = FasterWhisperSTT(s.stt_model, device=device, compute_type=s.stt_compute_type, language=s.stt_language)
            if s.tts_provider == "kokoro":
                from app.voice.kokoro_tts import KokoroTTS

                tts = KokoroTTS(s.tts_model_dir)
        return cls(stt, tts, s)

    def start(self) -> None:
        async def load(provider: Any, status: ComponentStatus, label: str) -> None:
            try:
                await provider.load()
                status.state, status.error = "ready", None
            except Exception as e:  # noqa: BLE001 - surface any load failure as status, never crash the app
                status.state, status.error = "error", str(e)[:300]
                log.error(f"{label} failed to load", extra={"error": str(e)[:300]})

        if self.stt:
            self._tasks.append(asyncio.create_task(load(self.stt, self.stt_status, "stt")))
        if self.tts:
            self._tasks.append(asyncio.create_task(load(self.tts, self.tts_status, "tts")))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    @property
    def stt_ready(self) -> bool:
        return self.stt is not None and self.stt_status.state == "ready"

    @property
    def tts_ready(self) -> bool:
        return self.tts is not None and self.tts_status.state == "ready"

    def describe(self) -> dict[str, Any]:
        return {
            "stt": {
                "provider": self.stt.name if self.stt else None,
                "model": self.stt.model if self.stt else None,
                "state": self.stt_status.state,
                "error": self.stt_status.error,
            },
            "tts": {
                "provider": self.tts.name if self.tts else None,
                "state": self.tts_status.state,
                "error": self.tts_status.error,
                "voices": self.tts.voices() if self.tts and self.tts_ready else [],
                "default_voice": self.settings.tts_voice,
                "default_speed": self.settings.tts_speed,
            },
        }


SendJson = Callable[[dict[str, Any]], Awaitable[None]]
SendAudio = Callable[[dict[str, Any], bytes], Awaitable[None]]


class Speaker:
    """Speaks one assistant reply: sentences are synthesised in order while the LLM is still streaming."""

    def __init__(
        self,
        tts: TTSProvider,
        *,
        voice: str,
        speed: float,
        send: SendJson,
        send_audio: SendAudio,
        turn_started: float,
    ) -> None:
        self.tts = tts
        self.voice = voice
        self.speed = speed
        self.send = send
        self.send_audio = send_audio
        self.turn_started = turn_started
        self.first_audio_ms: int | None = None
        self._chunker = SentenceChunker()
        self._queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()
        self._message_id: str | None = None
        self._worker = asyncio.create_task(self._run())
        self._failed = False
        self.chunks = 0

    @property
    def failed(self) -> bool:
        return self._failed

    def feed(self, message_id: str, delta: str) -> None:
        self._message_id = message_id
        for sentence in self._chunker.feed(delta):
            self._queue.put_nowait((message_id, sentence))

    async def finish(self) -> None:
        if self._message_id:
            for sentence in self._chunker.flush():
                self._queue.put_nowait((self._message_id, sentence))
        self._queue.put_nowait(None)
        await self._worker
        if self._message_id:
            await self.send({"type": "tts_end", "message_id": self._message_id, "first_audio_ms": self.first_audio_ms})

    async def close(self) -> None:
        if not self._worker.done():
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)

    async def _run(self) -> None:
        seq = 0
        while (item := await self._queue.get()) is not None:
            message_id, text = item
            if self._failed:
                continue
            try:
                audio = await self.tts.synthesize(text, voice=self.voice, speed=self.speed)
            except VoiceError as e:
                self._failed = True
                await self.send({"type": "error", "code": "tts_failed", "message": str(e)})
                continue
            except Exception:
                self._failed = True
                log.exception("tts synthesis failed")
                await self.send({"type": "error", "code": "tts_failed", "message": "Speech synthesis failed."})
                continue
            if self.first_audio_ms is None:
                self.first_audio_ms = int((time.perf_counter() - self.turn_started) * 1000)
                log.info("first audio", extra={"first_audio_ms": self.first_audio_ms, "tts_ms": audio.latency_ms})
            await self.send_audio(
                {
                    "type": "tts_chunk",
                    "message_id": message_id,
                    "seq": seq,
                    "sample_rate": audio.sample_rate,
                    "duration_s": round(audio.duration_s, 3),
                    "text": text,
                },
                audio.pcm16,
            )
            seq += 1
            self.chunks = seq


__all__ = ["VoiceManager", "Speaker", "VoiceError"]
