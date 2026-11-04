"""File Sorter - the desktop window (tkinter, comes with Python)."""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import actions, ai
from . import knowledge as kb
from .analysis import Settings, explain, human_size, match_folders, owning_app
from .scanner import FileEntry, ScanResult, scan

MAX_ROWS = 3000

VERDICT_COLORS = {
    kb.DELETE: "#1e8e3e",
    kb.REVIEW: "#b26a00",
    kb.MOVE: "#1a73e8",
    kb.KEEP: "#5f6368",
    kb.SYSTEM: "#c5221f",
}
VERDICT_BG = {
    kb.DELETE: "#e6f4ea",
    kb.REVIEW: "#fef7e0",
    kb.MOVE: "#e8f0fe",
    kb.KEEP: "#ffffff",
    kb.SYSTEM: "#fce8e6",
}
ALL = "Everything"
RUNNABLE_KINDS = {"executable", "library", "driver", "script", "installer"}
RUNNABLE_EXTS = (".exe", ".com", ".scr", ".pif", ".bat", ".cmd", ".vbs", ".js", ".jse", ".wsf", ".ps1",
                 ".msi", ".lnk", ".reg", ".hta", ".jar")


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def default_scan_path() -> str:
    return os.path.expanduser("~")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("File Sorter - what can I delete or move?")
        self.geometry("1280x800")
        self.minsize(900, 560)

        self.result: ScanResult | None = None
        self.rows: dict[str, FileEntry] = {}
        self.folder_rows: dict[str, str] = {}
        self.scan_thread: threading.Thread | None = None
        self.cancel = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.sort_key = "size"
        self.sort_desc = True
        self.folder_filter: str | None = None
        self.current: FileEntry | None = None
        self.busy = False  # a move/delete is running

        self.path_var = tk.StringVar(value=default_scan_path())
        self.dupes_var = tk.BooleanVar(value=True)
        self.media_mb_var = tk.IntVar(value=50)
        self.stale_days_var = tk.IntVar(value=365)
        self.search_var = tk.StringVar()
        self.show_var = tk.StringVar(value=ALL)
        self.status_var = tk.StringVar(value="Pick a folder or drive and press Scan.")

        self._style()
        self._build()
        self._show_welcome()
        self.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names() and sys.platform.startswith("linux"):
            style.theme_use("clam")
        style.configure("Treeview", rowheight=24)
        style.configure("Heading.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))

    def _build(self) -> None:
        # --- top bar
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Scan:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.path_var, width=60)
        entry.pack(side="left", padx=4, fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.start_scan())
        ttk.Button(top, text="Browse...", command=self.browse).pack(side="left", padx=2)
        self.drive_menu = ttk.Menubutton(top, text="Drives")
        self.drive_menu.pack(side="left", padx=2)
        self._fill_drive_menu()
        self.scan_btn = ttk.Button(top, text="Scan", style="Accent.TButton", command=self.start_scan)
        self.scan_btn.pack(side="left", padx=(8, 2))
        self.stop_btn = ttk.Button(top, text="Stop", command=self.stop_scan, state="disabled")
        self.stop_btn.pack(side="left", padx=2)

        opts = ttk.Frame(self, padding=(10, 0, 10, 6))
        opts.pack(fill="x")
        ttk.Checkbutton(opts, text="Find duplicate files", variable=self.dupes_var).pack(side="left")
        ttk.Label(opts, text="   Suggest moving photos/videos/archives bigger than").pack(side="left")
        ttk.Spinbox(opts, from_=1, to=100000, width=6, textvariable=self.media_mb_var).pack(side="left", padx=2)
        ttk.Label(opts, text="MB,  and files unused for").pack(side="left")
        ttk.Spinbox(opts, from_=30, to=10000, width=6, textvariable=self.stale_days_var).pack(side="left", padx=2)
        ttk.Label(opts, text="days").pack(side="left")
        self.drives_label = ttk.Label(opts, text="", foreground="#5f6368")
        self.drives_label.pack(side="right")
        self._update_drives_label()

        # --- summary cards
        self.cards = ttk.Frame(self, padding=(10, 0, 10, 6))
        self.cards.pack(fill="x")
        self.card_labels: dict[str, tk.Label] = {}
        for v in [ALL] + kb.VERDICTS:
            fg = VERDICT_COLORS.get(v, "#202124")
            bg = VERDICT_BG.get(v, "#f1f3f4")
            lbl = tk.Label(self.cards, text=v, justify="left", anchor="w", bg=bg, fg=fg,
                           font=("TkDefaultFont", 10, "bold"), padx=10, pady=6, cursor="hand2",
                           relief="groove", bd=1)
            lbl.pack(side="left", fill="x", expand=True, padx=2)
            lbl.bind("<Button-1>", lambda e, v=v: self.set_filter(v))
            self.card_labels[v] = lbl

        # --- main split
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill="both", expand=True)

        # files tab
        files_tab = ttk.Frame(self.tabs, padding=4)
        self.tabs.add(files_tab, text="Files")
        bar = ttk.Frame(files_tab)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Show:").pack(side="left")
        show = ttk.Combobox(bar, textvariable=self.show_var, values=[ALL] + kb.VERDICTS,
                            state="readonly", width=26)
        show.pack(side="left", padx=4)
        show.bind("<<ComboboxSelected>>", lambda e: self.refresh_files())
        ttk.Label(bar, text="  Search:").pack(side="left")
        search = ttk.Entry(bar, textvariable=self.search_var, width=24)
        search.pack(side="left", padx=4)
        self.search_var.trace_add("write", lambda *a: self._debounced_refresh())
        self.folder_chip = ttk.Button(bar, text="", command=self.clear_folder_filter)
        ttk.Button(bar, text="Select all shown", command=self.select_all).pack(side="right")

        cols = ("name", "size", "verdict", "type", "used", "folder")
        self.tree = ttk.Treeview(files_tab, columns=cols, show="headings", selectmode="extended")
        heads = {"name": "Name", "size": "Size", "verdict": "Suggestion", "type": "Type",
                 "used": "Last used", "folder": "Folder"}
        widths = {"name": 260, "size": 80, "verdict": 150, "type": 120, "used": 90, "folder": 300}
        for c in cols:
            self.tree.heading(c, text=heads[c], command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=widths[c], anchor="e" if c == "size" else "w",
                             stretch=c in ("name", "folder"))
        for v in kb.VERDICTS:
            self.tree.tag_configure(v, foreground=VERDICT_COLORS[v], background=VERDICT_BG[v])
        ysb = ttk.Scrollbar(files_tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())

        # folders tab
        folders_tab = ttk.Frame(self.tabs, padding=4)
        self.tabs.add(folders_tab, text="Biggest folders")
        ttk.Label(folders_tab, text="Double-click a folder to list its files.",
                  foreground="#5f6368").pack(anchor="w", pady=(0, 4))
        fcols = ("folder", "size", "files", "what")
        self.ftree = ttk.Treeview(folders_tab, columns=fcols, show="headings", selectmode="browse")
        for c, t, w in (("folder", "Folder", 380), ("size", "Size", 90), ("files", "Files", 70),
                        ("what", "What it is", 260)):
            self.ftree.heading(c, text=t)
            self.ftree.column(c, width=w, anchor="e" if c in ("size", "files") else "w",
                              stretch=c in ("folder", "what"))
        for v in kb.VERDICTS:
            self.ftree.tag_configure(v, foreground=VERDICT_COLORS[v])
        fsb = ttk.Scrollbar(folders_tab, orient="vertical", command=self.ftree.yview)
        self.ftree.configure(yscrollcommand=fsb.set)
        self.ftree.pack(side="left", fill="both", expand=True)
        fsb.pack(side="right", fill="y")
        self.ftree.bind("<<TreeviewSelect>>", lambda e: self.on_folder_select())
        self.ftree.bind("<Double-1>", lambda e: self.drill_into_folder())

        # details panel
        ttk.Label(right, text="What is this file?", style="Heading.TLabel").pack(anchor="w", padx=6, pady=(4, 2))
        txt_frame = ttk.Frame(right)
        txt_frame.pack(fill="both", expand=True, padx=6)
        self.details = tk.Text(txt_frame, wrap="word", relief="flat", padx=10, pady=8,
                               font=("TkDefaultFont", 10), background="#fbfbfb")
        dsb = ttk.Scrollbar(txt_frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=dsb.set, state="disabled")
        self.details.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")
        self.details.tag_configure("title", font=("TkDefaultFont", 13, "bold"), spacing3=6)
        self.details.tag_configure("h", font=("TkDefaultFont", 10, "bold"), spacing1=10, spacing3=2)
        self.details.tag_configure("mono", font=("TkFixedFont", 9), background="#f1f3f4")
        self.details.tag_configure("muted", foreground="#5f6368")
        for v in kb.VERDICTS:
            self.details.tag_configure(v, foreground=VERDICT_COLORS[v], font=("TkDefaultFont", 11, "bold"))

        btns = ttk.Frame(right, padding=(6, 6, 6, 0))
        btns.pack(fill="x")
        btns2 = ttk.Frame(right, padding=(6, 4, 6, 6))
        btns2.pack(fill="x")
        self.btn_open = ttk.Button(btns, text="Open", command=self.open_selected)
        self.btn_reveal = ttk.Button(btns, text="Show in folder", command=self.reveal_selected)
        self.btn_move = ttk.Button(btns, text="Move to other drive...", command=self.move_selected)
        self.btn_delete = ttk.Button(btns, text="Delete...", command=self.delete_selected)
        self.btn_ai = ttk.Button(btns2, text="Ask Claude about this file", command=self.ask_ai)
        for b in (self.btn_open, self.btn_reveal, self.btn_move, self.btn_delete):
            b.pack(side="left", padx=2, expand=True, fill="x")
        self.btn_ai.pack(side="left", padx=2, expand=True, fill="x")
        self._set_buttons(False)

        # status bar
        status = ttk.Frame(self, padding=(10, 2, 10, 6))
        status.pack(fill="x")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")

    def _fill_drive_menu(self) -> None:
        menu = tk.Menu(self.drive_menu, tearoff=False)
        for root, free, total in actions.list_drives():
            menu.add_command(label=f"{root}   ({human_size(free)} free of {human_size(total)})",
                             command=lambda r=root: self.path_var.set(r))
        menu.add_separator()
        menu.add_command(label="My user folder", command=lambda: self.path_var.set(os.path.expanduser("~")))
        self.drive_menu["menu"] = menu

    def _update_drives_label(self) -> None:
        drives = actions.list_drives()
        parts = [f"{r.rstrip(os.sep) or r} {human_size(f)} free" for r, f, t in drives[:4]]
        self.drives_label.configure(text="   ".join(parts))

    def _set_buttons(self, on: bool) -> None:
        for b in (self.btn_open, self.btn_reveal, self.btn_move, self.btn_delete, self.btn_ai):
            b.configure(state="normal" if on else "disabled")

    # ------------------------------------------------------------ details text
    def _write_details(self, chunks: list[tuple[str, str]]) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        for text, tag in chunks:
            # pass tags as a tuple: verdict names contain spaces
            self.details.insert("end", text, (tag,) if tag else ())
        self.details.configure(state="disabled")
        self.details.yview_moveto(0)

    def _show_welcome(self) -> None:
        chunks = [("Welcome to File Sorter\n", "title"),
                  ("1. Pick a folder or a whole drive at the top and press Scan.\n"
                   "2. Every file gets a suggestion. Click the coloured boxes to filter.\n"
                   "3. Click any file to see what it is, what uses it and whether it's safe to remove.\n"
                   "4. Select files and use Move or Delete. Deleting goes to the Recycle Bin.\n", "")]
        for v in kb.VERDICTS:
            chunks.append((f"\n{v}\n", v))
            chunks.append((kb.VERDICT_HELP[v] + "\n", "muted"))
        if not actions.recycle_bin_available():
            chunks.append(("\nTip: run 'pip install send2trash' so deleted files go to the Recycle Bin "
                           "instead of being removed permanently.\n", "muted"))
        self._write_details(chunks)

    # ------------------------------------------------------------------ scanning
    def browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self.path_var.get() or default_scan_path(),
                                    title="Choose a folder or drive to scan")
        if d:
            self.path_var.set(d)

    def start_scan(self) -> None:
        if self.scan_thread and self.scan_thread.is_alive():
            return
        root = self.path_var.get().strip()
        if len(root) == 2 and root[1] == ":":
            root += os.sep
        if not os.path.isdir(root):
            messagebox.showerror("File Sorter", f"'{root}' isn't a folder I can open.")
            return
        try:
            settings = Settings(move_media_mb=max(1, int(self.media_mb_var.get())),
                                stale_days=max(1, int(self.stale_days_var.get())))
        except (tk.TclError, ValueError):
            settings = Settings()
        self.cancel.clear()
        self.scan_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.start(12)
        self.status_var.set(f"Scanning {root} ...")
        self.folder_filter = None
        self.folder_chip.pack_forget()

        find_dupes = bool(self.dupes_var.get())  # read Tk variables on the main thread only

        def work() -> None:
            def progress(n: int, b: int, folder: str) -> None:
                self.events.put(("progress", n, b, folder))
            try:
                res = scan(root, settings, find_dupes, self.cancel, progress)
                self.events.put(("done", res))
            except Exception as e:  # noqa: BLE001
                self.events.put(("error", str(e)))

        self.scan_thread = threading.Thread(target=work, daemon=True)
        self.scan_thread.start()

    def stop_scan(self) -> None:
        self.cancel.set()
        self.status_var.set("Stopping...")

    def _poll(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "progress":
                    _, n, b, folder = ev
                    short = folder if len(folder) < 80 else "..." + folder[-77:]
                    self.status_var.set(f"Scanned {n:,} files ({human_size(b)})   {short}")
                elif kind == "done":
                    self._scan_finished(ev[1])
                elif kind == "error":
                    self._scan_stopped()
                    messagebox.showerror("File Sorter", f"Scan failed: {ev[1]}")
                elif kind == "ai":
                    self._show_ai_answer(ev[1], ev[2])
                elif kind == "status":
                    self.status_var.set(ev[1])
                elif kind == "action_done":
                    self._after_action(ev[1], ev[2])
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll)  # keep polling even if handling an event failed

    def _scan_stopped(self) -> None:
        self.progress.stop()
        self.scan_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _scan_finished(self, res: ScanResult) -> None:
        self._scan_stopped()
        self.result = res
        totals = res.totals()
        removable = totals[kb.DELETE][1] + totals[kb.REVIEW][1]
        movable = totals[kb.MOVE][1]
        state = "Scan stopped early" if res.cancelled else "Scan finished"
        self.status_var.set(
            f"{state}: {plural(len(res.files), 'file')} in {res.seconds:.0f}s. "
            f"You could free up to {human_size(removable)} by deleting and "
            f"{human_size(movable)} by moving." + (f"  ({res.errors:,} items couldn't be read)" if res.errors else ""))
        self.refresh_all()

    # ------------------------------------------------------------------ lists
    def refresh_all(self) -> None:
        self.refresh_cards()
        self.refresh_files()
        self.refresh_folders()

    def refresh_cards(self) -> None:
        if not self.result:
            return
        totals = self.result.totals()
        all_n = sum(v[0] for v in totals.values())
        all_b = sum(v[1] for v in totals.values())
        for v, lbl in self.card_labels.items():
            n, b = (all_n, all_b) if v == ALL else totals[v]
            mark = "> " if self.show_var.get() == v else ""
            lbl.configure(text=f"{mark}{v}\n{plural(n, 'file')}  -  {human_size(b)}")

    def set_filter(self, verdict: str) -> None:
        self.show_var.set(verdict)
        self.tabs.select(0)
        self.refresh_cards()
        self.refresh_files()

    def _debounced_refresh(self) -> None:
        if hasattr(self, "_debounce"):
            self.after_cancel(self._debounce)
        self._debounce = self.after(250, self.refresh_files)

    def _filtered(self) -> list[FileEntry]:
        if not self.result:
            return []
        show = self.show_var.get()
        q = self.search_var.get().strip().lower()
        prefix = None
        if self.folder_filter:
            prefix = os.path.join(self.folder_filter, "")
        out = []
        for f in self.result.files:
            if show != ALL and f.verdict != show:
                continue
            if prefix and not f.path.startswith(prefix):
                continue
            if q and q not in f.path.lower():
                continue
            out.append(f)
        return out

    def refresh_files(self) -> None:
        self.refresh_cards()
        items = self._filtered()
        keyfuncs = {
            "name": lambda f: f.name.lower(),
            "size": lambda f: f.size,
            "verdict": lambda f: kb.VERDICTS.index(f.verdict),
            "type": lambda f: f.assessment.kind_label,
            "used": lambda f: max(f.mtime, f.atime),
            "folder": lambda f: os.path.dirname(f.path).lower(),
        }
        items.sort(key=keyfuncs[self.sort_key], reverse=self.sort_desc)
        shown = items[:MAX_ROWS]
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        now = time.time()
        for i, f in enumerate(shown):
            iid = str(i)
            self.rows[iid] = f
            days = int((now - max(f.mtime, f.atime)) / 86400)
            used = "today" if days < 1 else f"{days} d ago" if days < 60 else \
                f"{days // 30} mo ago" if days < 730 else f"{days / 365:.1f} y ago"
            label = kb.SHORT[f.verdict] + (" (duplicate)" if f.duplicate_of else "")
            self.tree.insert("", "end", iid=iid, tags=(f.verdict,),
                             values=(f.name, human_size(f.size), label, f.assessment.kind_label,
                                     used, os.path.dirname(f.path)))
        total = sum(f.size for f in items)
        extra = f" (showing the first {MAX_ROWS:,})" if len(items) > MAX_ROWS else ""
        self.tabs.tab(0, text=f"Files - {len(items):,} - {human_size(total)}{extra}")

    def sort_by(self, col: str) -> None:
        if self.sort_key == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = col
            self.sort_desc = col in ("size", "used")
        self.refresh_files()

    def select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def refresh_folders(self) -> None:
        self.ftree.delete(*self.ftree.get_children())
        self.folder_rows = {}
        if not self.result:
            return
        biggest = sorted(self.result.folder_sizes.items(), key=lambda kv: kv[1], reverse=True)[:500]
        for i, (folder, size) in enumerate(biggest):
            m = match_folders(os.path.join(folder, "x"))
            primary = next((r for r in m if r.label not in kb.CONTEXT_ONLY_LABELS), None) or (m[0] if m else None)
            what = primary.label if primary else ""
            app = owning_app(os.path.join(folder, "x"))
            if app and app not in what:
                what = f"{what} - {app}" if what else app
            iid = str(i)
            self.folder_rows[iid] = folder
            self.ftree.insert("", "end", iid=iid, tags=((primary.verdict,) if primary else ()),
                              values=(folder, human_size(size), f"{self.result.folder_counts.get(folder, 0):,}", what))

    def clear_folder_filter(self) -> None:
        self.folder_filter = None
        self.folder_chip.pack_forget()
        self.refresh_files()

    def drill_into_folder(self) -> None:
        sel = self.ftree.selection()
        if not sel:
            return
        self.folder_filter = self.folder_rows[sel[0]]
        name = os.path.basename(self.folder_filter) or self.folder_filter
        self.folder_chip.configure(text=f"Only in: {name}  x")
        self.folder_chip.pack(side="left", padx=6)
        self.show_var.set(ALL)
        self.tabs.select(0)
        self.refresh_files()

    # ------------------------------------------------------------------ selection
    def selected_entries(self) -> list[FileEntry]:
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def on_select(self) -> None:
        sel = self.selected_entries()
        self._set_buttons(bool(sel))
        if not sel:
            return
        if len(sel) > 1:
            self.current = None
            self.btn_ai.configure(state="disabled")
            self.btn_open.configure(state="disabled")
            self.btn_reveal.configure(state="disabled")
            total = sum(f.size for f in sel)
            counts: dict[str, int] = {}
            for f in sel:
                counts[f.verdict] = counts.get(f.verdict, 0) + 1
            chunks = [(f"{plural(len(sel), 'file')} selected\n", "title"), (f"Total size: {human_size(total)}\n\n", "")]
            for v in kb.VERDICTS:
                if v in counts:
                    chunks.append((f"{plural(counts[v], 'file')}: {v}\n", v))
            self._write_details(chunks)
            return
        f = sel[0]
        self.current = f
        self.show_file(f)

    def show_file(self, f: FileEntry) -> None:
        try:
            sections = explain(f.path, f.assessment, f.size, f.mtime, f.atime, f.duplicate_of, not f.online_only)
        except OSError as e:
            sections = [("Error", str(e))]
        chunks: list[tuple[str, str]] = [(f.name + "\n", "title")]
        for head, body in sections:
            chunks.append((head + "\n", "h"))
            if head == "Recommendation":
                first, _, rest = body.partition("\n")
                chunks.append((first + "\n", f.verdict))
                chunks.append((rest + "\n", ""))
            elif head == "First lines of the file":
                chunks.append((body + "\n", "mono"))
            else:
                chunks.append((body + "\n", ""))
        chunks.append(("\nNot sure? Press 'Ask Claude about this file' for an AI explanation.\n", "muted"))
        self._write_details(chunks)

    def on_folder_select(self) -> None:
        sel = self.ftree.selection()
        if not sel or not self.result:
            return
        folder = self.folder_rows[sel[0]]
        self._set_buttons(False)
        m = match_folders(os.path.join(folder, "x"))
        prefix = os.path.join(folder, "")
        counts: dict[str, list[int]] = {}
        for f in self.result.files:
            if f.path.startswith(prefix):
                c = counts.setdefault(f.verdict, [0, 0])
                c[0] += 1
                c[1] += f.size
        chunks = [(os.path.basename(folder) or folder, "title"), ("\n" + folder + "\n", "muted")]
        chunks.append(("What it is\n", "h"))
        if m:
            for r in m:
                chunks.append((f"{r.label}: {r.what}\n", ""))
                if r.why:
                    chunks.append((r.why + "\n", "muted"))
        else:
            chunks.append(("A regular folder with no special meaning.\n", ""))
        app = owning_app(os.path.join(folder, "x"))
        if app:
            chunks.append((f"Belongs to: {app}\n", ""))
        chunks.append(("What's inside\n", "h"))
        chunks.append((f"{human_size(self.result.folder_sizes.get(folder, 0))} in "
                       f"{self.result.folder_counts.get(folder, 0):,} files\n", ""))
        for v in kb.VERDICTS:
            if v in counts:
                chunks.append((f"{v}: {plural(counts[v][0], 'file')}, {human_size(counts[v][1])}\n", v))
        chunks.append(("\nDouble-click to list these files.\n", "muted"))
        self._write_details(chunks)

    # ------------------------------------------------------------------ actions
    def open_selected(self) -> None:
        if self.current:
            if self.current.assessment.kind in RUNNABLE_KINDS or self.current.name.lower().endswith(RUNNABLE_EXTS):
                # opening a program runs it; show it in its folder instead
                self.reveal_selected()
                return
            try:
                actions.open_file(self.current.path)
            except OSError as e:
                messagebox.showerror("File Sorter", str(e))

    def reveal_selected(self) -> None:
        if self.current:
            try:
                actions.reveal_in_file_manager(self.current.path)
            except OSError as e:
                messagebox.showerror("File Sorter", str(e))

    def _guard_system(self, entries: list[FileEntry], action: str) -> list[FileEntry] | None:
        if self.busy:
            messagebox.showinfo("File Sorter", "Please wait until the current move/delete has finished.")
            return None
        system = [f for f in entries if f.verdict == kb.SYSTEM]
        if system:
            ok = [f for f in entries if f.verdict != kb.SYSTEM]
            msg = (("1 selected file is a system or program file. " if len(system) == 1 else
                    f"{len(system):,} selected files are system or program files. ") +
                   f"File Sorter won't {action} them because it could break your computer or an app.")
            if not ok:
                messagebox.showwarning("File Sorter", msg)
                return None
            if not messagebox.askokcancel("File Sorter", msg + f"\n\nContinue with the other {len(ok):,} files?"):
                return None
            return ok
        return entries

    def delete_selected(self) -> None:
        entries = self._guard_system(self.selected_entries(), "delete")
        if not entries:
            return
        total = sum(f.size for f in entries)
        risky = [f for f in entries if f.verdict in (kb.KEEP, kb.MOVE)]
        names = "\n".join(f"  {f.name}" for f in entries[:8]) + ("\n  ..." if len(entries) > 8 else "")
        warn = (f"\n\n{len(risky):,} of these are marked '{kb.KEEP}' or '{kb.MOVE}'. Are you sure?"
                if risky else "")
        if all(actions.recycle_bin_works_for(f.path) for f in entries):
            if not messagebox.askyesno("Delete files",
                                       f"Send {plural(len(entries), 'file')} ({human_size(total)}) to the Recycle Bin?\n\n"
                                       f"{names}{warn}"):
                return
            permanently = False
        else:
            why = ("Install 'send2trash' to use the Recycle Bin instead." if not actions.recycle_bin_available()
                   else "Some of these are on a network or removable drive, which has no Recycle Bin.")
            if not messagebox.askyesno("Delete files permanently",
                                       f"PERMANENTLY delete {plural(len(entries), 'file')} ({human_size(total)})?\n"
                                       "They will NOT go to the Recycle Bin and can't be recovered.\n"
                                       f"({why})\n\n{names}{warn}", icon="warning"):
                return
            permanently = True
        paths = [f.path for f in entries]
        self._run_action("Deleting", lambda progress: actions.delete_files(paths, permanently), "Deleted")

    def move_selected(self) -> None:
        entries = self._guard_system(self.selected_entries(), "move")
        if not entries or not self.result:
            return
        dest = filedialog.askdirectory(title="Choose where to move the files (e.g. your other drive)")
        if not dest:
            return
        dest = os.path.abspath(dest)
        root = os.path.abspath(self.result.root)
        try:
            inside = os.path.commonpath([dest, root]) == root
        except ValueError:  # different drives on Windows: that's the point
            inside = False
        if inside:
            messagebox.showerror("File Sorter", "Pick a folder outside the folder you scanned "
                                                "(ideally on your other drive).")
            return
        total = sum(f.size for f in entries)
        try:
            import shutil
            free = shutil.disk_usage(dest).free
        except OSError:
            free = None
        if free is not None and free < total:
            messagebox.showerror("File Sorter", f"Not enough space: you need {human_size(total)} but "
                                                f"the destination only has {human_size(free)} free.")
            return
        unmovable = [f for f in entries if f.assessment.kind in kb.UNMOVABLE_KINDS]
        warn = (f"\n\nWarning: {len(unmovable)} of these are program files; the program may stop working."
                if unmovable else "")
        example = actions.destination_for(entries[0].path, root, dest)
        if not messagebox.askyesno("Move files",
                                   f"Move {plural(len(entries), 'file')} ({human_size(total)}) to:\n{dest}\n\n"
                                   f"Folders are kept, e.g.\n{example}\n\n"
                                   f"A list of everything moved is saved in {actions.LOG_NAME} there.{warn}"):
            return
        paths = [f.path for f in entries]
        self._run_action("Moving", lambda progress: actions.move_files(paths, root, dest, progress), "Moved")

    def _run_action(self, doing: str, work, verb: str) -> None:
        """Run a move/delete off the UI thread so the window never shows 'Not Responding'."""
        self.busy = True
        for b in (self.btn_move, self.btn_delete, self.scan_btn):
            b.configure(state="disabled")
        self.progress.start(12)

        def progress(i: int, n: int, path: str) -> None:
            self.events.put(("status", f"{doing} {i + 1:,} of {n:,}: {os.path.basename(path)}"))

        def run() -> None:
            try:
                report = work(progress)
            except Exception as e:  # noqa: BLE001
                report = actions.ActionReport(failed=[("", str(e))])
            self.events.put(("action_done", report, verb))

        threading.Thread(target=run, daemon=True).start()

    def _after_action(self, report: actions.ActionReport, verb: str) -> None:
        self.busy = False
        self.progress.stop()
        self.scan_btn.configure(state="normal")
        done = {src for src, _ in report.done}
        if self.result:
            gone = [f for f in self.result.files if f.path in done]
            self.result.files = [f for f in self.result.files if f.path not in done]
            for f in gone:  # keep the "Biggest folders" numbers right
                d = os.path.dirname(f.path)
                while d in self.result.folder_sizes:
                    self.result.folder_sizes[d] -= f.size
                    self.result.folder_counts[d] -= 1
                    if os.path.dirname(d) == d:
                        break
                    d = os.path.dirname(d)
        self.status_var.set(f"{verb} {plural(len(report.done), 'file')} ({human_size(report.bytes)}).")
        if report.log_error:
            messagebox.showwarning("File Sorter", f"The files were moved, but the list of moved files couldn't "
                                                  f"be saved: {report.log_error}")
        if report.failed:
            lines = "\n".join(f"{os.path.basename(p)}: {e}" for p, e in report.failed[:10])
            messagebox.showwarning("File Sorter", f"{plural(len(report.failed), 'file')} couldn't be processed "
                                                  f"(they may be in use or need admin rights):\n\n{lines}")
        self.current = None
        self._set_buttons(False)
        self._update_drives_label()
        self.refresh_all()
        self._write_details([(f"{verb} {plural(len(report.done), 'file')} ({human_size(report.bytes)}).\n", "title")])

    # ------------------------------------------------------------------ AI
    def ask_ai(self) -> None:
        f = self.current
        if not f:
            return
        ok, why = ai.is_available()
        if not ok:
            messagebox.showinfo("Ask Claude", why)
            return
        if not messagebox.askokcancel(
                "Ask Claude",
                "This sends the file's name, folder path, size, dates and type to Claude "
                "(Anthropic's AI). The file's contents are NOT sent.\n\nContinue?"):
            return
        facts = self._facts_for_ai(f)
        self.btn_ai.configure(state="disabled", text="Asking Claude...")

        def work() -> None:
            try:
                answer = ai.ask_about_file(facts)
            except Exception as e:  # noqa: BLE001
                answer = f"Something went wrong: {e}"
            self.events.put(("ai", f.path, answer))

        threading.Thread(target=work, daemon=True).start()

    def _facts_for_ai(self, f: FileEntry) -> str:
        sections = explain(f.path, f.assessment, f.size, f.mtime, f.atime, f.duplicate_of, not f.online_only)
        lines = [f"Full path: {f.path}", f"Operating system: {sys.platform}"]
        for head, body in sections:
            if head == "First lines of the file":
                continue  # never send contents
            lines.append(f"\n[{head}]\n{body}")
        return "\n".join(lines)

    def _show_ai_answer(self, path: str, answer: str) -> None:
        self.btn_ai.configure(text="Ask Claude about this file")
        if self.current and self.current.path == path:
            self.btn_ai.configure(state="normal")
            self.details.configure(state="normal")
            self.details.insert("end", "\nClaude says\n", "h")
            self.details.insert("end", answer + "\n")
            self.details.configure(state="disabled")
            self.details.see("end")


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
