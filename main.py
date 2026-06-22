from __future__ import annotations

import json
import os
import queue
import shutil
import re
import subprocess
import threading
import time
import ctypes
import zipfile
import tempfile
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

APP_VERSION = "v1.1.1"
GITHUB_REPO_URL = "https://github.com/slp-222-swimin/TaikoNauts-Unofficial-Launcher"
GAME_BOOTSTRAP_URL = "https://pub-137e553b50604fb28196265eadbc30a2.r2.dev/bootstrap/TaikoNauts-latest.zip"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    url: str
    asset_name: str
    asset_url: str
    published_at: str


def fetch_latest_release() -> ReleaseInfo | None:
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/slp-222-swimin/TaikoNauts-Unofficial-Launcher/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "TaikoNautsLauncher"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        assets = data.get("assets") or []
        asset_name = ""
        asset_url = ""
        for a in assets:
            name: str = a.get("name", "")
            if name.lower().endswith(".exe") or name.lower().endswith(".zip"):
                asset_name = name
                asset_url = a.get("browser_download_url", "")
                break

        tag = data.get("tag_name", "")
        return ReleaseInfo(
            version=tag,
            url=data.get("html_url", ""),
            asset_name=asset_name,
            asset_url=asset_url,
            published_at=data.get("published_at", ""),
        )
    except Exception:
        return None


def is_version_newer(latest: str, current: str) -> bool:
    import re
    def parse(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.sub(r"^v", "", v).split("."))
    try:
        return parse(latest) > parse(current)
    except Exception:
        return False


def download_release_asset(
    release: ReleaseInfo, dest_dir: Path, progress_cb: object | None = None
) -> Path:
    import urllib.request
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    local_path = dest_dir / release.asset_name

    def reporthook(block_count: int, block_size: int, total_size: int) -> None:
        if progress_cb is not None:
            downloaded = block_count * block_size
            progress_cb(downloaded, total_size)

    urllib.request.urlretrieve(release.asset_url, str(local_path), reporthook)
    return local_path


def normalize_version_label(version: str) -> str:
    return version.lstrip("vV")

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


def save_launcher_state(exe_path: str, geometry: str | None = None, launcher_version: str = "") -> None:
    state = load_launcher_state()
    state["exePath"] = exe_path
    if geometry is not None:
        state["geometry"] = geometry
    if launcher_version:
        state["launcherVersion"] = launcher_version
    try:
        safe_write_json(STATE_FILE, state)
    except Exception:
        pass


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
    shell32.DragQueryPoint.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.POINT)]
    shell32.DragQueryPoint.restype = wintypes.BOOL
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


def extract_zip_archive(zip_path, target_dir):
    from pathlib import Path
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()

    import zipfile
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            if member.is_dir():
                (target_dir / member.filename).mkdir(parents=True, exist_ok=True)
                continue
            extracted = (target_dir / member.filename).resolve()
            if target_root not in extracted.parents and extracted != target_root:
                raise ValueError(f"Unsafe path in zip: {member.filename}")
            extracted.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as src, extracted.open("wb") as dst:
                dst.write(src.read())

    return target_dir


def select_payload_root(extracted_root):
    from pathlib import Path
    extracted_root = Path(extracted_root)
    children = [child for child in extracted_root.iterdir()]
    dirs = [child for child in children if child.is_dir()]
    files = [child for child in children if child.is_file()]
    if len(children) == 1 and len(dirs) == 1 and not files:
        return dirs[0]
    return extracted_root

def clear_zip_folder_keep_box_def(exe_path: Path) -> Path:
    game_root = resolve_game_root(exe_path)
    target_dir = game_root / "Songs" / "zip"
    target_dir.mkdir(parents=True, exist_ok=True)

    box_def = target_dir / "box.def"
    if not box_def.exists():
        box_def.write_text("#TITLE:解凍した譜面\n", encoding="utf-8", newline="\n")

    for child in target_dir.iterdir():
        if child.name.lower() == "box.def":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)

    return target_dir




