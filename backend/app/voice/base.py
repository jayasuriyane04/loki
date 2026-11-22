from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class Transcript:
    text: str
    language: str | None
    duration_s: float
    latency_ms: int


@dataclass
class SpeechAudio:
    pcm16: bytes  # mono little-endian int16
    sample_rate: int
    duration_s: float
    latency_ms: int


class VoiceError(Exception):
    """Safe-to-show error from a speech provider."""


class STTProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def load(self) -> None:
        """Load weights and warm up. Called once in the background at startup."""

    @abstractmethod
    async def transcribe(self, audio: np.ndarray, sample_rate: int) -> Transcript:
        """`audio` is mono float32 in [-1, 1]."""


class TTSProvider(ABC):
    name: str

    @abstractmethod
    async def load(self) -> None: ...

    @abstractmethod
    def voices(self) -> list[str]: ...

    @abstractmethod
    async def synthesize(self, text: str, *, voice: str, speed: float) -> SpeechAudio: ...
