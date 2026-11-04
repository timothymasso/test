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
    ("C:\\Temp\\leftover.dat", kb.REVIEW),  # a top-level Temp folder can be anybody's
    ("C:\\Temp\\setup_log.tmp", kb.DELETE),
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
    assert a("D:\\Projects\\server\\logs\\chat.log", mtime=NOW).verdict == kb.KEEP  # still being written
    assert a("C:\\Temp\\installer\\run.log", mtime=OLD).verdict == kb.DELETE
    assert a("C:\\Users\\me\\AppData\\Local\\SomeApp\\run.log", mtime=OLD).verdict == kb.SYSTEM
    # outside app data an old log could be something saved on purpose
    assert a("D:\\Projects\\server\\logs\\chat.log", mtime=OLD).verdict == kb.REVIEW


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


def test_lookalikes_are_not_duplicates_and_stop_works(tree):
    from file_sorter.scanner import mark_duplicates
    import threading
    vids = tree / "Videos"
    same_start = b"\x00\x00\x00\x18ftypmp42" + b"x" * (2 * MB)
    (vids / "one.mp4").write_bytes(same_start + b"END-ONE")
    (vids / "two.mp4").write_bytes(same_start + b"END-TWO")
    res = scan(str(tree), Settings(move_media_mb=1), find_duplicates=False)
    assert mark_duplicates(res.files) == 1  # only "copy of a.mp4"
    by_name = {f.name: f for f in res.files}
    assert by_name["one.mp4"].duplicate_of is None and by_name["two.mp4"].duplicate_of is None

    # Stop pressed: nothing is marked, and it returns right away
    res = scan(str(tree), Settings(move_media_mb=1), find_duplicates=False)
    stop = threading.Event()
    stop.set()
    assert mark_duplicates(res.files, stop) == 0


def test_treemap_layout_fills_the_area():
    from file_sorter.treemap import squarify
    for sizes in ([600.0], [300.0, 200.0, 100.0], [500.0, 1.0, 0.0, 99.0], [1.0] * 50):
        sizes = sorted(sizes, reverse=True)
        total = sum(sizes)
        rects = squarify([s / total * 400 * 300 for s in sizes], 0, 0, 400, 300)
        assert len(rects) == len([s for s in sizes if s > 0])
        assert abs(sum(w * h for _, _, w, h in rects) - 400 * 300) < 1e-6
        for x, y, w, h in rects:
            assert -1e-6 <= x and x + w <= 400 + 1e-6 and -1e-6 <= y and y + h <= 300 + 1e-6


def _three_copies(tree):
    vids = tree / "Videos"
    data = os.urandom(2 * MB)
    for i, name in enumerate(("holiday.mp4", "holiday (1).mp4", "holiday (2).mp4")):
        (vids / name).write_bytes(data)
        os.utime(vids / name, (OLD + i, OLD + i))  # holiday.mp4 is the oldest -> the original
    return scan(str(tree), Settings(move_media_mb=1))


def test_deleting_the_original_promotes_a_copy(tree):
    from file_sorter.scanner import regroup_duplicates
    res = _three_copies(tree)
    by_name = {f.name: f for f in res.files}
    assert by_name["holiday (1).mp4"].duplicate_of == by_name["holiday.mp4"].path
    # the original is deleted
    res.files = [f for f in res.files if f.name != "holiday.mp4"]
    changed = regroup_duplicates(res.files)
    heir, other = by_name["holiday (1).mp4"], by_name["holiday (2).mp4"]
    assert heir.duplicate_of is None and heir.verdict == kb.MOVE  # its own verdict is back
    assert [f for f, _ in changed] == [heir]
    assert other.duplicate_of == heir.path and other.verdict == kb.REVIEW
    # and when only one is left, it's not a duplicate of anything
    res.files = [f for f in res.files if f is not heir]
    regroup_duplicates(res.files)
    assert other.duplicate_of is None and other.verdict == kb.MOVE


