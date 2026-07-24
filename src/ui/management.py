from __future__ import annotations

import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.core.management import (
    resolve_song_root, scan_boxes, scan_dan_categories,
    extract_to_folder, ensure_box_def,
)
from src.core.utils import resolve_game_root
from src.ui.styles import (
    BG, BG_ELEVATED, PANEL, PANEL_ALT, CARD, CARD_HOVER,
    TEXT, TEXT_SECONDARY, MUTED, ACCENT, ACCENT_SOFT, ACCENT_GLOW,
    BORDER, SUCCESS, ERROR,
    FONT_FAMILY, FONT_HEADING, FONT_SECTION, FONT_BODY, FONT_SMALL, FONT_TINY,
)
from src.native.win32 import shell32, user32, WM_DROPFILES, GWL_WNDPROC, CFUNCTYPE_WNDPROC
import ctypes
from ctypes import wintypes


class ManagementWindow:
    def __init__(self, app, exe_path: Path) -> None:
        self.app = app
        self.exe_path = exe_path
        self.game_root = resolve_game_root(exe_path)
        self.song_root = resolve_song_root(exe_path)

        self.window = tk.Toplevel(app)
        self.window.title("Song / Dan Management")
        self.window.geometry("860x640")
        self.window.configure(bg=BG)
        self.window.transient(app)
        self.window.grab_set()

        self._drop_wndproc_ref = None
        self._drop_old_wndproc = None
        self._current_folder: Path | None = None

        self._boxes_cache: list | None = None
        self._categories_cache: list | None = None
        self._scan_thread: threading.Thread | None = None
        self._scan_cancel = False

        self._build_ui()
        self._enable_file_drop()
        self._refresh()

    def _build_ui(self) -> None:
        header = ttk.Frame(self.window, padding=(16, 12, 16, 4))
        header.pack(fill="x")
        ttk.Label(
            header, text="Song / Dan Management",
            font=(FONT_FAMILY, 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header, text="Browse songs, dan courses, and import beatmap files.",
            foreground=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        toolbar = tk.Frame(self.window, bg=BG)
        toolbar.pack(fill="x", padx=16, pady=(8, 0))
        ttk.Button(toolbar, text="🔄 Refresh", style="Ghost.TButton", command=self._refresh).pack(side="left")
        ttk.Button(toolbar, text="📂 Open Songs folder", style="Ghost.TButton", command=self._open_songs_folder).pack(side="left", padx=(8, 0))
        self._status_label = tk.Label(toolbar, text="", bg=BG, fg=ACCENT, font=FONT_SMALL)
        self._status_label.pack(side="right")

        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        self._tree = ttk.Treeview(
            body, columns=("info1", "info2"),
            show="tree headings",
            height=20,
        )
        self._tree.heading("#0", text="Name", anchor="w")
        self._tree.heading("info1", text="Details", anchor="w")
        self._tree.heading("info2", text="Info", anchor="w")
        self._tree.column("#0", width=280, anchor="w", stretch=True)
        self._tree.column("info1", width=180, anchor="w")
        self._tree.column("info2", width=160, anchor="w")

        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        drop_frame = tk.Frame(self.window, bg=PANEL_ALT, highlightthickness=1, highlightbackground=ACCENT_SOFT)
        drop_frame.pack(fill="x", padx=16, pady=(8, 12))

        self._drop_label = tk.Label(
            drop_frame, text="⬇  Drop .zip / .osz files here to extract into the selected folder",
            bg=PANEL_ALT, fg=TEXT, font=FONT_SECTION,
        )
        self._drop_label.pack(fill="x", padx=18, pady=12)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

    def _set_status(self, text: str) -> None:
        self._status_label.configure(text=text)
        self.window.update_idletasks()

    def _refresh(self) -> None:
        self._scan_cancel = True
        if self._scan_thread and self._scan_thread.is_alive():
            self._scan_thread.join(timeout=0.5)

        self._scan_cancel = False
        self._boxes_cache = None
        self._categories_cache = None

        for item in self._tree.get_children():
            self._tree.delete(item)
        self._tree.insert("", "end", text="🎵  Songs", open=True, values=("", ""))
        self._tree.insert("", "end", text="🥋  Dan", open=True, values=("", ""))
        self._tree.item(self._tree.get_children()[0], open=True)
        self._tree.item(self._tree.get_children()[1], open=True)

        self._set_status("Scanning...")

        self._scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._scan_thread.start()

    def _scan_worker(self) -> None:
        try:
            boxes = scan_boxes(self.song_root) if not self._scan_cancel else []
            if self._scan_cancel:
                return
            categories = scan_dan_categories(self.song_root) if not self._scan_cancel else []
            if self._scan_cancel:
                return

            self._boxes_cache = boxes
            self._categories_cache = categories
            self.window.after(0, self._populate_tree, boxes, categories)
        except Exception as exc:
            self.window.after(0, self._set_status, f"Error: {exc}")

    def _populate_tree(self, boxes, categories) -> None:
        if self._scan_cancel:
            return
        for item in self._tree.get_children():
            self._tree.delete(item)

        songs_id = self._tree.insert("", "end", text="🎵  Songs", open=True, values=("", ""))
        try:
            for box in boxes:
                box_id = self._tree.insert(songs_id, "end", text=f"  📁 {box.title}", open=False, values=(f"{len(box.songs)} songs", ""))
                for song in box.songs:
                    song_id = self._tree.insert(box_id, "end", text=f"    🎶 {song.title}", open=False, values=(song.maker, song.subtitle))
                    for course in song.courses:
                        self._tree.insert(song_id, "end", text=f"      ▸ {course.course}", values=(f"Lv.{course.level}", ""))
        except Exception:
            self._tree.insert(songs_id, "end", text="  (error)", values=("", ""))

        dan_id = self._tree.insert("", "end", text="🥋  Dan", open=True, values=("", ""))
        try:
            for cat in categories:
                cat_id = self._tree.insert(dan_id, "end", text=f"  🏷 {cat.title}", open=False, values=(f"{len(cat.dans)} courses", ""))
                for dan in cat.dans:
                    dan_id2 = self._tree.insert(cat_id, "end", text=f"    🥇 {dan.title}", open=False, values=("", ""))
                    for ref in dan.dan_songs:
                        if ref.is_hidden:
                            self._tree.insert(dan_id2, "end", text="      ???", values=("???", "???"))
                        elif ref.song:
                            song = ref.song
                            course_str = next((c.course for c in song.courses), "")
                            self._tree.insert(dan_id2, "end", text=f"      🎶 {song.title}", values=(song.maker, f"{course_str} Lv.{ref.difficulty}"))
                        else:
                            self._tree.insert(dan_id2, "end", text=f"      ? {ref.path}", values=("", ""))
        except Exception:
            self._tree.insert(dan_id, "end", text="  (error)", values=("", ""))

        count = sum(len(b.songs) for b in boxes)
        self._set_status(f"{len(boxes)} boxes, {len(categories)} dan categories, {count} songs")

    def _on_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        item = sel[0]
        self._current_folder = None
        if self._boxes_cache is None:
            return
        label = self._tree.item(item, "text").strip()
        for box in self._boxes_cache:
            if label.endswith(box.title):
                self._current_folder = box.folder
                return

    def _open_songs_folder(self) -> None:
        os.startfile(str(self.song_root))

    def _handle_dropfiles(self, hdrop) -> None:
        drop_point = wintypes.POINT()
        inside = bool(shell32.DragQueryPoint(hdrop, ctypes.byref(drop_point)))
        if not inside:
            return

        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        paths: list[Path] = []
        for index in range(count):
            length = shell32.DragQueryFileW(hdrop, index, None, 0) + 1
            buf = ctypes.create_unicode_buffer(length)
            shell32.DragQueryFileW(hdrop, index, buf, length)
            paths.append(Path(buf.value))

        target = self._resolve_drop_target()
        for p in paths:
            ext = p.suffix.lower()
            if ext not in (".zip", ".osz"):
                continue
            try:
                extract_to_folder(p, target)
                ensure_box_def(target)
                msg = f"Extracted {p.name} → {target}"
                self._drop_label.config(text=f"✅  {msg}")
                self._refresh()
            except Exception as exc:
                messagebox.showerror("Extract error", f"{p.name}\n\n{exc}")

        shell32.DragFinish(hdrop)

    def _resolve_drop_target(self) -> Path:
        if self._current_folder and self._current_folder.exists():
            return self._current_folder
        default = self.song_root / "zip"
        default.mkdir(parents=True, exist_ok=True)
        return default

    def _enable_file_drop(self) -> None:
        if os.name != "nt":
            return
        self.window.update_idletasks()
        hwnd = wintypes.HWND(self.window.winfo_id())
        shell32.DragAcceptFiles(hwnd, True)

        original = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
        if not original:
            return
        self._drop_old_wndproc = ctypes.c_void_p(original)

        def wndproc(window, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                self._handle_dropfiles(wparam)
                return 0
            return user32.CallWindowProcW(self._drop_old_wndproc, window, msg, wparam, lparam)

        self._drop_wndproc_ref = CFUNCTYPE_WNDPROC(wndproc)
        user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, self._drop_wndproc_ref)

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
