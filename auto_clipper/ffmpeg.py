from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .utils import human_time


class FFMpegError(RuntimeError):
    pass


def _candidate_dirs() -> list[str]:
    dirs: list[str] = []
    env = os.environ.get("AUTOCLIPPER_FFMPEG_DIR")
    if env:
        dirs.append(env)
    local = Path(__file__).resolve().parent.parent / "bin"
    dirs.append(str(local))
    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    for root in (program_files, program_files_x86, local_appdata):
        if not root:
            continue
        for name in ("ffmpeg", "FFmpeg", "ffmpeg-full_build", "Gyan.FFmpeg"):
            dirs.append(os.path.join(root, name, "bin"))
        # winget / scoop style install locations
        dirs.append(os.path.join(root, "Microsoft.WinGet", "Gyan.FFmpeg"))
    dirs.extend(
        [
            r"C:\ffmpeg\bin",
            r"C:\ProgramData\chocolatey\bin",
            r"C:\Users\poste\AppData\Local\Microsoft\WinGet\Packages",
        ]
    )
    return dirs


def find_binary(name: str, override: str | None = None) -> str | None:
    """Locate ffmpeg/ffprobe on PATH, in a configured folder, or common installs."""
    if override and os.path.isfile(override):
        return os.path.abspath(override)
    env_key = "AUTOCLIPPER_FFMPEG" if name == "ffmpeg" else "AUTOCLIPPER_FFPROBE"
    env_path = os.environ.get(env_key)
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)
    found = shutil.which(name)
    if found:
        return os.path.abspath(found)
    exe = name + (".exe" if os.name == "nt" else "")
    for directory in _candidate_dirs():
        direct = os.path.join(directory, exe)
        if os.path.isfile(direct):
            return os.path.abspath(direct)
        if os.path.isdir(directory):
            for root, _dirs, files in os.walk(directory):
                if exe in files:
                    return os.path.abspath(os.path.join(root, exe))
                # avoid crawling deep into unrelated trees
                if root.count(os.sep) - directory.count(os.sep) > 3:
                    _dirs[:] = []
    return None


class FFMpeg:
    def __init__(self, ffmpeg_path: str | None = None, ffprobe_path: str | None = None):
        self.ffmpeg_path = find_binary("ffmpeg", ffmpeg_path)
        self.ffprobe_path = find_binary("ffprobe", ffprobe_path)
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._cancelled = threading.Event()

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg_path and self.ffprobe_path)

    def info(self) -> dict:
        version = ""
        if self.ffmpeg_path:
            try:
                out = subprocess.run(
                    [self.ffmpeg_path, "-version"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.splitlines()
                version = out[0] if out else ""
            except Exception:
                pass
        return {
            "available": self.available,
            "ffmpeg": self.ffmpeg_path or "",
            "ffprobe": self.ffprobe_path or "",
            "version": version,
        }

    def set_paths(self, ffmpeg_path: str, ffprobe_path: str | None = None) -> dict:
        if ffmpeg_path:
            self.ffmpeg_path = find_binary("ffmpeg", ffmpeg_path)
        if ffprobe_path:
            self.ffprobe_path = find_binary("ffprobe", ffprobe_path)
        elif self.ffmpeg_path and not self.ffprobe_path:
            sibling = os.path.join(os.path.dirname(self.ffmpeg_path), "ffprobe.exe")
            if os.path.isfile(sibling):
                self.ffprobe_path = sibling
        return self.info()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            proc = self._process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def reset_cancel(self) -> None:
        self._cancelled.clear()

    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def command(self, args: list[str]) -> list[str]:
        if not self.ffmpeg_path:
            raise FFMpegError(
                "FFmpeg was not found. Install FFmpeg (https://ffmpeg.org/download.html) "
                "or set the path in Settings."
            )
        return [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y", *args]

    def probe(self, path: str) -> dict:
        if not self.ffprobe_path:
            raise FFMpegError("ffprobe was not found. Set the FFmpeg path in Settings.")
        cmd = [
            self.ffprobe_path, "-v", "error", "-show_entries",
            "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate",
            "-of", "json", path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise FFMpegError("Timed out while reading the video file.") from exc
        if result.returncode != 0:
            raise FFMpegError(result.stderr.strip() or "Could not read this media file.")
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise FFMpegError("Invalid response from ffprobe.") from exc
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = 0.0
        try:
            duration = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            pass
        if not duration and video:
            duration = _duration_from_stream(video)
        fps = _safe_fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
        return {
            "duration": duration,
            "size": int(fmt.get("size") or 0),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "fps": fps,
            "video_codec": video.get("codec_name", ""),
            "audio_codec": audio.get("codec_name", ""),
            "has_audio": bool(audio),
        }

    def run_stream(
        self,
        args: list[str],
        chunk_size: int = 65536,
        on_bytes: Callable[[bytes], None] | None = None,
    ) -> None:
        """Run ffmpeg and consume binary stdout without buffering it all in memory."""
        cmd = self.command(args)
        with self._lock:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
            )
            self._process = proc
        try:
            assert proc.stdout is not None
            while True:
                if self._cancelled.is_set():
                    proc.terminate()
                    break
                chunk = proc.stdout.read(chunk_size)
                if not chunk:
                    break
                if on_bytes:
                    on_bytes(chunk)
            stderr = proc.stderr.read() if proc.stderr else b""
            proc.wait()
            if proc.returncode != 0 and not self._cancelled.is_set():
                text = stderr.decode("utf-8", "replace").strip()
                raise FFMpegError(text[-600:] or "FFmpeg failed to process the video.")
        finally:
            with self._lock:
                self._process = None
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    def run_quick(self, args: list[str], timeout: int = 300) -> None:
        cmd = self.command(args)
        with self._lock:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self._process = proc
        try:
            _, stderr = proc.communicate(timeout=timeout)
            if proc.returncode != 0 and not self._cancelled.is_set():
                text = stderr.decode("utf-8", "replace").strip() if stderr else ""
                raise FFMpegError(text[-600:] or "FFmpeg failed.")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise FFMpegError("FFmpeg timed out while exporting a clip.")
        finally:
            with self._lock:
                self._process = None

    def thumbnail(self, source: str, at: float, destination: str) -> None:
        stamp = human_time(at)
        self.run_quick(
            [
                "-ss", stamp, "-i", source, "-frames:v", "1",
                "-vf", "scale=480:-2", "-q:v", "4", destination,
            ],
            timeout=60,
        )


def _safe_fps(value) -> float:
    try:
        num, den = str(value).split("/")
        fps = float(num) / float(den)
        if fps != fps or fps <= 0 or fps > 1000:
            return 30.0
        return fps
    except Exception:
        return 30.0


def _duration_from_stream(stream: dict) -> float:
    try:
        return float(stream.get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0
