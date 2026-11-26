"""Verify the bundled UI loads and the pywebview JS bridge responds."""
import os
import sys
import time

import webview

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clipper.api import Api
from auto_clipper.utils import resource_path


def check(window: webview.Window) -> None:
    try:
        if not window.events.loaded.wait(20):
            raise RuntimeError("window never loaded")
        time.sleep(1.5)
        print("title:", window.title)
        print("dom ready:", window.evaluate_js("document.readyState"))
        print("drop zone:", window.evaluate_js("!!document.getElementById('drop-zone')"))
        print("api methods:", window.evaluate_js("typeof window.pywebview.api.analyze"))
        window.run_js("window.pywebview.api.get_state().then(r => window.__state = r)")
        time.sleep(1.0)
        state = window.evaluate_js("window.__state && JSON.stringify(window.__state)")
        print("bridge state:", (state or "")[:220])
        assert state and '"status"' in state
        print("UI BRIDGE TEST PASSED")
    except Exception as exc:
        print("UI BRIDGE TEST FAILED:", exc)
    finally:
        sys.stdout.flush()
        window.destroy()
        time.sleep(0.5)
        os._exit(0)


def main() -> None:
    api = Api()
    window = webview.create_window(
        "Auto-Clipper test",
        resource_path(os.path.join("ui", "index.html")),
        js_api=api,
        width=1000,
        height=700,
    )
    api.attach_window(window)
    webview.start(check, args=window)


if __name__ == "__main__":
    main()
