from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class UpdaterSession:
    def __init__(self, exe_path: Path, on_log, on_state, on_exit, config: dict | None = None) -> None:
        self.exe_path = exe_path
        self.on_log = on_log
        self.on_state = on_state
        self.on_exit = on_exit
        self.config = config or {}
        self.process: subprocess.Popen[bytes] | None = None
        self._alive = False
        self._stop_requested = False
        self._out_file: tempfile.NamedTemporaryFile | None = None

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return

        updater_path = self.exe_path.parent / "TaikoNautsUpdater.exe"
        if not updater_path.exists():
            raise FileNotFoundError(f"Updater not found: {updater_path}")

        self._out_file = tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=".log", prefix="updater_",
        )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [str(updater_path)],
            cwd=str(self.exe_path.parent),
            stdin=subprocess.PIPE,
            stdout=self._out_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self._out_file.close()
        self._alive = True
        self.on_state(True)
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self) -> None:
        assert self.process is not None
        out_path = Path(self._out_file.name) if self._out_file else None
        last_pos = 0

        while self._alive:
            time.sleep(0.2)  # 5 FPS
            if not self._alive or not out_path or not out_path.exists():
                break
            try:
                with out_path.open("rb") as f:
                    f.seek(last_pos)
                    data = f.read()
                    last_pos = f.tell()
                if data:
                    text = data.decode("utf-8", errors="replace")
                    for line in text.splitlines():
                        self._auto_answer(line)
                    self.on_log(text)
            except (OSError, PermissionError):
                pass

        # process exited
        if out_path and out_path.exists():
            try:
                with out_path.open("rb") as f:
                    remaining = f.read()
                if remaining:
                    text = remaining.decode("utf-8", errors="replace")
                    self.on_log(text)
            except (OSError, PermissionError):
                pass

        return_code = self.process.wait()
        self.on_log(f"[process exited] code={return_code}\n")
        self._alive = False
        self.on_state(False)
        if out_path and out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
        if self.on_exit:
            self.on_exit(return_code, self.process.pid if self.process else -1, self._stop_requested)

    def _auto_answer(self, line: str) -> None:
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
        except Exception:
            pass

    def send(self, text: str) -> None:
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Updater is not running")
        if self.process.stdin is None:
            raise RuntimeError("Updater stdin is unavailable")
        self.process.stdin.write((text + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def stop(self) -> None:
        self._alive = False
        self._stop_requested = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
