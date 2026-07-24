from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from src.core.utils import read_game_config, resolve_game_root


# ── Song Root Resolution ───────────────────────────────────────

def resolve_song_root(exe_path: Path) -> Path:
    """Resolve the effective song root from GameConfig.json's songPath.
    songPath can be a string or a list of strings.
    Uses the first non-empty entry if list; falls back to game root if empty.
    """
    game_root = resolve_game_root(exe_path)
    config = read_game_config(exe_path)
    raw = config.get("songPath", "")
    if isinstance(raw, list):
        raw = next((s for s in raw if s), "")
    if isinstance(raw, str) and raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
        return (game_root / candidate).resolve()
    return game_root


# ── Data Models ────────────────────────────────────────────────

@dataclass
class SongEntry:
    title: str = ""
    subtitle: str = ""
    maker: str = ""
    wave: str = ""
    offset: float = 0.0
    demostart: float = 0.0
    genre: str = ""
    songgenreid: str = ""
    courses: list[CourseEntry] = field(default_factory=list)
    file_path: Path | None = None


@dataclass
class CourseEntry:
    course: str = ""
    level: int = 0
    file_path: Path | None = None


@dataclass
class BoxFolder:
    title: str
    folder: Path
    songs: list[SongEntry] = field(default_factory=list)


@dataclass
class DanSongRef:
    path: str
    difficulty: int = 0
    genre: str = ""
    is_hidden: bool = False
    song: SongEntry | None = None


@dataclass
class DanEntry:
    title: str
    folder: Path
    dan_songs: list[DanSongRef] = field(default_factory=list)


@dataclass
class DanCategory:
    title: str
    folder: Path
    dans: list[DanEntry] = field(default_factory=list)


# ── TJA Parser ─────────────────────────────────────────────────

TJA_HEADER_KEYS = {
    "TITLE", "SUBTITLE", "WAVE", "OFFSET", "DEMOSTART",
    "MAKER", "COURSE", "LEVEL", "GENRE", "SONGGENREID",
}


def parse_tja_header(tja_path: Path) -> dict:
    headers: dict[str, str] = {}
    try:
        text = tja_path.read_text("utf-8-sig")
    except Exception:
        return headers
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") and not line.startswith("#START"):
            if line.startswith("#") and ":" not in line:
                continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lstrip("#").upper()
        val = val.strip()
        if key in TJA_HEADER_KEYS:
            headers[key] = val
    return headers


def tja_header_to_song(tja_path: Path) -> SongEntry | None:
    h = parse_tja_header(tja_path)
    if not h:
        return None
    try:
        offset = float(h.get("OFFSET", "0"))
    except ValueError:
        offset = 0.0
    try:
        demostart = float(h.get("DEMOSTART", "0"))
    except ValueError:
        demostart = 0.0

    course_raw = h.get("COURSE", "")
    level_raw = h.get("LEVEL", "0")
    try:
        level = int(level_raw)
    except ValueError:
        level = 0

    song = SongEntry(
        title=h.get("TITLE", ""),
        subtitle=h.get("SUBTITLE", ""),
        maker=h.get("MAKER", ""),
        wave=h.get("WAVE", ""),
        offset=offset,
        demostart=demostart,
        genre=h.get("GENRE", ""),
        songgenreid=h.get("SONGGENREID", ""),
        file_path=tja_path,
    )
    song.courses.append(CourseEntry(
        course=course_raw,
        level=level,
        file_path=tja_path,
    ))
    return song


# ── osu!taiko Parser ───────────────────────────────────────────

OSU_HEADER_GENERAL = {"Mode", "AudioFilename", "AudioLeadIn", "PreviewTime"}
OSU_HEADER_METADATA = {"TitleUnicode", "ArtistUnicode", "Creator"}
OSU_HEADER_DIFFICULTY = {"OverallDifficulty"}


def parse_osu_header(osu_path: Path) -> dict:
    headers: dict[str, str] = {}
    section = ""
    try:
        text = osu_path.read_text("utf-8-sig")
    except Exception:
        return headers
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].lower()
            continue
        if section in ("general", "metadata", "difficulty") and ":" in line:
            key, _, val = line.partition(":")
            headers[key.strip()] = val.strip()
    return headers


def osu_header_to_song(osu_path: Path) -> SongEntry | None:
    h = parse_osu_header(osu_path)
    if not h:
        return None
    mode = h.get("Mode", "0")
    if mode != "1":
        return None

    try:
        leadin = float(h.get("AudioLeadIn", "0"))
    except ValueError:
        leadin = 0.0
    try:
        preview = int(h.get("PreviewTime", "-1"))
    except ValueError:
        preview = -1

    course_raw = h.get("Version", "")
    level_raw = h.get("OverallDifficulty", "0")
    try:
        level = int(float(level_raw))
    except ValueError:
        level = 0

    song = SongEntry(
        title=h.get("TitleUnicode", ""),
        subtitle=h.get("ArtistUnicode", ""),
        maker=h.get("Creator", ""),
        wave=h.get("AudioFilename", ""),
        offset=-leadin / 1000.0,
        demostart=preview / 1000.0 if preview >= 0 else 0.0,
        file_path=osu_path,
    )
    song.courses.append(CourseEntry(
        course=course_raw,
        level=level,
        file_path=osu_path,
    ))
    return song


# ── Song Discovery ─────────────────────────────────────────────

