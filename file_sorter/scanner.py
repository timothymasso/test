"""Walk a folder/drive, assess every file, find duplicates and big folders."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import knowledge as kb
from .analysis import Assessment, Settings, assess

SKIP_LINUX_ROOTS = {"/proc", "/sys", "/dev", "/run"}


@dataclass
class FileEntry:
    path: str
    size: int
    mtime: float
    atime: float
    assessment: Assessment
    duplicate_of: str | None = None

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def verdict(self) -> str:
        return self.assessment.verdict


@dataclass
class ScanResult:
    root: str
    files: list[FileEntry] = field(default_factory=list)
    folder_sizes: dict[str, int] = field(default_factory=dict)
    folder_counts: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    seconds: float = 0.0
    cancelled: bool = False

    def totals(self) -> dict[str, tuple[int, int]]:
        """verdict -> (file count, total bytes)"""
        out = {v: [0, 0] for v in kb.VERDICTS}
        for f in self.files:
            out[f.verdict][0] += 1
            out[f.verdict][1] += f.size
        return {k: (v[0], v[1]) for k, v in out.items()}


ProgressFn = Callable[[int, int, str], None]  # (files seen, bytes seen, current folder)


def scan(root: str, settings: Settings | None = None, find_duplicates: bool = True,
         cancel: threading.Event | None = None, progress: ProgressFn | None = None) -> ScanResult:
    settings = settings or Settings()
    cancel = cancel or threading.Event()
    root = os.path.abspath(root)
    result = ScanResult(root=root)
    start = time.time()
    now = start
    folder_sizes: dict[str, int] = defaultdict(int)
    folder_counts: dict[str, int] = defaultdict(int)

    stack = [root]
    seen_bytes = 0
    last_report = 0.0
    while stack:
        if cancel.is_set():
            result.cancelled = True
            break
        folder = stack.pop()
        if folder in SKIP_LINUX_ROOTS:
            continue
        try:
            it = os.scandir(folder)
        except OSError:
            result.errors += 1
            continue
        local_bytes = 0
        local_count = 0
        with it:
            for entry in it:
                try:
                    if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    result.errors += 1
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                size = st.st_size
                a = assess(entry.path, size, st.st_mtime, st.st_atime, settings, now)
                result.files.append(FileEntry(entry.path, size, st.st_mtime, st.st_atime, a))
                local_bytes += size
                local_count += 1
        seen_bytes += local_bytes
        # add this folder's direct files to it and every parent up to the root
        if local_count:
            d = folder
            while True:
                folder_sizes[d] += local_bytes
                folder_counts[d] += local_count
                if d == root or len(d) <= len(root):
                    break
                parent = os.path.dirname(d)
                if parent == d:
                    break
                d = parent
        if progress and time.time() - last_report > 0.15:
            last_report = time.time()
            progress(len(result.files), seen_bytes, folder)

    result.folder_sizes = dict(folder_sizes)
    result.folder_counts = dict(folder_counts)

    if find_duplicates and not result.cancelled:
        if progress:
            progress(len(result.files), seen_bytes, "Looking for duplicate files...")
        mark_duplicates(result.files, cancel)

    result.seconds = time.time() - start
    return result


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------

def _hash(path: str, limit: int | None = None) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            remaining = limit
            while True:
                chunk = f.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
                if not chunk:
                    break
                h.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
    except OSError:
        return None
    return h.hexdigest()


def mark_duplicates(files: list[FileEntry], cancel: threading.Event | None = None,
                    min_size: int = 1024 * 1024) -> int:
    """Find identical files (>= min_size). All copies except the oldest get a REVIEW verdict.

    Returns the number of files marked as duplicates.
    """
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for f in files:
        if f.size >= min_size and f.verdict not in (kb.SYSTEM, kb.DELETE):
            by_size[f.size].append(f)

    marked = 0
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        if cancel and cancel.is_set():
            break
        by_head: dict[str, list[FileEntry]] = defaultdict(list)
        for f in group:
            h = _hash(f.path, 64 * 1024)
            if h:
                by_head[h].append(f)
        for head_group in by_head.values():
            if len(head_group) < 2:
                continue
            by_full: dict[str, list[FileEntry]] = defaultdict(list)
            for f in head_group:
                h = _hash(f.path) if size > 64 * 1024 else "same"
                if h:
                    by_full[h].append(f)
            for dupes in by_full.values():
                if len(dupes) < 2:
                    continue
                dupes.sort(key=lambda f: (f.mtime, len(f.path)))
                original = dupes[0]
                for copy in dupes[1:]:
                    copy.duplicate_of = original.path
                    a = copy.assessment
                    if a.verdict in (kb.KEEP, kb.MOVE):
                        a.verdict = kb.REVIEW
                        a.reason = (f"Exact duplicate of another file ({os.path.basename(original.path)}). "
                                    "You only need one copy.")
                    marked += 1
    return marked
