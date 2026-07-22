from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


APP_TITLE = "TaikøNauts UNOFFL Launcher"
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent.parent
STATE_FILE = APP_DIR / "launcher_state.json"
GAME_CONFIG_RELATIVE = Path("Config") / "GameConfig.json"
SKINS_DIR_NAME = "Skins"
WINDOWS_GAME_EXE_NAME = "TaikoNauts.exe"
PROCESS_KILL_TIMEOUT_SEC = 20.0

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


@dataclass(frozen=True)
class SkinInfo:
    name: str
    version: str
    description: str
    folder: Path
    skin_path_value: str


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