def test_side_by_side_compare(tree, monkeypatch):
    from file_sorter import scanner
    big = os.urandom(scanner.CHUNK + MB)
    (tree / "Videos" / "x.mp4").write_bytes(big)
    (tree / "Videos" / "x copy.mp4").write_bytes(big)
    (tree / "Videos" / "x edited.mp4").write_bytes(big[:-10] + b"0123456789")  # differs only at the very end
    for max_open in (64, 1):  # side by side, and the whole-file-hash fallback for big groups
        monkeypatch.setattr(scanner, "MAX_OPEN", max_open)
        res = scan(str(tree), Settings(move_media_mb=1))
        by_name = {f.name: f for f in res.files}
        assert {by_name["x.mp4"].duplicate_of, by_name["x copy.mp4"].duplicate_of} - {None}
        assert by_name["x edited.mp4"].duplicate_of is None
        assert res.duplicates_checked


def test_space_map_index(tree):
    from file_sorter.scanner import index_shift
    res = scan(str(tree), Settings(move_media_mb=1), find_duplicates=False)
    root = res.map_root
    assert sum(res.breakdown[root].values()) == sum(f.size for f in res.files)
    videos = os.path.join(str(tree), "Videos")
    assert videos in res.subfolders[root]
    f = next(f for f in res.files if f.name == "a.mp4")
    before = sum(res.breakdown[root].values())
    index_shift(res, f, f.verdict, None)  # file deleted
    assert sum(res.breakdown[root].values()) == before - f.size
    assert sum(res.breakdown[videos].values()) == sum(x.size for x in res.files if x.path.startswith(videos)) - f.size


def test_space_map_index_windows_roots(monkeypatch):
    import ntpath
    import types
    from file_sorter import scanner
    from file_sorter.analysis import Assessment
    monkeypatch.setattr(scanner, "os", types.SimpleNamespace(path=ntpath))
    for root, files in (("C:\\", ["C:\\a.txt", "C:\\Users\\me\\b.txt"]),
                        ("\\\\nas\\share", ["\\\\nas\\share\\a.txt", "\\\\nas\\share\\Films\\b.mkv"])):
        res = scanner.ScanResult(root=root, files=[
            scanner.FileEntry(p, 100, 0, 0, Assessment(kb.KEEP, "", "other", "")) for p in files])
        scanner.build_index(res)
        assert sum(res.breakdown[res.map_root].values()) == 200, root
        assert res.subfolders[res.map_root], root


def test_unreadable_file_mid_compare_is_skipped(tree, monkeypatch):
    import builtins
    from file_sorter import scanner
    data = os.urandom(2 * MB)
    for name in ("p.mp4", "p copy.mp4", "p locked.mp4"):
        (tree / "Videos" / name).write_bytes(data)
    real_open = builtins.open

    class Locked:
        def __init__(self, fh):
            self.fh = fh

        def read(self, n=-1):
            raise PermissionError("locked by another program")

        def close(self):
            self.fh.close()

    def fake_open(path, mode="r", *a, **k):
        fh = real_open(path, mode, *a, **k)
        return Locked(fh) if str(path).endswith("p locked.mp4") and "b" in mode else fh

    res = scan(str(tree), Settings(move_media_mb=1), find_duplicates=False)
    monkeypatch.setattr(scanner, "_read_at", lambda path, offsets: b"same")  # get every file to the full compare
    monkeypatch.setattr(builtins, "open", fake_open)
    scanner.mark_duplicates(res.files)  # must not raise
    by_name = {f.name: f for f in res.files}
    assert by_name["p locked.mp4"].duplicate_of is None
    assert {by_name["p.mp4"].duplicate_of, by_name["p copy.mp4"].duplicate_of} - {None}


# ------------------------------------------------------------- smarter checks and groups

