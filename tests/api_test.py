"""End-to-end test of the Python API used by the UI."""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clipper.api import Api


def wait_for(api: Api, status: str, timeout: int = 120) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        state = api.get_state()
        if state["status"] == status:
            return state
        if state["status"] == "error":
            raise RuntimeError(state["error"])
        time.sleep(0.2)
    raise TimeoutError(f"status '{status}' not reached; last: {api.get_state()['status']}")


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, "sample.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=18",
                "-f", "lavfi", "-i", "sine=frequency=330:duration=18",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                "-shortest", source,
            ],
            check=True,
        )
        api = Api()
        loaded = api.load_file(source)
        print("load:", {k: loaded[k] for k in ("ok", "source") if k in loaded})
        assert loaded["ok"]

        started = api.analyze({"clip_length": 3, "max_clips": 2, "sensitivity": 70})
        assert started["ok"]
        state = wait_for(api, "ready")
        print("moments:", [(m["index"], m["start"], m["score"]) for m in state["moments"]])
        assert 1 <= len(state["moments"]) <= 2

        output = os.path.join(folder, "out")
        assert api.update_settings({"output_dir": output})["ok"]
        assert api.export_clips({"accurate": False})["ok"]
        state = wait_for(api, "done")
        print("exported:", [item["filename"] for item in state["exported"]])
        assert len(state["exported"]) == len(state["moments"])
        assert all(os.path.getsize(item["output"]) > 1000 for item in state["exported"])
        print("API TEST PASSED")


if __name__ == "__main__":
    main()
