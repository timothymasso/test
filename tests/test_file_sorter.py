import os
import pathlib
import shutil
import tempfile
import time

import pytest

from file_sorter import actions
from file_sorter import knowledge as kb
from file_sorter.analysis import Settings, assess, explain, match_folders, normalized_dir, owning_app
from file_sorter.scanner import scan

MB = 1024 * 1024
NOW = time.time()
OLD = NOW - 800 * 86400


def a(path, size=1000, mtime=NOW, atime=None):
    return assess(path, size, mtime, atime if atime is not None else mtime, Settings(), NOW)


# --------------------------------------------------------------------- rules

@pytest.mark.parametrize("path,verdict", [
    ("C:\\pagefile.sys", kb.SYSTEM),
    ("C:\\hiberfil.sys", kb.SYSTEM),
    ("C:\\Windows\\System32\\kernel32.dll", kb.SYSTEM),
    ("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", kb.SYSTEM),
    ("C:\\Windows\\Temp\\abc.tmp", kb.DELETE),
    ("C:\\Windows\\SoftwareDistribution\\Download\\x\\update.cab", kb.DELETE),
    ("C:\\Users\\me\\AppData\\Local\\Temp\\setup123.log", kb.DELETE),
    ("C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\Cache\\Cache_Data\\f_000001", kb.DELETE),
    ("C:\\Users\\me\\AppData\\Roaming\\Discord\\settings.json", kb.SYSTEM),
    ("C:\\$Recycle.Bin\\S-1-5\\$R123.mp4", kb.DELETE),
    ("C:\\Users\\me\\Downloads\\ChromeSetup.exe", kb.REVIEW),
    ("C:\\Users\\me\\Downloads\\something.msi", kb.REVIEW),
    ("C:\\Users\\me\\Downloads\\movie.mkv.crdownload", kb.DELETE),
    ("C:\\Users\\me\\Documents\\notes.txt", kb.KEEP),
    ("D:\\Projects\\temp\\thesis.docx", kb.KEEP),
    ("C:\\Temp\\leftover.dat", kb.DELETE),
    ("/tmp/abc.dat", kb.DELETE),
    ("C:\\Users\\me\\Pictures\\Thumbs.db", kb.DELETE),
    ("/Users/me/Library/Caches/com.apple.Safari/Cache.db", kb.DELETE),
    ("/Users/me/Library/Application Support/Slack/storage.json", kb.SYSTEM),
    ("/usr/lib/libc.so.6", kb.SYSTEM),
    ("/home/me/.cache/pip/http/abc", kb.DELETE),
    ("/home/me/project/node_modules/react/index.js", kb.REVIEW),
    ("/home/me/project/.git/objects/ab/cdef", kb.SYSTEM),
    ("/home/me/project/src/__pycache__/x.cpython-312.pyc", kb.DELETE),
    # review findings: real game/program/personal files must never be "safe to delete"
    ("D:\\SteamLibrary\\steamapps\\common\\The Witcher 3\\content\\content0\\texture.cache", kb.KEEP),
    ("D:\\SteamLibrary\\steamapps\\common\\Game\\cache\\shaders.dat", kb.KEEP),
    ("C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\django\\core\\cache\\db.py", kb.SYSTEM),
    ("C:\\Users\\me\\Documents\\Cache\\thesis.docx", kb.REVIEW),
    ("C:\\Users\\me\\OneDrive\\Pictures\\Caches\\wedding.jpg", kb.REVIEW),
    ("D:\\Temp\\family_photos\\img001.jpg", kb.REVIEW),
    ("C:\\Users\\me\\AppData\\Local\\Programs\\Microsoft VS Code\\resources\\app\\node_modules\\x\\rg.exe", kb.SYSTEM),
    ("C:\\Users\\me\\AppData\\Roaming\\npm\\node_modules\\typescript\\lib\\tsc.js", kb.SYSTEM),
    ("C:\\Users\\me\\.vscode\\extensions\\ms-python\\node_modules\\a\\index.js", kb.SYSTEM),
    ("C:\\Program Files\\SomeApp\\data\\index.dat", kb.SYSTEM),
    ("C:\\Users\\me\\VirtualBox VMs\\Win11\\Win11.vdi", kb.KEEP),
    ("C:\\Users\\me\\Documents\\Outlook Files\\me.pst", kb.KEEP),
    ("C:\\Users\\me\\.android\\avd\\Pixel.avd\\userdata-qemu.img", kb.SYSTEM),
    ("C:\\Users\\me\\anaconda3\\Lib\\site-packages\\torch\\lib\\torch_cuda.pyd", kb.SYSTEM),
    ("/home/me/.config/google-chrome/Default/Local Storage/leveldb/000003.log", kb.SYSTEM),
    ("/home/me/.config/google-chrome/Default/Cache/Cache_Data/f_0001", kb.DELETE),
    ("C:\\Users\\me\\code\\.notes.swp", kb.REVIEW),
])
def test_verdicts(path, verdict):
    assert a(path, mtime=OLD).verdict == verdict, a(path, mtime=OLD).reason