@pytest.mark.parametrize("path,verdict", [
    ("C:\\Windows\\Logs\\CBS\\CbsPersist_20240101.cab", kb.DELETE),
    ("C:\\Windows\\Installer\\1a2b3c.msi", kb.SYSTEM),
    ("C:\\Windows\\WinSxS\\amd64_x\\file.dll", kb.SYSTEM),
    ("C:\\ProgramData\\Package Cache\\{guid}\\vc_redist.x64.exe", kb.SYSTEM),
    ("C:\\Users\\me\\AppData\\Roaming\\Apple Computer\\MobileSync\\Backup\\abc\\00\\0011", kb.REVIEW),
    ("C:\\Users\\me\\AppData\\Roaming\\Adobe\\Common\\Media Cache Files\\clip.pek", kb.DELETE),
    ("C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data\\Crashpad\\reports\\x.dmp", kb.DELETE),
    ("C:\\Users\\me\\AppData\\Roaming\\Microsoft\\Teams\\Service Worker\\CacheStorage\\a\\b", kb.DELETE),
    ("C:\\Users\\me\\Documents\\~$report.docx", kb.DELETE),
    ("C:\\Users\\me\\AppData\\Local\\Microsoft\\Windows\\Explorer\\thumbcache_256.db", kb.DELETE),
    ("C:\\$SysReset\\Logs\\x.etl", kb.DELETE),
    ("C:\\ESD\\Windows\\sources\\install.esd", kb.REVIEW),
])
def test_smarter_verdicts(path, verdict):
    assert a(path, mtime=OLD).verdict == verdict, a(path, mtime=OLD).reason


def test_owning_app_names_games_and_apps():
    assert owning_app("D:\\SteamLibrary\\steamapps\\common\\Cyberpunk 2077\\archive\\x.archive") == \
        "Steam game: Cyberpunk 2077"
    assert owning_app("C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\Cache\\f") == "Google Chrome"


def test_product_key():
    from file_sorter.smart import product_key
    assert product_key("vlc-3.0.20-win64.exe") == product_key("vlc-3.0.18-win64.exe") == "vlcwin64"
    assert product_key("vlc-3.0.20-win64.exe", with_arch=False) == "vlc"
    assert product_key("ChromeSetup.exe") == "chrome"
    assert product_key("node-v20.11.0-x64.msi") != product_key("node-v20.11.0-x86.msi")  # x64 and x86 differ
    # years and KB numbers name different products, not versions of one
    assert product_key("TurboTax2022_Setup.exe") != product_key("TurboTax2023_Setup.exe")
    assert product_key("windows10.0-kb5034441-x64.msu") != product_key("windows10.0-kb5034122-x64.msu")
    assert product_key("Driver_Setup_1.2.exe") is None  # too generic to compare


def test_smart_installers_and_leftovers(tree):
    from file_sorter.smart import Program, leftover_app_data, smart_installers
    dl = tree / "Downloads"
    for name, age in (("vlc-3.0.18-win64.exe", 50), ("vlc-3.0.20-win64.exe", 10), ("ChromeSetup.exe", 5),
                      ("zoom_installer.exe", 5), ("TurboTax2022_Setup.exe", 400), ("TurboTax2023_Setup.exe", 30)):
        (dl / name).write_bytes(b"MZ" + b"\0" * 100)
        os.utime(dl / name, (NOW - age * 86400,) * 2)
    for app, age in (("Spotify", 300), ("OldGameLauncher", 300), ("StoreGame", 2)):
        d = tree / "AppData" / "Roaming" / app
        d.mkdir(parents=True)
        (d / "settings.json").write_text("{}")
        os.utime(d / "settings.json", (NOW - age * 86400,) * 2)
    res = scan(str(tree), Settings(), find_duplicates=False)
    installed = [Program("VLC media player", "VideoLAN", "", "3.0.20"), Program("Google Chrome"),
                 Program("Spotify", "Spotify AB")]
    smart_installers(res.files, installed)
    leftover_app_data(res.files, installed)
    by = {f.name: f for f in res.files}
    # guesses explain, but never make an installer "Safe to delete" (one-click Clean up must not take them)
    assert by["vlc-3.0.18-win64.exe"].verdict == kb.REVIEW and "newer" in by["vlc-3.0.18-win64.exe"].assessment.reason
    assert by["vlc-3.0.20-win64.exe"].verdict == kb.REVIEW and "already installed" in \
        by["vlc-3.0.20-win64.exe"].assessment.reason
    assert "already installed" in by["ChromeSetup.exe"].assessment.reason
    assert not by["zoom_installer.exe"].assessment.reason.startswith("Installer for")
    assert "Older installer" not in by["TurboTax2022_Setup.exe"].assessment.reason
    settings = [f for f in res.files if f.name == "settings.json"]
    verdicts = {os.path.basename(os.path.dirname(f.path)): f.verdict for f in settings}
    # StoreGame isn't registered as installed, but it's still being used: not a leftover
    assert verdicts == {"Spotify": kb.SYSTEM, "OldGameLauncher": kb.REVIEW, "StoreGame": kb.SYSTEM}
    # a folder holding saves (or mail, wallets, password vaults...) is never called a leftover
    saves = tree / "AppData" / "Roaming" / "OldRPG" / "saves"
    saves.mkdir(parents=True)
    (saves / "slot1.sav").write_bytes(b"x")
    os.utime(saves / "slot1.sav", (NOW - 400 * 86400,) * 2)
    res3 = scan(str(tree), Settings(), find_duplicates=False)
    leftover_app_data(res3.files, installed)
    assert next(f for f in res3.files if f.name == "slot1.sav").verdict == kb.SYSTEM
    # without a list of installed programs nothing is guessed
    res2 = scan(str(tree), Settings(), find_duplicates=False)
    assert leftover_app_data(res2.files, []) == 0


