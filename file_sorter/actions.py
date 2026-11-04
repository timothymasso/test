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


def _move_one(src: str, dst: str) -> int:
    """Copy src to dst, check it, then remove src. On any failure nothing is lost: the copy is removed
    and the original stays. Returns the size moved."""
    tmp = dst + ".partial"
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        size = os.path.getsize(src)
        shutil.copy2(src, tmp)
        if os.path.getsize(tmp) != size:
            raise OSError("the copy came out incomplete")
        os.replace(tmp, dst)
        try:
            os.remove(src)
        except PermissionError:
            os.chmod(src, stat.S_IWRITE)  # read-only files (camera/CD imports) refuse removal on Windows
            os.remove(src)
        return size
    except Exception:
        for leftover in (tmp, dst if os.path.exists(src) and os.path.exists(dst) else None):
            if leftover and os.path.exists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
        raise


def _log(log_path: str, src: str, dst: str, size: int) -> str | None:
    try:
        new = not os.path.exists(log_path)
        with open(log_path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["when", "original location", "new location", "bytes"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), src, dst, size])
        return None
    except OSError as e:
        return str(e)


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
        try:
            dst = destination_for(src, scan_root, dest_root)
            if os.path.exists(dst):
                stem, ext = os.path.splitext(dst)
                dst = f"{stem} (moved {time.strftime('%Y%m%d-%H%M%S')}){ext}"
            size = _move_one(src, dst)
        except Exception as e:  # noqa: BLE001 - report every failure to the user
            report.failed.append((src, f"{e} (the original was left where it was)"))
            continue
        report.done.append((src, dst))
        report.bytes += size
        report.log_error = _log(log_path, src, dst, size) or report.log_error
    return report


def move_back(log_path: str, progress=None) -> ActionReport:
    """Undo moves: put every file listed in a File Sorter move log back where it came from.
    Files moved back are taken off the log; anything that can't go back stays listed."""
    report = ActionReport()
    try:
        with open(log_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    except OSError as e:
        report.failed.append((log_path, str(e)))
        return report
    header, rows = (rows[0], rows[1:]) if rows and rows[0][:1] == ["when"] else (None, rows)
    keep = []
    for i, row in enumerate(rows):
        if len(row) < 3:
            continue
        original, moved_to = row[1], row[2]
        if progress:
            progress(i, len(rows), moved_to)
        if not os.path.exists(moved_to):
            if os.path.exists(original):
                continue  # already back where it belongs
            report.failed.append((moved_to, "it's no longer in the place it was moved to"))
            keep.append(row)
            continue
        if os.path.exists(original):
            report.failed.append((original, "a different file now has that name; left both alone"))
            keep.append(row)
            continue
        try:
            report.bytes += _move_one(moved_to, original)
            report.done.append((moved_to, original))
        except Exception as e:  # noqa: BLE001
            report.failed.append((moved_to, str(e)))
            keep.append(row)
    try:
        if keep:
            with open(log_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(header or ["when", "original location", "new location", "bytes"])
                w.writerows(keep)
        else:
            os.remove(log_path)
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


TRASH_BATCH = 200  # one Recycle Bin call per batch: far faster than one call per file on Windows


def delete_files(paths: list[str], permanently: bool = False, progress=None,
                 folders: dict[str, list[str]] | None = None) -> ActionReport:
    """Delete files (Recycle Bin unless permanently). `folders` maps folders to delete as a whole to
    the files inside them: one Recycle Bin item per folder instead of one per file.
    report.done always lists files."""
    report = ActionReport()
    folders = folders or {}
    every_file = list(paths) + [m for members in folders.values() for m in members]
    if not permanently and _send2trash is None:
        report.failed = [(p, "Recycle Bin support not installed (pip install send2trash)") for p in every_file]
        return report
    sizes: dict[str, int] = {}
    for p in every_file:
        try:
            sizes[p] = os.path.getsize(p)
        except OSError as e:
            report.failed.append((p, str(e)))
    units = [(p, [p]) for p in paths if p in sizes]
    units += [(d, [m for m in members if m in sizes]) for d, members in folders.items()]
    step = TRASH_BATCH if not permanently else 1

    def remove(unit: str) -> None:
        if permanently:
            shutil.rmtree(unit) if os.path.isdir(unit) and not os.path.islink(unit) else os.remove(unit)
        else:
            _send2trash(unit)

    for start in range(0, len(units), step):
        batch = units[start:start + step]
        if progress:
            progress(start, len(units), batch[0][0])
        try:
            if len(batch) == 1:
                remove(batch[0][0])
            else:
                _send2trash([u for u, _ in batch])
            failed_units = []
        except Exception:  # noqa: BLE001 - one bad item fails the batch: retry one by one to find it
            failed_units = []
            for unit, members in batch:
                if not os.path.lexists(unit):  # the failed batch already removed this one
                    continue
                try:
                    remove(unit)
                except Exception as e:  # noqa: BLE001
                    failed_units.append((unit, members, str(e)))
        bad = {u for u, _, _ in failed_units}
        for unit, members in batch:
            for m in members:
                if unit in bad and os.path.lexists(m):
                    continue
                report.done.append((m, ""))
                report.bytes += sizes[m]
        for unit, members, err in failed_units:
            report.failed += [(m, err) for m in members if os.path.lexists(m)]
    return report


# --------------------------------------------------------------------------- Windows tools
def recycle_bin_size() -> tuple[int, int] | None:
    """(bytes, items) in all Recycle Bins, or None if unknown."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]

        info = SHQUERYRBINFO(cbSize=ctypes.sizeof(SHQUERYRBINFO))
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
            return None
        return info.i64Size, info.i64NumItems
    except Exception:
        return None


def empty_recycle_bin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        flags = 0x1 | 0x4  # no confirmation (we asked already), no sound; keep the progress window
        hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags) & 0xFFFFFFFF
        return hr in (0, 0x8000FFFF)  # S_OK, or 'already empty'
    except Exception:
        return False


def open_disk_cleanup() -> None:
    subprocess.Popen(["cleanmgr.exe"])


def open_storage_settings() -> None:
    os.startfile("ms-settings:storagesense")  # type: ignore[attr-defined]


def turn_off_hibernation() -> bool:
    """Runs 'powercfg /hibernate off' as administrator (Windows asks for permission). Frees hiberfil.sys."""
    try:
        import ctypes
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", "powercfg.exe", "/hibernate off", None, 0) > 32
    except Exception:
        return False


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
