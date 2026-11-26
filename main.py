from __future__ import annotations

import logging
import os
import sys

import webview

from auto_clipper.api import Api
from auto_clipper.utils import resource_path

LOG_FILE = os.path.join(os.environ.get("APPDATA", "."), "Auto-Clipper", "app.log")


def configure_logging() -> None:
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.WARNING)


def main() -> None:
    configure_logging()
    api = Api()
    window = webview.create_window(
        "Auto-Clipper",
        resource_path(os.path.join("ui", "index.html")),
        js_api=api,
        width=1240,
        height=860,
        min_size=(940, 680),
        resizable=True,
        background_color="#0b0d1a",
        text_select=True,
    )
    api.attach_window(window)
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    main()