def test_groups(tree):
    from file_sorter.groups import build_groups
    game = tree / "SteamLibrary" / "steamapps" / "common" / "Portal"
    game.mkdir(parents=True)
    (game / "portal.pak").write_bytes(b"x" * 1000)
    res = scan(str(tree), Settings(move_media_mb=1))
    groups = {g.title: g for g in build_groups(res.files)}
    assert "Steam game: Portal" in groups
    assert "Duplicate copies" in groups and groups["Duplicate copies"].files[0].name == "copy of a.mp4"
    assert any(t.startswith("Videos from ") for t in groups)
    assert "Installers" in groups
    # a safe-to-delete old installer still groups with the installers
    from file_sorter.analysis import Assessment
    from file_sorter.groups import group_of
    from file_sorter.scanner import FileEntry
    old_inst = FileEntry("C:\\Users\\me\\Downloads\\vlc-3.0.18-win64.exe", 10, 0, 0,
                         Assessment(kb.DELETE, "Older installer", "executable", ""))
    assert group_of(old_inst)[1] == "Installers"
    # every file is in exactly one group
    assert sum(len(g.files) for g in groups.values()) == len(res.files)
    # groups that free the most space come first
    ordered = build_groups(res.files)
    wins = [g.deletable + g.movable + g.review for g in ordered]
    assert wins == sorted(wins, reverse=True)


def test_batch_delete_reports_each_file(tree, monkeypatch):
    calls = []

    def fake_trash(p):
        calls.append(p)
        if isinstance(p, list):
            for x in p[:1]:  # removes the first file, then fails
                os.remove(x)
            raise OSError("one file is locked")
        if p.endswith("locked.bin"):
            raise OSError("locked")
        os.remove(p)

    files = []
    for name in ("one.bin", "two.bin", "locked.bin"):
        (tree / name).write_bytes(b"x")
        files.append(str(tree / name))
    monkeypatch.setattr(actions, "_send2trash", fake_trash)
    report = actions.delete_files(files)
    assert isinstance(calls[0], list) and len(calls[0]) == 3  # one call for the whole batch
    assert sorted(os.path.basename(p) for p, _ in report.done) == ["one.bin", "two.bin"]
    assert [os.path.basename(p) for p, _ in report.failed] == ["locked.bin"]


# ------------------------------------------------------------- whole folders, undo, never touch

def test_whole_folders_never_above_a_junk_folder(tree):
    from file_sorter.scanner import whole_folders
    local = tree / "AppData" / "Local"
    data = local / "Google" / "Chrome" / "User Data" / "Default" / "Cache" / "Cache_Data"
    data.mkdir(parents=True)
    (data / "f1").write_bytes(b"x")
    (data.parent / "index").write_bytes(b"x")
    res = scan(str(tree), find_duplicates=False)
    paths = [f.path for f in res.files if str(local) in f.path]  # every file under AppData\Local
    singles, folders = whole_folders(paths, res)
    assert list(folders) == [str(data)]  # only inside the Cache folder; never Cache, Chrome or AppData\Local


