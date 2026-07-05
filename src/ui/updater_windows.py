from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ui.app import LauncherApp

from src.ui.styles import (
    BG, PANEL, TEXT, MUTED, ACCENT,
    CARD, FONT_FAMILY, FONT_BODY, FONT_HEADING,
    PANEL_ALT,
)
from src.core.utils import ReleaseInfo


class UpdaterConfigWindow:
    def __init__(self, parent: tk.Tk) -> None:
        self.parent = parent
        self.result: dict[str, bool] | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Updater Configuration")
        self.window.geometry("480x220")
        self.window.configure(bg=BG)
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        outer = ttk.Frame(self.window, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Updater Configuration", font=(FONT_FAMILY, 14, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Choose how the updater handles each prompt.").pack(anchor="w", pady=(4, 12))

        self.overwrite_exe = tk.BooleanVar(value=True)
        frame1 = ttk.Frame(outer)
        frame1.pack(fill="x", pady=(0, 6))
        tk.Checkbutton(
            frame1, variable=self.overwrite_exe, bg=BG, fg=TEXT,
            selectcolor=PANEL, activebackground=BG, activeforeground=TEXT,
            highlightthickness=0,
        ).pack(side="left")
        ttk.Label(frame1, text='Overwrite existing "TaikoNauts.exe"').pack(side="left", padx=(6, 0))

        self.overwrite_skin = tk.BooleanVar(value=True)
        frame2 = ttk.Frame(outer)
        frame2.pack(fill="x", pady=(0, 16))
        tk.Checkbutton(
            frame2, variable=self.overwrite_skin, bg=BG, fg=TEXT,
            selectcolor=PANEL, activebackground=BG, activeforeground=TEXT,
            highlightthickness=0,
        ).pack(side="left")
        ttk.Label(frame2, text='Overwrite "SimpleStyle" skin files').pack(side="left", padx=(6, 0))

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x")
        ttk.Button(button_row, text="Start Updater", style="Accent.TButton", command=self._confirm).pack(side="left")
        ttk.Button(button_row, text="Cancel", style="Ghost.TButton", command=self._cancel).pack(side="left", padx=8)

    def _confirm(self) -> None:
        self.result = {
            "overwrite_exe": self.overwrite_exe.get(),
            "overwrite_skin": self.overwrite_skin.get(),
        }
        self.window.grab_release()
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.grab_release()
        self.window.destroy()

    def show(self) -> dict[str, bool] | None:
        self.parent.wait_window(self.window)
        return self.result


class UpdaterWindow:
    def __init__(self, app: "LauncherApp") -> None:
        self.app = app
        self.window = tk.Toplevel(app)
        self.window.title("Updater")
        self.window.geometry("860x540")
        self.window.minsize(760, 460)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_var = tk.StringVar(value="Updater is stopped")
        self._log_lines: list[str] = []
        self._flush_scheduled = False
        self._line_count = 0

        root = ttk.Frame(self.window, padding=12)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        ttk.Label(header, text="Updater", font=(FONT_FAMILY, 16, "bold")).pack(anchor="w")
        ttk.Label(header, textvariable=self.status_var, foreground=MUTED).pack(anchor="w", pady=(4, 0))

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", pady=(10, 0))
        ttk.Button(toolbar, text="Clear log", style="Ghost.TButton", command=self.clear_log).pack(side="left")
        ttk.Button(toolbar, text="Stop", style="Danger.TButton", command=self.app.stop_updater).pack(side="left", padx=8)

        log_frame = tk.Frame(root, bg=PANEL_ALT)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))

        self.log_listbox = tk.Listbox(
            log_frame, bg=PANEL_ALT, fg=TEXT,
            font=(FONT_FAMILY, 9), selectbackground=ACCENT,
            selectforeground="#ffffff", relief="flat",
            highlightthickness=0, borderwidth=0,
            activestyle="none",
        )
        self.log_listbox.pack(side="left", fill="both", expand=True)

        log_scrollbar = tk.Scrollbar(log_frame, orient="vertical", command=self.log_listbox.yview)
        log_scrollbar.pack(side="right", fill="y")
        self.log_listbox.configure(yscrollcommand=log_scrollbar.set)

    def _on_close(self) -> None:
        self.window.withdraw()

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def destroy(self) -> None:
        if self._flush_scheduled:
            self.window.after_cancel(self._flush_scheduled)
            self._flush_scheduled = False
        if self._log_lines:
            self._flush_log()
        if self.window.winfo_exists():
            self.window.destroy()

    MAX_LOG_LINES = 1000

    def append_log(self, text: str) -> None:
        self._log_lines.append(text)
        if not self._flush_scheduled:
            self._flush_scheduled = self.window.after(50, self._flush_log)

    def _flush_log(self) -> None:
        self._flush_scheduled = False
        if not self._log_lines:
            return
        self.log_listbox.configure(state="normal")
        batch = "".join(self._log_lines)
        self._log_lines.clear()
        lines = batch.splitlines(keepends=False)
        for line in lines:
            self.log_listbox.insert("end", line)
        self._line_count += len(lines)
        if self._line_count > self.MAX_LOG_LINES:
            excess = self._line_count - int(self.MAX_LOG_LINES * 0.8)
            self.log_listbox.delete(0, excess - 1)
            self._line_count -= excess
        self.log_listbox.see("end")

    def set_state(self, running: bool) -> None:
        self.status_var.set("Updater is running" if running else "Updater is stopped")

    def clear_log(self) -> None:
        self.log_listbox.delete(0, "end")
        self._line_count = 0


class UpdateDownloadWindow:
    def __init__(self, parent: tk.Tk, release: ReleaseInfo) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title(f"Downloading {release.version}")
        self.window.geometry("460x180")
        self.window.configure(bg=BG)
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        outer = ttk.Frame(self.window, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Downloading Update", font=(FONT_FAMILY, 14, "bold")).pack(anchor="w")
        self.status_label = ttk.Label(outer, text="Starting...", foreground=MUTED)
        self.status_label.pack(anchor="w", pady=(8, 0))

        self.progress_bar = ttk.Progressbar(outer, mode="determinate", length=380)
        self.progress_bar.pack(fill="x", pady=(16, 0))

        self.size_label = ttk.Label(outer, text="", foreground=MUTED)
        self.size_label.pack(anchor="w", pady=(4, 0))

    def set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    def set_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = min(downloaded / total * 100, 100)
            self.progress_bar["value"] = pct
            self.size_label.config(
                text=f"{downloaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB"
            )
        else:
            self.progress_bar["value"] = 0

    def finish(self, downloaded_path: Path | None = None, error: str | None = None) -> None:
        self.window.grab_release()
        self.window.destroy()
