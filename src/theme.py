"""Centralized modern theme for NetToolkit (ttk).

Defines a flat light color palette, typography, and ttk styles so every tab
shares a consistent, polished look. Call :func:`apply_theme` once on the root
window; use :data:`PALETTE` and the named styles below when building widgets.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ── Color palette ────────────────────────────────────────────────────────
PALETTE = {
    "bg": "#eef1f5",        # window background
    "surface": "#ffffff",   # cards / panels
    "surface_alt": "#f8fafc",  # zebra rows / subtle fills
    "border": "#dbe2ea",    # hairline borders
    "text": "#1f2933",      # primary text
    "muted": "#6b7280",     # secondary text
    "accent": "#2563eb",    # primary blue
    "accent_hover": "#1d4ed8",
    "accent_active": "#1e40af",
    "header": "#0f172a",    # dark header bar
    "header_text": "#f8fafc",
    "success": "#15803d",
    "success_bg": "#dcfce7",
    "danger": "#b91c1c",
    "danger_bg": "#fee2e2",
    "warning": "#b45309",
    "info": "#0369a1",
    "track": "#e2e8f0",     # progress trough
}

# ── Fonts (resolved lazily in apply_theme) ───────────────────────────────
FONTS: dict[str, tkfont.Font] = {}


def _pick_family(root: tk.Misc, candidates: list[str], fallback: str) -> str:
    available = set(tkfont.families(root))
    for name in candidates:
        if name in available:
            return name
    return fallback


def apply_theme(root: tk.Tk) -> dict:
    """Apply the NetToolkit theme to *root* and return the palette."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # most customizable built-in ttk theme
    except tk.TclError:
        pass

    p = PALETTE
    ui_family = _pick_family(root, ["Segoe UI", "Inter", "Helvetica Neue"], "TkDefaultFont")
    mono_family = _pick_family(
        root, ["Cascadia Mono", "Consolas", "SF Mono", "Menlo"], "TkFixedFont"
    )

    FONTS["body"] = tkfont.Font(root=root, family=ui_family, size=10)
    FONTS["body_bold"] = tkfont.Font(root=root, family=ui_family, size=10, weight="bold")
    FONTS["heading"] = tkfont.Font(root=root, family=ui_family, size=12, weight="bold")
    FONTS["title"] = tkfont.Font(root=root, family=ui_family, size=17, weight="bold")
    FONTS["subtitle"] = tkfont.Font(root=root, family=ui_family, size=10)
    FONTS["mono"] = tkfont.Font(root=root, family=mono_family, size=9)

    root.configure(bg=p["bg"])
    root.option_add("*Font", FONTS["body"])
    # tk (non-ttk) widget defaults, e.g. Text/Entry popups.
    root.option_add("*Text.background", p["surface"])
    root.option_add("*Text.foreground", p["text"])

    # Base
    style.configure(".", background=p["bg"], foreground=p["text"], font=FONTS["body"])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
    style.configure(
        "TLabelframe.Label", background=p["bg"], foreground=p["muted"], font=FONTS["body_bold"]
    )

    # Header bar
    style.configure("Header.TFrame", background=p["header"])
    style.configure(
        "AppTitle.TLabel",
        background=p["header"],
        foreground=p["header_text"],
        font=FONTS["title"],
    )
    style.configure(
        "AppSubtitle.TLabel",
        background=p["header"],
        foreground="#94a3b8",
        font=FONTS["subtitle"],
    )

    # Cards / surfaces
    style.configure("Card.TFrame", background=p["surface"], relief="flat")
    style.configure("Card.TLabel", background=p["surface"], foreground=p["text"])
    style.configure(
        "Heading.TLabel",
        background=p["surface"],
        foreground=p["text"],
        font=FONTS["heading"],
    )
    style.configure(
        "Muted.TLabel", background=p["surface"], foreground=p["muted"]
    )
    style.configure(
        "MutedBg.TLabel", background=p["bg"], foreground=p["muted"]
    )
    style.configure(
        "Value.TLabel", background=p["surface"], foreground=p["text"], font=FONTS["body_bold"]
    )
    style.configure(
        "Success.TLabel", background=p["surface"], foreground=p["success"], font=FONTS["body_bold"]
    )
    style.configure(
        "Danger.TLabel", background=p["surface"], foreground=p["danger"], font=FONTS["body_bold"]
    )

    # Buttons — default (secondary, outlined feel)
    style.configure(
        "TButton",
        background=p["surface"],
        foreground=p["text"],
        bordercolor=p["border"],
        focuscolor=p["accent"],
        relief="flat",
        padding=(14, 8),
    )
    style.map(
        "TButton",
        background=[("active", p["surface_alt"]), ("disabled", p["bg"])],
        foreground=[("disabled", "#9aa5b1")],
        bordercolor=[("active", p["accent"])],
    )

    # Accent (primary) button
    style.configure(
        "Accent.TButton",
        background=p["accent"],
        foreground="#ffffff",
        bordercolor=p["accent"],
        relief="flat",
        padding=(16, 8),
        font=FONTS["body_bold"],
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", "#a9c0f5"),
            ("pressed", p["accent_active"]),
            ("active", p["accent_hover"]),
        ],
        foreground=[("disabled", "#eef2ff")],
    )

    # Danger button
    style.configure(
        "Danger.TButton",
        background=p["surface"],
        foreground=p["danger"],
        bordercolor=p["border"],
        relief="flat",
        padding=(14, 8),
    )
    style.map(
        "Danger.TButton",
        background=[("active", p["danger_bg"]), ("disabled", p["bg"])],
        foreground=[("disabled", "#c9a3a3")],
        bordercolor=[("active", p["danger"])],
    )

    # Entries / spinbox / combobox
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            name,
            fieldbackground=p["surface"],
            background=p["surface"],
            foreground=p["text"],
            bordercolor=p["border"],
            arrowcolor=p["muted"],
            relief="flat",
            padding=6,
        )
        style.map(
            name,
            bordercolor=[("focus", p["accent"])],
            fieldbackground=[("readonly", p["surface"])],
        )

    # Radiobutton / checkbutton on cards
    style.configure(
        "Card.TRadiobutton", background=p["surface"], foreground=p["text"]
    )
    style.map(
        "Card.TRadiobutton",
        background=[("active", p["surface"])],
        indicatorcolor=[("selected", p["accent"])],
    )

    # Notebook (tabs)
    style.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(6, 8, 6, 0))
    style.configure(
        "TNotebook.Tab",
        background=p["track"],
        foreground=p["muted"],
        padding=(10, 9),
        width=20,
        anchor="center",
        font=FONTS["body_bold"],
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", p["accent"]), ("active", "#d6dde6")],
        foreground=[("selected", "#ffffff"), ("active", p["text"])],
    )

    # Progressbar
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=p["track"],
        background=p["accent"],
        bordercolor=p["track"],
        lightcolor=p["accent"],
        darkcolor=p["accent"],
        thickness=10,
    )

    # Treeview
    style.configure(
        "Treeview",
        background=p["surface"],
        fieldbackground=p["surface"],
        foreground=p["text"],
        bordercolor=p["border"],
        rowheight=26,
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", "#dbeafe")],
        foreground=[("selected", p["text"])],
    )
    style.configure(
        "Treeview.Heading",
        background=p["surface_alt"],
        foreground=p["muted"],
        relief="flat",
        padding=(8, 6),
        font=FONTS["body_bold"],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", p["track"])],
    )

    # Scrollbars
    style.configure(
        "Vertical.TScrollbar",
        background=p["track"],
        troughcolor=p["bg"],
        bordercolor=p["bg"],
        arrowcolor=p["muted"],
        relief="flat",
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=p["track"],
        troughcolor=p["bg"],
        bordercolor=p["bg"],
        arrowcolor=p["muted"],
        relief="flat",
    )

    return p


def style_tree_tags(tree: ttk.Treeview) -> None:
    """Configure zebra striping + status color tags on a Treeview."""
    p = PALETTE
    tree.tag_configure("odd", background=PALETTE["surface"])
    tree.tag_configure("even", background=PALETTE["surface_alt"])
    tree.tag_configure("done", foreground=p["success"])
    tree.tag_configure("failed", foreground=p["danger"])
    tree.tag_configure("active", foreground=p["accent"])
    tree.tag_configure("canceled", foreground=p["muted"])