SONG_EXTENSIONS = {".tja", ".osu"}


def find_song_files_recursive(folder: Path) -> list[Path]:
    files: list[Path] = []
    for entry in folder.rglob("*"):
        if entry.is_file() and entry.suffix.lower() in SONG_EXTENSIONS:
            files.append(entry)
    files.sort(key=lambda p: p.name.lower())
    return files


def find_song_files(folder: Path) -> list[Path]:
    files: list[Path] = []
    for ext in SONG_EXTENSIONS:
        files.extend(folder.glob(f"*{ext}"))
    files.sort(key=lambda p: p.name.lower())
    return files


def parse_song_file(path: Path) -> SongEntry | None:
    ext = path.suffix.lower()
    if ext == ".tja":
        return tja_header_to_song(path)
    elif ext == ".osu":
        return osu_header_to_song(path)
    return None


# ── box.def Scanner ────────────────────────────────────────────

BOX_DEF_NAME = "box.def"


def read_box_def(box_def_path: Path) -> str:
    try:
        text = box_def_path.read_text("utf-8-sig").strip()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#TITLE:"):
                return line[len("#TITLE:"):].strip()
            if line.startswith("#TITLE"):
                return line[len("#TITLE"):].strip()
    except Exception:
        pass
    return box_def_path.parent.name


def _find_box_folders(root: Path) -> list[Path]:
    """Recursively find all folders containing box.def under root."""
    result: list[Path] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            if (entry / BOX_DEF_NAME).exists():
                result.append(entry)
            result.extend(_find_box_folders(entry))
    except PermissionError:
        pass
    return result


def scan_boxes(song_root: Path) -> list[BoxFolder]:
    if not song_root.exists():
        return []
    boxes: list[BoxFolder] = []
    for folder in _find_box_folders(song_root):
        title = read_box_def(folder / BOX_DEF_NAME)
        box = BoxFolder(title=title, folder=folder)
        for song_file in find_song_files_recursive(folder):
            song = parse_song_file(song_file)
            if song:
                box.songs.append(song)
        boxes.append(box)
    return boxes


# ── dan.def / dan.json Scanner ─────────────────────────────────

DAN_DEF_NAME = "dan.def"
DAN_JSON_NAME = "dan.json"


def read_dan_def(dan_def_path: Path) -> str:
    try:
        text = dan_def_path.read_text("utf-8-sig").strip()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#TITLE:"):
                return line[len("#TITLE:"):].strip()
    except Exception:
        pass
    return dan_def_path.parent.name


def read_dan_json(dan_json_path: Path) -> dict:
    try:
        return json.loads(dan_json_path.read_text("utf-8-sig"))
    except Exception:
        return {}


def parse_dan_entry(dan_folder: Path) -> DanEntry | None:
    dan_json_path = dan_folder / DAN_JSON_NAME
    if not dan_json_path.exists():
        return None
    data = read_dan_json(dan_json_path)
    title = str(data.get("title", dan_folder.name))
    entry = DanEntry(title=title, folder=dan_folder)

    for song_item in data.get("danSongs", []):
        if not isinstance(song_item, dict):
            continue
        rel_path = str(song_item.get("path", ""))
        difficulty = int(song_item.get("difficulty", 0))
        genre = str(song_item.get("genre", ""))
        is_hidden = bool(song_item.get("isHidden", False))

        ref = DanSongRef(
            path=rel_path,
            difficulty=difficulty,
            genre=genre,
            is_hidden=is_hidden,
        )
        song_path = (dan_folder / rel_path).resolve()
        if song_path.exists():
            song = parse_song_file(song_path)
            if song:
                song.genre = genre
                if course := next(iter(song.courses), None):
                    course.level = difficulty
                ref.song = song
        entry.dan_songs.append(ref)

    return entry


def _find_dan_folders(root: Path) -> list[Path]:
    """Recursively find all folders containing dan.def under root."""
    result: list[Path] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            if (entry / DAN_DEF_NAME).exists():
                result.append(entry)
            result.extend(_find_dan_folders(entry))
    except PermissionError:
        pass
    return result


def scan_dan_categories(song_root: Path) -> list[DanCategory]:
    if not song_root.exists():
        return []
    categories: list[DanCategory] = []
    for folder in _find_dan_folders(song_root):
        title = read_dan_def(folder / DAN_DEF_NAME)
        cat = DanCategory(title=title, folder=folder)
        for sub in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if not sub.is_dir():
                continue
            dan_entry = parse_dan_entry(sub)
            if dan_entry:
                cat.dans.append(dan_entry)
        categories.append(cat)
    return categories


# ── ZIP / OSZ Import ───────────────────────────────────────────

def extract_to_folder(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()

    resolved_path = zip_path.resolve()
    ext = resolved_path.suffix.lower()

    if ext == ".osz":
        import tempfile
        import shutil
        zip_path = Path(tempfile.mktemp(suffix=".zip"))
        shutil.copy2(resolved_path, zip_path)

    try:
        with zipfile.ZipFile(str(zip_path), "r") as archive:
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
    finally:
        if ext == ".osz" and zip_path != resolved_path:
            zip_path.unlink(missing_ok=True)


def ensure_box_def(folder: Path, title: str = "") -> None:
    box_def = folder / "box.def"
    if not box_def.exists():
        name = title or folder.name
        box_def.write_text(f"#TITLE:{name}\n", encoding="utf-8", newline="\n")
