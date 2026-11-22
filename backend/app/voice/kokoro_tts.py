import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from app.voice.base import SpeechAudio, TTSProvider, VoiceError

log = logging.getLogger(__name__)

MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"
RELEASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0"


class KokoroTTS(TTSProvider):
    name = "kokoro"

    def __init__(self, model_dir: str) -> None:
        self.model_dir = Path(model_dir)
        self._kokoro = None
        self._voices: list[str] = []
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")

    def _load_sync(self) -> None:
        model, voices = self.model_dir / MODEL_FILE, self.model_dir / VOICES_FILE
        if not model.exists() or not voices.exists():
            raise VoiceError(f"Kokoro model files missing in {self.model_dir}. Download {MODEL_FILE} and {VOICES_FILE} from {RELEASE_URL}")
        from kokoro_onnx import Kokoro

        start = time.perf_counter()
        self._kokoro = Kokoro(str(model), str(voices))
        self._voices = sorted(self._kokoro.get_voices())
        self._kokoro.create("Ready.", voice=self._voices[0])  # warm-up
        log.info("tts ready", extra={"voices": len(self._voices), "s": round(time.perf_counter() - start, 1)})

    async def load(self) -> None:
        await asyncio.get_running_loop().run_in_executor(self._pool, self._load_sync)

    def voices(self) -> list[str]:
        return self._voices

    def _lang_for(self, voice: str) -> str:
        # Kokoro voice ids: first letter = language (a = American, b = British English, ...)
        return {"a": "en-us", "b": "en-gb"}.get(voice[:1], "en-us")

    def _synth_sync(self, text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
        assert self._kokoro is not None
        return self._kokoro.create(text, voice=voice, speed=speed, lang=self._lang_for(voice))

    async def synthesize(self, text: str, *, voice: str, speed: float) -> SpeechAudio:
        if self._kokoro is None:
            raise VoiceError("Speech synthesis is still loading.")
        if voice not in self._voices:
            raise VoiceError(f"Unknown voice '{voice}'.")
        start = time.perf_counter()
        audio, sr = await asyncio.get_running_loop().run_in_executor(
            self._pool, self._synth_sync, text, voice, max(0.5, min(2.0, speed))
        )
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        return SpeechAudio(pcm, sr, len(audio) / sr, int((time.perf_counter() - start) * 1000))
