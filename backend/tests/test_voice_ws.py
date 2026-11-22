import json

import numpy as np
import pytest

from app.core.config import get_settings
from app.llm.router import LLMRouter
from app.main import app
from app.voice.base import SpeechAudio, STTProvider, Transcript, TTSProvider
from app.voice.manager import VoiceManager
from tests.conftest import FakeProvider


class FakeSTT(STTProvider):
    name, model = "fake-stt", "fake"

    def __init__(self, text: str = "What is the plan for Tarka today?"):
        self.text = text
        self.received: list[np.ndarray] = []

    async def load(self):
        pass

    async def transcribe(self, audio, sample_rate):
        self.received.append(audio)
        return Transcript(self.text, "en", len(audio) / sample_rate, 5)


class FakeTTS(TTSProvider):
    name = "fake-tts"

    def __init__(self):
        self.spoken: list[tuple[str, str, float]] = []

    async def load(self):
        pass

    def voices(self):
        return ["bm_george", "af_heart"]

    async def synthesize(self, text, *, voice, speed):
        self.spoken.append((text, voice, speed))
        return SpeechAudio(b"\x01\x00" * 240, 24000, 0.01, 1)


@pytest.fixture
def voice(client):
    stt, tts = FakeSTT(), FakeTTS()
    vm = VoiceManager(stt, tts, get_settings())
    vm.stt_status.state = vm.tts_status.state = "ready"
    app.state.voice = vm
    yield stt, tts


def _pcm(seconds: float = 1.0) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    return (np.sin(2 * np.pi * 220 * t) * 8000).astype("<i2").tobytes()


def _collect(ws) -> list[dict]:
    """Collect events until idle; binary frames are returned as {"type": "_binary", "size": n}."""
    out = []
    while True:
        frame = ws.receive()
        if frame.get("bytes") is not None:
            out.append({"type": "_binary", "size": len(frame["bytes"])})
            continue
        ev = json.loads(frame["text"])
        out.append(ev)
        if ev == {"type": "state", "state": "idle"}:
            return out


def test_voice_turn_transcribes_answers_and_speaks(client, user, voice):
    stt, tts = voice
    app.state.llm = LLMRouter(
        FakeProvider(reply="Tarka needs the auth module finished first. After that we can ship the beta build."),
        None,
        temperature=0,
        max_tokens=64,
    )
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "voice_config", "voice": "af_heart", "speed": 1.2})
        ws.send_json({"type": "audio_utterance", "sample_rate": 16000})
        ws.send_bytes(_pcm(1.5))
        events = _collect(ws)

    types = [e["type"] for e in events]
    assert types.index("stt_final") < types.index("message_saved") < types.index("assistant_start")
    assert next(e for e in events if e["type"] == "stt_final")["text"] == "What is the plan for Tarka today?"
    saved = next(e for e in events if e["type"] == "message_saved")["message"]
    assert saved["input_mode"] == "voice" and saved["content"] == "What is the plan for Tarka today?"
    assert abs(len(stt.received[0]) - 24000) <= 1

    # Each tts_chunk header is immediately followed by its audio frame, in order.
    for i, e in enumerate(events):
        if e["type"] == "tts_chunk":
            assert events[i + 1] == {"type": "_binary", "size": 480}
    chunks = [e for e in events if e["type"] == "tts_chunk"]
    assert [c["seq"] for c in chunks] == list(range(len(chunks)))
    assert [t for t, _, _ in tts.spoken] == [
        "Tarka needs the auth module finished first.",
        "After that we can ship the beta build.",
    ]
    assert all(v == "af_heart" and s == 1.2 for _, v, s in tts.spoken)
    end = next(e for e in events if e["type"] == "tts_end")
    assert end["first_audio_ms"] is not None
    assert types.index("tts_end") < len(types) - 1  # tts_end arrives before the final idle


def test_voice_turns_ask_for_short_spoken_answers(client, user, voice):
    fake = FakeProvider()
    app.state.llm = LLMRouter(fake, None, temperature=0, max_tokens=64)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(_pcm(1))
        _collect(ws)
        ws.send_json({"type": "user_message", "content": "typed now"})
        _collect(ws)
    voice_system, text_system = fake.calls[0][0].content, fake.calls[1][0].content
    assert "spoken aloud" in voice_system and "No lists" in voice_system
    assert "spoken aloud" not in text_system


def test_typed_messages_not_spoken_unless_enabled(client, user, voice):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "content": "hello there"})
        assert not any(e["type"] == "tts_chunk" for e in _collect(ws))
        ws.send_json({"type": "voice_config", "speak_text_replies": True})
        ws.send_json({"type": "user_message", "content": "hello again"})
        assert any(e["type"] == "tts_chunk" for e in _collect(ws))


def test_silence_reports_no_speech_and_saves_nothing(client, user, voice):
    stt, _ = voice
    stt.text = ""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(_pcm(0.5))
        events = _collect(ws)
    assert any(e.get("code") == "no_speech" for e in events)
    assert not any(e["type"] == "message_saved" for e in events)
    assert client.get("/api/conversations").json() == []


def test_spoken_stop_command_starts_no_turn(client, user, voice):
    stt, _ = voice
    stt.text = "Stop."
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(_pcm(0.6))
        events = _collect(ws)
    assert {"type": "stt_command", "command": "stop"} in events
    assert not any(e["type"] in ("message_saved", "assistant_start") for e in events)


def test_bad_audio_rejected(client, user, voice):
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(_pcm(0.2))
        assert json.loads(ws.receive()["text"])["code"] == "bad_request"  # no header
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(b"\x00" * 3)
        assert json.loads(ws.receive()["text"])["code"] == "bad_request"  # odd length
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(_pcm(61))
        assert json.loads(ws.receive()["text"])["code"] == "bad_request"  # too long


def test_stt_not_ready_is_reported(client, user):
    app.state.voice = VoiceManager(FakeSTT(), None, get_settings())  # stays "loading"
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(_pcm(0.5))
        ev = json.loads(ws.receive()["text"])
    assert ev["code"] == "stt_unavailable" and "starting up" in ev["message"]


def test_voice_status_endpoint(client, user, voice):
    body = client.get("/api/voice").json()
    assert body["stt"]["state"] == "ready" and body["tts"]["voices"] == ["bm_george", "af_heart"]


def test_barge_in_then_new_utterance_is_accepted(client, user, voice):
    app.state.llm = LLMRouter(
        FakeProvider(reply=" ".join(["Long sentence number one."] * 80), delay=0.01), None, temperature=0, max_tokens=64
    )
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(_pcm(1))
        while True:  # wait until LOKI is speaking
            frame = ws.receive()
            if frame.get("text") and json.loads(frame["text"])["type"] == "tts_chunk":
                break
        ws.send_json({"type": "cancel"})
        ws.send_json({"type": "audio_utterance"})
        ws.send_bytes(_pcm(1))
        events = []
        idles = 0
        while idles < 2:
            frame = ws.receive()
            if frame.get("text"):
                ev = json.loads(frame["text"])
                events.append(ev)
                idles += ev == {"type": "state", "state": "idle"}
    assert not any(e.get("code") == "busy" for e in events)
    ends = [e["message"]["status"] for e in events if e["type"] == "assistant_end"]
    assert ends[0] == "interrupted"
    assert sum(e["type"] == "stt_final" for e in events) == 1