def test_big_video_should_move():
    r = a("C:\\Users\\me\\Videos\\holiday.mp4", size=2 * 1024 * MB)
    assert r.verdict == kb.MOVE


def test_small_photo_kept():
    assert a("C:\\Users\\me\\Pictures\\cat.jpg", size=2 * MB).verdict == kb.KEEP


def test_old_unused_file_should_move():
    assert a("D:\\stuff\\project.dat", size=100 * MB, mtime=OLD).verdict == kb.MOVE


def test_recent_log_kept_old_log_deleted():
    assert a("C:\\Users\\me\\app\\run.log", mtime=NOW).verdict == kb.KEEP
    assert a("C:\\Users\\me\\app\\run.log", mtime=OLD).verdict == kb.DELETE


def test_partial_download_in_progress_is_not_deleted():
    assert a("C:\\Users\\me\\Downloads\\big.iso.part", mtime=NOW).verdict == kb.REVIEW


def test_program_files_are_never_suggested_for_moving():
    r = a("D:\\Tools\\bigtool.exe", size=4 * 1024 * MB, mtime=OLD)
    assert r.verdict == kb.KEEP


def test_big_files_in_unknown_folders():
    # a big game data file outside known folders is not moved blindly when its kind is game data
    assert a("D:\\Games\\X\\data.pak", size=4 * 1024 * MB, mtime=OLD).verdict == kb.KEEP
    # a big unknown file is still a move candidate
    assert a("D:\\stuff\\dump.raw", size=4 * 1024 * MB).verdict == kb.MOVE


def test_steam_game_kept_with_move_advice():
    r = a("D:\\SteamLibrary\\steamapps\\common\\SomeGame\\data.pak", size=10 * 1024 * MB)
    assert r.verdict == kb.KEEP
    assert "Steam" in r.reason


def test_cloud_folder_warns():
    r = a("C:\\Users\\me\\OneDrive\\Videos\\big.mp4", size=900 * MB)
    assert r.verdict == kb.MOVE
    assert any("cloud" in w for w in r.warnings)


def test_folder_names_not_at_root_are_not_system():
    # a user folder called "System" or "usr" is not the OS
    assert a("C:\\Users\\me\\Documents\\System\\report.docx").verdict == kb.KEEP
    assert a("/home/me/usr/notes.txt").verdict == kb.KEEP


def test_normalized_dir():
    assert normalized_dir("C:\\Users\\Me\\file.txt") == "/users/me/"
    assert normalized_dir("\\\\server\\share\\Videos\\a.mp4") == "/videos/"
    assert normalized_dir("/usr/lib/x.so") == "/usr/lib/"


