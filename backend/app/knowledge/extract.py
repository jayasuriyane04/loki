"""Validate uploads and extract text. Uploaded files are untrusted: nothing here executes or interprets them."""

import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath

CODE_LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".cs": "csharp",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".sql": "sql", ".sh": "shell", ".ps1": "powershell", ".css": "css", ".scss": "css",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".json": "json", ".ini": "ini", ".dockerfile": "docker",
}
TEXT_TYPES = {".md": "markdown", ".markdown": "markdown", ".mdx": "markdown", ".txt": "text", ".rst": "text",
              ".log": "text", ".csv": "text", ".html": "html", ".htm": "html", ".pdf": "pdf"}
SPECIAL_NAMES = {"dockerfile": ("code", "docker"), "makefile": ("code", "make"), "readme": ("text", None)}
# Never index these even inside an uploaded folder.
SKIP_PARTS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", ".idea"}
SECRET_FILES = re.compile(r"(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx)|id_rsa.*|credentials.*\.json|secrets?\..*)$", re.I)


class UploadRejected(ValueError):
    """Safe-to-show reason a file was not accepted."""


@dataclass
class Section:
    text: str
    page: int | None = None
    line_offset: int = 0  # 0-based line number of the first line of `text` in the original file


@dataclass
class Extracted:
    title: str
    file_type: str
    language: str | None
    sections: list[Section]
    page_count: int | None = None


def clean_source(path: str) -> str:
    """Normalise a client-supplied (relative) path; refuse traversal and absolute paths."""
    p = path.replace("\\", "/").strip().lstrip("/")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts) or re.match(r"^[a-zA-Z]:", parts[0]):
        raise UploadRejected("Invalid file path.")
    cleaned = "/".join(parts)
    if len(cleaned) > 500 or any(ord(c) < 32 for c in cleaned):
        raise UploadRejected("Invalid file path.")
    return cleaned


def classify(source: str) -> tuple[str, str | None]:
    """(file_type, language) for a path, or raise UploadRejected."""
    path = PurePosixPath(source)
    if any(part in SKIP_PARTS for part in path.parts[:-1]):
        raise UploadRejected("Skipped: dependency/build folder.")
    if SECRET_FILES.search(source):
        raise UploadRejected("Skipped: looks like a secrets file. LOKI never indexes secrets.")
    suffix = path.suffix.lower()
    stem = path.name.lower().split(".")[0]
    if suffix in TEXT_TYPES:
        return TEXT_TYPES[suffix], None
    if suffix in CODE_LANGUAGES:
        return "code", CODE_LANGUAGES[suffix]
    if stem in SPECIAL_NAMES:
        return SPECIAL_NAMES[stem]
    raise UploadRejected(f"Unsupported file type '{suffix or path.name}'.")


def _decode(data: bytes) -> str:
    if b"\x00" in data[:8192]:
        raise UploadRejected("This looks like a binary file, not text.")
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.out.append(data)


def _first_heading(text: str) -> str | None:
    m = re.search(r"^\s{0,3}#{1,2}\s+(.+?)\s*#*\s*$", text, re.M)
    return m.group(1).strip()[:300] if m else None


def extract(source: str, data: bytes, *, max_bytes: int) -> Extracted:
    if len(data) == 0:
        raise UploadRejected("File is empty.")
    if len(data) > max_bytes:
        raise UploadRejected(f"File is larger than {max_bytes // (1024 * 1024)} MB.")
    file_type, language = classify(source)
    name = PurePosixPath(source).name

    if file_type == "pdf":
        if not data.startswith(b"%PDF"):
            raise UploadRejected("Not a valid PDF file.")
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise UploadRejected("Password-protected PDFs are not supported.")
            pages = [(p.extract_text() or "") for p in reader.pages]
        except PdfReadError as e:
            raise UploadRejected(f"Could not read this PDF ({e}).") from e
        if not any(t.strip() for t in pages):
            raise UploadRejected("No text found in this PDF (scanned images need OCR, which isn't supported yet).")
        meta_title = (reader.metadata.title if reader.metadata else None) or ""
        title = meta_title.strip() or _first_heading(pages[0]) or name
        return Extracted(title[:300], "pdf", None, [Section(t, page=i + 1) for i, t in enumerate(pages)], len(pages))

    text = _decode(data)
    if file_type == "html":
        parser = _HTMLText()
        parser.feed(text)
        body = re.sub(r"\n{3,}", "\n\n", "".join(parser.out)).strip()
        if not body:
            raise UploadRejected("No readable text in this HTML file.")
        title = parser.title.strip() or _first_heading(body) or name
        return Extracted(title[:300], "markdown", None, [Section(body)])

    if not text.strip():
        raise UploadRejected("File has no text.")
    title = (_first_heading(text) if file_type == "markdown" else None) or name
    return Extracted(title[:300], file_type, language, [Section(text)])
