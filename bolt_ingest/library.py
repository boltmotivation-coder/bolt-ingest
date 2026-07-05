"""Per-ingest-folder library index (.bolt_library.json).

Remembers every clip bolt has downloaded (video + range -> filename, height),
so reruns skip what's already there and only re-download when the platform
now offers better quality — overwriting the same file, no "(1)" copies.
"""

import json
import re
from pathlib import Path

INDEX_NAME = ".bolt_library.json"

_YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([\w-]{11})")


def video_key(url: str) -> str:
    """Stable identity for a video: YouTube id when present (survives &pp= and
    other tracking junk), otherwise the URL sans query string."""
    m = _YT_ID.search(url)
    if m:
        return f"yt:{m.group(1)}"
    return url.split("?")[0].split("#")[0].rstrip("/")


def range_key(rng) -> str:
    return f"{rng[0]}-{rng[1]}" if rng else "full"


def load(ingest: Path) -> dict:
    try:
        return json.loads((ingest / INDEX_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(ingest: Path, lib: dict):
    try:
        (ingest / INDEX_NAME).write_text(json.dumps(lib, indent=1), encoding="utf-8")
    except OSError:
        pass


def lookup(lib: dict, ingest: Path, url: str, rng):
    """Existing entry for this video+range whose file is still on disk, or None.
    (If the editor deleted the clip, we just download it again.)"""
    entry = lib.get(f"{video_key(url)}|{range_key(rng)}")
    if entry and entry.get("file") and (ingest / entry["file"]).exists():
        return entry
    return None


def record(lib: dict, url: str, rng, filename: str, height):
    lib[f"{video_key(url)}|{range_key(rng)}"] = {
        "file": filename, "height": int(height or 0),
    }
