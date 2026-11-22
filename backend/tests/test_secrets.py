import pytest

from app.memory.secrets import find_secrets, redact


@pytest.mark.parametrize(
    "text",
    [
        "my password is hunter2!",
        "The wifi passcode: correcthorse",
        "use api key = sk-proj-abcdefghijklmnopqrstuvwx1234",
        "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "AKIAIOSFODNN7EXAMPLE is the access key",
        "card 4111 1111 1111 1111 exp 12/29",
        "postgres://admin:s3cretpw@db.internal:5432/app",
        "my aadhaar is 1234 5678 9012",
        "-----BEGIN RSA PRIVATE KEY-----",
        "the OTP is 482913",
        "wifi password Blue#Sky2024",
        "x9Kq2mZ7vP4tR8wL1nB6cY3hJ5dF0gS2",
    ],
)
def test_detects_secrets(text):
    assert find_secrets(text), text
    assert "[REDACTED]" in redact(text)


@pytest.mark.parametrize(
    "text",
    [
        "I prefer concise answers and use FastAPI for backends.",
        "My project Tarka uses PostgreSQL 16 with pgvector.",
        "I'm meeting Priya on 23 November at 10 AM.",
        "The password reset flow in Tarka is broken.",  # talks about passwords, contains none
        "My phone has 128 GB of storage and I was born in 1999.",
    ],
)
def test_ordinary_facts_are_not_secrets(text):
    assert find_secrets(text) == [], text
    assert redact(text) == text


def test_redaction_keeps_the_rest_of_the_sentence():
    out = redact("Remember my GitHub username is tonys and my password is Tr0ub4dor&3")
    assert "tonys" in out and "Tr0ub4dor" not in out
