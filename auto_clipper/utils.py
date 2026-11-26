from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".wmv",
    ".mpg", ".mpeg", ".3gp", ".ts", ".m2ts", ".vob", ".ogv", ".m4a",
    ".mp3", ".wav", ".flac", ".aac", ".ogg",
}


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def resource_path(relative: str) -> str:
    """Resolve a bundled asset path in both source and PyInstaller builds."""
    if is_frozen():
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), relative)


def human_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def human_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def is_video_file(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def file_info(path: str) -> dict:
    stat = os.stat(path)
    return {
        "name": os.path.basename(path),
        "path": os.path.abspath(path),
        "size": stat.st_size,
        "size_text": human_size(stat.st_size),
    }


def image_data_url(path: str) -> str:
    """Read a small image and return a base64 data URL for the web UI."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
    except OSError:
        return ""


def safe_name(name: str) -> str:
    keep = "-_.() "
    return "".join(c if c.isalnum() or c in keep else "_" for c in name).strip() or "video"
