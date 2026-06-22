from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def apply_update(manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    parent_pid: int = int(manifest["parent_pid"])
    payload_root = Path(manifest["payload_root"])
    target_root = Path(manifest["target_root"])
    restart_exe = manifest.get("restart_exe", "")
    workspace_root = Path(manifest["workspace_root"])

    updater_self = ""
    if getattr(sys, "frozen", False):
        updater_self = Path(sys.executable).resolve().name.lower()
    else:
        updater_self = Path(__file__).resolve().name.lower()

    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        while True:
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
            if not handle:
                break
            kernel32.CloseHandle(handle)
            time.sleep(0.3)
    else:
        while True:
            try:
                os.kill(parent_pid, 0)
                time.sleep(0.3)
            except OSError:
                break

    time.sleep(2)

    target_root = target_root.resolve()
    if target_root.exists():
        for child in target_root.iterdir():
            name_lower = child.name.lower()
            if name_lower == "launcher_state.json" or name_lower == updater_self:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    payload_root = payload_root.resolve()
    if payload_root.exists():
        for child in payload_root.iterdir():
            dest = target_root / child.name
            if child.is_dir():
                shutil.copytree(child, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(child, dest)

    import tempfile as _tempfile
    temp_root = Path(_tempfile.gettempdir())
    try:
        for p in temp_root.glob("_MEI*"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass

    if restart_exe and Path(restart_exe).exists():
        subprocess.Popen(
            [restart_exe],
            cwd=str(target_root),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--apply-update", type=str, default="", help="Path to update manifest JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.apply_update:
        manifest_path = Path(args.apply_update).resolve()
        return apply_update(manifest_path)
    print("This executable is a helper for TaikoNauts Unofficial Launcher updates.", file=sys.stderr)
    print("Do not run it directly.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
