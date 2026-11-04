# File Sorter

A desktop app that scans a folder or a whole drive and tells you:

- **what you can get rid of**: temp files, caches, crash dumps, old logs, unfinished downloads, old installers, duplicates, empty files
- **what you can move to your other drive**: big videos, photo libraries, archives, ISOs, virtual machine disks, backups, and big files you haven't opened in a long time
- **what you shouldn't touch**: Windows/macOS/Linux system files, installed programs and app data
- **what any file you click on actually is**: the file type, which program it belongs to, what happens if you delete it, and (for Windows programs) the description and maker stored inside the `.exe`/`.dll`

Everything runs on your computer. Nothing is uploaded unless you press **Ask Claude** (optional, see below).

## Install and run

**Easiest (Windows):** download **[FileSorter.exe](https://github.com/timothymasso/test/releases/download/latest/FileSorter.exe)** and double-click it. Nothing else to install. Windows may show "Windows protected your PC" because the program isn't signed: click **More info** -> **Run anyway**.

**Or run it with Python** (Windows, macOS or Linux). You need **Python 3.10 or newer**. On Windows, get it from [python.org](https://www.python.org/downloads/) and tick *"Add python.exe to PATH"* during setup. Python comes with everything the app needs.

1. Download this repository (green **Code** button → **Download ZIP**) and unzip it.
2. The first time, double-click **`setup.bat`**. It installs Recycle Bin support (so deleted files can be
   restored) and starts the app. On macOS/Linux run `pip install send2trash` instead.

3. After that, start the app by double-clicking **`run.pyw`**, or from a terminal:

   ```bash
   python -m file_sorter
   ```

## How to use it

1. Pick a folder, or a whole drive from **Drives**, and press **Scan**. Scanning your user folder (the default) is a good start. Scanning all of `C:\` takes longer and works best if you run the app as administrator.
   - **Scan** is quick and skips duplicates.
   - **Scan + find duplicates** also finds identical copies of your files. It takes longer because it has to compare file contents; you can press **Stop** at any time.
2. The **Space map** shows where your space goes: every box is a folder, sized by how much it holds and coloured by what's inside (green = delete, yellow = review, blue = move, grey = keep, red = don't touch). Click a box to look inside it.
3. The coloured cards and the bar under them show how much space each group uses. Click one to list only those files.

   | Suggestion | Meaning |
   |---|---|
   | **Safe to delete** (green) | Temp files, caches, crash dumps, Recycle Bin contents. Programs recreate these if they need them. |
   | **Review** (orange) | Probably not needed: old installers, duplicates, `.bak` files, `windows.old`, `node_modules`. Check before deleting. |
   | **Move to other drive** (blue) | Big personal files you want to keep that don't need to be on your main drive. |
   | **Keep** (grey) | Normal files. |
   | **System – don't touch** (red) | OS and program files. The app refuses to delete or move these. |

4. Click any file to see **what it is** in the panel on the right. Text files show their first lines; files with no or misleading extensions are identified from their contents (and you get a warning if, say, a "PDF" is really a program).
5. Select one or more files (Ctrl/Shift-click, or **Select all shown**), then:
   - **Move to other drive...**: pick a folder on the other drive. The original folder structure is kept, and every move is logged in `moved_by_file_sorter.csv` in that folder so you can always find things again. Files are copied and checked before the original is removed.
   - **Delete...**: sends files to the Recycle Bin (or deletes them permanently, after a warning, if `send2trash` isn't installed).
6. The **Groups** tab sorts files by what they belong to (an app's cache, a game, iPhone backups, installers, photos from 2021...). **Clean up X now** at the top deletes everything marked *Safe to delete* in one go (cloud-synced files are left out). Delete on a group only removes its *Safe to delete* files; *Review* files you pick by hand.
7. **Right-click** any file, group or folder for more options, including **Never touch** (File Sorter will leave that folder alone from then on).
8. **Tools** (top right): empty the Recycle Bin (deleted files only free space once it's emptied), Disk Cleanup, Storage settings, turn off hibernation, **move files back** from the other drive, and the never-touch list.
9. To see duplicates, choose **Duplicates** in the **Show** menu: each copy is listed next to its original. **Select all shown** picks only the extra copies, and the app won't let you delete every copy of a file.
10. The **Biggest folders** tab shows where your space goes. Double-click a folder to list its files.

### Things the app tells you to do elsewhere

Some big space users shouldn't be deleted by hand. The app points you to the right tool:

- `hiberfil.sys`: turn hibernation off with `powercfg /hibernate off` (admin Command Prompt)
- `pagefile.sys`: System Properties → Advanced → Performance → Virtual memory
- `Windows.old`, Windows Update files: **Disk Cleanup** → *Clean up system files*
- Steam / Xbox / Epic games: move them with the game launcher's own "Move" feature
- OneDrive / Dropbox files: use "Free up space" / online-only instead of deleting

## Optional: "Ask Claude about this file"

For files the built-in knowledge can't explain, the **Ask Claude** button asks Claude (Anthropic's AI) what the file is and whether it's safe to remove. It sends only the file's **path, name, size, dates and detected type**, never its contents, and asks you first every time.

To turn it on:

```bash
pip install anthropic
```

Then set your API key (from [console.anthropic.com](https://console.anthropic.com)) as the `ANTHROPIC_API_KEY` environment variable and restart the app. On Windows: Start → "Edit environment variables for your account" → New. Each question costs a fraction of a cent.

## For developers

```text
file_sorter/
  knowledge.py   file types, well-known files and folders, and the rules' vocabulary
  analysis.py    assess() decides the suggestion, explain() builds the "what is this" text
  scanner.py     walks the disk, finds duplicates, totals folder sizes
  actions.py     move (copy, verify, delete, log) and delete (Recycle Bin)
  ai.py          optional Claude explanation
  app.py         tkinter window
  widgets.py     theme, storage bar, drive meters, space map
  treemap.py     space map layout (squarified treemap)
  groups.py      groups files by what they belong to
  smart.py       installed-program checks: installer versions, leftover app data
  prefs.py       remembered settings and the never-touch list
```

Run the tests with:

```bash
pip install pytest && python -m pytest
```

To teach the app about a new file type or folder, add a line to `EXTENSIONS`, `KNOWN_FILES` or `FOLDER_RULES` in `knowledge.py`.
