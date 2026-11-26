from __future__ import annotations

import os
import threading
from typing import Callable

from .analyzer import Moment
from .ffmpeg import FFMpeg, FFMpegError
from .utils import human_time


class ClipExporter:
    def __init__(
        self,
        ffmpeg: FFMpeg,
        cancel: threading.Event,
        on_progress: Callable[[int, str], None],
    ):
        self.ffmpeg = ffmpeg
        self.cancel = cancel
        self.on_progress = on_progress

    def export_all(
        self,
        source: str,
        moments: list[Moment],
        output_dir: str,
        accurate: bool = True,
    ) -> list[dict]:
        os.makedirs(output_dir, exist_ok=True)
        exported: list[dict] = []
        total = max(1, len(moments))

        for position, moment in enumerate(moments, start=1):
            if self.cancel.is_set():
                raise InterruptedError("cancelled")
            filename = f"clip_{moment.index:02d}_{int(moment.start):04d}s.mp4"
            destination = os.path.join(output_dir, filename)
            self.on_progress(
                int((position - 1) / total * 100),
                f"Exporting clip {position}/{total}…",
            )

            if accurate:
                args = [
                    "-ss", f"{moment.start:.3f}", "-i", source,
                    "-t", f"{moment.duration:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", destination,
                ]
            else:
                args = [
                    "-ss", f"{moment.start:.3f}", "-i", source,
                    "-t", f"{moment.duration:.3f}",
                    "-c", "copy", "-avoid_negative_ts", "make_zero", destination,
                ]
            try:
                self.ffmpeg.run_quick(args, timeout=1800)
            except FFMpegError:
                # Stream copy can fail on unusual keyframe layouts; retry precise mode.
                if accurate:
                    raise
                retry = [
                    "-ss", f"{moment.start:.3f}", "-i", source,
                    "-t", f"{moment.duration:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", destination,
                ]
                self.ffmpeg.run_quick(retry, timeout=1800)

            if not os.path.isfile(destination):
                raise FFMpegError(f"Clip {moment.index} could not be created.")
            item = moment.as_dict()
            item.update({"output": destination, "filename": filename})
            exported.append(item)
            self.on_progress(int(position / total * 100), f"Exported clip {position}/{total}")

        self._write_manifest(source, exported, output_dir)
        self.on_progress(100, f"{len(exported)} clips exported")
        return exported

    @staticmethod
    def _write_manifest(source: str, clips: list[dict], output_dir: str) -> None:
        lines = [
            "AUTO-CLIPPER - Highlight report",
            "=" * 42,
            f"Source: {source}",
            f"Clips:  {len(clips)}",
            "",
        ]
        for clip in clips:
            lines.append(
                f"#{clip['index']:02d}  {clip['start_text']} - {clip['end_text']}  "
                f"score {clip['score']}/100  [{', '.join(clip['reasons'])}]"
            )
            lines.append(f"      {clip['filename']}")
        try:
            with open(os.path.join(output_dir, "highlights.txt"), "w", encoding="utf-8") as report:
                report.write("\n".join(lines) + "\n")
        except OSError:
            pass
