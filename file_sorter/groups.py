"""Group files by what they belong to: an app's cache, a game, your photos from 2021, installers..."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import knowledge as kb
from .analysis import base_name, hidden_app_folder, looks_like_installer, owning_app

JUNK_KINDS = {
    "temp": ("Temporary files", "Leftovers programs created while working and forgot to remove."),
    "cache": ("Cache and build files", "Files programs recreate automatically when needed."),
    "dump": ("Crash dumps and reports", "Memory snapshots and reports saved when something crashed."),
    "log": ("Old log files", "Diaries programs keep about what they did; only useful for troubleshooting."),
    "partial_download": ("Unfinished downloads", "Downloads that never completed; the files are incomplete."),
}
PREFIX_WITH_APP = kb.GENERIC_CACHE_FRAGMENTS | {"/node_modules/", "/__pycache__/", "/.pytest_cache/", "/temp/"}
PERSONAL = {
    "document": ("Documents", "Your documents, spreadsheets, presentations and e-books."),
    "spreadsheet": ("Documents", "Your documents, spreadsheets, presentations and e-books."),
    "presentation": ("Documents", "Your documents, spreadsheets, presentations and e-books."),
    "ebook": ("Documents", "Your documents, spreadsheets, presentations and e-books."),
    "text": ("Documents", "Your documents, spreadsheets, presentations and e-books."),
    "audio": ("Music and audio", "Songs, recordings and other audio."),
    "archive": ("Archives and disk images", "ZIP files, ISOs and other bundles of files."),
    "disk_image": ("Archives and disk images", "ZIP files, ISOs and other bundles of files."),
    "backup": ("Backups and old copies", "Backup copies programs or you made of other files."),
    "design": ("Design and video projects", "Projects from Photoshop, Premiere, Blender and similar apps."),
    "vm": ("Virtual machines", "Virtual computers' disks (VirtualBox, VMware, Hyper-V, WSL)."),
    "email": ("Email", "Mailboxes and saved emails."),
    "code": ("Code", "Source code files."),
}


@dataclass
class Group:
    key: str
    title: str
    what: str
    files: list = field(default_factory=list)
    by_verdict: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return sum(self.by_verdict.values())

    @property
    def deletable(self) -> int:
        return self.by_verdict.get(kb.DELETE, 0) + self.by_verdict.get(kb.REVIEW, 0)

    @property
    def movable(self) -> int:
        return self.by_verdict.get(kb.MOVE, 0)

    @property
    def main_verdict(self) -> str:
        """The suggestion that covers most of this group's bytes (ties go to the safer one)."""
        if not self.by_verdict:
            return kb.KEEP
        order = [kb.SYSTEM, kb.KEEP, kb.MOVE, kb.REVIEW, kb.DELETE]  # safest first
        return max(order, key=lambda v: (self.by_verdict.get(v, 0), -order.index(v)))


def group_of(f) -> tuple[str, str, str]:
    """(key, title, what it is) for one file."""
    a = f.assessment
    if f.duplicate_of:
        return "dupes", "Duplicate copies", "Extra copies of files you already have elsewhere. The original is kept."
    app = owning_app(f.path)
    loc = a.location
    if loc and loc.verdict in (kb.DELETE, kb.REVIEW) and loc.label not in kb.CONTEXT_ONLY_LABELS:
        # generic folder names ("Cache folder") get the app's name in front; specific ones stand alone
        title = f"{app}: {loc.label}" if app and loc.fragment in PREFIX_WITH_APP else loc.label
        return f"loc:{title}", title, loc.what
    if a.verdict in (kb.DELETE, kb.REVIEW) and (a.kind in JUNK_KINDS or a.verdict == kb.DELETE):
        title, what = JUNK_KINDS.get(a.kind, JUNK_KINDS["temp"])
        if app:
            return f"junk:{app}:{a.kind}", f"{app}: {title.lower()}", what
        return f"junk:{a.kind}", title, what
    if a.kind == "installer" or (a.kind == "executable" and a.verdict in (kb.DELETE, kb.REVIEW)
                                 and looks_like_installer(base_name(f.path))):
        return "installers", "Installers", "Setup programs you downloaded. Once a program is installed, " \
                                           "you don't need its installer."
    if a.reason.startswith("Left over from"):
        return f"leftover:{app or ''}", f"Leftovers: {app}" if app else "Leftover app data", \
            "Data from programs that no longer seem to be installed."
    if app:
        if app.startswith(("Steam game:", "Epic game:", "GOG game:", "Xbox game:")):
            return f"app:{app}", app, "An installed game. Uninstall or move it from its launcher."
        return f"app:{app}", app, f"Files that belong to {app}."
    hidden = hidden_app_folder(f.path)
    if hidden:
        return f"hidden:{hidden}", f"Program settings ({hidden})", "A hidden folder where a program keeps its " \
                                                                   "settings and data."
    if loc and loc.label not in kb.CONTEXT_ONLY_LABELS:
        return f"loc:{loc.label}", loc.label, loc.what
    if a.kind in ("video", "image", "raw_photo"):
        year = time.localtime(f.mtime).tm_year
        noun = "Videos" if a.kind == "video" else "Photos and pictures"
        return f"media:{a.kind == 'video'}:{year}", f"{noun} from {year}", \
            f"{noun} last changed in {year}. Older ones are good candidates for your other drive."
    if a.kind in PERSONAL:
        title, what = PERSONAL[a.kind]
        return f"kind:{title}", title, what
    if a.kind in ("executable", "library", "driver", "script"):
        return "programs", "Programs and tools", "Program files outside the usual install folders (portable apps, " \
                                                 "tools, scripts)."
    return "other", "Other files", "Files that don't fit any of the other groups."


def build_groups(files) -> list[Group]:
    groups: dict[str, Group] = {}
    for f in files:
        key, title, what = group_of(f)
        g = groups.get(key)
        if g is None:
            g = groups[key] = Group(key, title, what)
        g.files.append(f)
        g.by_verdict[f.verdict] = g.by_verdict.get(f.verdict, 0) + f.size
    # most space you can win back first, then biggest
    return sorted(groups.values(), key=lambda g: (g.deletable + g.movable, g.size), reverse=True)