def test_whole_folders_are_deleted_as_one(tree):
    from file_sorter.scanner import whole_folders
    proj = tree / "code" / "app" / "node_modules"
    for pkg in ("react", "lodash"):
        (proj / pkg / "lib").mkdir(parents=True)
        (proj / pkg / "index.js").write_text("x")
        (proj / pkg / "lib" / "a.js").write_text("x")
    (proj / "react" / "link").symlink_to(tree / "notes.txt")  # a folder holding a link is never deleted whole
    res = scan(str(tree), find_duplicates=False)
    paths = [f.path for f in res.files if "node_modules" in f.path]
    singles, folders = whole_folders(paths, res)
    # node_modules is a 'Review' folder, not a 'Safe to delete' one: nothing is collapsed there
    assert folders == {} and sorted(singles) == sorted(paths)
    tmp = tree / "AppData" / "Local" / "Temp"
    for d in ("ab12", "cd34"):
        (tmp / d / "sub").mkdir(parents=True)
        (tmp / d / "sub" / "x.tmp").write_text("x")
    (tmp / "cd34" / "link").symlink_to(tree / "notes.txt")  # a folder holding a link is never deleted whole
    res = scan(str(tree), find_duplicates=False)
    paths = [f.path for f in res.files if os.sep + "Temp" + os.sep in f.path]
    singles, folders = whole_folders(paths, res)
    # Temp itself stays (programs expect it); cd34 holds a link so only its clean subfolder goes whole
    assert sorted(folders) == [str(tmp / "ab12"), str(tmp / "cd34" / "sub")]
    # a partly selected folder is not deleted whole
    singles, folders = whole_folders([p for p in paths if "ab12" not in p], res)
    assert str(tmp / "ab12") not in folders


def test_delete_folder_units(tree, monkeypatch):
    d = tree / "AppData" / "Local" / "SomeApp" / "Cache" / "sub"
    d.mkdir(parents=True)
    (d / "x.bin").write_bytes(b"12345")
    (d / "y.bin").write_bytes(b"123")
    calls = []

    def fake_trash(p):
        calls.append(p)
        (shutil.rmtree if os.path.isdir(p) else os.remove)(p)

    monkeypatch.setattr(actions, "_send2trash", fake_trash)
    report = actions.delete_files([], folders={str(d): [str(d / "x.bin"), str(d / "y.bin")]})
    assert calls == [str(d)] and not d.exists()
    assert sorted(os.path.basename(p) for p, _ in report.done) == ["x.bin", "y.bin"] and report.bytes == 8


def test_move_back(tree, tmp_path_factory):
    dest = tmp_path_factory.mktemp("otherdrive")
    src = tree / "Videos" / "a.mp4"
    data = src.read_bytes()
    actions.move_files([str(src)], str(tree), str(dest))
    assert not src.exists()
    report = actions.move_back(str(dest / actions.LOG_NAME))
    assert report.done and src.read_bytes() == data
    assert not (dest / actions.LOG_NAME).exists()  # everything is back: the log is gone


def test_never_touch(tree):
    res = scan(str(tree), Settings(never_touch=(str(tree / "AppData"),)), find_duplicates=False)
    blob = next(f for f in res.files if f.name == "blob")
    assert blob.verdict == kb.KEEP and "never touch" in blob.assessment.reason


def test_prefs_roundtrip(tmp_path):
    from file_sorter.prefs import Prefs, is_inside
    p = Prefs(last_folder="C:\\Users\\me", never_touch=["D:\\Keep"], freed_bytes=123)
    path = str(tmp_path / "s.json")
    p.save(path)
    assert Prefs.load(path) == p
    assert Prefs.load(str(tmp_path / "missing.json")) == Prefs()
    (tmp_path / "bad.json").write_text("{not json")
    assert Prefs.load(str(tmp_path / "bad.json")) == Prefs()
    assert is_inside("/a/b/c.txt", ["/a/b"]) and not is_inside("/a/bc/d.txt", ["/a/b"])



