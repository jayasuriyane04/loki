"""Watched project folders: keep a local folder indexed in the knowledge base and say what changed.

The user adds a folder (path + project) in Settings. Every `interval_min` LOKI walks it, re-ingests new or changed
supported files under that project, removes documents for files that were deleted, and posts one notification
summarising the change. Only files the knowledge base would accept are read (same type rules and secret-file skips as
uploads). Nothing is ever written to the folder.
"""

import asyncio
import hashlib
import logging
import os
import time as clock
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Document, UserSettings
from app.db.session import SessionLocal
from app.knowledge.extract import UploadRejected, classify, clean_source
from app.personal.preferences import Preferences, WatchedFolder

log = logging.getLogger(__name__)

MAX_FILES = 2000
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".idea", ".vscode",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", "target", ".cache"}


@dataclass
class ScanResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: int = 0
    error: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def _walk(root: Path) -> list[tuple[str, Path]]:
    """(relative posix source, absolute path) for every candidate file; no symlinks, no skipped dirs."""
    out: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            out.append((p.relative_to(root).as_posix(), p))
            if len(out) >= MAX_FILES:
                return out
    return out


def _read_checked(source: str, path: Path, max_bytes: int) -> tuple[str, bytes]:
    file_type, _ = classify(source)  # raises UploadRejected for unsupported / secret-looking files
    if path.stat().st_size > max_bytes:
        raise UploadRejected("too large")
    data = path.read_bytes()
    if not data:
        raise UploadRejected("empty")
    if file_type == "pdf" and not data.startswith(b"%PDF"):
        raise UploadRejected("not a PDF")
    if file_type != "pdf" and b"\x00" in data[:8192]:
        raise UploadRejected("binary")
    return file_type, data


class FolderWatcher:
    def __init__(self, ingestor, notifier) -> None:
        self.ingestor = ingestor
        self.notifier = notifier
        self._last: dict[tuple[uuid.UUID, str], float] = {}
        self._stat: dict[tuple[uuid.UUID, str, str], tuple[int, int]] = {}  # (user, folder, source) -> (mtime, size)

    async def scan_due(self) -> int:
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(UserSettings)))
        scanned = 0
        now = clock.monotonic()
        for s in rows:
            prefs = Preferences.model_validate(s.preferences or {})
            if not prefs.background_processing:
                continue
            for wf in prefs.proactive.watched_folders:
                key = (s.user_id, wf.path)
                if now - self._last.get(key, -1e12) < wf.interval_min * 60:
                    continue
                self._last[key] = now
                await self.scan(s.user_id, wf, notify=True)
                scanned += 1
        return scanned

    async def scan(self, user_id: uuid.UUID, wf: WatchedFolder, *, notify: bool = False) -> ScanResult:
        res = ScanResult()
        root = Path(wf.path).expanduser()
        if not root.is_absolute() or not await asyncio.to_thread(root.is_dir):
            res.error = "Folder not found."
            return res
        root = root.resolve()
        settings = get_settings()
        max_bytes = settings.max_upload_mb * 1024 * 1024
        project = " ".join(wf.project.split())
        files = await asyncio.to_thread(_walk, root)
        first_scan = not any(k[0] == user_id and k[1] == wf.path for k in self._stat)
        storage = Path(settings.upload_dir).resolve() / str(user_id)
        storage.mkdir(parents=True, exist_ok=True)
        to_queue: list[uuid.UUID] = []
        seen: set[str] = set()

        async with SessionLocal() as db:
            existing = {d.source: d for d in await db.scalars(select(Document).where(
                Document.user_id == user_id, Document.project == project, Document.watch_root == str(root)))}
            for rel, path in files:
                try:
                    source = clean_source(rel)
                    st = path.stat()
                except (UploadRejected, OSError):
                    res.skipped += 1
                    continue
                seen.add(source)
                stat_key = (user_id, wf.path, source)
                sig = (int(st.st_mtime), st.st_size)
                doc = existing.get(source)
                if doc is not None and self._stat.get(stat_key) == sig:
                    continue  # unchanged since the last scan; skip hashing
                try:
                    file_type, data = await asyncio.to_thread(_read_checked, source, path, max_bytes)
                except (UploadRejected, OSError):
                    res.skipped += 1
                    continue
                self._stat[stat_key] = sig
                digest = hashlib.sha256(data).hexdigest()
                if doc is not None and doc.sha256 == digest and doc.status != "failed":
                    continue
                if doc is None:
                    doc = Document(user_id=user_id, project=project, title=Path(source).name[:300], source=source,
                                   file_type=file_type, sha256=digest, size_bytes=len(data), status="pending",
                                   storage_path="", chunk_count=0, watch_root=str(root))
                    db.add(doc)
                    await db.flush()
                    res.added.append(source)
                else:
                    res.updated.append(source)
                dest = storage / f"{doc.id}.bin"
                await asyncio.to_thread(dest.write_bytes, data)
                doc.storage_path, doc.sha256, doc.size_bytes, doc.status, doc.error = str(dest), digest, len(data), "pending", None
                to_queue.append(doc.id)
            for source, doc in existing.items():
                if source not in seen:
                    res.removed.append(source)
                    await asyncio.to_thread(Path(doc.storage_path).unlink, missing_ok=True)
                    await db.delete(doc)
            await db.commit()
        for doc_id in to_queue:
            self.ingestor.enqueue(doc_id)
        if res.changed:
            log.info("watched folder changed", extra={"project": project, "added": len(res.added),
                                                      "updated": len(res.updated), "removed": len(res.removed)})
        if notify and res.changed and not first_scan:
            await self.notifier.notify(user_id, "folder", f"{project}: files changed", _describe(res),
                                       data={"project": project, "path": wf.path}, respect_quiet=True)
        return res


def _describe(r: ScanResult) -> str:
    parts = []
    for label, items in (("Updated", r.updated), ("New", r.added), ("Removed", r.removed)):
        if items:
            shown = ", ".join(items[:5]) + (f" and {len(items) - 5} more" if len(items) > 5 else "")
            parts.append(f"{label}: {shown}")
    return "\n".join(parts) + "\nThe knowledge base has been updated."
