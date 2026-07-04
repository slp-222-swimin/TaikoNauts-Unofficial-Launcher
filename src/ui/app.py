from __future__ import annotations

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from ctypes import wintypes
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from src.core.utils import (
    APP_TITLE, APP_DIR, APP_VERSION, GITHUB_REPO_URL, GAME_BOOTSTRAP_URL,
    WINDOWS_GAME_EXE_NAME, PROCESS_KILL_TIMEOUT_SEC,
    ReleaseInfo, SkinInfo,
    fetch_latest_release, is_version_newer, download_release_asset,
    normalize_version_label,
    load_launcher_state, save_launcher_state,
    read_game_config, write_game_config,
    read_system_config, write_system_config,
    discover_skins, resolve_game_root, resolve_skin_path,
    extract_zip_to_songs, extract_zip_archive, select_payload_root,
    clear_zip_folder_keep_box_def, safe_write_json,
)
from src.core.updater_session import UpdaterSession
from src.ui.toast import show_toast, confirm_toast
from src.native.win32 import (
    WM_DROPFILES, GWL_WNDPROC, CFUNCTYPE_WNDPROC,
    find_child_processes_by_name, kill_process,
)
from src.ui.styles import (
    BG, BG_ELEVATED, PANEL, PANEL_ALT, CARD, CARD_HOVER,
    TEXT, TEXT_SECONDARY, MUTED, ACCENT, ACCENT_SOFT, ACCENT_GLOW,
    BORDER, BORDER_SUBTLE, SUCCESS, ERROR,
    SIDEBAR_BG, SIDEBAR_TEXT,
    SPLASH_DURATION_MS,
    CARD_PAD_X, CARD_PAD_Y, CARD_INNER, SECTION_GAP,
    FONT_FAMILY, FONT_TITLE, FONT_HEADING, FONT_SECTION,
    FONT_BODY, FONT_SMALL, FONT_TINY,
    setup_styles,
)
from src.ui.splash import SplashScreen
from src.ui.updater_windows import (
    UpdaterConfigWindow, UpdaterWindow, UpdateDownloadWindow,
)

