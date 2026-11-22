import asyncio
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from app.voice.base import STTProvider, Transcript, VoiceError

log = logging.getLogger(__name__)

# Whisper says these on silence / noise; drop them when they are the whole transcript.
_HALLUCINATIONS = {"", "you", "thank you.", "thanks for watching!", "thank you for watching.", "bye.", "."}


def _add_cuda_dll_dirs() -> None:
    """On Windows the CUDA runtime comes from the nvidia-* pip wheels; make their DLLs loadable."""
    if sys.platform != "win32":
        return
    root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for sub in ("cublas", "cudnn", "cuda_nvrtc"):
        d = root / sub / "bin"
        if d.is_dir():
            os.add_dll_directory(str(d))
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


class FasterWhisperSTT(STTProvider):
    name = "faster_whisper"

    def __init__(self, model: str, *, device: str, compute_type: str, language: str | None) -> None:
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        # One worker: the GPU handles one utterance at a time, and CTranslate2 models are not shared across threads.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

    def _load_sync(self) -> None:
        _add_cuda_dll_dirs()
        from faster_whisper import WhisperModel

        start = time.perf_counter()
        self._model = WhisperModel(self.model, device=self.device, compute_type=self.compute_type)
        # First GPU run compiles kernels (several seconds on new GPUs); do it now, not on the user's first sentence.
        segments, _ = self._model.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1, language="en")
        list(segments)
        log.info("stt ready", extra={"model": self.model, "device": self.device, "s": round(time.perf_counter() - start, 1)})

    async def load(self) -> None:
        await asyncio.get_running_loop().run_in_executor(self._pool, self._load_sync)

    def _transcribe_sync(self, audio: np.ndarray) -> tuple[str, str | None]:
        assert self._model is not None
        segments, info = self._model.transcribe(
            audio,
            beam_size=1,
            language=self.language,
            vad_filter=True,  # trims leading/trailing silence and noise the client VAD let through
            condition_on_previous_text=False,
        )
        kept = [s.text for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        return "".join(kept).strip(), info.language

    async def transcribe(self, audio: np.ndarray, sample_rate: int) -> Transcript:
        if self._model is None:
            raise VoiceError("Speech recognition is still loading.")
        if sample_rate != 16000:
            raise VoiceError("Audio must be 16 kHz.")
        start = time.perf_counter()
        text, lang = await asyncio.get_running_loop().run_in_executor(self._pool, self._transcribe_sync, audio)
        if text.lower() in _HALLUCINATIONS:
            text = ""
        return Transcript(text, lang, len(audio) / sample_rate, int((time.perf_counter() - start) * 1000))
