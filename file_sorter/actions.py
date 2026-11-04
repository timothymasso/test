"""Moving files to another drive and deleting them (to the Recycle Bin when possible)."""

from __future__ import annotations

import csv
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field

try:  # optional: pip install send2trash
    from send2trash import send2trash as _send2trash
except Exception:  # pragma: no cover - depends on the user's machine
    _send2trash = None

LOG_NAME = "moved_by_file_sorter.csv"


@dataclass
class ActionReport:
    done: list[tuple[str, str]] = field(default_factory=list)   # (source, destination or "")
    failed: list[tuple[str, str]] = field(default_factory=list)  # (source, error)
    bytes: int = 0
    log_error: str | None = None


def recycle_bin_available() -> bool:
    return _send2trash is not None


def destination_for(path: str, scan_root: str, dest_root: str) -> str:
    """Keep the folder structure: <dest_root>/<scan root name>/<path relative to scan root>."""
    path = os.path.abspath(path)
    scan_root = os.path.abspath(scan_root)
    try:
        rel = os.path.relpath(path, scan_root)
    except ValueError:  # different drive on Windows
        rel = os.path.basename(path)
    if rel.startswith(".."):
        rel = os.path.basename(path)
    base = os.path.basename(scan_root.rstrip("\\/")) or scan_root.replace(":", "").strip("\\/") or "drive"
    return os.path.join(dest_root, base, rel)


def move_files(paths: list[str], scan_root: str, dest_root: str,
               progress=None) -> ActionReport:
    """Copy each file to dest (keeping folders), check it, then remove the original.

    Nothing is ever lost: a failed copy is cleaned up and the original stays put.
    Each finished move is logged right away in dest_root/LOG_NAME.
    """
    report = ActionReport()
    log_path = os.path.join(dest_root, LOG_NAME)
    for i, src in enumerate(paths):
        if progress:
            progress(i, len(paths), src)
        dst = tmp = None
        try:
            dst = destination_for(src, scan_root, dest_root)
            if os.path.exists(dst):
                stem, ext = os.path.splitext(dst)
                dst = f"{stem} (moved {time.strftime('%Y%m%d-%H%M%S')}){ext}"
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            size = os.path.getsize(src)
            tmp = dst + ".partial"
            shutil.copy2(src, tmp)
            if os.path.getsize(tmp) != size:
                raise OSError("the copy came out incomplete")
            os.replace(tmp, dst)
            tmp = None
            try:
                os.remove(src)
            except PermissionError:
                os.chmod(src, stat.S_IWRITE)  # read-only files (camera/CD imports) refuse removal on Windows
                os.remove(src)
        except Exception as e:  # noqa: BLE001 - report every failure to the user
            for leftover in (tmp, dst if dst and os.path.exists(src) and os.path.exists(dst) else None):
                if leftover:
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
            report.failed.append((src, f"{e} (the original was left where it was)"))
            continue
        report.done.append((src, dst))
        report.bytes += size
        try:
            new = not os.path.exists(log_path)
            with open(log_path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["when", "original location", "new location", "bytes"])
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), src, dst, size])
        except OSError as e:
            report.log_error = str(e)
    return report


def recycle_bin_works_for(path: str) -> bool:
    """False for places where 'send to Recycle Bin' silently deletes for good."""
    if _send2trash is None:
        return False
    if sys.platform != "win32":
        return True
    if path.startswith("\\\\"):  # network share
        return False
    try:
        import ctypes
        kind = ctypes.windll.kernel32.GetDriveTypeW(os.path.splitdrive(os.path.abspath(path))[0] + "\\")
        return kind not in (2, 4)  # removable, network
    except Exception:
        return True


def delete_files(paths: list[str], permanently: bool = False) -> ActionReport:
    report = ActionReport()
    for p in paths:
        try:
            size = os.path.getsize(p)
            if _send2trash is not None and not permanently:
                _send2trash(p)
            elif permanently:
                os.remove(p)
            else:
                raise OSError("Recycle Bin support not installed (pip install send2trash)")
            report.done.append((p, ""))
            report.bytes += size
        except Exception as e:  # noqa: BLE001
            report.failed.append((p, str(e)))
    return report


def reveal_in_file_manager(path: str) -> None:
    """Open the folder containing the file, selecting it where the OS supports that."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def open_file(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def list_drives() -> list[tuple[str, int, int]]:
    """(drive root, free bytes, total bytes) for drives we can see."""
    roots = []
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            r = f"{letter}:\\"
            if os.path.exists(r):
                roots.append(r)
    elif sys.platform == "darwin":
        roots = ["/"] + [os.path.join("/Volumes", d) for d in _safe_listdir("/Volumes")]
    else:
        roots = ["/"]
        for base in ("/media", "/mnt", "/run/media"):
            for d in _safe_listdir(base):
                full = os.path.join(base, d)
                subs = _safe_listdir(full)
                if base == "/run/media" or (base == "/media" and subs and not os.path.ismount(full)):
                    roots += [os.path.join(full, s) for s in subs]
                else:
                    roots.append(full)
    out = []
    for r in roots:
        try:
            u = shutil.disk_usage(r)
            out.append((r, u.free, u.total))
        except OSError:
            continue
    return out


def _safe_listdir(p: str) -> list[str]:
    try:
        return sorted(os.listdir(p))
    except OSError:
        return []
