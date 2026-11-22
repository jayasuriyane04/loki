"""Structure-aware chunking. Each chunk remembers where it came from (heading path, page, line range) for citations."""

import re
from dataclasses import dataclass

from app.knowledge.extract import Extracted

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
# Top-level definitions that start a new logical unit in common languages.
_CODE_START = re.compile(
    r"^(?:@\w|def |async def |class |function |async function |export |const \w+\s*=\s*(?:async\s*)?\(|"
    r"func |fn |pub |impl |struct |enum |interface |type \w+|public |private |protected |static |"
    r"CREATE |ALTER |module |package |namespace |#\s*%%)"
)


@dataclass
class ChunkDraft:
    content: str
    heading_path: str | None
    page: int | None
    line_start: int | None  # 1-based, inclusive
    line_end: int | None

    def embedding_text(self, title: str) -> str:
        """What gets embedded: the passage plus its document/section context (helps retrieval)."""
        return f"{context_label(title, self.heading_path)}\n\n{self.content}"


def context_label(title: str, heading: str | None) -> str:
    return " > ".join(x for x in (title, heading) if x)


def passage_label(title: str, source: str, file_type: str, language: str | None, heading: str | None) -> str:
    """How a passage introduces itself to the embedder/reranker. Code is identified by path and language,
    which retrieval models understand far better than a bare file name."""
    if file_type == "code":
        return context_label(f"File {source} ({language or 'source code'})", heading)
    return context_label(title, heading)


def _clean(text: str) -> str:
    text = text.replace(" ", " ").replace("\t", "    ")
    text = re.sub(r"[  -​]+\n", "\n", text)  # trailing whitespace
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # PDF hyphenation across lines
    return re.sub(r"\n{3,}", "\n\n", text)


def _pack(
    units: list[tuple[str, int]], max_chars: int, overlap: int
) -> list[tuple[str, int, int]]:
    """Greedily pack (text, first_line) units into chunks of <= max_chars, splitting oversized units by lines.
    Returns (text, line_start, line_end) with 1-based inclusive line numbers. Consecutive chunks share a small
    overlap (the last lines of the previous chunk, up to `overlap` chars) so facts spanning a boundary survive."""
    lines: list[tuple[str, int]] = []
    for text, first in units:
        for i, line in enumerate(text.split("\n")):
            lines.append((line, first + i))
    chunks: list[tuple[str, int, int]] = []
    cur: list[tuple[str, int]] = []
    size = 0
    for line, n in lines:
        while len(line) > max_chars:  # a single enormous line (minified code, PDF paragraph)
            if cur:
                chunks.append(("\n".join(x for x, _ in cur), cur[0][1], cur[-1][1]))
                cur, size = [], 0
            chunks.append((line[:max_chars], n, n))
            line = line[max_chars - overlap:]
        if size + len(line) + 1 > max_chars and cur:
            chunks.append(("\n".join(x for x, _ in cur), cur[0][1], cur[-1][1]))
            carry: list[tuple[str, int]] = []
            carried = 0
            for prev in reversed(cur):
                if carried + len(prev[0]) > overlap:
                    break
                carry.insert(0, prev)
                carried += len(prev[0]) + 1
            if not carry and overlap:
                # The last line alone is longer than the overlap: carry its tail, starting at a word boundary.
                last, n_last = cur[-1]
                tail = last[-overlap:]
                tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
                carry, carried = [(tail, n_last)], len(tail) + 1
            cur, size = carry, carried
        cur.append((line, n))
        size += len(line) + 1
    if cur:
        chunks.append(("\n".join(x for x, _ in cur), cur[0][1], cur[-1][1]))
    return [(t.strip("\n"), a, b) for t, a, b in chunks if t.strip()]


def _markdown_sections(text: str) -> list[tuple[str | None, str, int]]:
    """Split on headings, tracking the heading path. Returns (heading_path, body, first_line_1based)."""
    out: list[tuple[str | None, str, int]] = []
    path: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 1
    in_fence = False

    def has_body(lines: list[str]) -> bool:  # a heading on its own is not worth a passage
        return any(x.strip() and not _HEADING.match(x) for x in lines)

    for i, line in enumerate(text.split("\n"), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            if has_body(buf):
                out.append((" > ".join(h for _, h in path) or None, "\n".join(buf), start))
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
            buf, start = [line], i
        else:
            buf.append(line)
    if has_body(buf):
        out.append((" > ".join(h for _, h in path) or None, "\n".join(buf), start))
    return out


def _code_units(text: str) -> list[tuple[str | None, str, int]]:
    """Split source code at top-level definitions; heading = the definition's first line."""
    out: list[tuple[str | None, str, int]] = []
    buf: list[str] = []
    start, label = 1, None
    for i, line in enumerate(text.split("\n"), start=1):
        if _CODE_START.match(line) and any(x.strip() for x in buf):
            out.append((label, "\n".join(buf), start))
            buf, start = [], i
            label = line.strip()[:120]
        elif not buf and _CODE_START.match(line):
            label = line.strip()[:120]
        buf.append(line)
    if any(x.strip() for x in buf):
        out.append((label, "\n".join(buf), start))
    return out


def chunk(doc: Extracted, *, max_chars: int, overlap: int) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for section in doc.sections:
        text = _clean(section.text) if doc.file_type != "code" else section.text
        if doc.file_type == "markdown":
            groups = _markdown_sections(text)
        elif doc.file_type == "code":
            groups = _code_units(text)
        else:
            groups = [(None, text, 1)]
        if doc.file_type == "code":
            # Merge only very small consecutive definitions (imports, constants, one-liners): a passage that is one
            # function scores far better in retrieval than a whole file.
            merged: list[tuple[str | None, str, int]] = []
            for label, body, first in groups:
                if merged and (len(merged[-1][1]) < 200 or len(body) < 120) and len(merged[-1][1]) + len(body) < max_chars:
                    merged[-1] = (merged[-1][0], merged[-1][1] + "\n" + body, merged[-1][2])
                else:
                    merged.append((label, body, first))
            groups = merged
        for heading, body, first in groups:
            for content, a, b in _pack([(body, first + section.line_offset)], max_chars, overlap):
                is_pdf = doc.file_type == "pdf"
                drafts.append(ChunkDraft(content, heading, section.page, None if is_pdf else a, None if is_pdf else b))
    return drafts