def test_match_folders_order():
    m = match_folders("C:\\Users\\me\\AppData\\Local\\Temp\\x.tmp")
    assert m[0].label == "Your temp folder"


def test_owning_app():
    assert owning_app("C:\\Program Files\\Mozilla Firefox\\firefox.exe") == "Firefox"
    assert owning_app("/Users/me/Library/Application Support/Slack/x.json") == "Slack"


# ---------------------------------------------------------------- scanning

@pytest.fixture
def tree():
    # Not under /tmp: the system temp folder is (correctly) treated as deletable.
    base = tempfile.mkdtemp(prefix="file_sorter_test_", dir=os.path.expanduser("~"))
    tmp_path = pathlib.Path(base)
    _build_tree(tmp_path)
    yield tmp_path
    shutil.rmtree(base, ignore_errors=True)


def _build_tree(tmp_path):
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "setup_x64.exe").write_bytes(b"MZ" + b"\0" * 5000)
    (tmp_path / "Videos").mkdir()
    (tmp_path / "Videos" / "a.mp4").write_bytes(os.urandom(2 * MB))
    (tmp_path / "Videos" / "copy of a.mp4").write_bytes((tmp_path / "Videos" / "a.mp4").read_bytes())
    os.utime(tmp_path / "Videos" / "a.mp4", (OLD, OLD))
    cache = tmp_path / "AppData" / "Local" / "SomeApp" / "Cache"
    cache.mkdir(parents=True)
    (cache / "blob").write_bytes(b"x" * 100)
    (tmp_path / "notes.txt").write_text("hello\nworld\n")
    (tmp_path / "mystery").write_bytes(b"%PDF-1.7 rest of pdf")
    (tmp_path / "empty.txt").write_bytes(b"")


def test_scan(tree):
    res = scan(str(tree), Settings(move_media_mb=1))
    by_name = {f.name: f for f in res.files}
    assert len(res.files) == 7
    assert by_name["setup_x64.exe"].verdict == kb.REVIEW
    assert by_name["blob"].verdict == kb.DELETE
    assert by_name["notes.txt"].verdict == kb.KEEP
    assert by_name["empty.txt"].verdict == kb.KEEP  # frees nothing, and may be a marker file
    # the older copy is the original, the newer one is the duplicate
    assert by_name["a.mp4"].verdict == kb.MOVE
    assert by_name["copy of a.mp4"].verdict == kb.REVIEW
    assert by_name["copy of a.mp4"].duplicate_of == by_name["a.mp4"].path
    assert res.folder_sizes[str(tree)] == sum(f.size for f in res.files)
    totals = res.totals()
    assert sum(n for n, _ in totals.values()) == 7


def test_explain_sniffs_unknown_files(tree):
    path = str(tree / "mystery")
    r = assess(path, 20, NOW, NOW)
    sections = dict(explain(path, r, 20, NOW, NOW))
    assert "PDF" in sections["What it is"]


def test_explain_previews_text(tree):
    path = str(tree / "notes.txt")
    r = assess(path, 12, NOW, NOW)
    sections = dict(explain(path, r, 12, NOW, NOW))
    assert sections["First lines of the file"].startswith("hello")


def test_explain_warns_about_disguised_programs(tmp_path):
    p = tmp_path / "invoice.pdf.txt"
    p.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)
    r = assess(str(p), 104, NOW, NOW)
    assert "malware" in dict(explain(str(p), r, 104, NOW, NOW))["What it is"]


# ----------------------------------------------------------------- actions

def test_move_keeps_structure_and_logs(tree, tmp_path_factory):
    dest = tmp_path_factory.mktemp("otherdrive")
    src = tree / "Videos" / "a.mp4"
    data = src.read_bytes()
    report = actions.move_files([str(src)], str(tree), str(dest))
    assert not report.failed
    moved_to = report.done[0][1]
    assert moved_to == os.path.join(str(dest), tree.name, "Videos", "a.mp4")
    assert open(moved_to, "rb").read() == data
    assert not src.exists()
    assert (dest / actions.LOG_NAME).exists()


