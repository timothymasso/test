"""Smarter checks that look at several files at once, or at what's installed on the PC.

* installers: older versions of the same installer, and installers for programs that are
  already installed, are safe to delete
* app data: folders under AppData that belong to programs that are no longer installed
"""

from __future__ import annotations

import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass

from . import knowledge as kb
from .analysis import base_name, looks_like_installer, windows_version_info


@dataclass(frozen=True)
class Program:
    name: str
    publisher: str = ""
    location: str = ""
    version: str = ""


def installed_programs() -> list[Program]:
    """Programs listed in Windows' 'Installed apps' (the uninstall registry keys). Empty elsewhere."""
    if sys.platform != "win32":
        return []
    import winreg

    keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    out = []
    for hive, path in keys:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                except OSError:
                    continue
                with sub:
                    def val(name: str) -> str:
                        try:
                            return str(winreg.QueryValueEx(sub, name)[0] or "")
                        except OSError:
                            return ""
                    if val("DisplayName"):
                        out.append(Program(val("DisplayName"), val("Publisher"), val("InstallLocation"),
                                           val("DisplayVersion")))
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# words that don't change which product an installer is for (architecture and edition DO, so they stay)
NOISE = {"setup", "installer", "install", "full", "offline", "online", "web", "latest", "release", "stable",
         "final", "enus", "en", "us", "user", "machine", "msi", "exe", "win", "windows"}
# only these are compared by version; others (.apk, .whl, .vsix...) are often a developer's own builds
SMART_INSTALLER_EXTS = (".exe", ".msi", ".msix", ".appx", ".dmg", ".pkg", ".deb", ".rpm")


ARCH = {"x64", "x86", "win64", "win32", "amd64", "arm64", "64bit", "32bit", "64", "32", "bit"}
GENERIC = {"driver", "drivers", "update", "updates", "setup", "app", "tool", "tools", "client", "program",
           "software", "patch", "install", "data", "file", "files"}


def product_key(file_name: str, with_arch: bool = True) -> str | None:
    """'vlc-3.0.20-win64.exe' -> 'vlc', 'ChromeSetup.exe' -> 'chrome'. None if nothing is left."""
    stem = os.path.splitext(file_name)[0].lower()
    stem = re.sub(r"(?<=[a-z])(?=\d{3,})", " ", stem)  # 7z2408 -> 7z 2408
    words = [w for w in re.split(r"[\s._\-()\[\]+]+", stem) if w]
    words = [re.sub(r"(user)?(setup|installer)$", "", w) or w for w in words]  # ChromeSetup -> chrome
    # drop dotted versions (3.0.20, v20.11.0) and short build numbers, but keep years (2023) and KB numbers:
    # TurboTax 2022 and 2023 are different products, not old and new versions of one
    keep = [w for w in words if w not in NOISE and (w == "7z" or not (
        re.fullmatch(r"v?\d+(\.\d+)+[a-z]?\d*", w) or (re.fullmatch(r"v?\d{1,3}", w) and w != "64")))]
    if not with_arch:
        keep = [w for w in keep if w not in ARCH]
    key = _norm("".join(keep))
    if len(key) < 2 or key in GENERIC:
        return None
    return key


def version_of(file_name: str) -> tuple[int, ...]:
    """The dotted version in a file name ('vlc-3.0.20-win64' -> (3, 0, 20)), or () if there is none."""
    m = re.findall(r"\d+(?:\.\d+)+", os.path.splitext(file_name)[0])
    best = max(m, key=lambda v: (v.count("."), len(v)), default="")
    return tuple(int(x) for x in best.split(".")) if best else ()


def _word_runs(name: str) -> set[str]:
    """'VLC media player' -> {'vlc', 'vlcmedia', 'vlcmediaplayer', 'media', 'mediaplayer', 'player'}"""
    words = re.findall(r"[a-z0-9]+", name.lower())
    return {"".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, len(words) + 1)}


def _matches_installed(names: list[str], installed: list[Program]) -> Program | None:
    """An installed program whose name contains the key as whole words ('chrome' in 'Google Chrome',
    but not 'git' in 'GitHub Desktop')."""
    for key in names:
        if not key or len(key) < 3:
            continue
        for p in installed:
            if key in _word_runs(p.name):
                return p
    return None


