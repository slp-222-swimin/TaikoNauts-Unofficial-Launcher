from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import ctypes
import zipfile
import sys
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from ctypes import wintypes


APP_TITLE = "TaikøNauts UNOFFL Launcher"
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
STATE_FILE = APP_DIR / "launcher_state.json"
GAME_CONFIG_RELATIVE = Path("Config") / "GameConfig.json"
SKINS_DIR_NAME = "Skins"
WINDOWS_GAME_EXE_NAME = "TaikoNauts.exe"
PROCESS_KILL_TIMEOUT_SEC = 20.0
WM_DROPFILES = 0x0233
GWL_WNDPROC = -4
CFUNCTYPE_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

BG = "#0d1117"
PANEL = "#161b22"
PANEL_ALT = "#11161d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#58a6ff"
ACCENT_2 = "#7c3aed"
ACCENT_SOFT = "#1f6feb"
BORDER = "#2b3240"
SUCCESS = "#2ea043"
WARNING = "#d29922"
ERROR = "#f85149"
SPLASH_DURATION_MS = 2200


@dataclass(frozen=True)
class SkinInfo:
    name: str
    version: str
    description: str
    folder: Path
    skin_path_value: str


def safe_read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def safe_write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolve_game_root(exe_path: Path) -> Path:
    return exe_path.resolve().parent


def resolve_game_config(exe_path: Path) -> Path:
    return resolve_game_root(exe_path) / GAME_CONFIG_RELATIVE


def resolve_skin_path(game_root: Path, skin_path_value: str) -> Path:
    candidate = Path(skin_path_value)
    if candidate.is_absolute():
        return candidate
    return (game_root / candidate).resolve()


def relative_skin_value(game_root: Path, skin_folder: Path) -> str:
    try:
        return str(skin_folder.resolve().relative_to(game_root.resolve()))
    except ValueError:
        return str(skin_folder.resolve())


def load_launcher_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return safe_read_json(STATE_FILE)
    except Exception:
        return {}


def save_launcher_state(exe_path: str) -> None:
    safe_write_json(STATE_FILE, {"exePath": exe_path})


def read_game_config(exe_path: Path) -> dict:
    config_path = resolve_game_config(exe_path)
    if not config_path.exists():
        return {}
    return safe_read_json(config_path)


def write_game_config(exe_path: Path, config: dict) -> None:
    config_path = resolve_game_config(exe_path)
    if not config_path.parent.exists():
        raise FileNotFoundError(f"Config folder not found: {config_path.parent}")
    safe_write_json(config_path, config)


def discover_skins(exe_path: Path) -> list[SkinInfo]:
    game_root = resolve_game_root(exe_path)
    skins_root = game_root / SKINS_DIR_NAME
    if not skins_root.exists():
        return []

    skins: list[SkinInfo] = []
    for skin_config_path in skins_root.rglob("SkinConfig.json"):
        try:
            raw = safe_read_json(skin_config_path)
        except Exception:
            continue

        folder = skin_config_path.parent
        skins.append(
            SkinInfo(
                name=str(raw.get("skinName") or folder.name),
                version=str(raw.get("skinVersion") or ""),
                description=str(raw.get("skinDescription") or ""),
                folder=folder,
                skin_path_value=relative_skin_value(game_root, folder),
            )
        )

    skins.sort(key=lambda s: (s.name.lower(), s.version.lower(), str(s.folder).lower()))
    return skins


def parse_prompt_options(text: str) -> list[str]:
    normalized = text.strip()
    lowered = normalized.lower()

    bracket_match = re.search(r"\[([^\]]{1,80})\]$", normalized)
    if bracket_match:
        raw = bracket_match.group(1)
        parts = [part.strip() for part in re.split(r"[\/|,]", raw) if part.strip()]
        if len(parts) >= 2:
            return parts[:6]

    if "yes/no" in lowered or "(y/n)" in lowered or "[y/n]" in lowered:
        return ["y", "n"]
    return []


if os.name == "nt":
    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * MAX_PATH),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragAcceptFiles.restype = None
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    shell32.DragFinish.restype = None

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_longlong


