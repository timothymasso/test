"""Decide what to do with a file and explain what it is."""

from __future__ import annotations

import fnmatch
import functools
import os
import re
import string
import sys
import time
from dataclasses import dataclass, field

from . import knowledge as kb

MB = 1024 * 1024
GB = 1024 * MB
DAY = 86400

# short aliases (keeps the rules readable)
DELETE_, REVIEW_, MOVE_, SYSTEM_, KEEP = kb.DELETE, kb.REVIEW, kb.MOVE, kb.SYSTEM, kb.KEEP


@dataclass
class Settings:
    move_media_mb: int = 50       # media/archives at least this big are suggested for moving
    move_any_mb: int = 500        # any (non-program) file at least this big is suggested for moving
    stale_days: int = 365         # files untouched this long ...
    stale_min_mb: int = 20        # ... and at least this big are suggested for moving
    old_log_days: int = 30        # logs older than this are safe to delete
    never_touch: tuple[str, ...] = ()  # folders the user asked to leave alone


@dataclass(frozen=True)
class FolderMatch:
    fragment: str
    label: str
    what: str
    verdict: str
    why: str


@dataclass
class Assessment:
    verdict: str
    reason: str
    kind: str
    type_desc: str
    location: FolderMatch | None = None
    contexts: list[FolderMatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    protected: bool = False  # belongs to an installed game/program

    @property
    def kind_label(self) -> str:
        return kb.KINDS.get(self.kind, "Other")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def normalized_dir(path: str) -> str:
    """'C:\\Users\\Me\\AppData\\file.txt' -> '/users/me/appdata/' (drive removed)."""
    p = path.replace("\\", "/").lower()
    p = p.rsplit("/", 1)[0] if "/" in p else ""
    if len(p) >= 2 and p[1] == ":" and p[0] in string.ascii_lowercase:
        p = p[2:]
    if p.startswith("//"):  # UNC path: //server/share/...
        parts = p.split("/")
        p = "/" + "/".join(parts[4:])
    if not p.startswith("/"):
        p = "/" + p
    if not p.endswith("/"):
        p += "/"
    return p


def base_name(path: str) -> str:
    """File name for both Windows and POSIX style paths."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _in_any(path: str, prefixes: tuple[str, ...]) -> bool:
    d = normalized_dir(path)
    return any(d.startswith(p[1:]) if p.startswith("^") else p in d for p in prefixes)


def match_folders(path: str) -> list[FolderMatch]:
    return list(_match_dir(normalized_dir(path)))


@functools.lru_cache(maxsize=8192)
def _match_dir(d: str) -> tuple[FolderMatch, ...]:
    return tuple(FolderMatch(frag, label, what, verdict, why)
                 for frag, label, what, verdict, why in kb.FOLDER_RULES
                 if (d.startswith(frag[1:]) if frag.startswith("^") else frag in d))


def extension_of(name: str) -> str:
    low = name.lower()
    for double in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"):
        if low.endswith(double):
            return ".tgz"
    return os.path.splitext(low)[1]


GAME_ANCHORS = [(("steamapps", "common"), "Steam game"), (("epic games",), "Epic game"),
                (("gog games",), "GOG game"), (("xboxgames",), "Xbox game")]


NOT_GAMES = {"launcher", "epic online services", "directxredist", "steamworks shared", "steam controller configs"}


def owning_app(path: str) -> str | None:
    """Guess which program a file belongs to from its folder."""
    p = path.replace("\\", "/")
    return _owning_app_dir(p.rsplit("/", 1)[0] if "/" in p else "")


@functools.lru_cache(maxsize=65536)
def _owning_app_dir(folder: str) -> str | None:
    parts = folder.split("/") + ["x"]  # 'x' stands for the file itself
    low = [p.lower() for p in parts]
    for anchor, label in GAME_ANCHORS:  # games: name the game itself
        n = len(anchor)
        for i in range(len(low) - n - 1):
            if tuple(low[i:i + n]) == anchor and low[i + n] not in NOT_GAMES:
                return f"{label}: {parts[i + n]}"
    d = normalized_dir(folder + "/x")
    for frag, app in kb.APP_PATHS:
        if frag in d:
            return app
    anchors = [
        ("program files",), ("program files (x86)",), ("programdata",),
        ("appdata", "local"), ("appdata", "roaming"), ("appdata", "locallow"),
        ("applications",), ("library", "application support"), ("library", "caches"),
        ("steamapps", "common"), ("opt",), (".config",), (".cache",), (".local", "share"),
    ]
    for anchor in anchors:
        n = len(anchor)
        for i in range(len(low) - n):
            if tuple(low[i:i + n]) == anchor and i + n < len(low) - 1:
                folder = parts[i + n]
                nice = kb.KNOWN_APPS.get(folder.lower())
                if folder.lower() in ("microsoft", "google", "packages") and i + n + 1 < len(low) - 1:
                    sub = parts[i + n + 1]
                    return f"{nice or folder} -> {sub}"
                return nice or folder
    return None


# ---------------------------------------------------------------------------
# Content sniffing
# ---------------------------------------------------------------------------

def sniff(path: str) -> tuple[str, str] | None:
    """Look at the first bytes of the file to identify its real type."""
    try:
        with open(path, "rb") as f:
            head = f.read(0x8010)
    except OSError:
        return None
    for magic, offset, desc, kind in kb.MAGIC:
        if head[offset:offset + len(magic)] == magic:
            return desc, kind
    if head and is_probably_text(head[:4096]):
        return "Plain text", "text"
    return None


def is_probably_text(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        # UTF-16 text has lots of NULs; accept it if there's a BOM
        return data[:2] in (b"\xff\xfe", b"\xfe\xff")
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in data)
    return printable / len(data) > 0.9


def text_preview(path: str, max_lines: int = 15, max_bytes: int = 4096) -> str | None:
    try:
        with open(path, "rb") as f:
            data = f.read(max_bytes)
    except OSError:
        return None
    if not is_probably_text(data):
        return None
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.splitlines()[:max_lines]
    return "\n".join(line[:160] for line in lines)


def windows_version_info(path: str) -> dict[str, str]:
    """Read the description/company/product embedded in a Windows EXE or DLL."""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version")
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        ver.GetFileVersionInfoW.restype = wintypes.BOOL
        ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        ver.VerQueryValueW.restype = wintypes.BOOL

        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return {}
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return {}

        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        langs = []
        if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) \
                and length.value >= 4:
            words = (ctypes.c_ushort * (length.value // 2)).from_address(ptr.value)
            for i in range(0, len(words) - 1, 2):
                langs.append(f"{words[i]:04x}{words[i + 1]:04x}")
        langs += ["040904b0", "040904e4", "000004b0"]

        out = {}
        for key in ("FileDescription", "ProductName", "CompanyName", "FileVersion", "OriginalFilename"):
            for lang in langs:
                q = f"\\StringFileInfo\\{lang}\\{key}"
                if ver.VerQueryValueW(buf, q, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
                    value = ctypes.wstring_at(ptr.value, length.value).rstrip("\x00").strip()
                    if value:
                        out[key] = value
                        break
        return out
    except Exception:
        return {}


INSTALLER_WORDS = ("setup", "install", "installer", "_x64", "-x64", "win64", "win32", "amd64", "update")


def looks_like_installer(name: str, version_info: dict[str, str] | None = None) -> bool:
    low = name.lower()
    if any(w in low for w in INSTALLER_WORDS):
        return True
    if version_info:
        desc = (version_info.get("FileDescription", "") + " " + version_info.get("ProductName", "")).lower()
        return "setup" in desc or "install" in desc
    return False


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

CLOUD_LABELS = {"OneDrive", "Dropbox", "Google Drive", "iCloud Drive"}
GAME_LABELS = {"Steam game", "Epic Games game", "Xbox / Game Pass game", "GOG game"}


def hidden_app_folder(path: str) -> str | None:
    """Name of a hidden (dot) settings folder the file is inside, e.g. '.vscode'."""
    return _hidden_in(normalized_dir(path))


@functools.lru_cache(maxsize=65536)
def _hidden_in(d: str) -> str | None:
    for seg in d.split("/"):
        if seg.startswith(".") and seg not in kb.HIDDEN_OK and seg not in (".", ".."):
            return seg
    return None


def assess(path: str, size: int, mtime: float, atime: float,
           settings: Settings | None = None, now: float | None = None) -> Assessment:
    s = settings or Settings()
    now = now or time.time()
    name = base_name(path)
    name_l = name.lower()
    ext = extension_of(name)
    kind, type_desc = kb.EXTENSIONS.get(ext, ("other", ""))

    matches = match_folders(path)
    primary = next((m for m in matches if m.label not in kb.CONTEXT_ONLY_LABELS), None)
    contexts = [m for m in matches if m.label in kb.CONTEXT_ONLY_LABELS]
    in_downloads = any(m.label == "Downloads" for m in contexts)
    in_cloud = any(m.label in CLOUD_LABELS for m in matches)
    in_game = primary is not None and primary.label in GAME_LABELS
    in_user_folder = bool(contexts) and not in_downloads  # Documents, Desktop, Pictures, Videos, Music

    last_used = max(mtime, atime)
    age_days = max(0.0, (now - last_used) / DAY)
    mod_age_days = max(0.0, (now - mtime) / DAY)

    a = Assessment(KEEP, "", kind, type_desc, primary, contexts)

    def done(verdict: str, reason: str) -> Assessment:
        a.verdict, a.reason = verdict, reason
        if in_cloud and verdict in (DELETE_, REVIEW_, MOVE_):
            a.warnings.append("This file is in a cloud-synced folder: deleting or moving it here also "
                              "removes it from the cloud and your other devices.")
        return a

    known = kb.KNOWN_FILES.get(name_l)
    # system folders win over well-known names (an app's own 'index.dat' is not IE's)
    if primary and primary.verdict == SYSTEM_ and not (known and known[1] == SYSTEM_):
        return done(SYSTEM_, f"Inside '{primary.label}': {primary.why}")

    if known:
        what, verdict, why = known
        a.type_desc = what
        return done(verdict, why)

    for pattern, what, verdict, why, max_size, where in kb.KNOWN_PATTERNS:
        hit = re.fullmatch(pattern[3:], name_l) if pattern.startswith("re:") else fnmatch.fnmatchcase(name_l, pattern)
        if (hit and (max_size is None or size <= max_size)
                and (where is None or _in_any(path, where))):
            a.type_desc = what
            # a name-only match in your own folders could be something you saved on purpose
            if verdict == DELETE_ and max_size is None and where is None and in_user_folder:
                return done(REVIEW_, f"{why} It's in one of your own folders, so check it first.")
            return done(verdict, why)

    if in_game:
        a.protected = True
        return done(KEEP, f"Part of an installed game. {primary.why}")

    if primary and primary.verdict == DELETE_:
        d = normalized_dir(path)
        generic = primary.fragment in kb.GENERIC_CACHE_FRAGMENTS and not any(m in d for m in kb.APP_DATA_MARKERS)
        in_trash = primary.label in ("Recycle Bin", "Trash")  # already deleted once by the user
        # Windows' own folders never hold personal files (any other folder name can, on any drive)
        windows_owned = primary.fragment.startswith(("^/windows/", "^/$", "^/programdata/"))
        if (kind in kb.PERSONAL_KINDS and not (in_trash or windows_owned)) or generic:
            return done(REVIEW_, f"It's in a folder called '{primary.label}', but this looks like a real file, "
                                 "not program-generated junk. Check before deleting.")
        return done(DELETE_, f"Inside '{primary.label}': {primary.why}")

    hidden = hidden_app_folder(path)
    if hidden:
        return done(SYSTEM_, f"Inside the hidden folder '{hidden}', where a program keeps its settings and data. "
                             "Remove it through that program instead.")

    if kind == "partial_download":
        if mod_age_days < 1:
            return done(REVIEW_, "Unfinished download that changed in the last day; it may still be downloading.")
        return done(DELETE_, "A download that never finished. The file is incomplete and can't be used.")

    if kind in ("temp", "dump", "cache") and in_user_folder:
        return done(REVIEW_, "Looks like a leftover from a program, but it's in one of your own folders, so "
                             "check it first.")
    if kind in ("temp", "dump", "cache"):
        return done(DELETE_, {"temp": "Temporary leftover from a program.",
                              "dump": "Crash dump; only useful for debugging an old crash.",
                              "cache": "Cache/build file that gets recreated automatically."}[kind])

    if kind == "log":
        if mod_age_days > s.old_log_days and in_user_folder:
            return done(REVIEW_, f"Old log file (not written to in {int(mod_age_days)} days). It's in one of your "
                                 "own folders, so it could be something you saved on purpose (like chat logs).")
        if mod_age_days > s.old_log_days:
            return done(DELETE_, f"Log file not written to in {int(mod_age_days)} days. "
                                 "Logs are only needed for troubleshooting.")
        return done(KEEP, "Log file that's still being written to.")

    if primary and primary.verdict == REVIEW_:
        return done(REVIEW_, f"Inside '{primary.label}': {primary.why}")

    if kind == "installer":
        return done(REVIEW_, "Installer package. Once the program is installed you normally don't need "
                             "the installer anymore (you can download it again).")

    if kind == "executable" and in_downloads and looks_like_installer(name):
        return done(REVIEW_, "Looks like a downloaded installer (setup program). If you already installed "
                             "the program, you can delete this.")

    if kind in kb.UNMOVABLE_KINDS:
        return done(KEEP, "Program file. If you don't need the program, uninstall it properly instead.")

    if kind == "vm":
        return done(KEEP, "Virtual machine disk. Move or delete it from inside the virtual machine app "
                          "(VirtualBox, VMware, Hyper-V) so the app knows where it went.")
    if kind == "email":
        return done(KEEP, "Mailbox data. Move it from inside Outlook (or your mail app); moving the file "
                          "by hand can make the mailbox disappear.")

    if kind == "backup":
        return done(REVIEW_, "Backup / old copy of another file. Delete it if the original is fine.")

    if in_downloads and kind in ("archive", "disk_image") and size >= MB:
        return done(REVIEW_, "Downloaded archive/disk image. If you already extracted or used it, "
                             "it's just a second copy. Otherwise move it to your other drive.")

    if kind in kb.MOVABLE_KINDS and size >= s.move_media_mb * MB:
        return done(MOVE_, f"Large {a.kind_label.lower()} file ({human_size(size)}). Personal files like "
                           "this don't need to be on your main drive.")

    movable = kind in kb.PERSONAL_KINDS or kind == "other"
    if movable and size >= s.move_any_mb * MB:
        return done(MOVE_, f"Very large file ({human_size(size)}). Good candidate for your other drive.")

    if movable and age_days > s.stale_days and size >= s.stale_min_mb * MB:
        return done(MOVE_, f"Not used in {int(age_days)} days and {human_size(size)} in size. "
                           "Archive it on your other drive.")

    if in_cloud:
        return done(KEEP, "Cloud-synced file.")
    if primary and primary.verdict == KEEP and primary.why:
        return done(KEEP, primary.why)
    return done(KEEP, "Nothing suggests this file is unneeded, and it's not big enough to bother moving.")


# ---------------------------------------------------------------------------
# Explanation for the details panel
# ---------------------------------------------------------------------------

def human_size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_age(ts: float, now: float | None = None) -> str:
    now = now or time.time()
    days = (now - ts) / DAY
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    if days < 1:
        rel = "today"
    elif days < 2:
        rel = "yesterday"
    elif days < 60:
        rel = f"{int(days)} days ago"
    elif days < 730:
        rel = f"{int(days / 30)} months ago"
    else:
        rel = f"{days / 365:.1f} years ago"
    return f"{stamp} ({rel})"


def explain(path: str, assessment: Assessment, size: int, mtime: float, atime: float,
            duplicate_of: str | None = None, read_contents: bool = True) -> list[tuple[str, str]]:
    """Return (heading, text) sections describing the file.

    read_contents=False skips peeking inside (reading a cloud placeholder downloads it)."""
    sections: list[tuple[str, str]] = []
    name = base_name(path)
    ext = extension_of(name)

    # --- What it is
    what = []
    if assessment.type_desc:
        what.append(assessment.type_desc)
    else:
        what.append(f"Unknown file type ({ext or 'no extension'}).")

    sniffed = sniff(path) if read_contents else None
    if sniffed:
        desc, s_kind = sniffed
        if assessment.kind == "other":
            what.append(f"Looking inside, it's actually: {desc}.")
        elif s_kind == "executable" and assessment.kind not in ("executable", "library", "driver", "installer"):
            what.append(f"Warning: the contents look like a {desc}, but the name says otherwise. "
                        "Files pretending to be something else can be malware.")

    info = windows_version_info(path) if read_contents and assessment.kind in ("executable", "library", "driver", "installer") else {}
    if info:
        bits = []
        if info.get("FileDescription"):
            bits.append(f"Description: {info['FileDescription']}")
        if info.get("ProductName"):
            bits.append(f"Product: {info['ProductName']}")
        if info.get("CompanyName"):
            bits.append(f"Made by: {info['CompanyName']}")
        if info.get("FileVersion"):
            bits.append(f"Version: {info['FileVersion']}")
        if bits:
            what.append("Built-in program info:\n  " + "\n  ".join(bits))
        if assessment.kind == "executable" and looks_like_installer(name, info):
            what.append("This looks like an installer/setup program rather than the app itself.")
    sections.append(("What it is", "\n".join(what)))

    # --- Where it lives
    where = []
    if assessment.location:
        where.append(f"{assessment.location.label}: {assessment.location.what}")
    for c in assessment.contexts:
        if not assessment.location or c.label != assessment.location.label:
            where.append(f"{c.label}: {c.what}")
    app = owning_app(path)
    if app:
        where.append(f"Belongs to: {app}")
    if not where:
        where.append("A regular folder with no special meaning.")
    where.append(f"Folder: {os.path.dirname(path)}")
    sections.append(("Where it lives", "\n".join(where)))

    # --- Verdict
    verdict = [f"{assessment.verdict}", assessment.reason]
    if duplicate_of:
        verdict.append(f"Exact duplicate of: {duplicate_of}")
    for w in assessment.warnings:
        verdict.append(f"Warning: {w}")
    verdict.append("")
    verdict.append(kb.VERDICT_HELP[assessment.verdict])
    sections.append(("Recommendation", "\n".join(verdict)))

    # --- Facts
    facts = [
        f"Size: {human_size(size)} ({size:,} bytes)",
        f"Last modified: {human_age(mtime)}",
        f"Last opened: {human_age(atime)}" + ("  (may be inaccurate: some systems don't track this)"
                                               if abs(atime - mtime) < 1 else ""),
        f"Type: {assessment.kind_label}",
    ]
    sections.append(("Details", "\n".join(facts)))

    # --- Peek
    if read_contents and assessment.kind in ("text", "config", "log", "code", "script", "spreadsheet", "other") \
            and size < 50 * MB:
        preview = text_preview(path)
        if preview:
            sections.append(("First lines of the file", preview))

    return sections
