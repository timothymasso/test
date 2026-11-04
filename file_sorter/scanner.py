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
from .analysis import Assessment, Settings, assess, human_size

SKIP_LINUX_ROOTS = {"/proc", "/sys", "/dev", "/run"}

# Windows file attributes
REPARSE_POINT = 0x400  # junctions and other links (is_junction() only exists on Python 3.12+)
ONLINE_ONLY = 0x400000 | 0x40000 | 0x1000  # OneDrive/cloud placeholders: reading them downloads them

# Folder names that hold a program's DLLs one or two levels below its real install folder.
BIN_DIRS = {"bin", "bin32", "bin64", "x64", "x86", "win64", "win32", "binaries", "lib", "plugins"}
USER_FOLDERS = {"downloads", "desktop", "documents", "pictures", "videos", "music", "movies"}


@dataclass
class FileEntry:
    path: str
    size: int
    mtime: float
    atime: float
    assessment: Assessment
    duplicate_of: str | None = None
    online_only: bool = False

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
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                        if not attrs & REPARSE_POINT:
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
                f = FileEntry(entry.path, size, st.st_mtime, st.st_atime, a)
                if getattr(st, "st_file_attributes", 0) & ONLINE_ONLY:
                    f.online_only = True
                    a.verdict = kb.KEEP
                    a.reason = ("Online-only cloud file: it's listed here but stored in the cloud, so it "
                                "takes (almost) no space on this drive.")
                result.files.append(f)
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
    protect_program_folders(result.files, root)

    if find_duplicates and not result.cancelled:
        if progress:
            progress(len(result.files), seen_bytes, "Looking for duplicate files...")
        n_files, last = len(result.files), [0.0]

        def dupe_progress(done: int, total: int) -> None:
            if progress and time.time() - last[0] > 0.2:
                last[0] = time.time()
                progress(n_files, seen_bytes,
                         f"Comparing possible duplicates: {human_size(done)} of {human_size(total)} read")

        mark_duplicates(result.files, cancel, progress=dupe_progress)
        result.cancelled = cancel.is_set()

    result.seconds = time.time() - start
    return result


# ---------------------------------------------------------------------------
# Installed programs outside the well-known folders (games on D:, portable apps)
# ---------------------------------------------------------------------------

def protect_program_folders(files: list[FileEntry], scan_root: str) -> int:
    """A folder that holds DLLs is an installed program: nothing under its install folder
    should be suggested for deleting or moving by hand. Returns the number of files changed."""
    roots = set()
    for f in files:
        if f.path.lower().endswith(".dll"):
            d = os.path.dirname(f.path)
            while os.path.basename(d).lower() in BIN_DIRS and os.path.dirname(d) != d:
                d = os.path.dirname(d)
            if d != scan_root and os.path.dirname(d) != d and os.path.basename(d).lower() not in USER_FOLDERS:
                roots.add(os.path.join(d, ""))
    if not roots:
        return 0
    changed = 0
    for f in files:
        a = f.assessment
        if a.verdict in (kb.KEEP, kb.SYSTEM):
            continue
        # explicit temp/trash folders stay deletable even if an installer unpacked DLLs there
        if a.location and a.location.verdict == kb.DELETE and a.location.fragment not in kb.GENERIC_CACHE_FRAGMENTS:
            continue
        d = os.path.dirname(f.path)
        while True:
            if os.path.join(d, "") in roots:
                a.verdict, a.protected = kb.KEEP, True
                a.reason = (f"Part of a program installed in {d}. Uninstall the program, or use its own "
                            "'move' option, instead of deleting or moving its files by hand.")
                changed += 1
                break
            parent = os.path.dirname(d)
            if parent == d or len(parent) < len(scan_root):
                break
            d = parent
    return changed


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------

SAMPLE = 64 * 1024
CHUNK = 4 * 1024 * 1024


def _sample_hash(path: str, size: int) -> str | None:
    """Hash the start, middle and end of a file: one quick read that tells most look-alikes apart."""
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            for offset in sorted({0, max(0, size // 2 - SAMPLE // 2), max(0, size - SAMPLE)}):
                f.seek(offset)
                h.update(f.read(SAMPLE))
    except OSError:
        return None
    return h.hexdigest()


def _full_hash(path: str, cancel: threading.Event | None, on_bytes) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK):
                if cancel and cancel.is_set():
                    return None
                h.update(chunk)
                on_bytes(len(chunk))
    except OSError:
        return None
    return h.hexdigest()


def mark_duplicates(files: list[FileEntry], cancel: threading.Event | None = None,
                    min_size: int = 1024 * 1024, progress=None) -> int:
    """Find identical files (>= min_size). All copies except the oldest get a REVIEW verdict.

    Same size -> same start/middle/end -> same full contents. Only files that pass the cheap
    checks are read completely. progress(done_bytes, total_bytes) reports the full reads.
    Returns the number of files marked as duplicates.
    """
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for f in files:
        # only personal files: identical DLLs in two games are both needed
        if (f.size >= min_size and f.verdict in (kb.KEEP, kb.MOVE) and not f.online_only
                and f.assessment.kind in kb.PERSONAL_KINDS and not f.assessment.protected):
            by_size[f.size].append(f)

    candidates: list[list[FileEntry]] = []
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        if cancel and cancel.is_set():
            return 0
        by_sample: dict[str, list[FileEntry]] = defaultdict(list)
        for f in _drop_hard_links(group):
            h = _sample_hash(f.path, size)
            if h:
                by_sample[h].append(f)
        candidates += [g for g in by_sample.values() if len(g) > 1]

    total = sum(f.size for g in candidates for f in g)
    done = 0

    def on_bytes(n: int) -> None:
        nonlocal done
        done += n
        if progress:
            progress(done, total)

    marked = 0
    for group in candidates:
        by_full: dict[str, list[FileEntry]] = defaultdict(list)
        for f in group:
            h = _full_hash(f.path, cancel, on_bytes)
            if cancel and cancel.is_set():
                return marked
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


def _drop_hard_links(group: list[FileEntry]) -> list[FileEntry]:
    """Hard links are one file with two names; deleting one frees nothing."""
    seen, out = set(), []
    for f in group:
        try:
            st = os.stat(f.path)  # DirEntry.stat() has no inode number on Windows
            key = (st.st_dev, st.st_ino) if st.st_ino else f.path
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
