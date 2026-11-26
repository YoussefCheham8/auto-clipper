from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from .analyzer import HighlightAnalyzer
from .dialogs import browse_file, browse_folder
from .exporter import ClipExporter
from .ffmpeg import FFMpeg, FFMpegError
from .utils import file_info, is_video_file

log = logging.getLogger("autoclipper")

DEFAULTS: dict[str, Any] = {
    "clip_length": 20,
    "max_clips": 5,
    "sensitivity": 65,
    "accurate": True,
    "output_dir": "",
    "ffmpeg_path": "",
}


class Api:
    """Python side of the pywebview JavaScript bridge."""

    def __init__(self) -> None:
        self.ffmpeg = FFMpeg()
        self._window = None
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self.settings = dict(DEFAULTS)
        self.settings.update(self._read_settings())
        if self.settings.get("ffmpeg_path"):
            self.ffmpeg.set_paths(self.settings["ffmpeg_path"])
        self.state: dict[str, Any] = {
            "status": "idle",
            "progress": 0,
            "stage": "",
            "message": "",
            "error": "",
            "source": None,
            "moments": [],
            "exported": [],
            "settings": dict(self.settings),
            "ffmpeg": self.ffmpeg.info(),
        }

    # ------------------------------------------------------------------
    # Window / settings
    # ------------------------------------------------------------------
    def attach_window(self, window) -> None:
        self._window = window
        window.events.loaded += self._on_loaded

    def _on_loaded(self) -> None:
        try:
            from webview.dom import DOMEventHandler

            body = self._window.dom.get_element("body")
            if body is not None:
                body.on("dragover", DOMEventHandler(lambda event: None, prevent_default=True))
                body.on("drop", DOMEventHandler(lambda event: None, prevent_default=True))

            zone = self._window.dom.get_element("#drop-zone")
            if zone is not None:
                zone.on("drop", DOMEventHandler(self._handle_drop, prevent_default=True))
        except Exception:
            log.exception("Could not install drag and drop handlers")

    def _handle_drop(self, event: dict) -> None:
        try:
            files = (event or {}).get("dataTransfer", {}).get("files", [])
            for item in files:
                path = item.get("pywebviewFullPath") or item.get("path")
                if path:
                    self.load_file(path)
                    break
        except Exception:
            log.exception("Drop handling failed")

    def _settings_file(self) -> str:
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(root, "Auto-Clipper")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "settings.json")

    def _read_settings(self) -> dict:
        try:
            with open(self._settings_file(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _persist_settings(self) -> None:
        try:
            with open(self._settings_file(), "w", encoding="utf-8") as handle:
                json.dump(self.settings, handle, indent=2)
        except OSError:
            pass

    def update_settings(self, options: dict | None = None) -> dict:
        options = options or {}
        for key in ("clip_length", "max_clips", "sensitivity", "accurate", "output_dir"):
            if key in options:
                self.settings[key] = options[key]
        with self._lock:
            self.state["settings"] = dict(self.settings)
        self._persist_settings()
        return {"ok": True, "settings": dict(self.settings)}

    def set_ffmpeg_path(self, path: str) -> dict:
        info = self.ffmpeg.set_paths(path)
        self.settings["ffmpeg_path"] = self.ffmpeg.ffmpeg_path or ""
        with self._lock:
            self.state["ffmpeg"] = info
            self.state["settings"] = dict(self.settings)
        self._persist_settings()
        return {"ok": info["available"], "ffmpeg": info}

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def get_state(self) -> dict:
        with self._lock:
            return dict(self.state)

    def get_health(self) -> dict:
        return self.ffmpeg.info()

    def _set(self, **changes) -> None:
        with self._lock:
            self.state.update(changes)

    def _progress(self, value: int, stage: str) -> None:
        with self._lock:
            self.state["progress"] = int(max(0, min(100, value)))
            self.state["stage"] = stage

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------
    def browse_file(self) -> dict:
        if not self._window:
            return {"ok": False, "error": "Window is not ready."}
        path = browse_file(self._window)
        if not path:
            return {"ok": False, "cancelled": True}
        return self.load_file(path)

    def browse_output_folder(self) -> dict:
        if not self._window:
            return {"ok": False, "error": "Window is not ready."}
        path = browse_folder(self._window)
        if not path:
            return {"ok": False, "cancelled": True}
        return self.update_settings({"output_dir": path})

    def load_file(self, path: str) -> dict:
        try:
            path = os.path.abspath(str(path).strip().strip('"'))
            if not os.path.isfile(path):
                return {"ok": False, "error": "That file does not exist."}
            if not is_video_file(path):
                return {"ok": False, "error": "Unsupported file type. Choose a video or audio file."}
            if not self.ffmpeg.available:
                self.ffmpeg.set_paths(self.settings.get("ffmpeg_path", ""))
            if not self.ffmpeg.available:
                return {
                    "ok": False,
                    "error": "FFmpeg is missing. Install FFmpeg or set its path in Settings.",
                }
            meta = self.ffmpeg.probe(path)
            if meta["duration"] <= 0:
                return {"ok": False, "error": "This file has no readable media stream."}
            source = file_info(path)
            source.update(meta)
            self._set(
                source=source,
                moments=[],
                exported=[],
                status="idle",
                progress=0,
                stage="",
                message="Ready to analyse",
                error="",
            )
            if not self.settings.get("output_dir"):
                folder = os.path.join(os.path.dirname(path), "AutoClipper_Clips")
                self.update_settings({"output_dir": folder})
            return {"ok": True, "source": source}
        except FFMpegError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("load_file failed")
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def analyze(self, options: dict | None = None) -> dict:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"ok": False, "error": "A task is already running."}
            source = self.state["source"]
        if not source:
            return {"ok": False, "error": "Choose a video first."}
        self.update_settings(options)
        self.ffmpeg.reset_cancel()
        self._set(
            status="analyzing", progress=0, stage="Starting…",
            message="Finding your best moments", error="", moments=[], exported=[],
        )
        self._worker = threading.Thread(
            target=self._analyze_worker, args=(dict(source),), daemon=True
        )
        self._worker.start()
        return {"ok": True}

    def _analyze_worker(self, source: dict) -> None:
        try:
            analyzer = HighlightAnalyzer(
                self.ffmpeg, self.ffmpeg._cancelled, self._progress
            )
            moments = analyzer.analyze(
                source=source["path"],
                duration=float(source["duration"]),
                has_audio=bool(source.get("has_audio")),
                clip_length=float(self.settings["clip_length"]),
                max_clips=int(self.settings["max_clips"]),
                sensitivity=float(self.settings["sensitivity"]) / 100.0,
            )
            self._set(
                status="ready",
                progress=100,
                stage="Complete",
                message=f"Found {len(moments)} highlight moments",
                moments=[moment.as_dict() for moment in moments],
                exported=[],
            )
        except InterruptedError:
            self._set(status="idle", progress=0, stage="", message="Analysis cancelled")
        except Exception as exc:
            log.exception("analysis failed")
            self._set(status="error", error=str(exc), stage="", message="Analysis failed")
        finally:
            self._worker = None

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_clips(self, options: dict | None = None) -> dict:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"ok": False, "error": "A task is already running."}
            source = self.state["source"]
            stored = [dict(item) for item in self.state["moments"]]
        if not source or not stored:
            return {"ok": False, "error": "Find highlight moments first."}
        self.update_settings(options)
        from .analyzer import Moment

        moments = [
            Moment(
                index=int(item["index"]),
                start=float(item["start"]),
                end=float(item["end"]),
                duration=float(item["duration"]),
                score=int(item["score"]),
                reasons=list(item.get("reasons", [])),
                thumbnail=item.get("thumbnail", ""),
            )
            for item in stored
        ]
        output_dir = self.settings.get("output_dir") or os.path.join(
            os.path.dirname(source["path"]), "AutoClipper_Clips"
        )
        self.ffmpeg.reset_cancel()
        self._set(
            status="exporting", progress=0, stage="Preparing…",
            message="Exporting clips", error="",
        )
        self._worker = threading.Thread(
            target=self._export_worker,
            args=(source["path"], moments, output_dir),
            daemon=True,
        )
        self._worker.start()
        return {"ok": True}

    def _export_worker(self, source_path: str, moments, output_dir: str) -> None:
        try:
            exporter = ClipExporter(
                self.ffmpeg, self.ffmpeg._cancelled, self._progress
            )
            exported = exporter.export_all(
                source_path,
                moments,
                output_dir,
                accurate=bool(self.settings["accurate"]),
            )
            self._set(
                status="done",
                progress=100,
                stage="Complete",
                message=f"{len(exported)} clips saved",
                exported=exported,
            )
        except InterruptedError:
            self._set(status="ready", progress=0, stage="", message="Export cancelled")
        except Exception as exc:
            log.exception("export failed")
            self._set(status="error", error=str(exc), stage="", message="Export failed")
        finally:
            self._worker = None

    # ------------------------------------------------------------------
    # Utility actions
    # ------------------------------------------------------------------
    def cancel(self) -> dict:
        self.ffmpeg.cancel()
        self._set(stage="Cancelling…")
        return {"ok": True}

    def open_folder(self) -> dict:
        path = self.settings.get("output_dir") or ""
        if not path:
            return {"ok": False, "error": "No output folder selected."}
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_clip(self, index: int) -> dict:
        with self._lock:
            clips = list(self.state["exported"])
        match = next((item for item in clips if item["index"] == int(index)), None)
        if not match or not os.path.isfile(match["output"]):
            return {"ok": False, "error": "Export this clip before playing it."}
        try:
            os.startfile(match["output"])  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def clear(self) -> dict:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"ok": False, "error": "Wait for the current task to finish."}
        self._set(
            status="idle", progress=0, stage="", message="",
            error="", source=None, moments=[], exported=[],
        )
        return {"ok": True}
