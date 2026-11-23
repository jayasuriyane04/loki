"""Voice evaluation: speech-recognition accuracy (WER) and latency, end-to-end voice turn latency, and barge-in.

Test speech is synthesised with LOKI's own Kokoro voices, so the audio is clean: WER here is a lower bound, not what a
real microphone in a room gives. Real-user testing (docs/USER_TESTING.md) covers that.
"""

import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from eval.common import pct, register, write_report

PHRASES = [
    "Remind me to call the bank tomorrow at ten in the morning.",
    "What is on my calendar for Friday?",
    "Add milk, eggs and coffee to my shopping list.",
    "How long is the grace period before late fees start?",
    "Search the web for the latest news about electric cars.",
    "Turn this into a note titled project ideas.",
    "What did we decide about the database migration yesterday?",
    "Open the documentation for the invoicing service.",
    "Set a reminder in two hours to stretch.",
    "Summarise the meeting notes from October.",
]
QUESTIONS = [
    "What time is it right now?",
    "Give me one tip for staying focused while working.",
    "What is the capital of Japan?",
    "Tell me a short fact about the moon.",
    "How many days are there in a leap year?",
]
LONG_ANSWER = "Explain in detail how a car engine works, step by step."
VOICES = ["af_heart", "bm_george"]


_NUMBERS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())}


def words(s: str, *, normalise: bool = False) -> list[str]:
    s = s.lower().replace("-", " ")
    out = re.findall(r"[a-z0-9']+", s)
    if normalise:  # formatting, not recognition: "ten" vs "10", British vs American spelling
        out = [_NUMBERS.get(w, re.sub(r"is(e|ed|es|ing)$", r"iz\1", w)) for w in out]
    return out


def wer(ref: str, hyp: str, *, normalise: bool = False) -> float:
    r, h = words(ref, normalise=normalise), words(hyp, normalise=normalise)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def to_16k(pcm16: bytes, rate: int) -> np.ndarray:
    x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
    n = int(len(x) * 16000 / rate)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def run(client, app) -> Path:
    vm = app.state.voice
    for _ in range(600):
        if vm.stt_status.state != "loading" and vm.tts_status.state != "loading":
            break
        time.sleep(0.5)
    if not (vm.stt_ready and vm.tts_ready):
        raise SystemExit(f"voice models not ready: {vm.describe()}")
    register(client, "voice")

    # 1) Recognition accuracy + latency on synthesised speech.
    async def synth(text: str, voice: str):
        return await vm.tts.synthesize(text, voice=voice, speed=1.0)

    async def transcribe(audio):
        return await vm.stt.transcribe(audio, 16000)

    stt_rows = []
    clips: dict[str, np.ndarray] = {}
    for voice in VOICES:
        for text in PHRASES:
            sp = client.portal.call(synth, text, voice)
            audio = to_16k(sp.pcm16, sp.sample_rate)
            tr = client.portal.call(transcribe, audio)
            stt_rows.append({"voice": voice, "ref": text, "hyp": tr.text, "wer": round(wer(text, tr.text, normalise=True), 3),
                             "wer_raw": round(wer(text, tr.text), 3),
                             "audio_s": round(len(audio) / 16000, 2), "stt_ms": tr.latency_ms,
                             "rtf": round(tr.latency_ms / 1000 / (len(audio) / 16000), 3)})
    for text in [*QUESTIONS, LONG_ANSWER]:
        sp = client.portal.call(synth, text, VOICES[0])
        clips[text] = to_16k(sp.pcm16, sp.sample_rate)

    # 2) End-to-end voice turns over the WebSocket, as the browser does it.
    def pcm_bytes(a: np.ndarray) -> bytes:
        return (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes()

    turns = []
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "client_info", "timezone": "UTC"})
        ws.send_json({"type": "voice_config", "speak_replies": True})
        for text in QUESTIONS:
            t0 = time.perf_counter()
            ws.send_json({"type": "audio_utterance", "sample_rate": 16000, "temporary": True})
            ws.send_bytes(pcm_bytes(clips[text]))
            row: dict[str, Any] = {"question": text}
            while True:
                frame = ws.receive()
                if frame.get("bytes") is not None:
                    continue
                import json

                ev = json.loads(frame["text"])
                now = time.perf_counter() - t0
                if ev["type"] == "stt_final":
                    row.update(heard=ev["text"], stt_ms=ev["latency_ms"], stt_done_s=round(now, 3))
                elif ev["type"] == "token" and "first_token_s" not in row:
                    row["first_token_s"] = round(now, 3)
                elif ev["type"] == "tts_chunk" and "first_audio_s" not in row:
                    row["first_audio_s"] = round(now, 3)
                elif ev["type"] == "tts_end":
                    row["server_first_audio_ms"] = ev["first_audio_ms"]
                elif ev["type"] == "error":
                    row["error"] = ev["code"]
                elif ev == {"type": "state", "state": "idle"}:
                    row["total_s"] = round(now, 3)
                    break
            turns.append(row)

        # 3) Barge-in: interrupt a long spoken answer as soon as audio starts; measure how fast LOKI goes quiet.
        barge = []
        for _ in range(3):
            ws.send_json({"type": "audio_utterance", "sample_rate": 16000, "temporary": True})
            ws.send_bytes(pcm_bytes(clips[LONG_ANSWER]))
            cancelled_at = None
            chunks_after = 0
            import json

            while True:
                frame = ws.receive()
                if frame.get("bytes") is not None:
                    continue
                ev = json.loads(frame["text"])
                if ev["type"] == "tts_chunk":
                    if cancelled_at is None:
                        ws.send_json({"type": "cancel"})
                        cancelled_at = time.perf_counter()
                    else:
                        chunks_after += 1
                if ev == {"type": "state", "state": "idle"}:
                    barge.append({"stop_ms": round((time.perf_counter() - cancelled_at) * 1000) if cancelled_at else None,
                                  "audio_chunks_after_cancel": chunks_after})
                    break

    headline = {
        "stt_wer": round(sum(r["wer"] for r in stt_rows) / len(stt_rows), 3),
        "stt_wer_raw": round(sum(r["wer_raw"] for r in stt_rows) / len(stt_rows), 3),
        "stt_exact": f"{sum(r['wer'] == 0 for r in stt_rows)}/{len(stt_rows)}",
        "stt_p50_ms": pct([r["stt_ms"] for r in stt_rows], 0.5),
        "stt_p95_ms": pct([r["stt_ms"] for r in stt_rows], 0.95),
        "first_audio_p50_s": pct([t.get("first_audio_s") for t in turns], 0.5),
        "first_audio_p95_s": pct([t.get("first_audio_s") for t in turns], 0.95),
        "turn_total_p50_s": pct([t.get("total_s") for t in turns], 0.5),
        "barge_in_stop_p50_ms": pct([b["stop_ms"] for b in barge], 0.5),
        "turn_errors": sum(1 for t in turns if t.get("error")),
    }
    config = {"stt": vm.describe()["stt"], "tts_voices": VOICES, "llm": app.state.llm.primary.model,
              "speech_source": "synthesised (Kokoro), clean audio"}
    return write_report("voice", config, headline, {"recognition": stt_rows, "turns": turns, "barge_in": barge})
