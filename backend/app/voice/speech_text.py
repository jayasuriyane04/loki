"""Turn a streamed Markdown reply into speakable sentences, incrementally."""

import re

_CODE_FENCE = "```"
_MIN_CHARS = 24  # avoid synthesising tiny fragments ("Sure.") on their own — they sound choppy
_MAX_CHARS = 280  # very long sentences are split at a clause boundary so audio starts sooner
_FIRST_MAX_CHARS = 90  # the first chunk is cut earlier: it decides how soon LOKI starts talking
_FIRST_MIN_CLAUSE = 25
_FIRST_SPLIT_OVER = 60  # a first sentence longer than this is split at its first clause boundary

_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]]?\s+|\n{2,}|\n(?=\s*(?:[-*•]|\d+[.)])\s)")
_CLAUSE_END = re.compile(r"[,;:]\s+")
# Natural places to breathe inside a long first sentence that has no punctuation to split on.
_SOFT_BREAK = re.compile(r"\s+(?=(?:and|but|or|so|because|which|while|where|although|though|since|with|as)\b)", re.I)


def clean_for_speech(text: str) -> str:
    t = re.sub(r"\s*\[\d{1,2}(?:\s*,\s*\d{1,2})*\]", "", text)  # citation markers [1], [2, 3] aren't spoken
    t = re.sub(r"`([^`]*)`", r"\1", t)  # inline code → plain
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)  # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)  # links → link text
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)  # headings
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)  # list markers
    t = re.sub(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", t)  # emphasis
    t = re.sub(r"^\s*>\s?", "", t, flags=re.M)
    t = re.sub(r"\|", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


class SentenceChunker:
    """Feed streamed deltas; get back cleaned sentences ready for TTS. Code blocks are never read aloud."""

    def __init__(self) -> None:
        self._buf = ""
        self._in_code = False
        self._announced_code = False
        self._emitted = False

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        while True:
            if self._in_code:
                end = self._buf.find(_CODE_FENCE)
                if end < 0:
                    # keep only a possible partial fence at the tail
                    self._buf = self._buf[-2:]
                    return out
                self._buf = self._buf[end + 3 :]
                self._in_code = False
                continue

            fence = self._buf.find(_CODE_FENCE)
            search_in = self._buf if fence < 0 else self._buf[:fence]
            sentence_end = None
            for m in _SENTENCE_END.finditer(search_in):
                if len(search_in[: m.start()].strip()) >= _MIN_CHARS:
                    sentence_end = m
                    break
            if not self._emitted and (sentence_end is None or sentence_end.start() > _FIRST_SPLIT_OVER):
                first_clause = next(
                    (m for m in _CLAUSE_END.finditer(search_in) if _FIRST_MIN_CLAUSE <= m.start() <= _FIRST_MAX_CHARS),
                    None,
                ) or next(
                    (m for m in _SOFT_BREAK.finditer(search_in) if _FIRST_MIN_CLAUSE <= m.start() <= _FIRST_MAX_CHARS),
                    None,
                )
                if first_clause:
                    out += self._emit(self._buf[: first_clause.end()])
                    self._buf = self._buf[first_clause.end() :]
                    continue
            if sentence_end:
                out += self._emit(self._buf[: sentence_end.end()])
                self._buf = self._buf[sentence_end.end() :]
                continue
            if fence >= 0:
                out += self._emit(self._buf[:fence])
                if not self._announced_code:
                    out.append("I've put the code on screen.")
                    self._announced_code = True
                self._buf = self._buf[fence + 3 :]
                self._in_code = True
                continue
            if len(self._buf) > _MAX_CHARS:
                clause = None
                for m in _CLAUSE_END.finditer(self._buf, 0, _MAX_CHARS):
                    clause = m
                cut = clause.end() if clause else _MAX_CHARS
                out += self._emit(self._buf[:cut])
                self._buf = self._buf[cut:]
                continue
            return out

    def flush(self) -> list[str]:
        rest, self._buf = ("" if self._in_code else self._buf), ""
        return self._emit(rest)

    def _emit(self, raw: str) -> list[str]:
        text = clean_for_speech(raw)
        if not re.search(r"\w", text):
            return []
        self._emitted = True
        return [text]


_STOP_PHRASES = {
    "stop", "stop it", "stop talking", "cancel", "never mind", "nevermind", "be quiet", "quiet",
    "shut up", "that's enough", "enough", "hold on", "wait", "ok stop", "okay stop", "loki stop",
}


def is_stop_command(transcript: str) -> bool:
    """A bare 'stop'-style utterance just silences LOKI; it should not start a new turn."""
    t = re.sub(r"[^\w\s']", "", transcript.lower()).strip()
    t = re.sub(r"^(hey |ok |okay )?loki,? ", "", t) if t not in _STOP_PHRASES else t
    return t in _STOP_PHRASES