def smart_installers(files, installed: list[Program]) -> int:
    """Explain old installer versions and installers of installed programs.

    These stay 'Review', never 'Safe to delete': a guess about which installer is which must not feed
    the one-click Clean up (old versions of paid software often can't be downloaded again)."""
    candidates = [f for f in files if f.verdict == kb.REVIEW and not f.duplicate_of
                  and f.path.lower().endswith(SMART_INSTALLER_EXTS)
                  and (f.assessment.kind == "installer" or looks_like_installer(base_name(f.path)))]
    changed = 0
    groups = defaultdict(list)
    for f in candidates:
        key = product_key(base_name(f.path))
        if key:
            groups[key].append(f)
    for key, group in groups.items():
        versioned = sorted((f for f in group if version_of(f.name)), key=lambda f: version_of(f.name))
        if len(versioned) > 1:  # only files that say which version they are can be compared
            newest = versioned[-1]
            for old in versioned[:-1]:
                if version_of(old.name) < version_of(newest.name):
                    old.assessment.reason = (f"Older installer: you also have a newer one ({newest.name}). "
                                             "Unless you need this exact version, you can delete it.")
                    changed += 1
        for f in group:
            if f.assessment.reason.startswith("Older installer"):
                continue  # that's the more useful thing to say
            info = windows_version_info(f.path) if f.path.lower().endswith(".exe") else {}
            prog = _matches_installed([product_key(f.name, with_arch=False) or "",
                                       _norm(info.get("ProductName", ""))], installed)
            if prog:
                ver = f" (version {prog.version})" if prog.version else ""
                f.assessment.reason = (f"Installer for {prog.name}, which looks already installed{ver}. If so, you "
                                       "can delete this; you can download it again if you ever need it.")
                changed += 1
    return changed


# AppData folders that belong to Windows itself or are handled by other rules
APPDATA_SKIP = {"microsoft", "packages", "temp", "programs", "d3dscache", "crashdumps", "comms", "history",
                "connecteddevicesplatform", "placeholdertilelogofolder", "publishers", "virtualstore",
                "peerdistrepub", "iconcache", "fontcache", "microsoftedge", "squirreltemp", "package cache",
                "low", "elevateddiagnostics", "apps", "identities", "media player", "windows", "mozilla",
                "nvidia", "nvidia corporation", "amd", "intel", "realtek", "dell", "hp", "lenovo", "asus"}


LEFTOVER_QUIET_DAYS = 60
USER_DATA_DIRS = {"saves", "savegames", "save", "saved games", "profiles", "profile", "wallets", "wallet", "mail",
                  "backup", "backups", "vault", "keys", "collection", "documents", "projects", "worlds"}
USER_DATA_EXTS = (".sqlite", ".sqlite3", ".db", ".kdbx", ".kdb", ".sl2", ".sav", ".wallet", ".mbox", ".msf",
                  ".pst", ".ost", ".anki2", ".key", ".pem")


def _holds_user_data(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    return low.endswith(USER_DATA_EXTS) or any(seg in USER_DATA_DIRS for seg in low.split("/")[:-1])


def leftover_app_data(files, installed: list[Program], now: float | None = None) -> int:
    """Data in AppData\\<Local|Roaming|LocalLow>\\<Folder> for programs that are no longer installed."""
    if not installed:  # no list of installed programs (not Windows): don't guess
        return 0
    now = now or time.time()
    known = [(_norm(p.name), _norm(p.publisher), _norm(p.location)) for p in installed]
    cache: dict[str, bool] = {}

    def is_installed(folder: str) -> bool:
        key = _norm(folder)
        if key not in cache:
            cache[key] = len(key) < 3 or any(
                key in name or key in pub or key in loc or (len(name) >= 4 and name in key)
                for name, pub, loc in known)
        return cache[key]

    # AppData\<area>\<folder> -> its files; only folders of programs that aren't installed
    candidates: dict[str, list] = defaultdict(list)
    for f in files:
        a = f.assessment
        if a.verdict != kb.SYSTEM or a.protected or not a.location or a.location.label != "App data":
            continue
        parts = f.path.replace("\\", "/").split("/")
        low = [p.lower() for p in parts]
        for i in range(len(low) - 3):
            if low[i] == "appdata" and low[i + 1] in ("local", "roaming", "locallow"):
                folder = parts[i + 2]
                if (folder.lower() not in APPDATA_SKIP and not folder.startswith(".")
                        and not is_installed(folder)):
                    candidates["/".join(parts[:i + 3])].append(f)
                break

    changed = 0
    cutoff = now - LEFTOVER_QUIET_DAYS * 86400
    for folder_path, group in candidates.items():
        if any(_holds_user_data(f.path) for f in group):  # saves, mail, wallets, password vaults...
            continue
        # an app you still use keeps writing to its folder (Store apps and some games never register
        # as installed): only call it a leftover when nothing in it changed for a while
        if max(f.mtime for f in group) > cutoff:
            continue
        folder = folder_path.rsplit("/", 1)[-1]
        for f in group:
            f.assessment.verdict = kb.REVIEW
            f.assessment.reason = (f"Looks left over from '{folder}': it isn't in your list of installed programs "
                                   f"and hasn't changed in {LEFTOVER_QUIET_DAYS}+ days. It may still hold settings "
                                   "you'd want if you reinstall it, so back it up before deleting.")
            changed += 1
    return changed
