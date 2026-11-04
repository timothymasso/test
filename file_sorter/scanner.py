"""Walk a folder/drive, assess every file, find duplicates and big folders."""

from __future__ import annotations

import hashlib
import heapq
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
    pre_dup: tuple[str, str] | None = None  # verdict and reason before it was marked a duplicate
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
    duplicates_checked: bool = False
    # space map index: folder -> verdict -> bytes (direct files / including subfolders), and subfolders
    map_root: str = ""
    by_dir: dict[str, dict[str, int]] = field(default_factory=dict)
    breakdown: dict[str, dict[str, int]] = field(default_factory=dict)
    subfolders: dict[str, set[str]] = field(default_factory=dict)

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

        def dupe_progress(message: str) -> None:
            if progress and time.time() - last[0] > 0.2:
                last[0] = time.time()
                progress(n_files, seen_bytes, message)

        mark_duplicates(result.files, cancel, progress=dupe_progress)
        result.cancelled = cancel.is_set()
        result.duplicates_checked = not result.cancelled

    build_index(result)

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
MAX_OPEN = 64  # compare at most this many same-looking files side by side


def _read_at(path: str, offsets: tuple[int, ...]) -> bytes | None:
    try:
        with open(path, "rb") as f:
            out = b""
            for off in offsets:
                f.seek(off)
                out += f.read(SAMPLE)
            return hashlib.blake2b(out, digest_size=20).digest()
    except OSError:
        return None


def _split(group: list[FileEntry], key) -> list[list[FileEntry]]:
    buckets: dict[object, list[FileEntry]] = defaultdict(list)
    for f in group:
        k = key(f)
        if k is not None:
            buckets[k].append(f)
    return [g for g in buckets.values() if len(g) > 1]


def _identical(group: list[FileEntry], cancel, on_bytes) -> list[list[FileEntry]]:
    """Read same-size files side by side, chunk by chunk, dropping each one the moment it differs."""
    if len(group) > MAX_OPEN:  # too many to keep open at once: split by a hash of the whole file
        def whole(f: FileEntry):
            h = hashlib.blake2b(digest_size=20)
            try:
                with open(f.path, "rb") as fh:
                    while chunk := fh.read(CHUNK):
                        if cancel and cancel.is_set():
                            return None
                        h.update(chunk)
                        on_bytes(len(chunk))
            except OSError:
                return None
            return h.digest()
        return _split(group, whole)

    handles = {}
    try:
        for f in group:
            try:
                handles[f.path] = open(f.path, "rb")
            except OSError:
                pass
        groups = [[f for f in group if f.path in handles]]
        done: list[list[FileEntry]] = []
        while groups:
            if cancel and cancel.is_set():
                return []
            nxt = []
            for g in groups:
                prints = {}  # path -> fingerprint of its next chunk; one chunk in memory at a time
                ended = True
                for f in g:
                    try:
                        chunk = handles[f.path].read(CHUNK)
                    except OSError:  # locked or vanished mid-read: just leave it out
                        continue
                    on_bytes(len(chunk))
                    ended = ended and not chunk
                    prints[f.path] = hashlib.blake2b(chunk, digest_size=20).digest()
                if ended and len(prints) > 1:  # all reached the end together: identical
                    done.append([f for f in g if f.path in prints])
                    continue
                nxt += _split(g, lambda f: prints.get(f.path))
            groups = nxt
        return done
    finally:
        for h in handles.values():
            h.close()


