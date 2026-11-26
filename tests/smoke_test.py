"""Headless smoke test for the analysis + export pipeline."""
import os
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clipper.analyzer import HighlightAnalyzer
from auto_clipper.exporter import ClipExporter
from auto_clipper.ffmpeg import FFMpeg


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, "sample.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=24",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=24",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                "-shortest", source,
            ],
            check=True,
        )

        ffmpeg = FFMpeg()
        print("ffmpeg:", ffmpeg.info())
        assert ffmpeg.available, "ffmpeg/ffprobe not found"
        meta = ffmpeg.probe(source)
        print("probe:", meta)
        assert meta["duration"] > 20

        moments = HighlightAnalyzer(
            ffmpeg, threading.Event(), lambda p, s: print(f"  {p:3d}% {s}")
        ).analyze(
            source, meta["duration"], meta["has_audio"],
            clip_length=4, max_clips=3, sensitivity=0.6,
        )
        print("moments:", [m.as_dict() for m in moments])
        assert len(moments) >= 1

        out = os.path.join(folder, "clips")
        exported = ClipExporter(ffmpeg, threading.Event(), lambda p, s: None).export_all(
            source, moments, out, accurate=True
        )
        print("exported:", [item["filename"] for item in exported])
        assert len(exported) == len(moments)
        assert all(os.path.getsize(item["output"]) > 1000 for item in exported)
        print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
