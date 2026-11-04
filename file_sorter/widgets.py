"""Drawn widgets: theme, storage bar, drive meters and the space map (treemap)."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import knowledge as kb
from .analysis import human_size
from .treemap import squarify

# --------------------------------------------------------------------------- theme
BG = "#f3f4f6"
SURFACE = "#ffffff"
BORDER = "#e5e7eb"
TEXT = "#111827"
MUTED = "#6b7280"
HEADER = "#111827"
ACCENT = "#2563eb"
DANGER = "#dc2626"

# strong colour (text, stripes) and soft colour (backgrounds) per verdict
COLORS = {
    kb.DELETE: ("#16a34a", "#dcfce7"),
    kb.REVIEW: ("#d97706", "#fef3c7"),
    kb.MOVE: ("#2563eb", "#dbeafe"),
    kb.KEEP: ("#9ca3af", "#f3f4f6"),
    kb.SYSTEM: ("#dc2626", "#fee2e2"),
}
# colours used to fill the space map (between strong and soft, readable with dark text)
MAP_FILL = {
    kb.DELETE: "#86efac",
    kb.REVIEW: "#fcd34d",
    kb.MOVE: "#93c5fd",
    kb.KEEP: "#d1d5db",
    kb.SYSTEM: "#fca5a5",
}
ICONS = {
    kb.DELETE: "✓",   # ✓
    kb.REVIEW: "?",
    kb.MOVE: "→",     # →
    kb.KEEP: "•",     # •
    kb.SYSTEM: "⚠",   # ⚠
}
# one symbol per file kind, all in the Basic Multilingual Plane so Tk 8.6 can draw them
KIND_ICONS = {
    "video": "▶", "audio": "♪", "image": "◩", "raw_photo": "◩", "design": "✎",
    "document": "▤", "spreadsheet": "▦", "presentation": "▥", "ebook": "▤", "text": "▤",
    "archive": "▣", "disk_image": "◉", "vm": "◉", "backup": "↺", "installer": "⤓",
    "executable": "⚙", "library": "⚙", "driver": "⚙", "script": "⚙", "code": "‹›",
    "temp": "◌", "log": "≡", "dump": "◌", "cache": "◌", "partial_download": "◌",
    "database": "◫", "config": "≡", "font": "A", "shortcut": "↗", "torrent": "↓",
    "email": "✉", "game_data": "◆", "other": "•",
}


FONTS: dict[str, tkfont.Font] = {}  # filled by apply_theme(); canvases need Font objects, not names


def fonts(root: tk.Misc) -> dict[str, tkfont.Font]:
    base = tkfont.nametofont("TkDefaultFont")
    family = "Segoe UI" if sys.platform == "win32" else base.actual("family")
    base.configure(family=family, size=10)
    tkfont.nametofont("TkTextFont").configure(family=family, size=10)
    tkfont.nametofont("TkHeadingFont").configure(family=family, size=10, weight="bold")
    return {
        "base": base,
        "small": tkfont.Font(root, family=family, size=9),
        "small_bold": tkfont.Font(root, family=family, size=9, weight="bold"),
        "bold": tkfont.Font(root, family=family, size=10, weight="bold"),
        "h2": tkfont.Font(root, family=family, size=12, weight="bold"),
        "title": tkfont.Font(root, family=family, size=15, weight="bold"),
        "big": tkfont.Font(root, family=family, size=15, weight="bold"),
    }


def apply_theme(root: tk.Tk) -> dict[str, tkfont.Font]:
    f = fonts(root)
    FONTS.update(f)
    root.configure(background=BG)
    style = ttk.Style(root)
    style.theme_use("clam")  # the one built-in theme that takes custom colours everywhere
    style.configure(".", background=BG, foreground=TEXT, font=f["base"], bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=BORDER, focuscolor=ACCENT)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Header.TFrame", background=HEADER)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=SURFACE)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("H2.TLabel", background=SURFACE, font=f["h2"])
    style.configure("TCheckbutton", background=SURFACE)
    style.map("TCheckbutton", background=[("active", SURFACE)])
    style.configure("TEntry", fieldbackground=SURFACE, padding=5)
    style.configure("TSpinbox", fieldbackground=SURFACE, padding=3, arrowsize=12)
    style.configure("TCombobox", fieldbackground=SURFACE, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)])

    style.configure("TButton", background=SURFACE, padding=(12, 6), borderwidth=1, bordercolor="#d1d5db",
                    lightcolor=SURFACE, darkcolor="#d1d5db")
    style.configure("TMenubutton", background=SURFACE, padding=(10, 5), bordercolor="#d1d5db",
                    lightcolor=SURFACE, darkcolor="#d1d5db", arrowcolor=MUTED)
    style.map("TButton", background=[("disabled", BG), ("active", "#f9fafb")],
              foreground=[("disabled", "#9ca3af")])
    for name, color, hover in (("Primary", ACCENT, "#1d4ed8"), ("Danger", DANGER, "#b91c1c"),
                               ("Clean", COLORS[kb.DELETE][0], "#15803d"),
                               ("Move", COLORS[kb.MOVE][0], "#1d4ed8")):
        style.configure(f"{name}.TButton", background=color, foreground="white", bordercolor=color,
                        lightcolor=color, darkcolor=color, font=f["bold"])
        style.map(f"{name}.TButton", background=[("disabled", "#cbd5e1"), ("active", hover)],
                  bordercolor=[("disabled", "#cbd5e1")], lightcolor=[("disabled", "#cbd5e1")],
                  darkcolor=[("disabled", "#cbd5e1")], foreground=[("disabled", "white")])

    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, rowheight=28,
                    borderwidth=0, relief="flat")
    style.map("Treeview", background=[("selected", "#1e3a8a")], foreground=[("selected", "white")])
    style.configure("Treeview.Heading", background="#f9fafb", foreground=MUTED, relief="flat",
                    font=f["bold"], padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", "#eef2ff")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # no inner border

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(16, 7), borderwidth=0,
                    font=f["bold"])
    style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", TEXT)],
              expand=[("selected", (0, 0, 0, 0))])
    style.configure("TPanedwindow", background=BG)
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=BORDER, borderwidth=0,
                    thickness=6)
    style.configure("Vertical.TScrollbar", background=BG, troughcolor=SURFACE, borderwidth=0, arrowsize=12)
    return f


# --------------------------------------------------------------------------- storage bar
class StorageBar(tk.Canvas):
    """One horizontal bar split by how many bytes fall into each verdict. Click a part to filter."""

    def __init__(self, master, on_click, **kw) -> None:
        super().__init__(master, height=26, background=SURFACE, highlightthickness=0, **kw)
        self.on_click = on_click
        self.totals: dict[str, int] = {}
        self.bind("<Configure>", lambda e: self.draw())
        # bound once: per-item bindings would pile up on every redraw
        self.bind("<Button-1>", lambda e: (v := self._verdict_at()) and self.on_click(v))
        self.bind("<Motion>", lambda e: self.configure(cursor="hand2" if self._verdict_at() else ""))

    def _verdict_at(self) -> str | None:
        for tag in self.gettags("current"):
            if tag.startswith("seg"):
                return kb.VERDICTS[int(tag[3:])]
        return None

    def set(self, totals: dict[str, int]) -> None:
        self.totals = totals
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), int(self["height"])
        total = sum(self.totals.values())
        if not total or w < 20:
            self.create_rectangle(0, 4, w, h - 4, fill=BORDER, outline="")
            return
        x = 0.0
        for i, v in enumerate(kb.VERDICTS):
            part = self.totals.get(v, 0) / total * w
            if part <= 0:
                continue
            self.create_rectangle(x, 4, x + part, h - 4, fill=COLORS[v][0], outline=SURFACE, width=1, tags=f"seg{i}")
            if part > 70:
                self.create_text(x + part / 2, h / 2, text=f"{self.totals[v] / total * 100:.0f}%", fill="white",
                                 font=FONTS.get("small_bold"), tags=f"seg{i}")
            x += part


# --------------------------------------------------------------------------- drive meters
class DriveMeter(tk.Canvas):
    def __init__(self, master, root: str, free: int, total: int) -> None:
        name = root.rstrip("\\/") or root
        if len(name) > 11:
            name = name[:10] + "\u2026"
        label_font, small = FONTS.get("small_bold"), FONTS.get("small")
        free_text = f"{human_size(free)} free"
        line = small.metrics("linespace") if small else 15
        width = max(150, (label_font.measure(name) + small.measure(free_text) + 16) if small else 160)
        bar_y = line + 4
        super().__init__(master, width=width, height=bar_y + 8, background=HEADER, highlightthickness=0)
        used = 1 - free / total if total else 0
        color = "#ef4444" if used > 0.9 else "#f59e0b" if used > 0.75 else "#22c55e"
        self.create_text(0, line / 2, anchor="w", text=name, fill="white", font=label_font)
        self.create_text(width, line / 2, anchor="e", text=free_text, fill="#9ca3af", font=small)
        self.create_rectangle(0, bar_y, width, bar_y + 6, fill="#374151", outline="")
        self.create_rectangle(0, bar_y, max(2, width * used), bar_y + 6, fill=color, outline="")


# --------------------------------------------------------------------------- space map
class SpaceMap(tk.Canvas):
    """Treemap of a folder: each box is a subfolder, sized by space used and striped by verdict.

    items: list of (label, path_or_None, verdict_bytes dict, is_folder)
    """

    MAX_BOXES = 60

    def __init__(self, master, on_open, on_hover, **kw) -> None:
        super().__init__(master, background=SURFACE, highlightthickness=0, **kw)
        self.on_open = on_open      # called with (path, is_folder)
        self.on_hover = on_hover    # called with text for the status line
        self.items: list = []
        self.boxes: list[tuple[str | None, bool, str]] = []  # per box: path, is_folder, hint
        self.hovered: int | None = None
        self.message = "Press Scan to see where your space goes."
        self.bind("<Configure>", lambda e: self.draw())
        # bound once on the canvas; per-item bindings would pile up and outlive their boxes
        self.bind("<Motion>", lambda e: self._hover(self._box_at()))
        self.bind("<Leave>", lambda e: self._hover(None))
        self.bind("<Button-1>", lambda e: self._click(self._box_at()))

    def show(self, items: list, message: str = "") -> None:
        self.items = items
        self.message = message
        self.draw()

    def _box_at(self) -> int | None:
        for tag in self.gettags("current"):
            if tag.startswith("box"):
                return int(tag[3:])
        return None

    def _click(self, i: int | None) -> None:
        if i is not None and self.boxes[i][0]:
            path, is_folder, _ = self.boxes[i]
            self.on_open(path, is_folder)

    def _hover(self, i: int | None) -> None:
        if i == self.hovered:
            return
        if self.hovered is not None:
            self.itemconfigure(f"frame{self.hovered}", outline=SURFACE, width=3)
        self.hovered = i
        if i is None:
            self.configure(cursor="")
            self.on_hover("")
            return
        self.itemconfigure(f"frame{i}", outline=TEXT, width=2)
        self.configure(cursor="hand2" if self.boxes[i][0] else "")
        self.on_hover(self.boxes[i][2])

    def draw(self) -> None:
        self.delete("all")
        self.boxes, self.hovered = [], None
        w, h = self.winfo_width(), self.winfo_height()
        items = [it for it in self.items if sum(it[2].values()) > 0]
        if not items or w < 40 or h < 40:
            self.create_text(w / 2, h / 2, text=self.message or "Nothing here.", fill=MUTED,
                             font=FONTS.get("h2"), width=max(100, w - 40))
            return
        items.sort(key=lambda it: sum(it[2].values()), reverse=True)
        if len(items) > self.MAX_BOXES:
            rest = items[self.MAX_BOXES - 1:]
            merged: dict[str, int] = {}
            for it in rest:
                for v, b in it[2].items():
                    merged[v] = merged.get(v, 0) + b
            items = items[:self.MAX_BOXES - 1] + [(f"{len(rest)} smaller items", None, merged, False)]
        sizes = [sum(it[2].values()) for it in items]
        total = sum(sizes)
        pad = 4
        rects = squarify([s / total * (w - 2 * pad) * (h - 2 * pad) for s in sizes], pad, pad, w - 2 * pad, h - 2 * pad)
        name_font, size_font = FONTS.get("bold"), FONTS.get("small")
        line = name_font.metrics("linespace") if name_font else 16
        for i, ((label, path, vb, is_folder), size, (x, y, rw, rh)) in enumerate(zip(items, sizes, rects)):
            tag = f"box{i}"
            sx = x  # stripes, one per verdict, proportional to bytes
            for v in kb.VERDICTS:
                part = vb.get(v, 0) / size * rw
                if part > 0:
                    self.create_rectangle(sx, y, sx + part, y + rh, fill=MAP_FILL[v], outline="", tags=tag)
                    sx += part
            self.create_rectangle(x, y, x + rw, y + rh, outline=SURFACE, width=3, tags=(tag, f"frame{i}"))
            if rw > 50 and rh > 2 * line + 8:
                self.create_text(x + 8, y + 6, anchor="nw", text=_fit(label, name_font, rw - 14), fill=TEXT,
                                 font=name_font, tags=tag)
                self.create_text(x + 8, y + 6 + line, anchor="nw", text=human_size(size), fill="#374151",
                                 font=size_font, tags=tag)
            freeable = vb.get(kb.DELETE, 0) + vb.get(kb.REVIEW, 0)
            movable = vb.get(kb.MOVE, 0)
            hint = f"{label}: {human_size(size)}"
            if freeable:
                hint += f"  |  {human_size(freeable)} could be deleted"
            if movable:
                hint += f"  |  {human_size(movable)} could be moved"
            hint += "  |  click to open" if (path and is_folder) else "  |  click to list these files" if path else ""
            self.boxes.append((path, is_folder, hint))


def _fit(text: str, font: tkfont.Font | None, width: float) -> str:
    """Shorten text with an ellipsis until it fits in `width` pixels."""
    if font is None or font.measure(text) <= width:
        return text
    while len(text) > 1 and font.measure(text + "\u2026") > width:
        text = text[:-1]
    return text + "\u2026"