class UpdaterConfigWindow:
    def __init__(self, app: "LauncherApp") -> None:
        self.app = app
        self.result: dict[str, bool] | None = None
        self.window = tk.Toplevel(app)
        self.window.title("Updater Configuration")
        self.window.geometry("480x220")
        self.window.configure(bg=BG)
        self.window.resizable(False, False)
        self.window.transient(app)
        self.window.grab_set()

        outer = ttk.Frame(self.window, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Updater Configuration", font=("Segoe UI", 14, "bold")).pack(anchor="w")
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
        ttk.Button(button_row, text="Start Updater", command=self._confirm).pack(side="left")
        ttk.Button(button_row, text="Cancel", command=self._cancel).pack(side="left", padx=8)

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
        self.app.wait_window(self.window)
        return self.result


class UpdaterSession:
    def __init__(self, exe_path: Path, on_log, on_state, on_exit, config: dict | None = None) -> None:
        self.exe_path = exe_path
        self.on_log = on_log
        self.on_state = on_state
        self.on_exit = on_exit
        self.config = config or {}
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
            stripped = line.rstrip("\n")
            self.on_log(stripped)
            self._auto_answer(stripped)

        return_code = self.process.wait()
        self.on_log(f"[process exited] code={return_code}")
        self._alive = False
        self.on_state(False)
        if self.on_exit:
            self.on_exit(return_code, self.process.pid if self.process else -1, self._stop_requested)

    def _auto_answer(self, line: str) -> None:
        import re
        text = re.sub(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] ", "", line).strip()
        if not text.endswith("(y/n)"):
            return
        lower = text.lower()
        if "executable file" in lower or "taikonauts.exe" in lower:
            answer = "y" if self.config.get("overwrite_exe", True) else "n"
        elif "overwrite" in lower and ("simplestyle" in lower or "skin" in lower):
            answer = "y" if self.config.get("overwrite_skin", True) else "n"
        else:
            answer = "y"
        try:
            self.send(answer)
            self.on_log(f"> {answer}")
        except Exception:
            pass

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
        self.window.geometry("860x540")
        self.window.minsize(760, 460)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_var = tk.StringVar(value="Updater is stopped")

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

        self.log_widget = ScrolledText(root, height=22, wrap="word")
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

    MAX_LOG_LINES = 1000

    def append_log(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        total = int(self.log_widget.index("end-1c").split(".")[0])
        if total > self.MAX_LOG_LINES:
            self.log_widget.delete("1.0", f"{total - self.MAX_LOG_LINES + 100}.0")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def set_state(self, running: bool) -> None:
        self.status_var.set("Updater is running" if running else "Updater is stopped")

    def clear_log(self) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")




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

        ttk.Label(outer, text="Downloading Update", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.status_label = ttk.Label(outer, text="Starting...")
        self.status_label.pack(anchor="w", pady=(8, 0))

        self.progress_bar = ttk.Progressbar(outer, mode="determinate", length=380)
        self.progress_bar.pack(fill="x", pady=(16, 0))

        self.size_label = ttk.Label(outer, text="")
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
        self.zip_status_var = tk.StringVar(value="ZIP area is ready")

        self.skins: list[SkinInfo] = []
        self.skin_map: dict[str, SkinInfo] = {}
        self.events: queue.Queue[tuple[str, object, object]] = queue.Queue()
        self.updater_session: UpdaterSession | None = None
        self.updater_window: UpdaterWindow | None = None
        self._drop_wndproc_ref = None
        self._drop_old_wndproc = None
        self.zip_drop_zone = None
        self.launcher_version: str = ""

        self._build_ui()
        self._enable_file_drop()
        self._load_saved_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.withdraw()
        self.after(100, self._drain_events)
        self.after(200, self._update_updater_btn)

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
        style.configure("ZipDropZone.TFrame", background=PANEL_ALT)
        style.configure("ZipDropZoneTitle.TLabel", background=PANEL_ALT, foreground=TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("ZipDropZoneText.TLabel", background=PANEL_ALT, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("ZipDropZoneStatus.TLabel", background=PANEL_ALT, foreground=ACCENT, font=("Segoe UI", 10))
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
        self._updater_btn = ttk.Button(action_row, text="Launch Updater", command=self.start_updater)
        self._updater_btn.pack(side="left", padx=8)
        ttk.Label(action_row, textvariable=self.status_var).pack(side="left", padx=12)

        zip_frame = ttk.LabelFrame(root, text="ZIP Import", padding=10)
        zip_frame.pack(fill="x", pady=(0, 8))

        self.zip_drop_zone = tk.Frame(
            zip_frame,
            bg=PANEL_ALT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            bd=0,
        )
        self.zip_drop_zone.pack(fill="x")

        zip_inner = tk.Frame(self.zip_drop_zone, bg=PANEL_ALT)
        zip_inner.pack(fill="x", padx=14, pady=14)

        tk.Label(
            zip_inner,
            text="Drop ZIP files here",
            bg=PANEL_ALT,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            zip_inner,
            text="Only files dropped onto this area will be extracted into Songs\\zip.",
            bg=PANEL_ALT,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        zip_actions = ttk.Frame(zip_inner)
        zip_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(zip_actions, text="Clear extracted folder", command=self.clear_extracted_zip_folder).pack(side="left")
        ttk.Label(zip_actions, textvariable=self.zip_status_var).pack(side="left", padx=12)

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

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(8, 0))
        version_text = f"v{normalize_version_label(APP_VERSION)}"
        version_link = tk.Label(
            footer,
            text=version_text,
            fg=ACCENT,
            bg=BG,
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        version_link.pack(side="left")
        version_link.bind("<Button-1>", lambda _: __import__("webbrowser").open(GITHUB_REPO_URL))

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
        self.after(50, self._drain_events)

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
            p = Path(saved_path)
            if p.suffix.lower() == ".exe":
                p = p.parent
            self.exe_path_var.set(str(p))
            self.current_root_var.set(f"Game root: {p.resolve()}")
            self.refresh_all()
        
        self.launcher_version = str(state.get("launcherVersion") or "")

        geometry = state.get("geometry")
        if geometry:
            try:
                self.geometry(geometry)
            except Exception:
                pass



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

        ttk.Label(outer, text="Update Available", font=("Segoe UI", 14, "bold")).pack(anchor="w")
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
            command=lambda: self._download_and_apply_update_release(release, window),
        ).pack(side="left")
        ttk.Button(
            button_row, text="Remind me later",
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
            self._updater_btn.config(text="Launch Updater", command=self.start_updater)
        else:
            self._updater_btn.config(text="Install Game", command=self._install_game)

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
            self._updater_btn.config(text="Launch Updater", command=self.start_updater)
            self.start_updater()
        except Exception as exc:
            messagebox.showerror("Install error", str(exc))
            self.status_var.set("Install failed")

    def save_current_state(self) -> None:
        exe_path = self.exe_path_var.get().strip()
        geometry = self.geometry()
        save_launcher_state(exe_path, geometry, APP_VERSION)

    def _on_close(self) -> None:
        try:
            self.save_current_state()
        except Exception:
            pass
        self.destroy()

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
                    target = extract_zip_to_songs(exe_path, path)
                    self.skin_message_var.set(f"Extracted {path.name} -> {target}")
                    self.zip_status_var.set(f"Extracted {path.name}")
                    messagebox.showinfo("Done", f"Extracted:\n{path.name}\n->\n{target}")
                except Exception as exc:
                    messagebox.showerror("ZIP extract error", f"{path}\n\n{exc}")
        finally:
            shell32.DragFinish(hdrop)

    def clear_extracted_zip_folder(self) -> None:
        try:
            exe_path = self.get_exe_path()
        except Exception as exc:
            messagebox.showerror("ZIP folder", str(exc))
            return

        target_dir = resolve_game_root(exe_path) / "Songs" / "zip"
        if not messagebox.askyesno(
            "Confirm cleanup",
            f"Delete everything in this folder except box.def?\n\n{target_dir}",
        ):
            return

        try:
            target = clear_zip_folder_keep_box_def(exe_path)
            self.zip_status_var.set(f"Cleared {target}")
            messagebox.showinfo("Done", f"Cleared extracted folder:\n{target}")
        except Exception as exc:
            messagebox.showerror("ZIP folder cleanup error", str(exc))

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

    def refresh_all(self) -> None:
        try:
            self.refresh_skins()
            raw = self.exe_path_var.get().strip()
            if raw and Path(raw).exists():
                self.current_root_var.set(f"Game root: {Path(raw).resolve()}")
            else:
                self.current_root_var.set("Game root not selected")
            self.status_var.set("Ready")
            self._update_updater_btn()
        except Exception as exc:
            messagebox.showerror("Refresh error", str(exc))

    def refresh_skins(self) -> None:
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
            messagebox.showerror("Error", str(exc))
            return
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
            save_launcher_state(str(self.exe_path_var.get().strip()))
            subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))
            self.status_var.set("Game launched")
        except Exception as exc:
            messagebox.showerror("Launch error", str(exc))

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
                messagebox.showinfo("Updater", "Updater is already running")
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
            messagebox.showerror("Updater error", str(exc))


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


if __name__ == "__main__":
    raise SystemExit(main())