def enumerate_processes() -> list[tuple[int, int, str]]:
    if os.name != "nt":
        return []

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return []

    processes: list[tuple[int, int, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            processes.append(
                (
                    int(entry.th32ProcessID),
                    int(entry.th32ParentProcessID),
                    entry.szExeFile,
                )
            )
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    return processes


def find_child_processes_by_name(parent_pid: int, exe_name: str) -> list[int]:
    target = exe_name.lower()
    matches: list[int] = []
    for pid, ppid, name in enumerate_processes():
        if ppid == parent_pid and name.lower() == target:
            matches.append(pid)
    return matches


def kill_process(pid: int) -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def extract_zip_to_songs(exe_path: Path, zip_path: Path) -> Path:
    game_root = resolve_game_root(exe_path)
    songs_root = game_root / "Songs"
    songs_root.mkdir(parents=True, exist_ok=True)

    target_dir = songs_root / "zip"
    target_dir.mkdir(parents=True, exist_ok=True)

    box_def = target_dir / "box.def"
    if not box_def.exists():
        box_def.write_text("#TITLE:解凍した譜面\n", encoding="utf-8", newline="\n")

    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            if member.is_dir():
                (target_dir / member.filename).mkdir(parents=True, exist_ok=True)
                continue
            extracted = (target_dir / member.filename).resolve()
            if target_dir.resolve() not in extracted.parents and extracted != target_dir.resolve():
                raise ValueError(f"Unsafe path in zip: {member.filename}")
            extracted.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as src, extracted.open("wb") as dst:
                dst.write(src.read())

    return target_dir


class UpdaterSession:
    def __init__(self, exe_path: Path, on_log, on_state, on_exit) -> None:
        self.exe_path = exe_path
        self.on_log = on_log
        self.on_state = on_state
        self.on_exit = on_exit
        self.process: subprocess.Popen[str] | None = None
        self._alive = False
        self._stop_requested = False

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return

        updater_path = self.exe_path.parent / "TaikoNautsUpdater.exe"
        if not updater_path.exists():
            raise FileNotFoundError(f"Updater not found: {updater_path}")

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [str(updater_path)],
            cwd=str(self.exe_path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self._alive = True
        self.on_state(True)
        threading.Thread(target=self._reader_loop, daemon=True).start()

    def _reader_loop(self) -> None:
        assert self.process is not None
        stdout = self.process.stdout
        if stdout is None:
            self.on_state(False)
            return

        for line in stdout:
            if not self._alive:
                break
            self.on_log(line.rstrip("\n"))

        return_code = self.process.wait()
        self.on_log(f"[process exited] code={return_code}")
        self._alive = False
        self.on_state(False)
        if self.on_exit:
            self.on_exit(return_code, self.process.pid if self.process else -1, self._stop_requested)

    def send(self, text: str) -> None:
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Updater is not running")
        if self.process.stdin is None:
            raise RuntimeError("Updater stdin is unavailable")
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def stop(self) -> None:
        self._alive = False
        self._stop_requested = True
        if self.process and self.process.poll() is None:
            self.process.terminate()


class UpdaterWindow:
    def __init__(self, app: "LauncherApp") -> None:
        self.app = app
        self.window = tk.Toplevel(app)
        self.window.title("Updater")
        self.window.geometry("860x620")
        self.window.minsize(760, 520)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_var = tk.StringVar(value="Updater is stopped")
        self.prompt_var = tk.StringVar(value="Waiting for updater input")
        self.input_var = tk.StringVar()
        self._prompt_buttons: list[ttk.Button] = []

        root = ttk.Frame(self.window, padding=12)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        ttk.Label(header, text="Updater", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(header, textvariable=self.status_var).pack(anchor="w", pady=(4, 0))

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", pady=(10, 0))
        ttk.Button(toolbar, text="Clear log", command=self.clear_log).pack(side="left")
        ttk.Button(toolbar, text="Stop", command=self.app.stop_updater).pack(side="left", padx=8)
        ttk.Label(toolbar, text="Input").pack(side="left", padx=(20, 6))
        self.input_entry = ttk.Entry(toolbar, textvariable=self.input_var)
        self.input_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(toolbar, text="Send", command=self.send_input).pack(side="left", padx=8)

        prompt_frame = ttk.Frame(root)
        prompt_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(prompt_frame, textvariable=self.prompt_var).pack(anchor="w")
        self.prompt_button_row = ttk.Frame(prompt_frame)
        self.prompt_button_row.pack_forget()

        self.log_widget = ScrolledText(root, height=18, wrap="word")
        self.log_widget.pack(fill="both", expand=True, pady=(10, 0))
        self.log_widget.configure(state="disabled")

    def _on_close(self) -> None:
        self.window.withdraw()

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def destroy(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()

    def append_log(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def set_state(self, running: bool) -> None:
        self.status_var.set("Updater is running" if running else "Updater is stopped")

    def clear_prompt(self) -> None:
        for widget in self.prompt_button_row.winfo_children():
            widget.destroy()
        self._prompt_buttons.clear()
        self.prompt_button_row.pack_forget()

    def set_prompt(self, text: str, options: list[str]) -> None:
        self.prompt_var.set(text or "Waiting for updater input")
        self.clear_prompt()
        if not options:
            return
        self.prompt_button_row.pack(fill="x", pady=(6, 0))
        for option in options:
            button = ttk.Button(
                self.prompt_button_row,
                text=option,
                command=lambda value=option: self.app.send_updater_input(value),
            )
            button.pack(side="left", padx=(0, 8))
            self._prompt_buttons.append(button)

    def clear_log(self) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def send_input(self) -> None:
        self.app.send_updater_input(self.input_var.get())
        self.input_var.set("")


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
            font=("Segoe UI", 22, "bold"),
        )
        self.title.pack(anchor="w", padx=28, pady=(32, 8))

        self.subtitle = tk.Label(
            inner,
            text="Preparing launcher workspace...",
            bg=PANEL,
            fg=PANEL,
            font=("Segoe UI", 10),
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
            font=("Segoe UI", 9),
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


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x700")
        self.minsize(900, 620)

        self.exe_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select TaikoNauts.exe")
        self.skin_message_var = tk.StringVar(value="")
        self.current_root_var = tk.StringVar(value="Game root not selected")
        self.skin_count_var = tk.StringVar(value="0 skins")
        self.drop_hint_var = tk.StringVar(value="Drop a ZIP file here to extract it into Songs\\zip")

        self.skins: list[SkinInfo] = []
        self.skin_map: dict[str, SkinInfo] = {}
        self.events: queue.Queue[tuple[str, object, object]] = queue.Queue()
        self.updater_session: UpdaterSession | None = None
        self.updater_window: UpdaterWindow | None = None
        self._drop_wndproc_ref = None
        self._drop_old_wndproc = None

        self._build_ui()
        self._enable_file_drop()
        self._load_saved_state()
        self.withdraw()
        self.after(100, self._drain_events)

    def _setup_styles(self) -> None:
        self.configure(bg=BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=TEXT, borderwidth=0)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("TButton", padding=(14, 9))
        style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT)
        style.configure(
            "TLabelframe",
            background=BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.configure("TLabelframe.Label", background=BG, foreground=TEXT, font=("Segoe UI", 10, "bold"))
        style.configure("AppHero.TFrame", background=PANEL)
        style.configure("AppHeroAlt.TFrame", background=PANEL_ALT)
        style.configure("AppCard.TFrame", background=PANEL)
        style.configure("AppCardAlt.TFrame", background=PANEL_ALT)
        style.configure("AppTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 22, "bold"))
        style.configure("AppSubtitle.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("AppCardTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("AppCardText.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("AppAccent.TButton", background=ACCENT, foreground="white", padding=(16, 10))
        style.configure("AppGhost.TButton", background=PANEL_ALT, foreground=TEXT, padding=(16, 10))
        style.map("AppAccent.TButton", background=[("active", "#79c0ff"), ("pressed", "#388bfd")])
        style.map("AppGhost.TButton", background=[("active", "#1b2230"), ("pressed", "#0f141d")])
        style.configure(
            "Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=28,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=PANEL_ALT,
            foreground=TEXT,
            relief="flat",
            padding=(10, 8),
        )
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", "white")])
        style.map("Treeview.Heading", background=[("active", "#1d2533")])

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        ttk.Label(header, text="TaikøNauts UNOFFL Launcher", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(header, text="Launch the game, open the updater, and switch skins.").pack(anchor="w", pady=(4, 0))

        path_frame = ttk.LabelFrame(root, text="Game", padding=10)
        path_frame.pack(fill="x", pady=(12, 8))
        path_row = ttk.Frame(path_frame)
        path_row.pack(fill="x")
        ttk.Entry(path_row, textvariable=self.exe_path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="Browse...", command=self.select_exe).pack(side="left", padx=(8, 0))
        ttk.Button(path_row, text="Refresh", command=self.refresh_all).pack(side="left", padx=(8, 0))

        action_row = ttk.Frame(path_frame)
        action_row.pack(fill="x", pady=(10, 0))
        ttk.Button(action_row, text="Launch Game", command=self.launch_game).pack(side="left")
        ttk.Button(action_row, text="Launch Updater", command=self.start_updater).pack(side="left", padx=8)
        ttk.Label(action_row, textvariable=self.status_var).pack(side="left", padx=12)

        skin_frame = ttk.LabelFrame(root, text="Skins", padding=10)
        skin_frame.pack(fill="both", expand=True)

        skin_toolbar = ttk.Frame(skin_frame)
        skin_toolbar.pack(fill="x")
        ttk.Button(skin_toolbar, text="Reload skins", command=self.refresh_skins).pack(side="left")
        ttk.Button(skin_toolbar, text="Apply selected skin", command=self.apply_selected_skin).pack(side="left", padx=8)
        ttk.Label(skin_toolbar, textvariable=self.skin_message_var).pack(side="left", padx=12)

        self.skin_tree = ttk.Treeview(
            skin_frame,
            columns=("name", "version", "path", "description"),
            show="headings",
            height=12,
        )
        self.skin_tree.heading("name", text="Name", anchor="w")
        self.skin_tree.heading("version", text="Version", anchor="w")
        self.skin_tree.heading("path", text="SkinPath", anchor="w")
        self.skin_tree.heading("description", text="Description", anchor="w")
        self.skin_tree.column("name", width=180, anchor="w")
        self.skin_tree.column("version", width=130, anchor="w")
        self.skin_tree.column("path", width=280, anchor="w")
        self.skin_tree.column("description", width=460, anchor="w")
        self.skin_tree.pack(fill="both", expand=True, pady=(8, 0))
        self.skin_tree.bind("<<TreeviewSelect>>", self._on_skin_select)

    def _queue_log(self, text: str) -> None:
        self.events.put(("log", text, ""))
        options = parse_prompt_options(text)
        if options:
            self.events.put(("prompt", text, "\u001f".join(options)))

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
            while True:
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
                elif kind == "prompt":
                    options = [item for item in str(extra).split("\u001f") if item]
                    if self.updater_window:
                        self.updater_window.set_prompt(str(payload), options)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _ensure_updater_window(self) -> None:
        if self.updater_window and self.updater_window.window.winfo_exists():
            self.updater_window.show()
            return
        self.updater_window = UpdaterWindow(self)
        self.updater_window.show()

    def _load_saved_state(self) -> None:
        state = load_launcher_state()
        saved_path = str(state.get("exePath") or "").strip()
        if saved_path and Path(saved_path).exists():
            self.exe_path_var.set(saved_path)
            self.current_root_var.set(f"Game root: {Path(saved_path).resolve().parent}")
            self.refresh_all()

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

    def _handle_dropfiles(self, hdrop) -> None:
        if os.name != "nt":
            return

        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        dropped_paths: list[Path] = []
        for index in range(count):
            length = shell32.DragQueryFileW(hdrop, index, None, 0) + 1
            buffer = ctypes.create_unicode_buffer(length)
            shell32.DragQueryFileW(hdrop, index, buffer, length)
            dropped_paths.append(Path(buffer.value))

        shell32.DragFinish(hdrop)

        for path in dropped_paths:
            if path.suffix.lower() != ".zip":
                continue
            try:
                exe_path = self.get_exe_path()
                target = extract_zip_to_songs(exe_path, path)
                self.skin_message_var.set(f"Extracted {path.name} -> {target}")
                messagebox.showinfo("Done", f"Extracted:\n{path.name}\n->\n{target}")
            except Exception as exc:
                messagebox.showerror("ZIP extract error", f"{path}\n\n{exc}")

    def select_exe(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select TaikoNauts.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if selected:
            self.exe_path_var.set(selected)
            self.current_root_var.set(f"Game root: {Path(selected).resolve().parent}")
            try:
                save_launcher_state(selected)
            except Exception:
                pass
            self.refresh_all()

    def get_exe_path(self) -> Path:
        raw = self.exe_path_var.get().strip()
        if not raw:
            raise ValueError("TaikoNauts.exe path is not set")
        exe_path = Path(raw)
        if not exe_path.exists():
            raise FileNotFoundError(f"TaikoNauts.exe not found: {exe_path}")
        return exe_path

    def refresh_all(self) -> None:
        try:
            self.refresh_skins()
            try:
                exe_path = self.get_exe_path()
                self.current_root_var.set(f"Game root: {exe_path.resolve().parent}")
            except Exception:
                self.current_root_var.set("Game root not selected")
            self.status_var.set("Ready")
        except Exception as exc:
            messagebox.showerror("Refresh error", str(exc))

    def refresh_skins(self) -> None:
        exe_path = self.get_exe_path()
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

    def _on_skin_select(self, _event=None) -> None:
        selection = self.skin_tree.selection()
        if not selection:
            return
        skin = self.skin_map.get(selection[0])
        if skin:
            self.skin_message_var.set(f"Selected: {skin.name}")

    def apply_selected_skin(self) -> None:
        exe_path = self.get_exe_path()
        selection = self.skin_tree.selection()
        if not selection:
            messagebox.showwarning("No selection", "Select a skin first")
            return
        skin = self.skin_map.get(selection[0])
        if not skin:
            messagebox.showerror("Error", "Selected skin not found")
            return

        config = read_game_config(exe_path)
        config["skinPath"] = skin.skin_path_value
        write_game_config(exe_path, config)
        self.skin_message_var.set(f"skinPath updated: {skin.skin_path_value}")
        messagebox.showinfo("Done", f"skinPath updated:\n{skin.skin_path_value}")

    def launch_game(self) -> None:
        try:
            exe_path = self.get_exe_path()
            save_launcher_state(str(exe_path))
            subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))
            self.status_var.set("Game launched")
        except Exception as exc:
            messagebox.showerror("Launch error", str(exc))

    def start_updater(self) -> None:
        try:
            exe_path = self.get_exe_path()
            save_launcher_state(str(exe_path))
            if self.updater_session and self.updater_session.process and self.updater_session.process.poll() is None:
                self._ensure_updater_window()
                messagebox.showinfo("Updater", "Updater is already running")
                return

            self._ensure_updater_window()
            self.updater_session = UpdaterSession(
                exe_path,
                self._queue_log,
                self._queue_state,
                self._handle_updater_exit,
            )
            self.updater_session.start()
            self._queue_log("[launcher] updater started")
        except Exception as exc:
            messagebox.showerror("Updater error", str(exc))

    def send_updater_input(self, text: str | None = None) -> None:
        if not self.updater_session:
            messagebox.showwarning("Updater", "Updater is not running")
            return
        value = text if text is not None else ""
        if not value:
            return
        try:
            self.updater_session.send(value)
            self._queue_log(f"> {value}")
        except Exception as exc:
            messagebox.showerror("Send error", str(exc))

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
        app.focus_force()

    app.after(SPLASH_DURATION_MS, show_main)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