@pytest.mark.parametrize("path,size,verdict", [
    ("C:\\Users\\me\\Documents\\Thesis.~final.docx", 9000, kb.KEEP),
    ("C:\\Users\\me\\Pictures\\photo.~1.jpg", 300000, kb.KEEP),
    ("C:\\Users\\me\\Pictures\\~$wedding.jpg", 5 * MB, kb.KEEP),
    ("C:\\Users\\me\\Documents\\~$budget.xlsx", 165, kb.DELETE),
    ("C:\\Users\\me\\AppData\\Local\\Temp\\report.~tmp", 1000, kb.DELETE),
    ("C:\\Users\\me\\Desktop\\cbs_notes.log", 1000, kb.REVIEW),  # old log in a user folder: check it
    ("C:\\Windows\\Logs\\CBS\\CBS.log", 10 * MB, kb.DELETE),
    ("D:\\AMD\\Shareholder letter.pdf", 100000, kb.REVIEW),
    ("D:\\AMD\\Ryzen build photo.jpg", 3 * MB, kb.REVIEW),
    ("C:\\AMD\\Chipset_Drivers\\Packages\\x.inf", 1000, kb.DELETE),  # C:\AMD is the AMD installer's
    ("D:\\AMD\\Chipset_Drivers\\Packages\\x.inf", 1000, kb.REVIEW),  # D:\AMD could be anybody's
    ("C:\\NVIDIA\\Installer2\\Display.Driver\\nvlddmkm.sys", 1000, kb.DELETE),
    ("C:\\AMD\\Chipset_Drivers\\install.log", 1000, kb.DELETE),
    ("D:\\Temp\\MyProject\\data.db", 1000, kb.REVIEW),
    ("D:\\Temp\\MyProject\\disk.vhd", 10 * MB, kb.REVIEW),  # never deleted from a Temp-name guess
    ("C:\\Users\\me\\OneDrive - Contoso\\Projects\\build.log", 1000, kb.REVIEW),
    ("C:\\Users\\me\\OneDrive - Contoso\\Projects\\x.tmp", 1000, kb.REVIEW),
    ("C:\\Users\\me\\iCloudDrive\\Notes\\old.log", 1000, kb.REVIEW),
    ("G:\\My Drive\\Work\\server.log", 1000, kb.REVIEW),
    ("C:\\Users\\me\\Dropbox (Personal)\\logs\\a.log", 1000, kb.REVIEW),
    ("D:\\Games\\Portable\\index.dat", 1000, kb.KEEP),
    ("D:\\Projects\\x\\build\\main.pyc", 1000, kb.REVIEW),
    ("C:\\Users\\me\\OneDrive\\Logs\\config.json", 1000, kb.KEEP),
    ("C:\\Users\\me\\AppData\\Local\\Microsoft\\OneDrive\\logs\\Business1\\x.odl", 1000, kb.DELETE),
    ("C:\\Users\\me\\Documents\\oracle_export.dmp", 50 * MB, kb.REVIEW),
    ("C:\\Users\\me\\Documents\\mIRC\\logs\\friends.log", 5000, kb.REVIEW),
])
def test_review_false_positives(path, size, verdict):
    r = a(path, size=size, mtime=OLD)
    assert r.verdict == verdict, r.reason


# ------------------------------------------------------------- third review: data-safety regressions

def _temp_tree(tree):
    t = tree / "AppData" / "Local" / "Temp" / "{guid}"
    (t / "sub").mkdir(parents=True)
    (t / "a.bin").write_bytes(b"x")
    (t / "sub" / "b.bin").write_bytes(b"x")
    return t


def _fake_trash(monkeypatch, locked=()):
    calls = []

    def trash(p):
        for x in (p if isinstance(p, list) else [p]):
            if any(str(x).endswith(name) for name in locked):
                raise OSError("in use")
            calls.append(str(x))
            (shutil.rmtree if os.path.isdir(x) else os.remove)(x)
    monkeypatch.setattr(actions, "_send2trash", trash)
    return calls


