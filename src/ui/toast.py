from __future__ import annotations

import tkinter as tk
from typing import Literal

from .styles import *

TOAST_WIDTH = 360
TOAST_GAP = 10
PAD = 14
_duration_map: dict[str, int] = dict(info=3500, success=3000, warning=4000, error=5000)
_color_map: dict[str, str] = dict(info=ACCENT, success=SUCCESS, warning=WARNING, error=ERROR)


class ToastNotification(tk.Toplevel):
    instances: list[ToastNotification] = []
    _keyed: dict[str, ToastNotification] = {}

    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        message: str,
        toast_type: Literal["info", "success", "warning", "error"] = "info",
        duration: int | None = None,
        key: str | None = None,
    ):
        super().__init__(parent)
        self._parent = parent
        self._toast_type = toast_type
        self._duration = duration if duration is not None else _duration_map.get(toast_type, 3500)
        self._dying = False
        self._animating = False
        self._key = key

        if key is not None:
            old = ToastNotification._keyed.get(key)
            if old is not None and old.winfo_exists():
                old._close_immediate()
            ToastNotification._keyed[key] = self

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        accent_color = _color_map.get(toast_type, ACCENT)

        outer = tk.Frame(self, bg=CARD)
        outer.pack(fill="both", expand=True)

        inner = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1, padx=0, pady=0)
        inner.pack(fill="both", expand=True)

        accent_bar = tk.Frame(inner, bg=accent_color, width=4)
        accent_bar.pack(side="left", fill="y")

        body = tk.Frame(inner, bg=CARD, padx=14, pady=14)
        body.pack(side="left", fill="both", expand=True)

        header = tk.Frame(body, bg=CARD)
        header.pack(fill="x")

        tk.Label(header, text=title, anchor="w", font=FONT_SECTION, bg=CARD, fg=accent_color).pack(side="left")
        close_btn = tk.Label(header, text="✕", font=FONT_BODY, bg=CARD, fg=MUTED, cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._close_ani())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg=TEXT))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=MUTED))

        tk.Label(body, text=message, anchor="w", justify="left", wraplength=TOAST_WIDTH - PAD * 2 - 50,
                 font=FONT_BODY, bg=CARD, fg=TEXT_SECONDARY).pack(fill="x", pady=(4, 0))

        self.update_idletasks()
        self._snap_position()
        self._bind_configure()

        self.attributes("-alpha", 0.0)
        self._animating = True
        ToastNotification.instances.append(self)
        self._fade_in()

    # ── screen helpers ────────────────────────────────────────────
    def _parent_scr_x(self) -> int:
        return self._parent.winfo_rootx()

    def _parent_scr_y(self) -> int:
        return self._parent.winfo_rooty()

    def _compute_position(self) -> None:
        ToastNotification.instances = [t for t in ToastNotification.instances if t.winfo_exists()]
        pw = self._parent.winfo_width()
        ph = self._parent.winfo_height()
        px = self._parent_scr_x()
        py = self._parent_scr_y()
        tw = self.winfo_reqwidth()
        th = self.winfo_reqheight()
        y = py + TOAST_GAP
        for t in ToastNotification.instances:
            if t is not self:
                y += t.winfo_height() + TOAST_GAP
        x = px + pw - tw - TOAST_GAP
        if y + th > py + ph:
            y = py + TOAST_GAP
        self._toast_x = x
        self._toast_y = y

    def _snap_position(self) -> None:
        self._compute_position()
        self.geometry(f"+{self._toast_x}+{self._toast_y}")

    # ── parent tracking ──────────────────────────────────────────
    def _bind_configure(self) -> None:
        self._configure_bid = self._parent.bind("<Configure>", self._on_parent_configure, add="+")

    def _unbind_configure(self) -> None:
        try:
            self._parent.unbind("<Configure>", self._configure_bid)
        except (tk.TclError, AttributeError):
            pass

    def _on_parent_configure(self, _event: tk.Event | None = None) -> None:
        if self._animating or self._dying:
            return
        if not self.winfo_exists():
            return
        self._snap_position()

    # ── animation ────────────────────────────────────────────────
    def _fade_in(self) -> None:
        def _step(i: int) -> None:
            if not self.winfo_exists():
                return
            frac = (i + 1) / 8
            try:
                self.attributes("-alpha", frac)
            except tk.TclError:
                return
            if i + 1 < 8:
                self.after(20, lambda i=i + 1: _step(i))
            else:
                self._animating = False
                self._schedule_dismiss()

        _step(0)

    def _schedule_dismiss(self) -> None:
        if not self._dying:
            self.after(self._duration, self._close_ani)

    def _close_immediate(self) -> None:
        self._dying = True
        self._animating = True
        self._unbind_configure()
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _close_ani(self) -> None:
        if self._dying:
            return
        self._dying = True
        self._animating = True
        self._unbind_configure()
        self._fade_out()

    def _fade_out(self) -> None:
        def _step(i: int) -> None:
            if not self.winfo_exists():
                return
            frac = 1.0 - (i + 1) / 6
            try:
                self.attributes("-alpha", max(0.0, frac))
            except tk.TclError:
                return
            if i + 1 < 6:
                self.after(30, lambda i=i + 1: _step(i))
            else:
                self._destroy_self()

        _step(0)

    def _destroy_self(self) -> None:
        try:
            ToastNotification.instances = [t for t in ToastNotification.instances if t is not self]
            if self._key is not None:
                ToastNotification._keyed.pop(self._key, None)
            self.destroy()
        except tk.TclError:
            pass