def test_move_does_not_overwrite(tree, tmp_path_factory):
    dest = tmp_path_factory.mktemp("otherdrive")
    target = dest / tree.name / "notes.txt"
    target.parent.mkdir(parents=True)
    target.write_text("existing")
    report = actions.move_files([str(tree / "notes.txt")], str(tree), str(dest))
    assert target.read_text() == "existing"
    assert report.done[0][1] != str(target)


def test_delete_permanently(tree):
    p = tree / "empty.txt"
    report = actions.delete_files([str(p)], permanently=True)
    assert report.done and not p.exists()


def test_delete_without_recycle_bin_refuses_unless_permanent(tree, monkeypatch):
    monkeypatch.setattr(actions, "_send2trash", None)
    p = tree / "notes.txt"
    report = actions.delete_files([str(p)])
    assert report.failed and p.exists()


def test_every_folder_rule_uses_a_known_verdict():
    for rule in kb.FOLDER_RULES:
        assert rule[3] in kb.VERDICTS
    for _, verdict, _ in kb.KNOWN_FILES.values():
        assert verdict in kb.VERDICTS
    for kind, _ in kb.EXTENSIONS.values():
        assert kind in kb.KINDS


def test_program_folders_outside_known_places_are_protected(tree):
    game = tree / "Games" / "Cyberpunk"
    (game / "bin" / "x64").mkdir(parents=True)
    (game / "bin" / "x64" / "engine.dll").write_bytes(b"MZ")
    (game / "archive").mkdir()
    (game / "archive" / "basegame.archive").write_bytes(b"\0" * 100)
    (game / "cache").mkdir()
    (game / "cache" / "shaders.cache").write_bytes(b"x")
    res = scan(str(tree), Settings(move_any_mb=0))
    by_name = {f.name: f for f in res.files}
    assert by_name["basegame.archive"].verdict == kb.KEEP
    assert by_name["shaders.cache"].verdict == kb.KEEP
    # unrelated files elsewhere are untouched
    assert by_name["blob"].verdict == kb.DELETE


def test_duplicates_skip_program_files_and_hard_links(tree):
    for d in ("A", "B"):
        (tree / "Games2" / d).mkdir(parents=True)
        (tree / "Games2" / d / "PhysX.dll").write_bytes(b"MZ" + b"1" * (2 * MB))
    os.link(tree / "Videos" / "a.mp4", tree / "Videos" / "hardlink.mp4")
    res = scan(str(tree), Settings(move_media_mb=1))
    by_name = {f.name: f for f in res.files}
    assert not any(f.duplicate_of for f in res.files if f.name == "PhysX.dll")
    # the hard link is the same file as a.mp4, so only the real copy is a duplicate
    assert by_name["hardlink.mp4"].duplicate_of is None
    assert by_name["copy of a.mp4"].duplicate_of is not None


def test_failed_move_leaves_original_and_no_partial(tree, tmp_path_factory, monkeypatch):
    dest = tmp_path_factory.mktemp("otherdrive")
    src = tree / "Videos" / "a.mp4"
    data = src.read_bytes()

    def broken_copy(s, d):
        with open(d, "wb") as f:
            f.write(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(actions.shutil, "copy2", broken_copy)
    report = actions.move_files([str(src)], str(tree), str(dest))
    assert report.failed and not report.done
    assert src.read_bytes() == data
    leftovers = [p for p in dest.rglob("*") if p.is_file()]
    assert leftovers == []


def test_move_read_only_file(tree, tmp_path_factory):
    dest = tmp_path_factory.mktemp("otherdrive")
    src = tree / "notes.txt"
    os.chmod(src, 0o444)
    report = actions.move_files([str(src)], str(tree), str(dest))
    assert report.done and not src.exists()