def test_folder_with_a_new_file_is_not_deleted_whole(tree, monkeypatch):
    from file_sorter.scanner import whole_folders
    t = _temp_tree(tree)
    res = scan(str(tree), find_duplicates=False)
    paths = [f.path for f in res.files if "{guid}" in f.path]
    singles, folders = whole_folders(paths, res)
    assert list(folders) == [str(t)]
    (t / "sub" / "thesis.docx").write_text("written after the scan")
    calls = _fake_trash(monkeypatch)
    report = actions.delete_files(singles, folders=folders)
    assert str(t) not in calls  # looked again, saw the new file, deleted file by file instead
    assert (t / "sub" / "thesis.docx").exists()
    assert len(report.done) == 2 and not report.failed


def test_folder_with_an_empty_subfolder_is_not_deleted_whole(tree, monkeypatch):
    from file_sorter.scanner import whole_folders
    t = _temp_tree(tree)
    (t / "keepme").mkdir()
    res = scan(str(tree), find_duplicates=False)
    singles, folders = whole_folders([f.path for f in res.files if "{guid}" in f.path], res)
    calls = _fake_trash(monkeypatch)
    actions.delete_files(singles, folders=folders)
    assert (t / "keepme").is_dir() and str(t) not in calls


def test_locked_file_in_a_folder_still_frees_the_rest(tree, monkeypatch):
    from file_sorter.scanner import whole_folders
    t = _temp_tree(tree)
    (t / "locked.bin").write_bytes(b"x")
    res = scan(str(tree), find_duplicates=False)
    singles, folders = whole_folders([f.path for f in res.files if "{guid}" in f.path], res)

    def trash(p):
        if os.path.isdir(p):
            raise OSError("a file in it is in use")
        if str(p).endswith("locked.bin"):
            raise OSError("in use")
        os.remove(p)
    monkeypatch.setattr(actions, "_send2trash", trash)
    report = actions.delete_files(singles, folders=folders)
    assert sorted(os.path.basename(p) for p, _ in report.done) == ["a.bin", "b.bin"]
    assert [os.path.basename(p) for p, _ in report.failed] == ["locked.bin"]


def test_no_whole_folders_after_a_stopped_scan(tree):
    from file_sorter.scanner import whole_folders
    _temp_tree(tree)
    res = scan(str(tree), find_duplicates=False)
    res.cancelled = True
    singles, folders = whole_folders([f.path for f in res.files if "{guid}" in f.path], res)
    assert folders == {}


def test_never_whole_inside_windows_folders_or_special_names(tree):
    from file_sorter.scanner import _inside_junk_folder
    assert _inside_junk_folder("C:\\Users\\me\\AppData\\Local\\Temp\\{guid}") if os.sep == "\\" else True
    assert not _inside_junk_folder(str(tree / "AppData" / "Local" / "Temp" / "Low"))
    assert not _inside_junk_folder(str(tree / "AppData" / "Local" / "Microsoft" / "Windows" / "INetCache" /
                                       "Content.Outlook"))


def test_move_back_refuses_other_csv_files(tmp_path):
    bank = tmp_path / "bank.csv"
    bank.write_text("Date,Description,Amount,Balance\n2024-01-01,Coffee,-3\n")
    before = bank.read_text()
    report = actions.move_back(str(bank))
    assert report.failed and bank.read_text() == before


def test_move_never_overwrites_a_partial_file(tree, tmp_path_factory):
    dest = tmp_path_factory.mktemp("otherdrive")
    target = dest / tree.name / "Videos" / "a.mp4.partial"
    target.parent.mkdir(parents=True)
    target.write_text("someone's real file")
    report = actions.move_files([str(tree / "Videos" / "a.mp4")], str(tree), str(dest))
    assert report.done and target.read_text() == "someone's real file"


def test_never_touch_never_weakens_system_files(tree):
    git = tree / "code" / ".git" / "objects"
    git.mkdir(parents=True)
    (git / "pack").write_bytes(b"x")
    res = scan(str(tree), Settings(never_touch=(str(tree),)), find_duplicates=False)
    by = {f.name: f for f in res.files}
    assert by["pack"].verdict == kb.SYSTEM  # still refused outright, not just "are you sure?"
    assert by["blob"].verdict == kb.KEEP and by["blob"].assessment.protected