def show_toast(
    parent: tk.Tk,
    title: str,
    message: str,
    toast_type: Literal["info", "success", "warning", "error"] = "info",
    duration: int | None = None,
    key: str | None = None,
) -> ToastNotification:
    return ToastNotification(parent, title, message, toast_type, duration, key=key)


def confirm_toast(
    parent: tk.Tk,
    title: str,
    message: str,
) -> bool:
    win = tk.Toplevel(parent)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.resizable(False, False)

    outer = tk.Frame(win, bg=CARD)
    outer.pack(fill="both", expand=True)

    inner = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1, padx=0, pady=0)
    inner.pack(fill="both", expand=True)

    tk.Frame(inner, bg=ACCENT, width=4).pack(side="left", fill="y")

    body = tk.Frame(inner, bg=CARD, padx=16, pady=14)
    body.pack(side="left", fill="both", expand=True)

    tk.Label(body, text=title, anchor="w", font=FONT_HEADING, bg=CARD, fg=TEXT).pack(fill="x")
    tk.Label(body, text=message, anchor="w", justify="left", wraplength=320,
             font=FONT_BODY, bg=CARD, fg=TEXT_SECONDARY).pack(fill="x", pady=(6, 14))

    btn_frame = tk.Frame(body, bg=CARD)
    btn_frame.pack(fill="x")

    result: tk.Variable = tk.BooleanVar(value=False)

    def _done(val: bool) -> None:
        result.set(val)
        try:
            parent.unbind("<Configure>", bid)
        except (tk.TclError, AttributeError):
            pass
        win.destroy()

    tk.Button(btn_frame, text="Cancel", font=FONT_BODY, bg=PANEL_ALT, fg=TEXT,
              activebackground=CARD_HOVER, activeforeground=TEXT,
              bd=0, padx=18, pady=6, cursor="hand2",
              command=lambda: _done(False)).pack(side="right", padx=(6, 0))
    tk.Button(btn_frame, text="Yes", font=(FONT_FAMILY, 10, "bold"), bg=ACCENT_SOFT, fg="#ffffff",
              activebackground=ACCENT, activeforeground="#ffffff",
              bd=0, padx=18, pady=6, cursor="hand2",
              command=lambda: _done(True)).pack(side="right")

    def _repos() -> None:
        if not win.winfo_exists():
            return
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        ww = win.winfo_reqwidth()
        wh = win.winfo_reqheight()
        x = px + pw - ww - TOAST_GAP
        y = py + TOAST_GAP
        win.geometry(f"+{x}+{y}")

    win.update_idletasks()
    bid = parent.bind("<Configure>", lambda e: _repos(), add="+")
    _repos()
    win.attributes("-alpha", 0.0)
    win.wait_visibility()

    for i in range(8):
        frac = (i + 1) / 8
        try:
            win.attributes("-alpha", frac)
        except tk.TclError:
            break
        win.update()
        win.after(20)
    win.attributes("-alpha", 1.0)

    win.wait_variable(result)
    return result.get()
