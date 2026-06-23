from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path


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
