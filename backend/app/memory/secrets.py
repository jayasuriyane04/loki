"""Detect and redact secrets so they never reach memory extraction or storage."""

import math
import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai/anthropic key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("google key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("connection string", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@]+@", re.I)),
    # "my password is hunter2", "pin: 1234", "api key = abc" (the value is what gets redacted)
    (
        "credential",
        re.compile(
            r"\b(?:password|passcode|passwd|pass\s*phrase|pin(?:\s*code)?|otp|one[- ]time code|2fa code|"
            r"verification code|security code|cvv|api[\s_\-]?key|access[\s_\-]?token|secret(?:[\s_\-]?key)?|"
            r"auth(?:entication)?[\s_\-]?token|bearer)\b"
            # either an explicit separator ("is", "=", ":") then any value, or a value that looks secret-like
            r"(?:\s*(?:is|was|=|:|-)\s*[\"']?(\S{3,})|\s+[\"']?((?=\S*[\d!@#$%^&*])\S{3,}))",
            re.I,
        ),
    ),
    ("us ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("aadhaar", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]

_CARD = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
_TOKENISH = re.compile(r"[A-Za-z0-9_\-+/=]{24,}")


def _luhn(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        checksum += d
    return len(digits) >= 13 and checksum % 10 == 0


def _entropy(s: str) -> float:
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def _high_entropy_token(s: str) -> bool:
    classes = sum(bool(re.search(p, s)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes >= 3 and _entropy(s) > 4.0


def find_secrets(text: str) -> list[str]:
    """Names of the kinds of secret found (empty list = clean)."""
    found = [name for name, pat in _PATTERNS if pat.search(text)]
    if any(_luhn(m.group()) for m in _CARD.finditer(text)):
        found.append("card number")
    if any(_high_entropy_token(m.group()) for m in _TOKENISH.finditer(text)):
        found.append("token")
    return found


def redact(text: str) -> str:
    out = text
    for name, pat in _PATTERNS:
        if name == "credential":
            out = pat.sub(lambda m: m.group(0).replace(m.group(1) or m.group(2), "[REDACTED]"), out)
        else:
            out = pat.sub("[REDACTED]", out)
    out = _CARD.sub(lambda m: "[REDACTED]" if _luhn(m.group()) else m.group(), out)
    out = _TOKENISH.sub(lambda m: "[REDACTED]" if _high_entropy_token(m.group()) else m.group(), out)
    return out
