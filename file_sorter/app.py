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
from . import widgets as W
from .analysis import Settings, explain, human_size, match_folders, owning_app
from .groups import Group, build_groups
from .prefs import Prefs, is_inside
from .scanner import FileEntry, ScanResult, index_shift, regroup_duplicates, scan, whole_folders

MAX_ROWS = 3000

VERDICT_COLORS = {v: c[0] for v, c in W.COLORS.items()}
VERDICT_COLORS[kb.KEEP] = "#4b5563"  # darker grey so Keep rows stay readable
VERDICT_BG = {v: c[1] for v, c in W.COLORS.items()}
VERDICT_BG[kb.KEEP] = W.SURFACE
ALL = "Everything"
DUPES = "Duplicates (copies and originals)"
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
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1400, sw - 40)}x{min(900, sh - 80)}+10+10")
        self.minsize(1000, 640)
        if sys.platform == "win32":
            self.state("zoomed")  # start maximised: there's a lot to show

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

        self.prefs = Prefs.load()
        self.path_var = tk.StringVar(value=self.prefs.last_folder or default_scan_path())
        self.map_folder: str | None = None      # folder shown in the space map
        self.folder_direct = False              # folder filter: only files directly in it
        self.groups: list[Group] = []
        self.group_rows: dict[str, Group] = {}   # groups tab: group row id -> group
        self.gfile_rows: dict[str, FileEntry] = {}  # groups tab: file row id -> file
        self.media_mb_var = tk.IntVar(value=self.prefs.move_media_mb)
        self.stale_days_var = tk.IntVar(value=self.prefs.stale_days)
        self.search_var = tk.StringVar()
        self.show_var = tk.StringVar(value=ALL)
        self.status_var = tk.StringVar(value="Pick a folder or drive and press Scan.")

        self._style()
        self._build()
        self._show_welcome()
        self.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _style(self) -> None:
        self.f = W.apply_theme(self)

    def _card(self, parent, **pack) -> ttk.Frame:
        """A white panel with a thin border."""
        outer = tk.Frame(parent, background=W.BORDER, padx=1, pady=1)
        outer.pack(**pack)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=(14, 10))
        inner.pack(fill="both", expand=True)
        return inner

    def _build(self) -> None:
        f = self.f
        # --- header
        header = tk.Frame(self, background=W.HEADER, padx=18, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="File Sorter", bg=W.HEADER, fg="white", font=f["title"]).pack(side="left")
        tk.Label(header, text="   See what you can delete, and what to move to another drive",
                 bg=W.HEADER, fg="#9ca3af", font=f["base"]).pack(side="left", pady=(5, 0))
        self.drive_box = tk.Frame(header, background=W.HEADER)
        self.drive_box.pack(side="right")
        tools = tk.Menubutton(header, text="Tools \u25be", bg="#1f2937", fg="white", activebackground="#374151",
                              activeforeground="white", relief="flat", padx=12, pady=4, font=f["bold"],
                              cursor="hand2")
        tools.pack(side="right", padx=(0, 16))
        tools["menu"] = self._tools_menu(tools)
        self._update_drives_label()

        # --- scan bar
        bar = self._card(self, fill="x", padx=14, pady=(14, 0))
        row = ttk.Frame(bar, style="Card.TFrame")
        row.pack(fill="x")
        # buttons are packed from the right first, so on a narrow screen the path box shrinks instead
        self.stop_btn = ttk.Button(row, text="Stop", command=self.stop_scan, state="disabled")
        self.stop_btn.pack(side="right", padx=(6, 0))
        self.dupe_btn = ttk.Button(row, text="Scan + find duplicates",
                                   command=lambda: self.start_scan(find_dupes=True))
        self.dupe_btn.pack(side="right", padx=(6, 0))
        self.scan_btn = ttk.Button(row, text="Scan", style="Primary.TButton", command=self.start_scan)
        self.scan_btn.pack(side="right", padx=(14, 0))
        self.drive_menu = ttk.Menubutton(row, text="Drives")
        self.drive_menu.pack(side="right", padx=(6, 0))
        self._fill_drive_menu()
        ttk.Button(row, text="Browse...", command=self.browse).pack(side="right", padx=(6, 0))
        ttk.Label(row, text="Folder or drive", style="CardMuted.TLabel").pack(side="left", padx=(0, 8))
        entry = ttk.Entry(row, textvariable=self.path_var, width=20)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.start_scan())
        opts = ttk.Frame(bar, style="Card.TFrame")
        opts.pack(fill="x", pady=(8, 0))
        ttk.Label(opts, text="Suggest moving photos, videos and archives bigger than",
                  style="CardMuted.TLabel").pack(side="left")
        ttk.Spinbox(opts, from_=1, to=100000, width=6, textvariable=self.media_mb_var).pack(side="left", padx=4)
        ttk.Label(opts, text="MB, and files not used for", style="CardMuted.TLabel").pack(side="left")
        ttk.Spinbox(opts, from_=30, to=10000, width=6, textvariable=self.stale_days_var).pack(side="left", padx=4)
        ttk.Label(opts, text="days.   'Scan' is quick; 'Scan + find duplicates' also compares files.",
                  style="CardMuted.TLabel").pack(side="left")

        # --- summary: headline, cards, storage bar
        summary = self._card(self, fill="x", padx=14, pady=(10, 0))
        hrow = ttk.Frame(summary, style="Card.TFrame")
        hrow.pack(fill="x")
        self.cleanup_btn = ttk.Button(hrow, text="\u2713  Clean up", style="Clean.TButton", state="disabled",
                                      command=self.clean_up)
        self.cleanup_btn.pack(side="right")
        self.headline = ttk.Label(hrow, text="Scan a folder to see where your space goes.", style="H2.TLabel")
        self.headline.pack(side="left", anchor="w")
        self.freed_label = ttk.Label(hrow, text="", style="CardMuted.TLabel")
        self.freed_label.pack(side="right", padx=12)
        self._show_freed()
        cards = ttk.Frame(summary, style="Card.TFrame")
        cards.pack(fill="x", pady=(8, 6))
        self.card_widgets: dict[str, tuple] = {}
        for v in [ALL] + kb.VERDICTS:
            color = W.COLORS.get(v, (W.TEXT, W.BG))[0]
            box = tk.Frame(cards, background=W.SURFACE, highlightthickness=1, highlightbackground=W.BORDER,
                           cursor="hand2")
            box.pack(side="left", fill="x", expand=True, padx=(0, 8))
            stripe = tk.Frame(box, background=color, height=4)
            stripe.pack(fill="x")
            name = tk.Label(box, text=f"{W.ICONS.get(v, '')}  {kb.SHORT.get(v, 'Everything')}".strip(),
                            bg=W.SURFACE, fg=W.MUTED, font=f["bold"], anchor="w")
            size = tk.Label(box, text="-", bg=W.SURFACE, fg=color if v != kb.KEEP else W.TEXT,
                            font=f["big"], anchor="w")
            count = tk.Label(box, text=" ", bg=W.SURFACE, fg=W.MUTED, font=f["small"], anchor="w")
            for w in (name, size, count):
                w.pack(fill="x", padx=10)
            count.pack_configure(pady=(0, 6))
            name.pack_configure(pady=(6, 0))
            for w in (box, stripe, name, size, count):
                w.bind("<Button-1>", lambda e, v=v: self.set_filter(v))
            self.card_widgets[v] = (box, size, count)
        self.storage_bar = W.StorageBar(summary, on_click=self.set_filter)
        self.storage_bar.pack(fill="x")

        # --- main split
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=14, pady=10)
        left = ttk.Frame(paned)
        right_outer = tk.Frame(paned, background=W.BORDER, padx=1, pady=1)
        paned.add(left, weight=3)
        paned.add(right_outer, weight=2)
        right = ttk.Frame(right_outer, style="Card.TFrame")
        right.pack(fill="both", expand=True)

        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill="both", expand=True)

        # groups tab
        groups_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=10)
        self.groups_tab = groups_tab
        self.tabs.add(groups_tab, text="  Groups  ")
        ttk.Label(groups_tab, text="Your files, grouped by what they belong to. Click a group to see what it is; "
                                   "press Delete or Move to act on the whole group.",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(0, 8))
        gcols = ("size", "action", "files", "what")
        self.gtree = ttk.Treeview(groups_tab, columns=gcols, show="tree headings", selectmode="extended")
        self.gtree.heading("#0", text="Group", anchor="w")
        self.gtree.column("#0", width=300, stretch=True)
        for c, t, wd, anchor in (("size", "Size", 85, "e"), ("action", "You can", 150, "w"),
                                 ("files", "Files", 70, "e"), ("what", "What it is", 330, "w")):
            self.gtree.heading(c, text=t, anchor=anchor)
            self.gtree.column(c, width=wd, anchor=anchor, stretch=c == "what")
        for v in kb.VERDICTS:
            self.gtree.tag_configure(v, foreground=VERDICT_COLORS[v])
        self.gtree.tag_configure("group", font=self.f["bold"])
        self.gtree.tag_configure("more", foreground=W.MUTED)
        gsb = ttk.Scrollbar(groups_tab, orient="vertical", command=self.gtree.yview)
        self.gtree.configure(yscrollcommand=gsb.set)
        self.gtree.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self.gtree.bind("<<TreeviewOpen>>", lambda e: self._fill_group(self.gtree.focus()))
        self.gtree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.gtree.bind("<Delete>", lambda e: self.delete_selected())

        # space map tab
        map_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=10)
        self.map_tab = map_tab
        self.tabs.add(map_tab, text="  Space map  ")
        mbar = ttk.Frame(map_tab, style="Card.TFrame")
        mbar.pack(fill="x", pady=(0, 8))
        self.up_btn = ttk.Button(mbar, text="\u2191 Up", command=self.map_up, state="disabled")
        self.up_btn.pack(side="left")
        self.map_path = ttk.Label(mbar, text="", style="H2.TLabel")
        self.map_path.pack(side="left", padx=10)
        legend = ttk.Frame(map_tab, style="Card.TFrame")
        legend.pack(fill="x", pady=(0, 6))
        for v in kb.VERDICTS:
            tk.Label(legend, text="\u25a0", fg=W.MAP_FILL[v], bg=W.SURFACE, font=f["h2"]).pack(side="left")
            tk.Label(legend, text=kb.SHORT[v] + "  ", fg=W.MUTED, bg=W.SURFACE, font=f["small"]).pack(side="left")
        self.space_map = W.SpaceMap(map_tab, on_open=self.map_open, on_hover=self._map_hover)
        self.space_map.pack(fill="both", expand=True)
        self.map_hint = ttk.Label(map_tab, text="Each box is a folder, sized by how much space it uses. "
                                                "Colours show what's inside. Click a box to look inside it.",
                                  style="CardMuted.TLabel")
        self.map_hint.pack(fill="x", pady=(8, 0))

        # files tab
        files_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=10)
        self.files_tab = files_tab
        self.tabs.add(files_tab, text="  Files  ")
        fbar = ttk.Frame(files_tab, style="Card.TFrame")
        fbar.pack(fill="x", pady=(0, 8))
        ttk.Label(fbar, text="Show", style="CardMuted.TLabel").pack(side="left")
        show = ttk.Combobox(fbar, textvariable=self.show_var, values=[ALL] + kb.VERDICTS + [DUPES],
                            state="readonly", width=30)
        show.pack(side="left", padx=6)
        show.bind("<<ComboboxSelected>>", lambda e: self.refresh_files())
        ttk.Label(fbar, text="   Search", style="CardMuted.TLabel").pack(side="left")
        search = ttk.Entry(fbar, textvariable=self.search_var, width=24)
        search.pack(side="left", padx=6)
        self.search_var.trace_add("write", lambda *a: self._debounced_refresh())
        self.folder_chip = ttk.Button(fbar, text="", command=self.clear_folder_filter)
        ttk.Button(fbar, text="Select all shown", command=self.select_all).pack(side="right")

        cols = ("name", "size", "verdict", "type", "used", "folder")
        self.tree = ttk.Treeview(files_tab, columns=cols, show="headings", selectmode="extended")
        heads = {"name": "Name", "size": "Size", "verdict": "Suggestion", "type": "Type",
                 "used": "Last used", "folder": "Folder"}
        widths = {"name": 270, "size": 85, "verdict": 165, "type": 130, "used": 90, "folder": 300}
        for c in cols:
            self.tree.heading(c, text=heads[c], anchor="e" if c == "size" else "w",
                              command=lambda c=c: self.sort_by(c))
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
        folders_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=10)
        self.tabs.add(folders_tab, text="  Biggest folders  ")
        ttk.Label(folders_tab, text="Double-click a folder to list its files.",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(0, 8))
        fcols = ("folder", "size", "files", "what")
        self.ftree = ttk.Treeview(folders_tab, columns=fcols, show="headings", selectmode="browse")
        for c, t, w in (("folder", "Folder", 380), ("size", "Size", 90), ("files", "Files", 70),
                        ("what", "What it is", 260)):
            self.ftree.heading(c, text=t, anchor="e" if c in ("size", "files") else "w")
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

        self.tabs.bind("<<NotebookTabChanged>>", lambda e: self._tab_changed())
        for tree in (self.tree, self.gtree, self.ftree):
            tree.bind("<Button-3>", lambda e, t=tree: self._context_menu(e, t))
            tree.bind("<Button-2>" if sys.platform == "darwin" else "<Control-Button-1>",
                      lambda e, t=tree: self._context_menu(e, t))
        self.bind_all("<Control-f>", lambda e: self._focus_search(search))
        self.bind_all("<F5>", lambda e: self.start_scan())
        self.tree.bind("<Control-a>", lambda e: (self.select_all(), "break")[1])
        self.bind_all("<Escape>", lambda e: self._clear_selection())

        # details panel: verdict banner, text, actions
        self.badge = tk.Frame(right, background=W.BG, padx=14, pady=8)
        self.badge_icon = tk.Label(self.badge, text="", bg=W.BG, fg="white", font=f["big"], width=2)
        self.badge_icon.pack(side="left")
        self.badge_text = tk.Label(self.badge, text="", bg=W.BG, fg="white", font=f["h2"], anchor="w",
                                   justify="left")
        self.badge_text.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.badge.bind("<Configure>", lambda e: self.badge_text.configure(wraplength=max(100, e.width - 80)))
        self.details_frame = ttk.Frame(right, style="Card.TFrame")
        self.details_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.details = tk.Text(self.details_frame, wrap="word", relief="flat", padx=12, pady=10,
                               font=f["base"], background=W.SURFACE, foreground=W.TEXT, borderwidth=0,
                               highlightthickness=0, spacing1=1, spacing3=1)
        dsb = ttk.Scrollbar(self.details_frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=dsb.set, state="disabled")
        self.details.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")
        self.details.tag_configure("title", font=f["title"], spacing3=8)
        self.details.tag_configure("h", font=f["bold"], foreground=W.MUTED, spacing1=12, spacing3=3)
        self.details.tag_configure("mono", font=("TkFixedFont", 9), background=W.BG, lmargin1=6, lmargin2=6)
        self.details.tag_configure("muted", foreground=W.MUTED)
        for v in kb.VERDICTS:
            self.details.tag_configure(v, foreground=VERDICT_COLORS[v], font=f["h2"])

        # two rows, pinned to the bottom so they never scroll away: actions, then helpers
        helpers = ttk.Frame(right, style="Card.TFrame", padding=(10, 4, 10, 10))
        helpers.pack(fill="x", side="bottom", before=self.details_frame)
        acts = ttk.Frame(right, style="Card.TFrame", padding=(10, 6, 10, 0))
        acts.pack(fill="x", side="bottom", before=helpers)
        self.btn_move = ttk.Button(acts, text="\u2192  Move to other drive", style="Move.TButton",
                                   command=self.move_selected)
        self.btn_delete = ttk.Button(acts, text="\u2715  Delete", style="Danger.TButton",
                                     command=self.delete_selected)
        self.btn_open = ttk.Button(helpers, text="Open", command=self.open_selected)
        self.btn_reveal = ttk.Button(helpers, text="Show in folder", command=self.reveal_selected)
        self.btn_ai = ttk.Button(helpers, text="Ask Claude", command=self.ask_ai)
        for b in (self.btn_move, self.btn_delete, self.btn_open, self.btn_reveal, self.btn_ai):
            b.pack(side="left", padx=3, expand=True, fill="x")
        self._set_buttons(False)

        # status bar
        status = tk.Frame(self, background=W.SURFACE, padx=14, pady=6, highlightthickness=1,
                          highlightbackground=W.BORDER)
        status.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=180)
        tk.Label(status, textvariable=self.status_var, bg=W.SURFACE, fg=W.MUTED, font=f["small"],
                 anchor="w").pack(side="left", fill="x", expand=True)
        status.pack_forget()
        status.pack(fill="x", before=paned, side="bottom")

    def _fill_drive_menu(self) -> None:
        menu = tk.Menu(self.drive_menu, tearoff=False)
        for root, free, total in actions.list_drives():
            menu.add_command(label=f"{root}   ({human_size(free)} free of {human_size(total)})",
                             command=lambda r=root: self.path_var.set(r))
        menu.add_separator()
        menu.add_command(label="My user folder", command=lambda: self.path_var.set(os.path.expanduser("~")))
        self.drive_menu["menu"] = menu

    def _update_drives_label(self) -> None:
        for w in self.drive_box.winfo_children():
            w.destroy()
        for root, free, total in actions.list_drives()[:3]:
            W.DriveMeter(self.drive_box, root, free, total).pack(side="left", padx=(16, 0))

    def _spin(self, on: bool) -> None:
        if on:
            self.progress.pack(side="right")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _set_buttons(self, on: bool) -> None:
        for b in (self.btn_open, self.btn_reveal, self.btn_move, self.btn_delete, self.btn_ai):
            b.configure(state="normal" if on else "disabled")

    # ------------------------------------------------------------ details text
    def _set_badge(self, verdict: str | None, text: str = "") -> None:
        if not verdict:
            self.badge.pack_forget()
            return
        color = VERDICT_COLORS[verdict] if verdict != kb.KEEP else "#6b7280"
        for w in (self.badge, self.badge_icon, self.badge_text):
            w.configure(background=color)
        self.badge_icon.configure(text=W.ICONS[verdict])
        self.badge_text.configure(text=text or verdict)
        self.badge.pack(fill="x", before=self.details_frame)

    def _write_details(self, chunks: list[tuple[str, str]], badge: str | None = None, badge_text: str = "") -> None:
        self._set_badge(badge, badge_text)
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
                   "2. The Space map shows where your space goes. Click the coloured cards to list files.\n"
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

    def start_scan(self, find_dupes: bool = False) -> None:
        if self.busy or (self.scan_thread and self.scan_thread.is_alive()):
            return
        root = self.path_var.get().strip()
        if len(root) == 2 and root[1] == ":":
            root += os.sep
        if not os.path.isdir(root):
            messagebox.showerror("File Sorter", f"'{root}' isn't a folder I can open.")
            return
        try:
            media_mb, stale = max(1, int(self.media_mb_var.get())), max(1, int(self.stale_days_var.get()))
        except (tk.TclError, ValueError):
            media_mb, stale = 50, 365
        settings = Settings(move_media_mb=media_mb, stale_days=stale, never_touch=tuple(self.prefs.never_touch))
        self.prefs.last_folder, self.prefs.move_media_mb, self.prefs.stale_days = root, media_mb, stale
        self.prefs.save()
        self.cancel.clear()
        self.scan_btn.configure(state="disabled")
        self.dupe_btn.configure(state="disabled")
        self.cleanup_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._spin(True)
        self.status_var.set(f"Scanning {root} ...")
        self.folder_filter = None
        self.folder_direct = False
        self.folder_chip.pack_forget()

        def work() -> None:
            def progress(n: int, b: int, folder: str) -> None:
                self.events.put(("progress", n, b, folder))
            try:
                res = scan(root, settings, find_dupes, self.cancel, progress)
                self.events.put(("progress", len(res.files), 0, "Grouping files..."))
                self.events.put(("done", res, build_groups(res.files)))  # grouping off the UI thread too
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
                    self.groups = ev[2]
                    self._scan_finished(ev[1])
                elif kind == "error":
                    self._scan_stopped()
                    messagebox.showerror("File Sorter", f"Scan failed: {ev[1]}")
                elif kind == "ai":
                    self._show_ai_answer(ev[1], ev[2])
                elif kind == "status":
                    self.status_var.set(ev[1])
                elif kind == "action_done":
                    self._after_action(*ev[1:])
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll)  # keep polling even if handling an event failed

    def _scan_stopped(self) -> None:
        self._spin(False)
        self.scan_btn.configure(state="normal")
        self.dupe_btn.configure(state="normal")
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
        self.map_folder = res.map_root
        self.refresh_all()
        self.tabs.select(self.groups_tab)

    # ------------------------------------------------------------------ lists
    def refresh_all(self) -> None:
        self.refresh_files()  # also refreshes the cards
        self.refresh_groups()
        self.refresh_folders()
        self.draw_map()

    # ------------------------------------------------------------------ groups
    def refresh_groups(self) -> None:
        """Show self.groups (built off the UI thread after each scan or move/delete)."""
        self.gtree.delete(*self.gtree.get_children())
        self.group_rows, self.gfile_rows = {}, {}
        if not self.result:
            self.groups = []
        for i, g in enumerate(self.groups):
            iid = f"g{i}"
            self.group_rows[iid] = g
            if g.deletable:
                action = f"\u2713 Free {human_size(g.deletable)}"
            elif g.key == "dupes" or g.review:
                action = f"? Check {human_size(g.review)}"
            elif g.movable:
                action = f"\u2192 Move {human_size(g.movable)}"
            else:
                action = f"{W.ICONS[g.main_verdict]} {kb.SHORT[g.main_verdict]}"
            self.gtree.insert("", "end", iid=iid, text=f"  {g.title}", open=False, tags=(g.main_verdict, "group"),
                              values=(human_size(g.size), action, f"{len(g.files):,}", g.what))
            self.gtree.insert(iid, "end", iid=f"{iid}/_")  # placeholder so the group can be opened

    def _fill_group(self, iid: str) -> None:
        g = self.group_rows.get(iid)
        if not g or not self.gtree.exists(f"{iid}/_"):
            return
        self.gtree.delete(f"{iid}/_")
        files = sorted(g.files, key=lambda f: f.size, reverse=True)
        for j, f in enumerate(files[:300]):
            fid = f"{iid}/{j}"
            self.gfile_rows[fid] = f
            label = kb.SHORT[f.verdict] + (" (duplicate)" if f.duplicate_of else "")
            self.gtree.insert(iid, "end", iid=fid, tags=(f.verdict,),
                              text=f"   {W.KIND_ICONS.get(f.assessment.kind, chr(0x2022))}  {f.name}",
                              values=(human_size(f.size), f"{W.ICONS[f.verdict]} {label}", "", os.path.dirname(f.path)))
        if len(files) > 300:
            self.gtree.insert(iid, "end", iid=f"{iid}/more", tags=("more",),
                              text=f"   ... and {len(files) - 300:,} smaller files (Delete/Move still include them)")

    def _group_files(self, g: Group, action: str) -> list[FileEntry]:
        """Which files of a group an action applies to: only the ones suggested for it. 'Review' files
        need picking by hand (open the group), except the extra copies in the duplicates group."""
        if action == "delete":
            if g.key == "dupes":
                return [f for f in g.files if f.duplicate_of]
            return [f for f in g.files if f.verdict == kb.DELETE]
        if action == "move":
            return [f for f in g.files if f.verdict == kb.MOVE]
        return list(g.files)

    def show_group(self, g: Group) -> None:
        chunks: list[tuple[str, str]] = [(g.title + "\n", "title"), (g.what + "\n", "")]
        chunks.append(("What's in it\n", "h"))
        chunks.append((f"{plural(len(g.files), 'file')}, {human_size(g.size)}\n", ""))
        for v in kb.VERDICTS:
            if g.by_verdict.get(v):
                n = sum(1 for f in g.files if f.verdict == v)
                chunks.append((f"{W.ICONS[v]}  {v}: {plural(n, 'file')}, {human_size(g.by_verdict[v])}\n", v))
        dels, moves = self._group_files(g, "delete"), self._group_files(g, "move")
        chunks.append(("What the buttons do\n", "h"))
        if dels:
            what = "extra copies (the originals stay)" if g.key == "dupes" else "files marked Safe to delete"
            chunks.append((f"Delete removes the {plural(len(dels), 'file')}: {what} "
                           f"({human_size(sum(f.size for f in dels))}). Everything else stays.\n", ""))
        else:
            chunks.append(("Nothing here is marked Safe to delete, so Delete does nothing for the whole group.\n", ""))
        if g.review and g.key != "dupes":
            chunks.append((f"{human_size(g.review)} is marked Review: open the group, check those files and "
                           "select the ones you want to delete.\n", ""))
        if moves:
            chunks.append((f"Move sends the {plural(len(moves), 'file')} marked Move "
                           f"({human_size(sum(f.size for f in moves))}) to your other drive.\n", ""))
        chunks.append(("Biggest files\n", "h"))
        for f in sorted(g.files, key=lambda f: f.size, reverse=True)[:6]:
            chunks.append((f"{human_size(f.size):>10}   {W.ICONS[f.verdict]} {f.name}\n", ""))
        chunks.append(("\nOpen the group (click the arrow) to see every file and why.\n", "muted"))
        if g.deletable:
            badge = f"You can free {human_size(g.deletable)} here"
        elif g.review:
            badge = f"{human_size(g.review)} to check"
        elif g.movable:
            badge = f"You can move {human_size(g.movable)} to another drive"
        else:
            badge = g.main_verdict
        self._write_details(chunks, g.main_verdict, badge)

    def refresh_cards(self) -> None:
        if not self.result:
            return
        totals = self.result.totals()
        all_n = sum(v[0] for v in totals.values())
        all_b = sum(v[1] for v in totals.values())
        for v, (box, size, count) in self.card_widgets.items():
            n, b = (all_n, all_b) if v == ALL else totals[v]
            size.configure(text=human_size(b))
            count.configure(text=plural(n, "file"))
            chosen = self.show_var.get() == v
            box.configure(highlightthickness=2 if chosen else 1,
                          highlightbackground=W.COLORS.get(v, (W.TEXT,))[0] if chosen else W.BORDER)
        self.storage_bar.set({v: totals[v][1] for v in kb.VERDICTS})
        self.cleanup_btn.configure(text=f"\u2713  Clean up {human_size(totals[kb.DELETE][1])} now",
                                   state="normal" if totals[kb.DELETE][0] and not self.busy else "disabled")
        free, review, move = totals[kb.DELETE][1], totals[kb.REVIEW][1], totals[kb.MOVE][1]
        self.headline.configure(text=f"You can free {human_size(free)} right away, {human_size(review)} more "
                                     f"after a quick check, and move {human_size(move)} to another drive.")

    def set_filter(self, verdict: str) -> None:
        self.show_var.set(verdict)
        self.tabs.select(self.files_tab)
        self.refresh_files()  # also refreshes the cards

    def _debounced_refresh(self) -> None:
        if hasattr(self, "_debounce"):
            self.after_cancel(self._debounce)
        self._debounce = self.after(250, self.refresh_files)

    def _originals(self) -> set[str]:
        return {f.duplicate_of for f in self.result.files if f.duplicate_of} if self.result else set()

    def _filtered(self) -> list[FileEntry]:
        if not self.result:
            return []
        show = self.show_var.get()
        q = self.search_var.get().strip().lower()
        prefix = None
        if self.folder_filter:
            prefix = os.path.join(self.folder_filter, "")
        originals = self._originals() if show == DUPES else set()
        out = []
        for f in self.result.files:
            if show == DUPES:
                if not (f.duplicate_of or f.path in originals):
                    continue
            elif show != ALL and f.verdict != show:
                continue
            if prefix and not f.path.startswith(prefix):
                continue
            if prefix and self.folder_direct and os.path.dirname(f.path) != self.folder_filter:
                continue
            if q and q not in f.path.lower():
                continue
            out.append(f)
        return out

    def refresh_files(self) -> None:
        self.refresh_cards()
        items = self._filtered()
        originals = self._originals()
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
            label = kb.SHORT[f.verdict] + (" (duplicate)" if f.duplicate_of else
                                           " (has copies)" if f.path in originals else "")
            self.tree.insert("", "end", iid=iid, tags=(f.verdict,),
                             values=(f"{W.KIND_ICONS.get(f.assessment.kind, chr(0x2022))}   {f.name}",
                                     human_size(f.size), f"{W.ICONS[f.verdict]}  {label}", f.assessment.kind_label,
                                     used, os.path.dirname(f.path)))
        if not items and self.show_var.get() == DUPES and self.result:
            if not self.result.duplicates_checked:
                why = "This scan didn't look for duplicates. Press 'Scan + find duplicates' at the top."
            elif self.search_var.get().strip() or self.folder_filter:
                why = "None match your search or folder filter. Clear them to see all duplicates."
            else:
                why = ("No identical copies were found. Only personal files of 1 MB or more "
                       "(photos, videos, documents, archives...) are compared.")
            self._write_details([("No duplicates to show\n", "title"), (why + "\n", "")])
        total = sum(f.size for f in items)
        extra = f" (showing the first {MAX_ROWS:,})" if len(items) > MAX_ROWS else ""
        self.tabs.tab(self.files_tab, text=f"  Files: {len(items):,} ({human_size(total)}){extra}  ")

    def sort_by(self, col: str) -> None:
        if self.sort_key == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = col
            self.sort_desc = col in ("size", "used")
        self.refresh_files()

    def select_all(self) -> None:
        if self.show_var.get() == DUPES:  # only the extra copies, never the originals
            self.tree.selection_set([i for i, f in self.rows.items() if f.duplicate_of])
        else:
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
        self.folder_direct = False
        self.folder_chip.pack_forget()
        self.refresh_files()

    def drill_into_folder(self) -> None:
        sel = self.ftree.selection()
        if not sel:
            return
        self.show_folder_files(self.folder_rows[sel[0]])

    def show_folder_files(self, folder: str, direct: bool = False) -> None:
        self.folder_filter = folder
        self.folder_direct = direct
        name = os.path.basename(self.folder_filter) or self.folder_filter
        self.folder_chip.configure(text=f"Only in: {name}   \u2715")
        self.folder_chip.pack(side="left", padx=6)
        self.show_var.set(ALL)
        self.tabs.select(self.files_tab)
        self.refresh_files()

    # ------------------------------------------------------------------ space map
    def draw_map(self) -> None:
        r = self.result
        if not r:
            return
        folder = self.map_folder or r.map_root
        # if everything in this folder was moved/deleted, go up to the nearest folder that still has files
        while folder != r.map_root and sum(r.breakdown.get(folder, {}).values()) <= 0:
            parent = os.path.dirname(folder)
            folder = r.map_root if parent == folder or len(parent) < len(r.map_root) else parent
        self.map_folder = folder
        items = [(os.path.basename(c) or c, c, dict(r.breakdown[c]), True) for c in r.subfolders.get(folder, ())]
        if r.by_dir.get(folder):
            items.append(("Files in this folder", folder, dict(r.by_dir[folder]), False))
        self.space_map.show(items, "Only empty (0-byte) files here." if r.folder_counts.get(folder)
                        else "This folder is empty.")
        total = sum(r.breakdown.get(folder, {}).values())
        self.map_path.configure(text=f"{folder}   ({human_size(total)})")
        self.up_btn.configure(state="normal" if folder != r.map_root else "disabled")

    def map_open(self, path: str, is_folder: bool) -> None:
        if is_folder and self.result and self.result.subfolders.get(path):
            self.map_folder = path
            self.draw_map()
        else:  # a folder without subfolders, or the loose files of this folder: list them
            self.show_var.set(ALL)
            self.show_folder_files(path, direct=not is_folder)

    def map_up(self) -> None:
        if self.result and self.map_folder and self.map_folder != self.result.map_root:
            self.map_folder = os.path.dirname(self.map_folder)
            self.draw_map()

    def _map_hover(self, text: str) -> None:
        self.map_hint.configure(text=text or "Each box is a folder, sized by how much space it uses. "
                                             "Colours show what's inside. Click a box to look inside it.")

    # ------------------------------------------------------------------ selection
    def selected_entries(self, action: str = "") -> list[FileEntry]:
        if self.tabs.select() != str(self.groups_tab):
            return [self.rows[i] for i in self.tree.selection() if i in self.rows]
        out, seen = [], set()
        for iid in self.gtree.selection():
            files = (self._group_files(self.group_rows[iid], action) if iid in self.group_rows
                     else [self.gfile_rows[iid]] if iid in self.gfile_rows else [])
            for f in files:
                if f.path not in seen:
                    seen.add(f.path)
                    out.append(f)
        return out

    def on_select(self) -> None:
        sel = self.selected_entries()
        group_chosen = self.tabs.select() == str(self.groups_tab) and any(
            i in self.group_rows for i in self.gtree.selection())
        self._set_buttons(bool(sel) or group_chosen)
        if not sel and not group_chosen:
            return
        if self.tabs.select() == str(self.groups_tab):
            chosen = self.gtree.selection()
            if len(chosen) == 1 and chosen[0] in self.group_rows:
                self.current = None
                for b in (self.btn_open, self.btn_reveal):
                    b.configure(state="disabled")
                self.show_group(self.group_rows[chosen[0]])
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
        chunks.append(("\nNot sure? Press 'Ask Claude' for an AI explanation.\n", "muted"))
        self._write_details(chunks, f.verdict, f.verdict + ("  (duplicate)" if f.duplicate_of else ""))

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
        if self.busy or (self.scan_thread and self.scan_thread.is_alive()):
            messagebox.showinfo("File Sorter", "Please wait until the current scan or move/delete has finished.")
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

    def _every_copy_selected(self, entries: list[FileEntry]) -> str | None:
        """Name of a file whose every copy (original included) is in `entries`, if any."""
        if not self.result:
            return None
        groups: dict[str, set[str]] = {}
        for f in self.result.files:
            if f.duplicate_of:
                groups.setdefault(f.duplicate_of, {f.duplicate_of}).add(f.path)
        chosen = {f.path for f in entries}
        for original, members in groups.items():
            if members <= chosen:
                return os.path.basename(original)
        return None

    def delete_selected(self) -> None:
        entries = self.selected_entries("delete")
        if not entries and self.tabs.select() == str(self.groups_tab) and self.gtree.selection():
            messagebox.showinfo("File Sorter", "Nothing in this group is marked Safe to delete.\n\nOpen the group "
                                               "(click the arrow), check the files and select the ones you want "
                                               "to delete.")
            return
        self._delete(entries)

    def clean_up(self) -> None:
        """One click: delete everything marked 'Safe to delete'."""
        if self.result:
            # one click needs the strictest bar: no cloud-synced files (deleting them deletes them everywhere)
            self._delete([f for f in self.result.files if f.verdict == kb.DELETE and not f.assessment.warnings],
                         cleanup=True)

    def _summary(self, entries: list[FileEntry]) -> str:
        if len(entries) <= 8:
            return "\n".join(f"  {f.name}" for f in entries)
        groups = build_groups(entries)
        lines = [f"  {g.title}: {plural(len(g.files), 'file')}, {human_size(g.size)}" for g in groups[:8]]
        if len(groups) > 8:
            lines.append(f"  ... and {len(groups) - 8} more groups")
        return "\n".join(lines)

    def _delete(self, entries: list[FileEntry], cleanup: bool = False) -> None:
        entries = self._guard_system(entries, "delete")
        if not entries:
            return
        lost = self._every_copy_selected(entries)
        if lost:
            messagebox.showwarning("File Sorter",
                                   f"You selected every copy of '{lost}'. Deleting them all would lose that "
                                   "file completely.\n\nUnselect one copy (the one you want to keep) and try again.")
            return
        total = sum(f.size for f in entries)
        risky = [f for f in entries if f.verdict in (kb.KEEP, kb.MOVE)]
        names = self._summary(entries)
        warn = (f"\n\n{len(risky):,} of these are marked '{kb.KEEP}' or '{kb.MOVE}'. Are you sure?"
                if risky else "")
        drives = {os.path.splitdrive(f.path)[0]: f.path for f in entries}  # one check per drive is enough
        if all(actions.recycle_bin_works_for(p) for p in drives.values()):
            intro = ("Clean up everything marked 'Safe to delete'? These are caches, temporary files, crash "
                     "dumps, update leftovers and similar files programs recreate or never need again. "
                     "Files in cloud-synced folders are left out.\n\n" if cleanup else "")
            if not messagebox.askyesno("Clean up" if cleanup else "Delete files",
                                       f"{intro}Send {plural(len(entries), 'file')} ({human_size(total)}) to the "
                                       f"Recycle Bin?\n\n{names}{warn}"):
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
        singles, folders = whole_folders([f.path for f in entries], self.result) if self.result else \
            ([f.path for f in entries], {})
        self._last_delete_permanent = permanently
        self._run_action("Deleting", lambda progress: actions.delete_files(singles, permanently, progress, folders),
                         "Deleted")

    def move_selected(self) -> None:
        entries = self._guard_system(self.selected_entries("move"), "move")
        if not entries or not self.result:
            return
        dest = filedialog.askdirectory(title="Choose where to move the files (e.g. your other drive)",
                                       initialdir=self.prefs.move_destination or None)
        if not dest:
            return
        self.prefs.move_destination = dest
        self.prefs.save()
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
        for b in (self.btn_move, self.btn_delete, self.scan_btn, self.dupe_btn, self.cleanup_btn):
            b.configure(state="disabled")
        self._spin(True)
        last = [0.0]
        files = list(self.result.files) if self.result else []

        def progress(i: int, n: int, path: str) -> None:
            if time.time() - last[0] > 0.1:  # a status per file would flood the window
                last[0] = time.time()
                self.events.put(("status", f"{doing} {i + 1:,} of {n:,}: {os.path.basename(path)}"))

        def run() -> None:
            try:
                report = work(progress)
            except Exception as e:  # noqa: BLE001
                report = actions.ActionReport(failed=[("", str(e))])
            done = {src for src, _ in report.done}
            remaining = [f for f in files if f.path not in done]
            gone = [f for f in files if f.path in done]
            changed = regroup_duplicates(remaining)  # a copy whose original is gone is no longer a duplicate
            self.events.put(("action_done", report, verb, remaining, gone, changed, build_groups(remaining)))

        threading.Thread(target=run, daemon=True).start()

    def _after_action(self, report: actions.ActionReport, verb: str, remaining=None, gone=(), changed=(),
                      groups=None) -> None:
        self.busy = False
        self._spin(False)
        self.scan_btn.configure(state="normal")
        self.dupe_btn.configure(state="normal")
        if self.result and remaining is not None:
            self.result.files = remaining
            for f in gone:
                index_shift(self.result, f, f.verdict, None)
            for f, old in changed:
                index_shift(self.result, f, old, f.verdict)
            for f in gone:  # keep the "Biggest folders" numbers right
                d = os.path.dirname(f.path)
                while d in self.result.folder_sizes:
                    self.result.folder_sizes[d] -= f.size
                    self.result.folder_counts[d] -= 1
                    if os.path.dirname(d) == d:
                        break
                    d = os.path.dirname(d)
            self.groups = groups if groups is not None else build_groups(remaining)
        self.status_var.set(f"{verb} {plural(len(report.done), 'file')} ({human_size(report.bytes)}).")
        if verb == "Deleted" and report.bytes:
            self.prefs.freed_bytes += report.bytes
            self.prefs.save()
            self._show_freed()
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
        if verb == "Deleted" and report.bytes and not getattr(self, "_last_delete_permanent", True):
            self._offer_empty_recycle_bin()

    def _offer_empty_recycle_bin(self) -> None:
        """Files in the Recycle Bin still use space; offer to empty it so the space is really freed."""
        info = actions.recycle_bin_size()
        if not info or not info[0]:
            return
        size, items = info
        if messagebox.askyesno("Empty the Recycle Bin?",
                               f"The deleted files are in the Recycle Bin, which now holds {human_size(size)} "
                               f"({items:,} items). That space only becomes free when the Recycle Bin is "
                               "emptied.\n\nEmpty it now? (You won't be able to restore those files afterwards.)"):
            if actions.empty_recycle_bin():
                self.status_var.set(f"Emptied the Recycle Bin: {human_size(size)} freed.")
                self._update_drives_label()

    # ------------------------------------------------------------------ tools, menus, never touch
    def _show_freed(self) -> None:
        if self.prefs.freed_bytes:
            self.freed_label.configure(text=f"Freed with File Sorter so far: {human_size(self.prefs.freed_bytes)}")

    def _tools_menu(self, parent) -> tk.Menu:
        menu = tk.Menu(parent, tearoff=False)
        win = sys.platform == "win32"
        state = "normal" if win else "disabled"
        menu.add_command(label="Empty the Recycle Bin...", command=self.tool_empty_bin, state=state)
        menu.add_command(label="Open Disk Cleanup (Windows update leftovers)",
                         command=lambda: self._try(actions.open_disk_cleanup), state=state)
        menu.add_command(label="Open Storage settings (Storage Sense)",
                         command=lambda: self._try(actions.open_storage_settings), state=state)
        menu.add_command(label="Turn off hibernation (frees hiberfil.sys)...", command=self.tool_hibernation,
                         state=state)
        menu.add_separator()
        menu.add_command(label="Move files back from the other drive...", command=self.tool_move_back)
        menu.add_command(label="Never-touch list...", command=self.tool_never_touch_list)
        return menu

    def _try(self, fn) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("File Sorter", f"That didn't work: {e}")

    def tool_empty_bin(self) -> None:
        info = actions.recycle_bin_size()
        if info is not None and not info[1]:
            messagebox.showinfo("File Sorter", "The Recycle Bin is already empty.")
            return
        size = f" ({human_size(info[0])}, {info[1]:,} items)" if info else ""
        if messagebox.askyesno("Empty the Recycle Bin?", f"Permanently delete everything in the Recycle Bin{size}? "
                                                         "You won't be able to restore it afterwards."):
            if actions.empty_recycle_bin():
                self.status_var.set("Emptied the Recycle Bin.")
                self._update_drives_label()

    def tool_hibernation(self) -> None:
        if messagebox.askyesno("Turn off hibernation?",
                               "Windows keeps a hidden file (hiberfil.sys) as big as a large part of your memory, "
                               "used for hibernation and Fast Startup. Turning hibernation off deletes it.\n\n"
                               "Your PC will start a little slower from a full shutdown, and 'Hibernate' disappears "
                               "from the power menu. You can turn it back on with 'powercfg /hibernate on'.\n\n"
                               "Windows will ask for administrator permission. Continue?"):
            if not actions.turn_off_hibernation():
                messagebox.showwarning("File Sorter", "Hibernation wasn't turned off (permission was refused?).")

    def tool_move_back(self) -> None:
        if self.busy:
            return
        log = filedialog.askopenfilename(title="Open the list of moved files (moved_by_file_sorter.csv)",
                                         initialdir=self.prefs.move_destination or None,
                                         filetypes=[("File Sorter move list", actions.LOG_NAME), ("CSV", "*.csv")])
        if not log:
            return
        if not messagebox.askyesno("Move files back?", "Put every file in this list back where it was before it "
                                                       "was moved? Files are copied back and checked first."):
            return
        self._run_action("Moving back", lambda progress: actions.move_back(log, progress), "Moved back")

    def tool_never_touch_list(self) -> None:
        win = tk.Toplevel(self)
        win.title("Never touch")
        win.configure(background=W.SURFACE)
        win.transient(self)
        ttk.Label(win, text="File Sorter never suggests deleting or moving anything in these folders.",
                  style="Card.TLabel", padding=(12, 10)).pack(anchor="w")
        box = tk.Listbox(win, width=70, height=10, relief="flat", highlightthickness=1,
                         highlightbackground=W.BORDER, font=self.f["base"])
        box.pack(fill="both", expand=True, padx=12)
        for p in self.prefs.never_touch:
            box.insert("end", p)
        row = ttk.Frame(win, style="Card.TFrame", padding=12)
        row.pack(fill="x")

        def add() -> None:
            d = filedialog.askdirectory(parent=win, title="Folder to never touch")
            if d:
                self.never_touch(d, ask=False)
                box.insert("end", os.path.abspath(d))

        def remove() -> None:
            for i in reversed(box.curselection()):
                folder = box.get(i)
                self.prefs.never_touch = [p for p in self.prefs.never_touch if p != folder]
                box.delete(i)
            self.prefs.save()
            messagebox.showinfo("File Sorter", "Removed. Scan again to get suggestions for that folder.", parent=win)

        ttk.Button(row, text="Add folder...", command=add).pack(side="left")
        ttk.Button(row, text="Remove", command=remove).pack(side="left", padx=6)
        ttk.Button(row, text="Close", command=win.destroy).pack(side="right")

    def never_touch(self, folder: str, ask: bool = True) -> None:
        folder = os.path.abspath(folder)
        if ask and not messagebox.askyesno("Never touch this folder?",
                                           f"Never suggest deleting or moving anything in:\n{folder}\n\n"
                                           "You can undo this in Tools -> Never-touch list."):
            return
        if folder not in self.prefs.never_touch:
            self.prefs.never_touch.append(folder)
            self.prefs.save()
        if self.result:
            for f in self.result.files:
                if f.verdict != kb.KEEP and is_inside(f.path, [folder]):
                    index_shift(self.result, f, f.verdict, kb.KEEP)
                    f.assessment.verdict, f.assessment.protected = kb.KEEP, True
                    f.assessment.reason = "You told File Sorter to never touch this folder."
            self.groups = build_groups(self.result.files)
            self.refresh_all()

    def _context_menu(self, event, tree: ttk.Treeview) -> None:
        iid = tree.identify_row(event.y)
        if not iid:
            return
        if iid not in tree.selection():
            tree.selection_set(iid)
        entry = (self.rows.get(iid) if tree is self.tree else self.gfile_rows.get(iid) if tree is self.gtree
                 else None)
        if tree is self.ftree:
            folder = self.folder_rows.get(iid)
        elif entry:
            folder = os.path.dirname(entry.path)
        elif iid in self.group_rows and self.group_rows[iid].files:
            try:
                folder = os.path.commonpath([os.path.dirname(f.path) for f in self.group_rows[iid].files[:2000]])
            except ValueError:  # files on different drives
                folder = None
        else:
            folder = None
        menu = tk.Menu(self, tearoff=False)
        if entry:
            menu.add_command(label="Open", command=self.open_selected)
            menu.add_command(label="Show in folder", command=self.reveal_selected)
            menu.add_separator()
        menu.add_command(label="Delete...", command=self.delete_selected)
        menu.add_command(label="Move to other drive...", command=self.move_selected)
        if folder and self.result and len(folder) > len(self.result.map_root):
            menu.add_separator()
            short = folder if len(folder) < 60 else "..." + folder[-57:]
            menu.add_command(label=f"Never touch {short}", command=lambda: self.never_touch(folder))
        menu.tk_popup(event.x_root, event.y_root)

    def _tab_changed(self) -> None:
        """A selection on another tab must never be what Delete/Move act on."""
        current = self.tabs.select()
        for tree, tab in ((self.tree, self.files_tab), (self.gtree, self.groups_tab)):
            if str(tab) != current and tree.selection():
                tree.selection_remove(tree.selection())
        self.current = None
        self._set_buttons(False)

    def _clear_selection(self) -> None:
        for tree in (self.tree, self.gtree, self.ftree):
            if tree.selection():
                tree.selection_remove(tree.selection())
        self.current = None
        self._set_buttons(False)

    def _focus_search(self, search) -> None:
        self.tabs.select(self.files_tab)
        search.focus_set()

    # ------------------------------------------------------------------ AI
    def _selected_group(self) -> Group | None:
        if self.tabs.select() == str(self.groups_tab):
            chosen = self.gtree.selection()
            if len(chosen) == 1 and chosen[0] in self.group_rows:
                return self.group_rows[chosen[0]]
        return None

    def ask_ai(self) -> None:
        f = self.current
        g = None if f else self._selected_group()
        if not f and not g:
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
        facts = self._facts_for_ai(f) if f else self._facts_for_group(g)
        key = f.path if f else f"group:{g.key}"
        self.btn_ai.configure(state="disabled", text="Asking...")

        def work() -> None:
            try:
                answer = ai.ask_about_file(facts)
            except Exception as e:  # noqa: BLE001
                answer = f"Something went wrong: {e}"
            self.events.put(("ai", key, answer))

        threading.Thread(target=work, daemon=True).start()

    def _facts_for_ai(self, f: FileEntry) -> str:
        sections = explain(f.path, f.assessment, f.size, f.mtime, f.atime, f.duplicate_of, not f.online_only)
        lines = [f"Full path: {f.path}", f"Operating system: {sys.platform}"]
        for head, body in sections:
            if head == "First lines of the file":
                continue  # never send contents
            lines.append(f"\n[{head}]\n{body}")
        return "\n".join(lines)

    def _facts_for_group(self, g: Group) -> str:
        lines = [f"A group of {len(g.files):,} files ({human_size(g.size)}) that File Sorter calls: {g.title}",
                 f"File Sorter's description: {g.what}", f"Operating system: {sys.platform}", "Totals:"]
        lines += [f"  {v}: {human_size(b)}" for v, b in g.by_verdict.items() if b]
        lines.append("Biggest files (path, size, File Sorter's suggestion):")
        for f in sorted(g.files, key=lambda f: f.size, reverse=True)[:25]:
            lines.append(f"  {f.path}  {human_size(f.size)}  {f.verdict}")
        lines.append("Explain what this group of files is, which program uses it, and what is safe to delete.")
        return "\n".join(lines)

    def _show_ai_answer(self, path: str, answer: str) -> None:
        self.btn_ai.configure(text="Ask Claude")
        g = self._selected_group()
        if (self.current and self.current.path == path) or (g and path == f"group:{g.key}"):
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