def test_prefs_with_wrong_types_fall_back(tmp_path):
    import json
    from file_sorter.prefs import Prefs
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"freed_bytes": "x", "never_touch": "C:\\\\", "last_folder": 5, "stale_days": 30}))
    p = Prefs.load(str(path))
    assert p.freed_bytes == 0 and p.never_touch == [] and p.last_folder == "" and p.stale_days == 30



# ------------------------------------------------------------- fourth review

def test_folder_rechecked_right_before_its_batch(tree, monkeypatch):
    from file_sorter.scanner import whole_folders
    t = _temp_tree(tree)
    res = scan(str(tree), find_duplicates=False)
    singles, folders = whole_folders([f.path for f in res.files if "{guid}" in f.path], res)
    assert list(folders) == [str(t)]
    calls = _fake_trash(monkeypatch)

    def progress(i, n, path):  # a file appears after deleting started, before the folder's turn
        (t / "sub" / "NEW_user_file.docx").write_text("x")
    actions.delete_files(singles, progress=progress, folders=folders)
    assert (t / "sub" / "NEW_user_file.docx").exists() and str(t) not in calls


def test_permanent_folder_delete_never_removes_unseen_files(tree):
    t = _temp_tree(tree)
    members = [str(t / "a.bin"), str(t / "sub" / "b.bin")]
    (t / "sub" / "surprise.docx").write_text("x")
    with pytest.raises(OSError):
        actions._remove_folder_permanently(str(t), members)
    assert (t / "sub" / "surprise.docx").exists()


def test_outlook_secure_temp_folder_is_never_deleted_whole():
    from file_sorter.scanner import _inside_junk_folder
    base = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Microsoft", "Windows", "INetCache")
    assert not _inside_junk_folder(os.path.join(base, "Content.Outlook", "K3J9QZ2B"))
    assert not _inside_junk_folder(os.path.join(base, "Content.Outlook", "K3J9QZ2B", "sub"))


def test_cloud_duplicate_is_not_offered_for_deleting(tree):
    from file_sorter.groups import build_groups
    data = os.urandom(2 * MB)
    (tree / "Pictures" / "trip").mkdir(parents=True)
    (tree / "Pictures" / "trip" / "IMG_1.jpg").write_bytes(data)
    os.utime(tree / "Pictures" / "trip" / "IMG_1.jpg", (OLD, OLD))
    (tree / "OneDrive" / "Pictures").mkdir(parents=True)
    (tree / "OneDrive" / "Pictures" / "IMG_1.jpg").write_bytes(data)
    res = scan(str(tree), Settings(move_media_mb=100))
    cloud_copy = next(f for f in res.files if "OneDrive" in f.path)
    assert cloud_copy.duplicate_of and cloud_copy.assessment.cloud and cloud_copy.assessment.warnings
    dupes = next(g for g in build_groups(res.files) if g.key == "dupes")
    deletable = [f for f in dupes.files if f.duplicate_of and not f.assessment.cloud]
    assert cloud_copy not in deletable


def test_leftovers_never_override_never_touch(tree):
    from file_sorter.smart import Program, leftover_app_data
    d = tree / "AppData" / "Roaming" / "OldGame"
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    os.utime(d / "config.json", (NOW - 400 * 86400,) * 2)
    res = scan(str(tree), Settings(never_touch=(str(d),)), find_duplicates=False)
    leftover_app_data(res.files, [Program("Something Else")])
    f = next(f for f in res.files if f.name == "config.json")
    assert f.verdict == kb.SYSTEM and f.assessment.protected



def test_permanent_delete_never_uses_the_recycle_bin(tree, monkeypatch):
    from file_sorter.scanner import whole_folders
    t = _temp_tree(tree)
    res = scan(str(tree), find_duplicates=False)
    singles, folders = whole_folders([f.path for f in res.files if "{guid}" in f.path], res)
    (t / "new.txt").write_text("x")  # folder changed: its files go one by one
    calls = _fake_trash(monkeypatch)
    report = actions.delete_files(singles, permanently=True, folders=folders)
    assert calls == [] and len(report.done) == 2 and (t / "new.txt").exists()


def test_system_drive_setting_may_be_empty(monkeypatch):
    monkeypatch.setenv("SystemDrive", "")
    assert a("C:\\AMD\\x\\y.inf").verdict in kb.VERDICTS
