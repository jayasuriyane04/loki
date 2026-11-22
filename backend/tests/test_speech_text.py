from app.voice.speech_text import SentenceChunker, clean_for_speech, is_stop_command


def test_long_first_sentence_is_cut_at_a_clause_for_fast_first_audio():
    out = _run(["Mars is the fourth planet from the Sun, known as the Red Planet for its iron oxide surface. It is cold."])
    assert out[0] == "Mars is the fourth planet from the Sun,"
    assert out[1:] == ["known as the Red Planet for its iron oxide surface.", "It is cold."]


def test_long_first_sentence_without_commas_breaks_at_a_conjunction():
    out = _run(['Mars is the fourth planet from the Sun and is often called the "Red Planet" because of its colour. Yes.'])
    assert out[0] == "Mars is the fourth planet from the Sun"
    assert out[1].startswith("and is often called")


def test_stop_commands():
    for t in ["Stop.", "stop!", "Never mind.", "Hey LOKI, stop.", "Okay stop", "Be quiet."]:
        assert is_stop_command(t), t
    for t in ["Stop the server and restart it.", "Don't stop", "What is a stop word?"]:
        assert not is_stop_command(t), t


def _run(deltas: list[str]) -> list[str]:
    c = SentenceChunker()
    out: list[str] = []
    for d in deltas:
        out += c.feed(d)
    return out + c.flush()


def test_streams_sentences_as_they_complete():
    c = SentenceChunker()
    assert c.feed("The build passed on the first try. Next we") == ["The build passed on the first try."]
    assert c.flush() == ["Next we"]


def test_short_sentences_are_merged_not_spoken_alone():
    assert _run(["Sure. ", "I can help you with the database migration today."]) == [
        "Sure. I can help you with the database migration today."
    ]


def test_code_blocks_are_announced_once_and_never_read():
    text = "Here is the fix for the session bug:\n```python\nx = 1\nprint(x)\n```\nThen restart the server and try again."
    out = _run([text[i : i + 7] for i in range(0, len(text), 7)])  # arbitrary token boundaries
    joined = " ".join(out)
    assert "print" not in joined and "x = 1" not in joined
    assert joined.count("I've put the code on screen.") == 1
    assert out[-1] == "Then restart the server and try again."


def test_markdown_is_cleaned():
    assert clean_for_speech("## Plan\n- **Fast** `uvicorn` [docs](https://x.y)") == "Plan\nFast uvicorn docs"


def test_list_items_split_into_separate_utterances():
    out = _run(["Three tips for naming things:\n- Use clear descriptive names\n- Avoid abbreviations in names\n"])
    assert out == ["Three tips for naming things:", "Use clear descriptive names", "Avoid abbreviations in names"]


def test_long_runs_split_at_clauses():
    text = "word " * 40 + ", and " + "more " * 40
    out = _run([text])
    assert len(out) >= 2 and all(len(s) <= 290 for s in out)