if os.name == "nt":
    from src.native.win32 import shell32, user32


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("800x600")
        self.minsize(700, 500)

        self.exe_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select game folder")
        self.skin_message_var = tk.StringVar(value="")
        self.current_root_var = tk.StringVar(value="Game root not selected")
        self.skin_count_var = tk.StringVar(value="0 skins")
        self.drop_hint_var = tk.StringVar(value="Drop a ZIP file here to extract it into Songs\\zip")
        self.zip_status_var = tk.StringVar(value="Ready")
        self.zip_extract_var = tk.StringVar(value="Songs\\zip")
        self._active_tab = tk.StringVar(value="game")

        self.skins: list[SkinInfo] = []
        self.skin_map: dict[str, SkinInfo] = {}
        self.events: queue.Queue[tuple[str, object, object]] = queue.Queue()
        self.updater_session: UpdaterSession | None = None
        self.updater_window: UpdaterWindow | None = None
        self._drop_wndproc_ref = None
        self._drop_old_wndproc = None
        self.zip_drop_zone = None
        self.launcher_version: str = ""
        self._tab_frames: dict[str, tk.Frame] = {}
        self._sidebar_btns: dict[str, ttk.Button] = {}

        setup_styles(self)
        self._build_ui()
        self._enable_file_drop()
        self._load_saved_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.withdraw()
        self.after(100, self._drain_events)
        self.after(200, self._update_updater_btn)

    # ── UI Construction ─────────────────────────────────────────

    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True)

        # ── Sidebar ─────────────────────────────────────────────
        sidebar = tk.Frame(root, bg=SIDEBAR_BG, width=170)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tabs = [
            ("game", "🎮", "Game"),
            ("skins", "🎨", "Skins"),
            ("zip", "📦", "ZIP Import"),
            ("config", "⚙", "Config"),
        ]
        for key, emoji, label in tabs:
            btn = ttk.Button(
                sidebar,
                text=f"  {emoji}  {label}",
                style="Sidebar.TButton",
                command=lambda k=key: self._switch_tab(k),
            )
            btn.pack(fill="x")
            self._sidebar_btns[key] = btn

        # Spacer + version link at sidebar bottom
        sidebar_spacer = tk.Frame(sidebar, bg=SIDEBAR_BG)
        sidebar_spacer.pack(fill="both", expand=True)
        version_text = f"v{normalize_version_label(APP_VERSION)}"
        version_link = tk.Label(
            sidebar, text=version_text,
            fg=MUTED, bg=SIDEBAR_BG, font=FONT_TINY, cursor="hand2",
        )
        version_link.pack(side="bottom", pady=(0, 12))
        version_link.bind("<Enter>", lambda _: version_link.configure(fg=ACCENT))
        version_link.bind("<Leave>", lambda _: version_link.configure(fg=MUTED))
        version_link.bind("<Button-1>", lambda _: __import__("webbrowser").open(GITHUB_REPO_URL))

        # ── Content area ────────────────────────────────────────
        content = tk.Frame(root, bg=CARD)
        content.pack(side="right", fill="both", expand=True, padx=(1, 0))

        self._content = content
        self._build_tab_game()
        self._build_tab_skins()
        self._build_tab_zip()
        self._build_tab_config()
        self._switch_tab("game")

    def _switch_tab(self, name: str) -> None:
        self._active_tab.set(name)
        for key, frame in self._tab_frames.items():
            frame.pack_forget() if key != name else None
            style = "SidebarActive.TButton" if key == name else "Sidebar.TButton"
            self._sidebar_btns[key].configure(style=style)
        self._tab_frames[name].pack(fill="both", expand=True)

    def _build_tab_game(self) -> None:
        frame = tk.Frame(self._content, bg=CARD)
        self._tab_frames["game"] = frame

        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="x", padx=CARD_PAD_X, pady=CARD_PAD_Y)

        tk.Label(inner, text="🎮  Game", bg=CARD, fg=TEXT, font=FONT_HEADING).pack(anchor="w")

        path_row = ttk.Frame(inner)
        path_row.pack(fill="x", pady=(CARD_INNER, 0))
        ttk.Entry(path_row, textvariable=self.exe_path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="Browse…", style="Ghost.TButton", command=self.select_exe).pack(side="left", padx=(8, 0))
        ttk.Button(path_row, text="Refresh", style="Ghost.TButton", command=self.refresh_all).pack(side="left", padx=(6, 0))

        action_row = tk.Frame(inner, bg=CARD)
        action_row.pack(fill="x", pady=(CARD_INNER, 0))
        ttk.Button(action_row, text="▶  Launch Game", style="Accent.TButton", command=self.launch_game).pack(side="left")
        self._updater_btn = ttk.Button(action_row, text="⬆  Launch Updater", command=self.start_updater)
        self._updater_btn.pack(side="left", padx=(8, 0))

        status_frame = tk.Frame(action_row, bg=CARD)
        status_frame.pack(side="left", padx=(16, 0))
        tk.Label(status_frame, textvariable=self.status_var, bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w")

    def _build_tab_skins(self) -> None:
        frame = tk.Frame(self._content, bg=CARD)
        self._tab_frames["skins"] = frame

        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="both", expand=True, padx=CARD_PAD_X, pady=CARD_PAD_Y)

        tk.Label(inner, text="🎨  Skins", bg=CARD, fg=TEXT, font=FONT_HEADING).pack(anchor="w")

        toolbar = tk.Frame(inner, bg=CARD)
        toolbar.pack(fill="x", pady=(CARD_INNER, 0))
        ttk.Button(toolbar, text="Reload skins", style="Ghost.TButton", command=self.refresh_skins).pack(side="left")
        ttk.Button(toolbar, text="Apply selected skin", style="Accent.TButton", command=self.apply_selected_skin).pack(side="left", padx=(8, 0))
        tk.Label(toolbar, textvariable=self.skin_message_var, bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(12, 0))

        tree_frame = tk.Frame(inner, bg=BG_ELEVATED, highlightthickness=1, highlightbackground=BORDER, bd=0)
        tree_frame.pack(fill="both", expand=True, pady=(CARD_INNER, 0))

        self.skin_tree = ttk.Treeview(
            tree_frame,
            columns=("name", "version", "path", "description"),
            show="headings",
            height=6,
        )
        self.skin_tree.heading("name", text="Name", anchor="w")
        self.skin_tree.heading("version", text="Version", anchor="w")
        self.skin_tree.heading("path", text="SkinPath", anchor="w")
        self.skin_tree.heading("description", text="Description", anchor="w")
        self.skin_tree.column("name", width=120, anchor="w")
        self.skin_tree.column("version", width=80, anchor="w")
        self.skin_tree.column("path", width=160, anchor="w")
        self.skin_tree.column("description", width=220, anchor="w")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.skin_tree.yview)
        self.skin_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.skin_tree.pack(fill="both", expand=True)
        self.skin_tree.bind("<<TreeviewSelect>>", self._on_skin_select)

    def _build_tab_zip(self) -> None:
        frame = tk.Frame(self._content, bg=CARD)
        self._tab_frames["zip"] = frame

        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="x", padx=CARD_PAD_X, pady=CARD_PAD_Y)

        tk.Label(inner, text="📦  Beatmap Import", bg=CARD, fg=TEXT, font=FONT_HEADING).pack(anchor="w")

        extract_row = ttk.Frame(inner)
        extract_row.pack(fill="x", pady=(CARD_INNER, 0))
        ttk.Label(extract_row, text="Extract to:", font=FONT_BODY).pack(side="left")
        ttk.Entry(extract_row, textvariable=self.zip_extract_var).pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Button(extract_row, text="Browse...", style="Ghost.TButton", command=lambda: self._browse_zip_extract()).pack(side="left", padx=(8, 0))

        clear_row = ttk.Frame(inner)
        clear_row.pack(fill="x", pady=(6, 0))
        ttk.Button(clear_row, text="Clear extracted folder", style="Ghost.TButton", command=self.clear_extracted_zip_folder).pack(side="left")
        tk.Label(clear_row, textvariable=self.zip_status_var, bg=CARD, fg=ACCENT, font=FONT_SMALL).pack(side="left", padx=(12, 0))

        self.zip_drop_zone = tk.Frame(
            inner, bg=PANEL_ALT,
            highlightthickness=1, highlightbackground=ACCENT_SOFT,
            highlightcolor=ACCENT, bd=0,
        )
        self.zip_drop_zone.pack(fill="x", pady=(CARD_INNER, 0))

        drop_inner = tk.Frame(self.zip_drop_zone, bg=PANEL_ALT)
        drop_inner.pack(fill="x", padx=18, pady=18)
        tk.Label(drop_inner, text="⬇  Drop ZIP files here", bg=PANEL_ALT, fg=TEXT, font=FONT_SECTION).pack(anchor="w")
        tk.Label(
            drop_inner,
            text="Only files dropped onto this area will be extracted into the path above.",
            bg=PANEL_ALT, fg=MUTED, font=FONT_BODY,
        ).pack(anchor="w", pady=(4, 0))

    def _build_tab_config(self) -> None:
        frame = tk.Frame(self._content, bg=CARD)
        self._tab_frames["config"] = frame

        header = tk.Frame(frame, bg=CARD)
        header.pack(fill="x", padx=CARD_PAD_X, pady=(CARD_PAD_Y, 0))
        tk.Label(header, text="⚙  System Config", bg=CARD, fg=TEXT, font=FONT_HEADING).pack(side="left")
        ttk.Button(header, text="Save", style="Accent.TButton", command=self._save_system_config).pack(side="right")
        ttk.Button(header, text="Reload", style="Ghost.TButton", command=self._load_system_config).pack(side="right", padx=(0, 8))

        canvas = tk.Canvas(frame, bg=CARD, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scroll_inner = tk.Frame(canvas, bg=CARD)
        scroll_inner.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(CARD_PAD_X, 0), pady=(0, CARD_PAD_Y))

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bound_to_mousewheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbound_from_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bound_to_mousewheel)
        canvas.bind("<Leave>", _unbound_from_mousewheel)
        scroll_inner.bind("<Enter>", _bound_to_mousewheel)
        scroll_inner.bind("<Leave>", _unbound_from_mousewheel)

        self._config_vars: dict[str, tk.StringVar | tk.BooleanVar] = {}
        self._config_slider_vars: dict[str, tuple] = {}

        # ── Display ─────────────────────────────────────────────
        self._config_section_label(scroll_inner, "Display")

        self._config_var("fullscreen", tk.BooleanVar(value=False))
        self._config_checkbox(scroll_inner, "Fullscreen", "fullscreen")

        self._config_var("vSync", tk.BooleanVar(value=False))
        self._config_checkbox(scroll_inner, "V-Sync", "vSync")

        self._config_var("showFPS", tk.BooleanVar(value=True))
        self._config_checkbox(scroll_inner, "Show FPS", "showFPS")

        self._config_var("useBackgroundMovie", tk.BooleanVar(value=True))
        self._config_checkbox(scroll_inner, "Background Movie", "useBackgroundMovie")

        self._config_var("resolution", tk.StringVar(value="1920x1080"))
        self._config_resolution(scroll_inner)

        self._config_var("targetFPS", tk.StringVar(value="0"))
        self._config_slider(scroll_inner, "Target FPS (0=unlimited)", "targetFPS", 0, 240, resolution=1, no_limit=True)

        self._config_var("backgroundMovieType", tk.StringVar(value="BlurWithMiniWindow"))
        self._config_dropdown(scroll_inner, "Movie Type", "backgroundMovieType", ["None", "Blur", "BlurWithMiniWindow"])

        self._config_var("backgroundMovieOpacity", tk.StringVar(value="1"))
        self._config_slider(scroll_inner, "Movie Opacity", "backgroundMovieOpacity", 0.0, 1.0, resolution=0.01, decimals=4)

        self._config_var("backgroundMovieBlurAmount", tk.StringVar(value="0"))
        self._config_slider(scroll_inner, "Movie Blur Amount", "backgroundMovieBlurAmount", 0.0, 1.0, resolution=0.01, decimals=4)

        # ── Audio ───────────────────────────────────────────────
        self._config_section_label(scroll_inner, "Audio")

        self._config_var("audioMode", tk.StringVar(value="WASAPIShared"))
        self._config_dropdown(scroll_inner, "Audio Mode", "audioMode", ["DirectSound", "WASAPIShared", "WASAPIExclusive", "ASIO"])

        self._config_var("audioBufferSize", tk.StringVar(value="5"))
        self._config_slider(scroll_inner, "Audio Buffer Size", "audioBufferSize", 5, 200, resolution=1)

        self._config_var("masterVolume", tk.StringVar(value="50"))
        self._config_slider(scroll_inner, "Master Volume", "masterVolume", 0, 100, resolution=1)

        self._config_var("seVolume", tk.StringVar(value="100"))
        self._config_slider(scroll_inner, "SE Volume", "seVolume", 0, 100, resolution=1)

        self._config_var("musicVolume", tk.StringVar(value="100"))
        self._config_slider(scroll_inner, "Music Volume", "musicVolume", 0, 100, resolution=1)

        self._config_var("bgmVolume", tk.StringVar(value="100"))
        self._config_slider(scroll_inner, "BGM Volume", "bgmVolume", 0, 100, resolution=1)

        self._config_var("voiceVolume", tk.StringVar(value="100"))
        self._config_slider(scroll_inner, "Voice Volume", "voiceVolume", 0, 100, resolution=1)

        self._config_var("overallSoundOffset", tk.StringVar(value="0"))
        self._config_entry(scroll_inner, "Sound Offset (ms)", "overallSoundOffset")

        self._config_var("overallNotePositionOffset", tk.StringVar(value="0"))
        self._config_entry(scroll_inner, "Note Position Offset", "overallNotePositionOffset")

        self._config_var("inputDelay", tk.StringVar(value="0"))
        self._config_entry(scroll_inner, "Input Delay (ms)", "inputDelay")

        # ── Gameplay ────────────────────────────────────────────
        self._config_section_label(scroll_inner, "Gameplay")

        self._config_var("preloadFonts", tk.BooleanVar(value=True))
        self._config_checkbox(scroll_inner, "Preload Fonts", "preloadFonts")

        self._config_var("useDonchan", tk.BooleanVar(value=True))
        self._config_checkbox(scroll_inner, "Use Donchan", "useDonchan")

        self._config_var("clearNewSongOnPlay", tk.BooleanVar(value=True))
        self._config_checkbox(scroll_inner, "Clear New Song on Play", "clearNewSongOnPlay")

        self._config_var("animationStopInEnsoGame", tk.BooleanVar(value=False))
        self._config_checkbox(scroll_inner, "Stop Animation in Enso", "animationStopInEnsoGame")

        self._config_var("showJudgeFrameAfterimage", tk.BooleanVar(value=False))
        self._config_checkbox(scroll_inner, "Judge Frame Afterimage", "showJudgeFrameAfterimage")

        self._config_var("useNewResultAnimation", tk.BooleanVar(value=False))
        self._config_checkbox(scroll_inner, "New Result Animation", "useNewResultAnimation")

        self._config_var("includeGaidenInDanAssignmentFolder", tk.BooleanVar(value=False))
        self._config_checkbox(scroll_inner, "Include Gaiden in Dan", "includeGaidenInDanAssignmentFolder")

        self._config_status_var = tk.StringVar(value="")
        tk.Label(scroll_inner, textvariable=self._config_status_var, bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w", pady=(12, 0))

    def _config_var(self, key: str, var: tk.StringVar | tk.BooleanVar) -> None:
        self._config_vars[key] = var

    def _config_section_label(self, parent: tk.Frame, text: str) -> None:
        tk.Label(parent, text=text, bg=CARD, fg=ACCENT, font=FONT_SECTION).pack(anchor="w", pady=(16, 4))

    def _config_checkbox(self, parent: tk.Frame, label: str, key: str) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=2)
        var = self._config_vars[key]
        tk.Checkbutton(
            row, variable=var, bg=CARD, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, activeforeground=TEXT, highlightthickness=0,
        ).pack(side="left")
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT_BODY).pack(side="left", padx=(6, 0))

    def _config_entry(self, parent: tk.Frame, label: str, key: str) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT_BODY, width=28, anchor="w").pack(side="left")
        var = self._config_vars[key]
        ttk.Entry(row, textvariable=var, width=30).pack(side="left", padx=(8, 0))

    def _config_dropdown(self, parent: tk.Frame, label: str, key: str, values: list[str]) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT_BODY, width=28, anchor="w").pack(side="left")
        var = self._config_vars[key]
        cb = ttk.Combobox(row, textvariable=var, values=values, state="readonly", width=28)
        cb.pack(side="left", padx=(8, 0))

    def _config_slider(self, parent: tk.Frame, label: str, key: str, from_: float, to: float, resolution: float = 1, decimals: int = 0, no_limit: bool = False) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=CARD, fg=TEXT, font=FONT_BODY, width=28, anchor="w").pack(side="left")
        var = self._config_vars[key]

        canvas = tk.Canvas(row, bg=CARD, height=18, highlightthickness=0, bd=0)
        canvas.pack(side="left", fill="x", expand=True, padx=(8, 8))

        def _slider_value() -> float:
            try:
                return float(var.get())
            except (ValueError, TypeError):
                return from_

        def _get_width() -> int:
            return max(canvas.winfo_width(), 50)

        def _draw(value: float) -> None:
            canvas.delete("all")
            cw = _get_width()
            ch = 18
            pct = max(0.0, min(1.0, (value - from_) / (to - from_)))
            thumb_w = 16
            tx = int((cw - thumb_w) * pct)
            
            canvas.create_rectangle(0, 0, cw, ch, fill="#1f2937", outline="", tags="track")
            canvas.create_rectangle(tx, 0, tx + thumb_w, ch, fill=ACCENT, outline="", tags="thumb")
            
            text_val = f"{value:.{decimals}f}" if decimals > 0 else str(int(value))
            canvas.create_text(cw / 2, ch / 2, text=text_val, fill=TEXT, font=(FONT_FAMILY, 10, "bold"), tags="text")

        canvas.bind("<Configure>", lambda _: _draw(_slider_value()))

        def _update_var(value: float) -> None:
            if no_limit:
                value = max(from_, value)
            else:
                value = max(from_, min(to, value))
            if decimals > 0:
                var.set(f"{value:.{decimals}f}")
            else:
                var.set(str(int(value)))
            _draw(value)

        def _on_press(event):
            _on_drag(event)

        def _on_drag(event):
            cw = max(canvas.winfo_width(), 50)
            pct = max(0.0, min(1.0, event.x / cw))
            value = from_ + pct * (to - from_)
            if resolution > 0:
                value = round(value / resolution) * resolution
            _update_var(value)

        canvas.bind("<Button-1>", _on_press)
        canvas.bind("<B1-Motion>", _on_drag)

        self._config_slider_vars[key] = (_update_var, _draw)

    def _config_resolution(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Resolution", bg=CARD, fg=TEXT, font=FONT_BODY, width=28, anchor="w").pack(side="left")
        var = self._config_vars["resolution"]
        resolutions = ["1024x600", "1280x720", "1366x768", "1600x900", "1920x1080", "Custom"]
        cb = ttk.Combobox(row, textvariable=var, values=resolutions, width=28)
        cb.pack(side="left", padx=(8, 0))

        def _on_select(_event):
            if var.get() != "Custom":
                return
            dialog = tk.Toplevel(self)
            dialog.title("Custom Resolution")
            dialog.geometry("300x120")
            dialog.configure(bg=BG)
            dialog.transient(self)
            dialog.grab_set()
            inner = ttk.Frame(dialog, padding=16)
            inner.pack(fill="both", expand=True)
            ttk.Label(inner, text="Width:").grid(row=0, column=0, sticky="w", pady=4)
            w_var = tk.StringVar(value="1920")
            ttk.Entry(inner, textvariable=w_var, width=10).grid(row=0, column=1, pady=4)
            ttk.Label(inner, text="Height:").grid(row=1, column=0, sticky="w", pady=4)
            h_var = tk.StringVar(value="1080")
            ttk.Entry(inner, textvariable=h_var, width=10).grid(row=1, column=1, pady=4)

            def _confirm():
                try:
                    w = int(w_var.get())
                    h = int(h_var.get())
                    if w > 0 and h > 0:
                        var.set(f"{w}x{h}")
                        dialog.destroy()
                except ValueError:
                    pass

            ttk.Button(inner, text="OK", style="Accent.TButton", command=_confirm).grid(row=2, column=1, sticky="e", pady=(12, 0))

        cb.bind("<<ComboboxSelected>>", _on_select)

    def _load_system_config(self, silent: bool = False) -> None:
        try:
            exe_path = self.get_exe_path()
        except (ValueError, FileNotFoundError):
            self._config_status_var.set("Select game folder first")
            return
        config = read_system_config(exe_path)
        for key, var in self._config_vars.items():
            val = config.get(key)
            if val is None:
                continue
            if isinstance(var, tk.BooleanVar):
                var.set(bool(val))
            else:
                var.set(str(val))
            if key in self._config_slider_vars:
                try:
                    self._config_slider_vars[key][0](float(val))
                except (ValueError, TypeError):
                    pass
        self._config_status_var.set("Loaded")
        if not silent:
            show_toast(self, "Config loaded", "SystemConfig.json reloaded", "info")

    def _save_system_config(self) -> None:
        try:
            exe_path = self.get_exe_path()
        except (ValueError, FileNotFoundError):
            self._config_status_var.set("Select game folder first")
            return
        config = read_system_config(exe_path)
        for key, var in self._config_vars.items():
            if isinstance(var, tk.BooleanVar):
                config[key] = var.get()
            else:
                raw = var.get().strip()
                try:
                    config[key] = int(raw)
                except ValueError:
                    try:
                        config[key] = float(raw)
                    except ValueError:
                        config[key] = raw
        try:
            write_system_config(exe_path, config)
            self._config_status_var.set("Saved")
            show_toast(self, "Config saved", "SystemConfig.json written", "success")
        except Exception as exc:
            self._config_status_var.set(f"Save failed: {exc}")

    # ── Event Queue ─────────────────────────────────────────────

    def _queue_log(self, text: str) -> None:
        self.events.put(("log", text, ""))

    def _queue_state(self, running: bool) -> None:
        self.events.put(("state", running, ""))

    def _handle_updater_exit(self, return_code: int, updater_pid: int, stop_requested: bool) -> None:
        if stop_requested or return_code != 0 or updater_pid <= 0:
            return
        threading.Thread(
            target=self._watch_and_kill_game_launch,
            args=(updater_pid,),
            daemon=True,
        ).start()

    def _watch_and_kill_game_launch(self, updater_pid: int) -> None:
        deadline = time.monotonic() + PROCESS_KILL_TIMEOUT_SEC
        while time.monotonic() < deadline:
            child_pids = find_child_processes_by_name(updater_pid, WINDOWS_GAME_EXE_NAME)
            if child_pids:
                for pid in child_pids:
                    if kill_process(pid):
                        self._queue_log(f"[launcher] killed {WINDOWS_GAME_EXE_NAME} pid={pid}")
                    else:
                        self._queue_log(f"[launcher] failed to kill {WINDOWS_GAME_EXE_NAME} pid={pid}")
                return
            time.sleep(0.2)

    def _drain_events(self) -> None:
        try:
            for _ in range(50):
                kind, payload, extra = self.events.get_nowait()
                if kind == "log":
                    if self.updater_window:
                        self.updater_window.append_log(str(payload))
                elif kind == "state":
                    running = bool(payload)
                    self.status_var.set("Updater is running" if running else "Updater is stopped")
                    if self.updater_window:
                        self.updater_window.set_state(running)
                        if not running:
                            self.updater_window.destroy()
                            self.updater_window = None
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _ensure_updater_window(self) -> None:
        if self.updater_window and self.updater_window.window.winfo_exists():
            self.updater_window.show()
            return
        self.updater_window = UpdaterWindow(self)
        self.updater_window.show()

    # ── State Loading ───────────────────────────────────────────

    def _load_saved_state(self) -> None:
        state = load_launcher_state()
        saved_path = str(state.get("exePath") or "").strip()
        if saved_path and Path(saved_path).exists():
            p = Path(saved_path)
            if p.suffix.lower() == ".exe":
                p = p.parent
            self.exe_path_var.set(str(p))
            self.current_root_var.set(f"Game root: {p.resolve()}")
            self.refresh_all(silent=True)
            self.after(100, lambda: self._load_system_config(silent=True))

        self.launcher_version = str(state.get("launcherVersion") or "")
        saved_zip = state.get("zipExtractPath")
        if saved_zip:
            self.zip_extract_var.set(str(saved_zip))

        geometry = state.get("geometry")
        if geometry:
            try:
                self.geometry(geometry)
            except Exception:
                pass

    # ── Update Check ────────────────────────────────────────────

    def _show_update_prompt(self, release: ReleaseInfo) -> None:
        current_version = self.launcher_version or APP_VERSION

        window = tk.Toplevel(self)
        window.title(f"Update Available: {release.version}")
        window.geometry("540x280")
        window.configure(bg=BG)
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()

        outer = ttk.Frame(window, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Update Available", font=(FONT_FAMILY, 14, "bold")).pack(anchor="w")
        text = (
            f"A new version is available: {normalize_version_label(release.version)}\n"
            f"Your current version: {normalize_version_label(current_version)}\n\n"
            f"Would you like to download and install the update?"
        )
        ttk.Label(outer, text=text, justify="left").pack(anchor="w", pady=(12, 0))

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(24, 0))
        ttk.Button(
            button_row, text=f"Download {normalize_version_label(release.version)}",
            style="Accent.TButton",
            command=lambda: self._download_and_apply_update_release(release, window),
        ).pack(side="left")
        ttk.Button(
            button_row, text="Remind me later",
            style="Ghost.TButton",
            command=window.destroy,
        ).pack(side="left", padx=8)

    def _download_and_apply_update_release(self, release: ReleaseInfo, prompt_window: tk.Toplevel) -> None:
        workspace_root = Path(tempfile.mkdtemp(prefix="taikonauts_update_"))
        window = UpdateDownloadWindow(self, release)
        result: dict[str, object] = {"path": None, "error": None}

        def worker() -> None:
            try:
                def progress(downloaded: int, total: int) -> None:
                    window.set_progress(downloaded, total)

                window.set_status("Starting download")
                downloaded_path = download_release_asset(release, workspace_root, progress)
                result["path"] = downloaded_path
                self.after(0, lambda: window.finish(downloaded_path=downloaded_path))
            except Exception as exc:
                result["error"] = str(exc)
                self.after(0, lambda: window.finish(error=str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.wait_window(window.window)

        if result["error"]:
            raise RuntimeError(str(result["error"]))
        downloaded_path = result["path"]
        if not isinstance(downloaded_path, Path):
            raise RuntimeError("Update download did not complete.")

        if downloaded_path.suffix.lower() != ".zip" or not zipfile.is_zipfile(downloaded_path):
            raise ValueError(f"Update asset is not a ZIP file: {downloaded_path.name}")

        extracted_root = extract_zip_archive(downloaded_path, workspace_root / "extracted")
        payload_root = select_payload_root(extracted_root)
        restart_exe = str(Path(sys.executable).resolve()) if getattr(sys, "frozen", False) else ""

        manifest = {
            "parent_pid": os.getpid(),
            "payload_root": str(payload_root),
            "target_root": str(APP_DIR),
            "restart_exe": restart_exe,
            "workspace_root": str(workspace_root),
        }
        manifest_path = workspace_root / "update_manifest.json"
        safe_write_json(manifest_path, manifest)

        self.status_var.set(f"Applying update: {downloaded_path.name}")

        prompt_window.destroy()

        try:
            if getattr(sys, "frozen", False):
                helper_exe = APP_DIR / "LauncherUpdater.exe"
                if helper_exe.exists():
                    cmd = [str(helper_exe), "--apply-update", str(manifest_path)]
                else:
                    raise FileNotFoundError(f"Updater not found: {helper_exe}")
            else:
                helper_script = APP_DIR / "launcher_updater.py"
                cmd = [sys.executable, str(helper_script), "--apply-update", str(manifest_path)]

            subprocess.Popen(cmd, cwd=str(APP_DIR))
        except Exception:
            shutil.rmtree(workspace_root, ignore_errors=True)
            raise

        self.save_current_state()
        self.after(0, self.destroy)

    def _update_updater_btn(self) -> None:
        raw = self.exe_path_var.get().strip()
        if raw and (Path(raw) / WINDOWS_GAME_EXE_NAME).exists():
            self._updater_btn.config(text="⬆  Launch Updater", command=self.start_updater)
        else:
            self._updater_btn.config(text="⬇  Install Game", command=self._install_game)

    def _install_game(self) -> None:
        try:
            raw = self.exe_path_var.get().strip()
            if not raw:
                raise ValueError("Select a game folder first")
            dest = Path(raw)
            dest.mkdir(parents=True, exist_ok=True)

            self.status_var.set("Downloading game...")

            import urllib.request
            download_req = urllib.request.Request(
                GAME_BOOTSTRAP_URL,
                headers={"User-Agent": "TaikoNautsLauncher/1.0"},
            )
            zip_path = dest / "TaikoNauts-latest.zip"
            with urllib.request.urlopen(download_req, timeout=120) as resp:
                with zip_path.open("wb") as f:
                    shutil.copyfileobj(resp, f)

            self.status_var.set("Extracting game...")
            self.update_idletasks()

            extract_zip_archive(zip_path, dest)
            zip_path.unlink(missing_ok=True)

            exe_found = list(dest.rglob(WINDOWS_GAME_EXE_NAME))
            if exe_found:
                game_root = exe_found[0].resolve().parent
                self.exe_path_var.set(str(game_root))
                self.current_root_var.set(f"Game root: {game_root}")

            self.status_var.set("Game installed")
            self._updater_btn.config(text="⬆  Launch Updater", command=self.start_updater)
            self.start_updater()
        except Exception as exc:
            show_toast(self, "Install error", str(exc), "error")
            self.status_var.set("Install failed")

    def _browse_zip_extract(self) -> None:
        try:
            exe_path = self.get_exe_path()
            default = exe_path.parent / self.zip_extract_var.get()
        except Exception:
            default = Path(self.zip_extract_var.get())
        selected = filedialog.askdirectory(
            title="Select extract target folder",
            initialdir=str(default.parent) if default.parent.exists() else None,
        )
        if selected:
            try:
                exe_path = self.get_exe_path()
                rel = Path(selected).resolve().relative_to(exe_path.parent.resolve())
                self.zip_extract_var.set(str(rel).replace("\\", "/"))
            except (ValueError, FileNotFoundError):
                self.zip_extract_var.set(selected)

    # ── State Persistence ───────────────────────────────────────

    def save_current_state(self) -> None:
        exe_path = self.exe_path_var.get().strip()
        geometry = self.geometry()
        save_launcher_state(exe_path, geometry, APP_VERSION, self.zip_extract_var.get())

    def _on_close(self) -> None:
        try:
            self.save_current_state()
        except Exception:
            pass
        self.destroy()

    # ── Drag & Drop ─────────────────────────────────────────────

    def _enable_file_drop(self) -> None:
        if os.name != "nt":
            return
        self.update_idletasks()
        hwnd = wintypes.HWND(self.winfo_id())
        shell32.DragAcceptFiles(hwnd, True)

        original_wndproc = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
        if not original_wndproc:
            return

        self._drop_old_wndproc = ctypes.c_void_p(original_wndproc)

        def _wndproc(window, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                self._handle_dropfiles(wparam)
                return 0
            return user32.CallWindowProcW(self._drop_old_wndproc, window, msg, wparam, lparam)

        self._drop_wndproc_ref = CFUNCTYPE_WNDPROC(_wndproc)
        user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, self._drop_wndproc_ref)

    def _widget_client_rect(self, widget) -> tuple[int, int, int, int]:
        x = 0
        y = 0
        width = widget.winfo_width()
        height = widget.winfo_height()
        current = widget
        while True:
            x += current.winfo_x()
            y += current.winfo_y()
            if current.master is self:
                break
            current = current.master
        return x, y, x + width, y + height

    def _point_in_zip_drop_zone(self, x: int, y: int) -> bool:
        if not self.zip_drop_zone or not self.zip_drop_zone.winfo_exists():
            return False
        left, top, right, bottom = self._widget_client_rect(self.zip_drop_zone)
        return left <= x < right and top <= y < bottom

    def _handle_dropfiles(self, hdrop) -> None:
        if os.name != "nt":
            return

        drop_point = wintypes.POINT()
        inside_zone = bool(shell32.DragQueryPoint(hdrop, ctypes.byref(drop_point)))
        try:
            if not inside_zone:
                self.zip_status_var.set("Drop ZIP files onto the ZIP area")
                return
            if not self._point_in_zip_drop_zone(drop_point.x, drop_point.y):
                self.zip_status_var.set("Drop ZIP files onto the ZIP area")
                return

            count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
            dropped_paths: list[Path] = []
            for index in range(count):
                length = shell32.DragQueryFileW(hdrop, index, None, 0) + 1
                buffer = ctypes.create_unicode_buffer(length)
                shell32.DragQueryFileW(hdrop, index, buffer, length)
                dropped_paths.append(Path(buffer.value))

            for path in dropped_paths:
                if path.suffix.lower() != ".zip":
                    continue
                try:
                    exe_path = self.get_exe_path()
                    target = extract_zip_to_songs(exe_path, path, self.zip_extract_var.get())
                    self.skin_message_var.set(f"Extracted {path.name} -> {target}")
                    self.zip_status_var.set(f"Extracted {path.name}")
                    show_toast(self, "Done", f"Extracted:\n{path.name}\n->\n{target}", "success")
                except Exception as exc:
                    show_toast(self, "ZIP extract error", f"{path}\n\n{exc}", "error")
        finally:
            shell32.DragFinish(hdrop)

    def clear_extracted_zip_folder(self) -> None:
        try:
            exe_path = self.get_exe_path()
        except Exception as exc:
            show_toast(self, "ZIP folder", str(exc), "error")
            return

        game_root = resolve_game_root(exe_path)
        target_dir = game_root / self.zip_extract_var.get()
        if not confirm_toast(
            self,
            "Confirm cleanup",
            f"Delete everything in this folder except box.def?\n\n{target_dir}",
        ):
            return

        try:
            target = clear_zip_folder_keep_box_def(exe_path, self.zip_extract_var.get())
            self.zip_status_var.set(f"Cleared {target}")
            show_toast(self, "Done", f"Cleared extracted folder:\n{target}", "success", key="clear-zip")
        except Exception as exc:
            show_toast(self, "ZIP folder cleanup error", str(exc), "error", key="clear-zip")

    # ── Game Actions ────────────────────────────────────────────

    def select_exe(self) -> None:
        selected = filedialog.askdirectory(
            title="Select TaikoNauts game folder",
        )
        if selected:
            self.exe_path_var.set(selected)
            self.current_root_var.set(f"Game root: {Path(selected).resolve()}")
            try:
                save_launcher_state(selected)
            except Exception:
                pass
            self.refresh_all()
            self._update_updater_btn()

    def get_exe_path(self) -> Path:
        raw = self.exe_path_var.get().strip()
        if not raw:
            raise ValueError("Game folder is not set")
        root = Path(raw)
        if not root.exists():
            raise FileNotFoundError(f"Game folder not found: {root}")
        exe_path = root / WINDOWS_GAME_EXE_NAME
        if not exe_path.exists():
            raise FileNotFoundError(f"Game executable not found: {exe_path}")
        return exe_path

    def refresh_all(self, silent: bool = False) -> None:
        try:
            self.refresh_skins(silent=silent)
            raw = self.exe_path_var.get().strip()
            if raw and Path(raw).exists():
                self.current_root_var.set(f"Game root: {Path(raw).resolve()}")
            else:
                self.current_root_var.set("Game root not selected")
            self.status_var.set("Ready")
            self._update_updater_btn()
            if not silent:
                show_toast(self, "Refreshed", "Game info and skins reloaded", "success")
        except Exception as exc:
            show_toast(self, "Refresh error", str(exc), "error")

    def refresh_skins(self, silent: bool = False) -> None:
        try:
            exe_path = self.get_exe_path()
        except (ValueError, FileNotFoundError):
            self.skins = []
            self.skin_map.clear()
            for item in self.skin_tree.get_children():
                self.skin_tree.delete(item)
            self.skin_message_var.set("Select game folder")
            self.skin_count_var.set("0 skins")
            return
        self.skins = discover_skins(exe_path)
        self.skin_map.clear()

        for item in self.skin_tree.get_children():
            self.skin_tree.delete(item)

        current_skin = ""
        try:
            config = read_game_config(exe_path)
            current_skin = str(config.get("skinPath") or "")
        except Exception:
            current_skin = ""

        current_skin_path = resolve_skin_path(resolve_game_root(exe_path), current_skin) if current_skin else None

        for skin in self.skins:
            item_id = self.skin_tree.insert(
                "",
                "end",
                values=(skin.name, skin.version, skin.skin_path_value, skin.description),
            )
            self.skin_map[item_id] = skin
            if current_skin_path and skin.folder.resolve() == current_skin_path.resolve():
                self.skin_tree.selection_set(item_id)
                self.skin_tree.see(item_id)

        if not self.skins:
            self.skin_message_var.set("No skins found")
            self.skin_count_var.set("0 skins")
        else:
            self.skin_message_var.set(f"Loaded {len(self.skins)} skins")
            self.skin_count_var.set(f"{len(self.skins)} skins")
            if not silent:
                show_toast(self, "Skins reloaded", f"{len(self.skins)} skins found", "success")

    def _on_skin_select(self, _event=None) -> None:
        selection = self.skin_tree.selection()
        if not selection:
            return
        skin = self.skin_map.get(selection[0])
        if skin:
            self.skin_message_var.set(f"Selected: {skin.name}")

    def apply_selected_skin(self) -> None:
        try:
            exe_path = self.get_exe_path()
        except (ValueError, FileNotFoundError) as exc:
            show_toast(self, "Error", str(exc), "error")
            return
        selection = self.skin_tree.selection()
        if not selection:
            show_toast(self, "No selection", "Select a skin first", "warning")
            return
        skin = self.skin_map.get(selection[0])
        if not skin:
            show_toast(self, "Error", "Selected skin not found", "error")
            return

        config = read_game_config(exe_path)
        config["skinPath"] = skin.skin_path_value
        write_game_config(exe_path, config)
        self.skin_message_var.set(f"skinPath updated: {skin.skin_path_value}")
        show_toast(self, "Done", f"skinPath updated:\n{skin.skin_path_value}", "success")

    def launch_game(self) -> None:
        try:
            exe_path = self.get_exe_path()
            save_launcher_state(str(self.exe_path_var.get().strip()))
            subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))
            self.status_var.set("Game launched")
        except Exception as exc:
            show_toast(self, "Launch error", str(exc), "error")

    def start_updater(self) -> None:
        try:
            config_window = UpdaterConfigWindow(self)
            config = config_window.show()
            if config is None:
                return

            raw = self.exe_path_var.get().strip()
            if not raw:
                raise ValueError("Game folder is not set")
            game_root = Path(raw)
            if not game_root.exists():
                raise FileNotFoundError(f"Game folder not found: {game_root}")
            exe_path = game_root / WINDOWS_GAME_EXE_NAME
            save_launcher_state(str(raw))
            if self.updater_session and self.updater_session.process and self.updater_session.process.poll() is None:
                self._ensure_updater_window()
                show_toast(self, "Updater", "Updater is already running", "warning")
                return

            self._ensure_updater_window()
            self.updater_session = UpdaterSession(
                exe_path,
                self._queue_log,
                self._queue_state,
                self._handle_updater_exit,
                config,
            )
            self.updater_session.start()
            self._queue_log("[launcher] updater started")
        except Exception as exc:
            show_toast(self, "Updater error", str(exc), "error")


    def stop_updater(self) -> None:
        if self.updater_session:
            self.updater_session.stop()
            self._queue_log("[launcher] stop requested")


def main() -> int:
    app = LauncherApp()
    splash = SplashScreen(app)

    def show_main() -> None:
        splash.close()
        app.deiconify()
        app.lift()
        app.update_idletasks()
        app.focus_force()
        threading.Thread(
            target=lambda: _check_update_background(app),
            daemon=True,
        ).start()

    def _check_update_background(app: LauncherApp) -> None:
        release = fetch_latest_release()
        if release and is_version_newer(release.version, APP_VERSION):
            app.after(0, lambda: app._show_update_prompt(release))

    app.after(SPLASH_DURATION_MS, show_main)
    app.mainloop()
    return 0
