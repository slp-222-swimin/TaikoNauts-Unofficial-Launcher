from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.ui.styles import (
    BG, PANEL, TEXT, MUTED, ACCENT, ACCENT_SOFT,
    FONT_FAMILY,
)


class SplashScreen:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.configure(bg=BG)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.0)

        width = 560
        height = 300
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 0)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

        outer = tk.Frame(self.window, bg=BG, bd=0, highlightthickness=2, highlightbackground=ACCENT_SOFT)
        outer.pack(fill="both", expand=True)

        inner = tk.Frame(outer, bg=PANEL, bd=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        self.title = tk.Label(
            inner,
            text="TaikøNauts UNOFFL Launcher",
            bg=PANEL,
            fg=PANEL,
            font=(FONT_FAMILY, 22, "bold"),
        )
        self.title.pack(anchor="w", padx=28, pady=(32, 8))

        self.subtitle = tk.Label(
            inner,
            text="Preparing launcher workspace...",
            bg=PANEL,
            fg=PANEL,
            font=(FONT_FAMILY, 10),
        )
        self.subtitle.pack(anchor="w", padx=28)

        self.progress = ttk.Progressbar(inner, mode="indeterminate", length=380)
        self.progress.pack(anchor="w", padx=28, pady=(36, 12))
        self.progress.start(12)

        self.footer = tk.Label(
            inner,
            text="Loading game path, skins, and updater hooks.",
            bg=PANEL,
            fg=PANEL,
            font=(FONT_FAMILY, 9),
        )
        self.footer.pack(anchor="w", padx=28)

        self._fade_steps = 34
        self._fade_step = 0
        self.window.after(50, self._animate)

    def _hex_to_rgb(self, value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(self, rgb: tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def _blend(self, start: str, end: str, ratio: float) -> str:
        sr, sg, sb = self._hex_to_rgb(start)
        er, eg, eb = self._hex_to_rgb(end)
        rr = int(sr + (er - sr) * ratio)
        rg = int(sg + (eg - sg) * ratio)
        rb = int(sb + (eb - sb) * ratio)
        return self._rgb_to_hex((rr, rg, rb))

    def _animate(self) -> None:
        if not self.window.winfo_exists():
            return

        ratio = min(self._fade_step / max(self._fade_steps, 1), 1.0)
        eased = ratio * ratio * (3 - 2 * ratio)

        self.window.attributes("-alpha", 0.12 + (0.88 * eased))
        self.title.configure(fg=self._blend(PANEL, TEXT, eased))
        self.subtitle.configure(fg=self._blend(PANEL, MUTED, eased))
        self.footer.configure(fg=self._blend(PANEL, MUTED, eased))

        if self._fade_step < self._fade_steps:
            self._fade_step += 1
            self.window.after(55, self._animate)

    def close(self) -> None:
        if self.progress:
            self.progress.stop()
        if self.window.winfo_exists():
            self.window.destroy()
