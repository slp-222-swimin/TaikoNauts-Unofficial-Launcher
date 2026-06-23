from __future__ import annotations

import tkinter as tk
from tkinter import ttk


# ── Colour Palette ──────────────────────────────────────────────
BG            = "#0d1117"
BG_ELEVATED   = "#111820"
PANEL         = "#161b22"
PANEL_ALT     = "#11161d"
CARD          = "#161b22"
CARD_HOVER    = "#1c2333"
TEXT          = "#e6edf3"
TEXT_SECONDARY = "#c9d1d9"
MUTED         = "#8b949e"
ACCENT        = "#58a6ff"
ACCENT_2      = "#7c3aed"
ACCENT_SOFT   = "#1f6feb"
ACCENT_GLOW   = "#388bfd"
BORDER        = "#21262d"
BORDER_SUBTLE = "#1b2028"
SUCCESS       = "#2ea043"
WARNING       = "#d29922"
ERROR         = "#f85149"
SURFACE_HOVER = "#1c2333"

# ── Layout Constants ────────────────────────────────────────────
SPLASH_DURATION_MS = 2200
CARD_PAD_X   = 20
CARD_PAD_Y   = 16
CARD_INNER   = 14
SECTION_GAP  = 10
CORNER_RADIUS = 8

# ── Font Definitions ───────────────────────────────────────────
FONT_FAMILY  = "Segoe UI"
FONT_TITLE   = (FONT_FAMILY, 20, "bold")
FONT_HEADING = (FONT_FAMILY, 13, "bold")
FONT_SECTION = (FONT_FAMILY, 11, "bold")
FONT_BODY    = (FONT_FAMILY, 10)
FONT_SMALL   = (FONT_FAMILY, 9)
FONT_TINY    = (FONT_FAMILY, 8)


def setup_styles(root: tk.Tk) -> None:
    """Configure all ttk styles for the modern dark theme."""
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # ── Base ────────────────────────────────────────────────────
    style.configure(".", background=BG, foreground=TEXT, borderwidth=0)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)

    # ── Buttons ─────────────────────────────────────────────────
    style.configure(
        "TButton",
        background=PANEL,
        foreground=TEXT,
        padding=(16, 9),
        font=FONT_BODY,
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("active", CARD_HOVER), ("pressed", BG_ELEVATED)],
        relief=[("pressed", "flat")],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT_SOFT,
        foreground="#ffffff",
        padding=(18, 10),
        font=(FONT_FAMILY, 10, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT), ("pressed", ACCENT_GLOW)],
    )

    style.configure(
        "Ghost.TButton",
        background=PANEL_ALT,
        foreground=TEXT_SECONDARY,
        padding=(16, 9),
        font=FONT_BODY,
    )
    style.map(
        "Ghost.TButton",
        background=[("active", SURFACE_HOVER), ("pressed", BG_ELEVATED)],
    )

    style.configure(
        "Danger.TButton",
        background="#3d1214",
        foreground=ERROR,
        padding=(16, 9),
        font=FONT_BODY,
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#5a1a1e"), ("pressed", "#2d0c0e")],
    )

    # ── Entry ───────────────────────────────────────────────────
    style.configure(
        "TEntry",
        fieldbackground=BG_ELEVATED,
        foreground=TEXT,
        insertcolor=TEXT,
        borderwidth=1,
        padding=(10, 8),
    )
    style.map("TEntry", fieldbackground=[("focus", PANEL)])

    # ── LabelFrame (Card) ──────────────────────────────────────
    style.configure(
        "TLabelframe",
        background=CARD,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        relief="flat",
    )
    style.configure(
        "TLabelframe.Label",
        background=CARD,
        foreground=ACCENT,
        font=FONT_SECTION,
    )

    # ── Card Frames ────────────────────────────────────────────
    style.configure("Card.TFrame", background=CARD)
    style.configure("CardAlt.TFrame", background=PANEL_ALT)
    style.configure("CardInner.TFrame", background=CARD)

    # ── Card Labels ────────────────────────────────────────────
    style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT, font=FONT_HEADING)
    style.configure("CardSubtitle.TLabel", background=CARD, foreground=MUTED, font=FONT_BODY)
    style.configure("CardText.TLabel", background=CARD, foreground=MUTED, font=FONT_BODY)
    style.configure("CardAccent.TLabel", background=CARD, foreground=ACCENT, font=FONT_BODY)

    # ── Hero / Header ──────────────────────────────────────────
    style.configure("Hero.TFrame", background=CARD)
    style.configure("HeroTitle.TLabel", background=CARD, foreground=TEXT, font=FONT_TITLE)
    style.configure("HeroSubtitle.TLabel", background=CARD, foreground=MUTED, font=FONT_BODY)

    # ── ZIP Drop Zone ──────────────────────────────────────────
    style.configure("DropZone.TFrame", background=PANEL_ALT)
    style.configure("DropZoneTitle.TLabel", background=PANEL_ALT, foreground=TEXT, font=FONT_SECTION)
    style.configure("DropZoneHint.TLabel", background=PANEL_ALT, foreground=MUTED, font=FONT_BODY)
    style.configure("DropZoneStatus.TLabel", background=PANEL_ALT, foreground=ACCENT, font=FONT_SMALL)

    # ── Status Labels ──────────────────────────────────────────
    style.configure("Status.TLabel", background=CARD, foreground=MUTED, font=FONT_SMALL)
    style.configure("StatusAccent.TLabel", background=CARD, foreground=ACCENT, font=FONT_SMALL)

    # ── Treeview ───────────────────────────────────────────────
    style.configure(
        "Treeview",
        background=BG_ELEVATED,
        fieldbackground=BG_ELEVATED,
        foreground=TEXT,
        rowheight=32,
        borderwidth=0,
        font=FONT_BODY,
    )
    style.configure(
        "Treeview.Heading",
        background=PANEL,
        foreground=TEXT_SECONDARY,
        relief="flat",
        padding=(12, 8),
        font=(FONT_FAMILY, 9, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT_SOFT)],
        foreground=[("selected", "#ffffff")],
    )
    style.map("Treeview.Heading", background=[("active", CARD_HOVER)])

    # ── Progressbar ────────────────────────────────────────────
    style.configure(
        "TProgressbar",
        troughcolor=BG_ELEVATED,
        background=ACCENT,
        borderwidth=0,
        thickness=6,
    )

    # ── Scrollbar ──────────────────────────────────────────────
    style.configure(
        "Vertical.TScrollbar",
        background=PANEL,
        troughcolor=BG,
        borderwidth=0,
        arrowsize=0,
    )
    style.map("Vertical.TScrollbar", background=[("active", CARD_HOVER)])
