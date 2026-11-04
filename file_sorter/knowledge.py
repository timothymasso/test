"""Built-in knowledge about file types, well-known files and well-known folders.

Everything here works offline. The tables are used for two things:

* deciding what to recommend for a file (delete / review / move / keep / leave alone)
* explaining in plain language what a file is and what it does
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

DELETE = "Safe to delete"
REVIEW = "Review - probably deletable"
MOVE = "Move to other drive"
KEEP = "Keep"
SYSTEM = "System - don't touch"

VERDICTS = [DELETE, REVIEW, MOVE, KEEP, SYSTEM]

# short labels for the file list
SHORT = {DELETE: "Delete", REVIEW: "Review", MOVE: "Move", KEEP: "Keep", SYSTEM: "Don't touch"}

VERDICT_HELP = {
    DELETE: "Temporary files, caches, crash dumps and leftovers. Programs recreate "
            "these when they need them, so deleting them only frees space.",
    REVIEW: "Probably not needed (old installers, duplicates, old logs, empty files), "
            "but take a quick look before you delete them.",
    MOVE: "Big or rarely used personal files (videos, photos, archives, backups, "
          "disk images). You want to keep them, but they don't need to sit on your main drive.",
    KEEP: "Normal files that are in use or too small to bother with.",
    SYSTEM: "Part of the operating system or an installed program. Deleting or moving "
            "these can break Windows/macOS/Linux or the app they belong to.",
}

# ---------------------------------------------------------------------------
# File kinds (by extension)
# ---------------------------------------------------------------------------

# kind -> short label
KINDS = {
    "video": "Video",
    "audio": "Audio",
    "image": "Image",
    "raw_photo": "Camera RAW photo",
    "document": "Document",
    "spreadsheet": "Spreadsheet",
    "presentation": "Presentation",
    "ebook": "E-book",
    "text": "Text",
    "archive": "Archive",
    "installer": "Installer",
    "disk_image": "Disk image",
    "vm": "Virtual machine disk",
    "executable": "Program",
    "library": "Program library",
    "driver": "Driver / system file",
    "script": "Script",
    "code": "Source code",
    "temp": "Temporary file",
    "log": "Log file",
    "dump": "Crash dump",
    "cache": "Cache file",
    "backup": "Backup",
    "database": "Database",
    "config": "Settings / config",
    "font": "Font",
    "shortcut": "Shortcut",
    "torrent": "Torrent",
    "partial_download": "Unfinished download",
    "design": "Design / 3D file",
    "game_data": "Game data",
    "email": "Email data",
    "other": "Other",
}

# extension -> (kind, what it is)
EXTENSIONS: dict[str, tuple[str, str]] = {
    # Video
    ".mp4": ("video", "MPEG-4 video, the most common video format (phones, downloads, screen recordings)."),
    ".mkv": ("video", "Matroska video container, often used for movies and TV episodes."),
    ".mov": ("video", "QuickTime video, typical for iPhone and Mac recordings."),
    ".avi": ("video", "Older Windows video format."),
    ".wmv": ("video", "Windows Media Video."),
    ".webm": ("video", "Web video format (YouTube, browsers)."),
    ".m4v": ("video", "Apple MPEG-4 video (iTunes movies/TV)."),
    ".flv": ("video", "Old Flash video."),
    ".mpg": ("video", "MPEG video."), ".mpeg": ("video", "MPEG video."),
    ".ts": ("video", "MPEG transport stream video (TV recordings, some downloads). "
                     "Note: .ts is also used for TypeScript source code in programming projects."),
    ".mts": ("video", "AVCHD camcorder video."), ".m2ts": ("video", "Blu-ray / camcorder video."),
    ".3gp": ("video", "Old mobile phone video."),
    ".vob": ("video", "DVD video file."),
    # Audio
    ".mp3": ("audio", "MP3 music or audio."), ".wav": ("audio", "Uncompressed audio (large)."),
    ".flac": ("audio", "Lossless compressed music."), ".aac": ("audio", "AAC audio."),
    ".m4a": ("audio", "AAC/Apple audio (iTunes, voice memos)."), ".ogg": ("audio", "Ogg Vorbis audio."),
    ".wma": ("audio", "Windows Media Audio."), ".aiff": ("audio", "Uncompressed Apple audio."),
    ".aif": ("audio", "Uncompressed Apple audio."), ".opus": ("audio", "Opus audio (voice messages, streaming)."),
    ".mid": ("audio", "MIDI music notes (tiny)."),
    # Images
    ".jpg": ("image", "JPEG photo or picture."), ".jpeg": ("image", "JPEG photo or picture."),
    ".png": ("image", "PNG image (screenshots, graphics)."), ".gif": ("image", "GIF image / animation."),
    ".bmp": ("image", "Uncompressed bitmap image."), ".webp": ("image", "WebP image from the web."),
    ".heic": ("image", "iPhone photo (HEIF format)."), ".heif": ("image", "HEIF photo."),
    ".tif": ("image", "TIFF image (scans, print)."), ".tiff": ("image", "TIFF image (scans, print)."),
    ".svg": ("image", "Scalable vector graphic."), ".ico": ("image", "Icon image."),
    ".psd": ("design", "Adobe Photoshop project."), ".ai": ("design", "Adobe Illustrator artwork."),
    ".xcf": ("design", "GIMP image project."), ".indd": ("design", "Adobe InDesign layout."),
    ".blend": ("design", "Blender 3D project."), ".fbx": ("design", "3D model."), ".obj": ("design", "3D model (or compiled object code)."),
    ".stl": ("design", "3D-printing model."), ".prproj": ("design", "Adobe Premiere Pro video project."),
    ".aep": ("design", "Adobe After Effects project."), ".kra": ("design", "Krita painting."),
    # Camera RAW
    ".cr2": ("raw_photo", "Canon RAW photo (unprocessed, large)."), ".cr3": ("raw_photo", "Canon RAW photo."),
    ".nef": ("raw_photo", "Nikon RAW photo."), ".arw": ("raw_photo", "Sony RAW photo."),
    ".dng": ("raw_photo", "Adobe DNG RAW photo."), ".raf": ("raw_photo", "Fujifilm RAW photo."),
    ".orf": ("raw_photo", "Olympus RAW photo."), ".rw2": ("raw_photo", "Panasonic RAW photo."),
    # Documents
    ".pdf": ("document", "PDF document."), ".doc": ("document", "Older Microsoft Word document."),
    ".docx": ("document", "Microsoft Word document."), ".odt": ("document", "OpenDocument text."),
    ".rtf": ("document", "Rich-text document."), ".pages": ("document", "Apple Pages document."),
    ".xls": ("spreadsheet", "Older Excel spreadsheet."), ".xlsx": ("spreadsheet", "Excel spreadsheet."),
    ".xlsm": ("spreadsheet", "Excel spreadsheet with macros."), ".ods": ("spreadsheet", "OpenDocument spreadsheet."),
    ".csv": ("spreadsheet", "Comma-separated data table (opens in Excel)."),
    ".numbers": ("spreadsheet", "Apple Numbers spreadsheet."),
    ".ppt": ("presentation", "Older PowerPoint presentation."), ".pptx": ("presentation", "PowerPoint presentation."),
    ".odp": ("presentation", "OpenDocument presentation."), ".key": ("presentation", "Apple Keynote presentation."),
    ".epub": ("ebook", "E-book."), ".mobi": ("ebook", "Kindle e-book."), ".azw3": ("ebook", "Kindle e-book."),
    ".txt": ("text", "Plain text file."), ".md": ("text", "Markdown text / notes."),
    ".one": ("document", "OneNote notebook section."),
    # Email
    ".pst": ("email", "Outlook mailbox archive. Can be huge; it holds your emails, so don't delete "
                      "unless you're sure it's an old copy."),
    ".ost": ("email", "Outlook offline mailbox cache. Outlook re-downloads it from the server "
                      "if it's removed (when Outlook is closed)."),
    ".eml": ("email", "Single saved email message."), ".msg": ("email", "Saved Outlook email message."),
    # Archives
    ".zip": ("archive", "ZIP compressed archive. If you've already extracted it, the .zip is a copy."),
    ".rar": ("archive", "RAR compressed archive."), ".7z": ("archive", "7-Zip compressed archive."),
    ".tar": ("archive", "TAR archive."), ".gz": ("archive", "Gzip compressed file."),
    ".tgz": ("archive", "Compressed TAR archive."), ".bz2": ("archive", "Bzip2 compressed file."),
    ".xz": ("archive", "XZ compressed file."), ".zst": ("archive", "Zstandard compressed file."),
    # Installers
    ".msi": ("installer", "Windows installer package. Once the program is installed you usually don't need it."),
    ".msix": ("installer", "Modern Windows app installer."), ".appx": ("installer", "Windows Store app package."),
    ".dmg": ("installer", "macOS disk image, usually an app installer. Not needed after the app is in Applications."),
    ".pkg": ("installer", "macOS installer package."),
    ".deb": ("installer", "Debian/Ubuntu software package."), ".rpm": ("installer", "Fedora/Red Hat software package."),
    ".apk": ("installer", "Android app package."), ".appimage": ("installer", "Portable Linux app."),
    ".msu": ("installer", "Windows Update package."),
    # Disk images / VMs
    ".iso": ("disk_image", "CD/DVD disk image (OS installers, old games). Large; you can re-download most of these."),
    ".img": ("disk_image", "Raw disk image."), ".bin": ("disk_image", "Raw disk image or binary data."),
    ".vhd": ("vm", "Virtual hard disk (Hyper-V / Windows backup)."), ".vhdx": ("vm", "Virtual hard disk (Hyper-V, WSL, Docker)."),
    ".vmdk": ("vm", "VMware / VirtualBox virtual disk."), ".vdi": ("vm", "VirtualBox virtual disk."),
    ".qcow2": ("vm", "QEMU/KVM virtual disk."), ".ova": ("vm", "Exported virtual machine."),
    # Programs
    ".exe": ("executable", "Windows program. Could be an installed app, a portable tool or an installer (setup)."),
    ".com": ("executable", "Old-style DOS/Windows program."),
    ".app": ("executable", "macOS application bundle."),
    ".dll": ("library", "Windows code library used by programs. Programs break if it's removed."),
    ".so": ("library", "Linux shared library used by programs."), ".dylib": ("library", "macOS shared library."),
    ".sys": ("driver", "Windows driver or system file. Never delete."),
    ".drv": ("driver", "Windows driver."), ".cat": ("driver", "Windows driver security catalog."),
    ".inf": ("driver", "Driver/setup information file."), ".mui": ("library", "Windows language resource."),
    ".efi": ("driver", "Boot loader / firmware program."),
    ".jar": ("executable", "Java program / library."),
    # Scripts / code
    ".bat": ("script", "Windows batch script (runs commands)."), ".cmd": ("script", "Windows command script."),
    ".ps1": ("script", "PowerShell script."), ".sh": ("script", "Shell script."),
    ".vbs": ("script", "VBScript (be careful with unknown ones, can be malware)."),
    ".py": ("code", "Python source code."), ".js": ("code", "JavaScript source code."),
    ".tsx": ("code", "TypeScript React source code."), ".java": ("code", "Java source code."),
    ".c": ("code", "C source code."), ".cpp": ("code", "C++ source code."), ".h": ("code", "C/C++ header."),
    ".cs": ("code", "C# source code."), ".go": ("code", "Go source code."), ".rs": ("code", "Rust source code."),
    ".html": ("code", "Web page."), ".htm": ("code", "Web page."), ".css": ("code", "Web stylesheet."),
    ".php": ("code", "PHP source code."), ".rb": ("code", "Ruby source code."),
    ".pyc": ("cache", "Compiled Python bytecode cache. Python rebuilds it automatically."),
    ".class": ("cache", "Compiled Java class (rebuilt when the project is compiled)."),
    ".o": ("cache", "Compiled object file (build output, rebuilt on compile)."),
    ".pdb": ("cache", "Program debug symbols. Only developers need these."),
    ".ilk": ("cache", "Visual Studio incremental-link file (build output)."),
    ".ipch": ("cache", "Visual Studio IntelliSense cache."),
    # Temp / logs / dumps / cache
    ".tmp": ("temp", "Temporary file a program created while working. Usually forgotten leftovers."),
    ".temp": ("temp", "Temporary file."), ".bak": ("backup", "Backup copy made by a program before saving."),
    ".old": ("backup", "Old copy kept after an update or edit."), ".~tmp": ("temp", "Temporary file."),
    ".swp": ("temp", "Vim editor swap file (leftover if the editor crashed)."),
    ".crdownload": ("partial_download", "Chrome download that never finished."),
    ".part": ("partial_download", "Firefox/other download that never finished."),
    ".partial": ("partial_download", "Edge/other download that never finished."),
    ".download": ("partial_download", "Safari download that never finished."),
    ".log": ("log", "Log file: a diary a program writes about what it did. Only useful for troubleshooting."),
    ".etl": ("log", "Windows event trace log (diagnostics)."), ".evtx": ("log", "Windows Event Log."),
    ".dmp": ("dump", "Crash dump: a memory snapshot saved when a program or Windows crashed. Only useful for debugging."),
    ".mdmp": ("dump", "Mini crash dump."), ".hdmp": ("dump", "Heap crash dump."),
    ".cache": ("cache", "Cache file. Programs rebuild caches automatically."),
    ".thumbcache": ("cache", "Thumbnail cache."),
    # Databases / config
    ".db": ("database", "Database file used by some program."), ".sqlite": ("database", "SQLite database used by a program."),
    ".sqlite3": ("database", "SQLite database."), ".mdb": ("database", "Microsoft Access database."),
    ".accdb": ("database", "Microsoft Access database."),
    ".ini": ("config", "Settings file."), ".cfg": ("config", "Settings file."), ".conf": ("config", "Settings file."),
    ".json": ("config", "Data/settings in JSON format."), ".xml": ("config", "Data/settings in XML format."),
    ".yaml": ("config", "Settings in YAML format."), ".yml": ("config", "Settings in YAML format."),
    ".reg": ("config", "Windows Registry export (double-clicking it changes your registry)."),
    ".plist": ("config", "macOS settings file."),
    # Misc
    ".ttf": ("font", "Font."), ".otf": ("font", "Font."), ".woff": ("font", "Web font."), ".woff2": ("font", "Web font."),
    ".lnk": ("shortcut", "Windows shortcut pointing to another file or program. Tiny."),
    ".url": ("shortcut", "Internet shortcut."),
    ".torrent": ("torrent", "Torrent link file (tiny). Not the download itself."),
    ".vpk": ("game_data", "Valve game data package."), ".pak": ("game_data", "Game data package."),
    ".sav": ("game_data", "Game save file. Keep if you care about your progress."),
    ".backup": ("backup", "Backup file."), ".tib": ("backup", "Acronis backup image."),
    ".wim": ("disk_image", "Windows image (system backup or installer)."),
    ".esd": ("disk_image", "Compressed Windows installer image."),
}

# ---------------------------------------------------------------------------
# Well-known individual files (matched on lowercase file name)
# name -> (what it is, verdict, why)
# ---------------------------------------------------------------------------

KNOWN_FILES: dict[str, tuple[str, str, str]] = {
    "pagefile.sys": (
        "Windows page file: extra 'virtual memory' on disk that Windows uses when RAM is full.",
        SYSTEM,
        "Can't be deleted while Windows runs. You can shrink or move it in System Properties -> "
        "Advanced -> Performance -> Virtual memory.",
    ),
    "hiberfil.sys": (
        "Hibernation file: Windows saves the contents of RAM here when the PC hibernates or uses Fast Startup.",
        SYSTEM,
        "To remove it, turn hibernation off by running 'powercfg /hibernate off' in an admin "
        "Command Prompt. Don't delete it by hand.",
    ),
    "swapfile.sys": ("Windows swap file for Store apps.", SYSTEM, "Managed by Windows together with the page file."),
    "dumpstack.log": ("Windows boot-time crash logging file.", SYSTEM, "Managed by Windows."),
    "dumpstack.log.tmp": ("Windows boot-time crash logging file.", SYSTEM, "Managed by Windows."),
    "memory.dmp": (
        "Full Windows crash dump (written after a blue screen).",
        DELETE,
        "Only useful for diagnosing an old blue-screen crash. Can be several GB.",
    ),
    "thumbs.db": ("Old Windows thumbnail cache for this folder.", DELETE, "Windows rebuilds it if needed."),
    "desktop.ini": (
        "Hidden Windows file that stores this folder's custom icon/name/view settings.",
        KEEP,
        "Tiny; deleting it just resets the folder's look.",
    ),
    ".ds_store": ("macOS Finder folder-view settings.", DELETE, "Tiny; Finder recreates it."),
    "ntuser.dat": ("Your Windows user profile's registry (all your settings).", SYSTEM, "Deleting it destroys your profile."),
    "ntuser.dat.log1": ("Registry transaction log for your profile.", SYSTEM, "Managed by Windows."),
    "ntuser.dat.log2": ("Registry transaction log for your profile.", SYSTEM, "Managed by Windows."),
    "usrclass.dat": ("Part of your Windows profile registry.", SYSTEM, "Managed by Windows."),
    "bootmgr": ("Windows boot manager.", SYSTEM, "Your PC won't start without it."),
    "bootnxt": ("Windows boot file.", SYSTEM, "Needed to start Windows."),
    "iconcache.db": ("Windows icon cache.", DELETE, "Windows rebuilds it (may need a restart)."),
    "index.dat": ("Old Internet Explorer history/cache index.", DELETE, "Leftover from old browsers."),
    "package-lock.json": ("npm dependency lock file for a JavaScript project.", KEEP, "Part of a code project."),
    ".gitignore": ("Tells Git which files to ignore in a code project.", KEEP, "Part of a code project."),
}

# ---------------------------------------------------------------------------
# Well-known folders. Each rule is matched against the lowercase folder path
# with forward slashes, without the drive letter and wrapped in slashes
# ("/users/me/appdata/local/temp/"). A fragment starting with "^" must match
# at the start of the path (the drive root); others can match anywhere.
# The first matching rule wins, so more specific rules go first.
# (fragment, label, what it is, verdict, why)
# ---------------------------------------------------------------------------

FOLDER_RULES: list[tuple[str, str, str, str, str]] = [
    # --- trash
    ("^/$recycle.bin/", "Recycle Bin", "Files you already deleted, sitting in the Recycle Bin.", DELETE,
     "Empty the Recycle Bin to free this space for real."),
    ("/.trash/", "Trash", "Files you already deleted, sitting in the Trash.", DELETE, "Empty the Trash."),
    ("/.local/share/trash/", "Trash", "Files you already deleted, sitting in the Trash.", DELETE, "Empty the Trash."),
    # --- Windows leftovers that are safe to clean
    ("^/windows/softwaredistribution/download/", "Windows Update downloads",
     "Update files Windows already downloaded and (usually) installed.", DELETE,
     "Safe to clear. Best done with Disk Cleanup -> 'Clean up system files' or Settings -> Storage -> Temporary files."),
    ("^/windows/temp/", "Windows temp folder", "Temporary files created by Windows and installers.", DELETE,
     "Safe to clear (files in use will simply be skipped)."),
    ("^/windows.old/", "Previous Windows installation",
     "A copy of your old Windows from before the last big upgrade, kept so you can roll back.", REVIEW,
     "If the upgrade works fine, remove it with Disk Cleanup -> 'Previous Windows installation(s)'. Often 10-30 GB."),
    ("^/$windows.~bt/", "Windows upgrade files", "Leftover files from a Windows upgrade.", REVIEW,
     "Remove with Disk Cleanup -> 'Temporary Windows installation files'."),
    ("^/$windows.~ws/", "Windows upgrade files", "Leftover files from a Windows upgrade.", REVIEW,
     "Remove with Disk Cleanup -> 'Temporary Windows installation files'."),
    ("^/windows/minidump/", "Crash dumps", "Small memory dumps from past blue-screen crashes.", DELETE,
     "Only useful for diagnosing old crashes."),
    ("^/windows/livekernelreports/", "Kernel crash reports", "Diagnostic dumps from driver/GPU hiccups.", DELETE,
     "Only useful for diagnosing old problems."),
    ("^/programdata/microsoft/windows/wer/", "Windows Error Reporting",
     "Crash reports Windows collected about programs that crashed.", DELETE, "Only useful for troubleshooting."),
    ("/appdata/local/microsoft/windows/wer/", "Windows Error Reporting",
     "Crash reports Windows collected about programs that crashed.", DELETE, "Only useful for troubleshooting."),
    ("/appdata/local/crashdumps/", "Crash dumps", "Memory dumps from programs that crashed.", DELETE,
     "Only useful for troubleshooting."),
    ("/appdata/local/microsoft/windows/explorer/", "Explorer thumbnail cache",
     "Thumbnail and icon caches for File Explorer.", DELETE, "Windows rebuilds them automatically."),
    ("/appdata/local/microsoft/windows/inetcache/", "Internet cache", "Cached web content.", DELETE,
     "Rebuilt automatically."),
    ("/appdata/local/temp/", "Your temp folder", "Temporary files programs created for you and forgot to clean up.",
     DELETE, "Safe to clear; anything in use will be skipped."),
    ("/appdata/local/nvidia/dxcache/", "NVIDIA shader cache", "Pre-compiled graphics shaders.", DELETE,
     "Rebuilt automatically (games may stutter briefly the first time)."),
    ("/appdata/local/nvidia/glcache/", "NVIDIA shader cache", "Pre-compiled graphics shaders.", DELETE,
     "Rebuilt automatically."),
    ("/appdata/local/d3dscache/", "DirectX shader cache", "Pre-compiled graphics shaders.", DELETE,
     "Rebuilt automatically."),
    ("/appdata/local/amd/dxcache/", "AMD shader cache", "Pre-compiled graphics shaders.", DELETE, "Rebuilt automatically."),
    ("^/nvidia/installer2/", "Old NVIDIA installer files", "Leftover driver installer files.", DELETE,
     "Not needed after the driver is installed."),
    ("/appdata/local/packages/", "Store app data", "Data for Microsoft Store apps.", SYSTEM,
     "Clear app data from Settings -> Apps instead."),
    # --- operating system / installed programs (anchored to the drive root)
    ("^/windows/", "Windows", "The Windows operating system.", SYSTEM,
     "Never delete or move files here by hand. Use Disk Cleanup for safe cleanup."),
    ("^/program files/", "Installed programs", "Programs installed on this PC.", SYSTEM,
     "Uninstall from Settings -> Apps instead of deleting files. Moving these breaks the program."),
    ("^/program files (x86)/", "Installed programs (32-bit)", "32-bit programs installed on this PC.", SYSTEM,
     "Uninstall from Settings -> Apps instead of deleting files."),
    ("^/programdata/", "Program data", "Shared data and settings for installed programs.", SYSTEM,
     "Belongs to installed programs. Uninstall the program instead."),
    ("^/system volume information/", "System Restore data", "Restore points and system indexing data.", SYSTEM,
     "Manage restore points in System Protection settings."),
    ("^/recovery/", "Recovery partition data", "Windows recovery tools.", SYSTEM, "Needed to repair Windows."),
    ("^/boot/", "Boot files", "Files your computer needs to start.", SYSTEM, "Your computer may not start without them."),
    ("^/efi/", "Boot files", "Boot loader files.", SYSTEM, "Your computer may not start without them."),
    ("^/applications/", "Applications", "Installed macOS apps.", SYSTEM, "Uninstall apps by dragging them to the Trash."),
    ("^/system/", "System", "Operating system files.", SYSTEM, "Part of the operating system."),
    ("^/usr/", "System programs", "Operating system programs and libraries.", SYSTEM, "Part of the operating system."),
    ("^/etc/", "System settings", "Operating system configuration.", SYSTEM, "Part of the operating system."),
    ("^/var/lib/", "System data", "Data for system services.", SYSTEM, "Part of the operating system."),
    ("^/var/log/", "System logs", "Logs from system services.", REVIEW, "Use your system's log rotation instead."),
    ("^/opt/", "Optional software", "Installed third-party software.", SYSTEM, "Uninstall properly instead."),
    ("^/snap/", "Snap packages", "Installed snap apps.", SYSTEM, "Remove with 'snap remove'."),
    ("^/proc/", "Kernel files", "Virtual files from the Linux kernel.", SYSTEM, "Not real files."),
    ("^/sys/", "Kernel files", "Virtual files from the Linux kernel.", SYSTEM, "Not real files."),
    ("^/dev/", "Devices", "Device files.", SYSTEM, "Not real files."),
    ("^/library/", "Library", "Shared app support files and settings (macOS).", SYSTEM, "Belongs to apps and the OS."),
    # --- browser and app caches
    ("/cache/", "Cache folder", "A program's cache: copies of things it downloaded or computed so it can load faster.",
     DELETE, "The program rebuilds it. Close the program first."),
    ("/cache2/", "Browser cache", "Firefox's web cache.", DELETE, "Rebuilt automatically. Close the browser first."),
    ("/code cache/", "Browser code cache", "Cached compiled website scripts.", DELETE, "Rebuilt automatically."),
    ("/gpucache/", "GPU cache", "Cached graphics data for a browser or Electron app.", DELETE, "Rebuilt automatically."),
    ("/shadercache/", "Shader cache", "Pre-compiled graphics shaders.", DELETE, "Rebuilt automatically."),
    ("/steamapps/shadercache/", "Steam shader cache", "Pre-compiled shaders for your Steam games.", DELETE,
     "Rebuilt automatically."),
    ("/caches/", "Cache folder", "Cached data an app can rebuild.", DELETE, "Rebuilt automatically."),
    ("/.cache/", "Cache folder", "Per-user cache directory for many programs.", DELETE, "Rebuilt automatically."),
    ("/library/caches/", "macOS caches", "App caches on macOS.", DELETE, "Rebuilt automatically."),
    ("/library/logs/", "macOS logs", "App logs on macOS.", DELETE, "Only useful for troubleshooting."),
    # --- developer stuff that can be regenerated
    ("/node_modules/", "node_modules", "Downloaded JavaScript libraries for a code project.", REVIEW,
     "Can be re-downloaded with 'npm install'. Delete the whole folder for projects you're not working on."),
    ("/__pycache__/", "Python cache", "Compiled Python bytecode.", DELETE, "Python rebuilds it automatically."),
    ("/.pytest_cache/", "Pytest cache", "Test runner cache.", DELETE, "Rebuilt automatically."),
    ("/.gradle/caches/", "Gradle cache", "Downloaded Java/Android build libraries.", DELETE, "Re-downloaded when needed."),
    ("/.m2/repository/", "Maven cache", "Downloaded Java libraries.", REVIEW, "Re-downloaded when needed."),
    ("/.npm/_cacache/", "npm cache", "npm download cache.", DELETE, "Re-downloaded when needed."),
    ("/appdata/local/npm-cache/", "npm cache", "npm download cache.", DELETE, "Re-downloaded when needed."),
    ("/appdata/local/pip/cache/", "pip cache", "Python package download cache.", DELETE, "Re-downloaded when needed."),
    ("/appdata/local/yarn/cache/", "Yarn cache", "Yarn download cache.", DELETE, "Re-downloaded when needed."),
    ("/.nuget/packages/", "NuGet cache", "Downloaded .NET libraries.", REVIEW, "Re-downloaded when needed."),
    ("/.git/", "Git repository data", "Version history of a code project.", SYSTEM,
     "Deleting it erases the project's history. Leave it alone."),
    ("/obj/debug/", "Build output", "Intermediate files from compiling a project.", DELETE, "Rebuilt on next build."),
    ("/bin/debug/", "Build output", "Debug build of a project.", REVIEW, "Rebuilt on next build."),
    # --- games
    ("/steamapps/downloading/", "Steam downloads in progress", "Partially downloaded Steam updates.", REVIEW,
     "Steam will re-download if needed."),
    ("/steamapps/common/", "Steam game", "An installed Steam game.", KEEP,
     "To move a game to another drive, use Steam -> Settings -> Storage -> Move. Don't drag the folder yourself."),
    ("/epic games/", "Epic Games game", "An installed Epic Games game.", KEEP,
     "Uninstall from the Epic launcher if you don't play it. Moving it by hand breaks the launcher."),
    ("/xboxgames/", "Xbox / Game Pass game", "An installed Xbox app game.", KEEP,
     "Move it with the Xbox app -> Manage -> Files -> Move."),
    # --- cloud sync folders
    ("/onedrive/", "OneDrive", "Files synced with your OneDrive cloud storage.", KEEP,
     "Deleting here deletes from the cloud too. Use 'Free up space' (right-click) to keep it online-only instead."),
    ("/dropbox/", "Dropbox", "Files synced with Dropbox.", KEEP,
     "Deleting here deletes from the cloud too. Use Dropbox's online-only option to free space."),
    ("/google drive/", "Google Drive", "Files synced with Google Drive.", KEEP,
     "Deleting here deletes from the cloud too."),
    ("/icloud drive/", "iCloud Drive", "Files synced with iCloud.", KEEP, "Deleting here deletes from the cloud too."),
    # --- per-user app data (after caches, so caches inside AppData stay deletable)
    ("/appdata/", "App data", "Settings and data for programs you use.", SYSTEM,
     "Belongs to your apps. Deleting files here can reset or break them (caches and temp folders excepted)."),
    ("/library/", "Library", "App support files and settings (macOS).", SYSTEM, "Belongs to apps and the OS."),
    # --- user folders (context only)
    ("/downloads/", "Downloads", "Things you downloaded from the internet.", KEEP, ""),
    ("/desktop/", "Desktop", "Files on your desktop.", KEEP, ""),
    ("/documents/", "Documents", "Your documents folder.", KEEP, ""),
    ("/pictures/", "Pictures", "Your pictures folder.", KEEP, ""),
    ("/videos/", "Videos", "Your videos folder.", KEEP, ""),
    ("/movies/", "Movies", "Your movies folder.", KEEP, ""),
    ("/music/", "Music", "Your music folder.", KEEP, ""),
    ("^/temp/", "Temp folder", "A temporary-files folder at the top of the drive.", DELETE,
     "Temporary files are safe to remove."),
    ("^/tmp/", "Temp folder", "The system temporary-files folder.", DELETE, "Temporary files are safe to remove."),
    ("^/var/tmp/", "Temp folder", "The system temporary-files folder.", DELETE, "Temporary files are safe to remove."),
]

# Folder rules that are only "context" (they describe where the file is but
# should not decide the verdict on their own).
CONTEXT_ONLY_LABELS = {"Downloads", "Desktop", "Documents", "Pictures", "Videos", "Movies", "Music"}

# Some apps that commonly live under Program Files / AppData, for nicer
# "this belongs to ..." messages. Matched on lowercase folder name.
KNOWN_APPS = {
    "google": "Google (Chrome and other Google apps)",
    "chrome": "Google Chrome",
    "microsoft": "Microsoft",
    "microsoft office": "Microsoft Office",
    "mozilla": "Mozilla (Firefox / Thunderbird)",
    "mozilla firefox": "Firefox",
    "steam": "Steam",
    "discord": "Discord",
    "spotify": "Spotify",
    "slack": "Slack",
    "zoom": "Zoom",
    "nvidia corporation": "NVIDIA graphics drivers",
    "nvidia": "NVIDIA graphics",
    "amd": "AMD drivers",
    "adobe": "Adobe",
    "code": "Visual Studio Code",
    "microsoft vs code": "Visual Studio Code",
    "teams": "Microsoft Teams",
    "whatsapp": "WhatsApp",
    "obs-studio": "OBS Studio",
    "epic games": "Epic Games Launcher",
    "riot games": "Riot Games (League of Legends / Valorant)",
    "battle.net": "Battle.net",
    "origin": "EA Origin",
    "ea games": "EA",
    "ubisoft": "Ubisoft Connect",
    "docker": "Docker",
    "jetbrains": "JetBrains IDEs",
    "python": "Python",
    "java": "Java",
    "7-zip": "7-Zip",
    "vlc": "VLC media player",
    "brave software": "Brave browser",
    "opera software": "Opera browser",
    "packages": "Microsoft Store apps",
}

# Magic bytes for identifying files with a missing or misleading extension.
# (prefix bytes, offset, description, kind)
MAGIC = [
    (b"%PDF", 0, "PDF document", "document"),
    (b"PK\x03\x04", 0, "ZIP archive (or an Office document / Java jar / app package, which are ZIPs inside)", "archive"),
    (b"Rar!", 0, "RAR archive", "archive"),
    (b"7z\xbc\xaf\x27\x1c", 0, "7-Zip archive", "archive"),
    (b"\x1f\x8b", 0, "Gzip compressed data", "archive"),
    (b"MZ", 0, "Windows program or library (EXE/DLL)", "executable"),
    (b"\x7fELF", 0, "Linux program or library", "executable"),
    (b"\xcf\xfa\xed\xfe", 0, "macOS program", "executable"),
    (b"\x89PNG", 0, "PNG image", "image"),
    (b"\xff\xd8\xff", 0, "JPEG image", "image"),
    (b"GIF8", 0, "GIF image", "image"),
    (b"RIFF", 0, "RIFF media (WAV audio, AVI video or WebP image)", "video"),
    (b"ftyp", 4, "MP4 / MOV / HEIC media", "video"),
    (b"\x1a\x45\xdf\xa3", 0, "Matroska / WebM video", "video"),
    (b"ID3", 0, "MP3 audio", "audio"),
    (b"fLaC", 0, "FLAC audio", "audio"),
    (b"OggS", 0, "Ogg audio/video", "audio"),
    (b"SQLite format 3", 0, "SQLite database (programs store data in these)", "database"),
    (b"\xd0\xcf\x11\xe0", 0, "Old Microsoft Office document or Windows installer (OLE file)", "document"),
    (b"MDMP", 0, "Windows crash dump", "dump"),
    (b"PAGEDU64", 0, "Windows kernel crash dump", "dump"),
    (b"CD001", 0x8001, "ISO disk image", "disk_image"),
    (b"conectix", 0, "Virtual hard disk (VHD)", "vm"),
    (b"vhdxfile", 0, "Virtual hard disk (VHDX)", "vm"),
    (b"KDMV", 0, "VMware virtual disk", "vm"),
]

# Kinds that are personal "bulk" files worth moving to a second drive.
MOVABLE_KINDS = {"video", "audio", "image", "raw_photo", "archive", "disk_image", "vm",
                 "backup", "design", "ebook", "email"}
# Kinds that should never be moved by hand (they belong to installed software).
UNMOVABLE_KINDS = {"executable", "library", "driver"}