def mark_duplicates(files: list[FileEntry], cancel: threading.Event | None = None,
                    min_size: int = 1024 * 1024, progress=None) -> int:
    """Find identical files (>= min_size). All copies except the oldest get a REVIEW verdict.

    Same size -> same first 64 KB -> same middle and end -> same contents, compared side by
    side so that look-alikes stop being read as soon as they differ.
    progress(message) reports what's happening. Returns the number of files marked.
    """
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for f in files:
        # only personal files: identical DLLs in two games are both needed
        if (f.size >= min_size and f.verdict in (kb.KEEP, kb.MOVE) and not f.online_only
                and f.assessment.kind in kb.PERSONAL_KINDS and not f.assessment.protected):
            by_size[f.size].append(f)
    same_size = [_drop_hard_links(g) for g in by_size.values() if len(g) > 1]
    n_check = sum(len(g) for g in same_size)

    candidates: list[list[FileEntry]] = []
    checked = 0
    for group in same_size:
        if cancel and cancel.is_set():
            return 0
        size = group[0].size
        for g in _split(group, lambda f: _read_at(f.path, (0,))):
            candidates += _split(g, lambda f: _read_at(f.path, (size // 2, max(0, size - SAMPLE))))
        checked += len(group)
        if progress:
            progress(f"Looking for duplicates: checked {checked:,} of {n_check:,} same-size files")

    total = sum(f.size for g in candidates for f in g)
    done = 0

    def on_bytes(n: int) -> None:
        nonlocal done
        done += n
        if progress:
            progress(f"Comparing possible duplicates: {human_size(done)} of up to {human_size(total)} read")

    marked = 0
    for group in candidates:
        for dupes in _identical(group, cancel, on_bytes):
            if cancel and cancel.is_set():
                return marked
            dupes.sort(key=lambda f: (f.mtime, len(f.path)))
            original = dupes[0]
            for copy in dupes[1:]:
                _mark_copy(copy, original)
                marked += 1
    return marked


def _mark_copy(copy: FileEntry, original: FileEntry) -> None:
    a = copy.assessment
    if copy.pre_dup is None:
        copy.pre_dup = (a.verdict, a.reason)
    copy.duplicate_of = original.path
    a.verdict = kb.REVIEW
    a.reason = (f"Exact duplicate of another file ({os.path.basename(original.path)}). "
                "You only need one copy.")


def regroup_duplicates(files: list[FileEntry]) -> list[tuple[FileEntry, str]]:
    """After files were moved or deleted: a copy whose original is gone becomes the new original
    (getting its own verdict back), so the last copy of something is never labelled 'duplicate'.
    Returns (file, old_verdict) for every file whose verdict changed."""
    present = {f.path for f in files}
    orphans: dict[str, list[FileEntry]] = defaultdict(list)
    for f in files:
        if f.duplicate_of and f.duplicate_of not in present:
            orphans[f.duplicate_of].append(f)
    changed = []
    for group in orphans.values():
        group.sort(key=lambda f: (f.mtime, len(f.path)))
        heir = group[0]
        old = heir.verdict
        heir.duplicate_of = None
        if heir.pre_dup:
            heir.assessment.verdict, heir.assessment.reason = heir.pre_dup
            heir.pre_dup = None
        if heir.verdict != old:
            changed.append((heir, old))
        for copy in group[1:]:
            _mark_copy(copy, heir)
    return changed


# ---------------------------------------------------------------------------
# Space map index
# ---------------------------------------------------------------------------

def build_index(result: ScanResult) -> None:
    """Bytes per verdict for every folder (direct files, and including subfolders)."""
    # files directly in the scan root have this as their dirname ("C:\\", "\\\\nas\\share\\", "/x")
    root = result.map_root = os.path.dirname(os.path.join(result.root, "x"))
    by_dir: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f in result.files:
        by_dir[os.path.dirname(f.path)][f.verdict] += f.size
    breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    subfolders: dict[str, set[str]] = defaultdict(set)
    for d, vb in by_dir.items():
        for v, b in vb.items():
            breakdown[d][v] += b
    # roll up bottom-up: longest (deepest) paths first, each folder adds itself to its parent once
    heap = [(-len(d), d) for d in breakdown if d != root]
    heapq.heapify(heap)
    seen = {d for _, d in heap}
    while heap:
        _, d = heapq.heappop(heap)
        parent = os.path.dirname(d)
        if parent == d or len(parent) < len(root):
            continue
        subfolders[parent].add(d)
        agg = breakdown[parent]
        for v, b in breakdown[d].items():
            agg[v] += b
        if parent != root and parent not in seen:
            seen.add(parent)
            heapq.heappush(heap, (-len(parent), parent))
    result.by_dir, result.breakdown, result.subfolders = by_dir, breakdown, subfolders


def index_shift(result: ScanResult, f: FileEntry, old: str | None, new: str | None) -> None:
    """Move a file's bytes from verdict `old` to `new` (None = removed/added) in the index."""
    d = os.path.dirname(f.path)
    for v, sign in ((old, -1), (new, 1)):
        if v is None:
            continue
        if d in result.by_dir:
            result.by_dir[d][v] = result.by_dir[d].get(v, 0) + sign * f.size
        x = d
        while x in result.breakdown:
            result.breakdown[x][v] = result.breakdown[x].get(v, 0) + sign * f.size
            if x == result.map_root:
                break
            parent = os.path.dirname(x)
            if parent == x:
                break
            x = parent


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
