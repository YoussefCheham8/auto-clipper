from __future__ import annotations

import webview


VIDEO_FILTER = "Video / audio files (*.mp4;*.mkv;*.mov;*.webm;*.avi;*.m4v;*.flv;*.wmv;*.mp3;*.wav;*.m4a)"
ALL_FILTER = "All files (*.*)"


def run_on_gui(window, func):
    """Execute a dialog callback on the WinForms UI thread when available."""
    try:
        from System import Func, Type
        from webview.platforms.winforms import BrowserView

        instance = BrowserView.instances.get(getattr(window, "uid", None))
        if instance is not None:
            holder: dict = {}

            def _work() -> None:
                try:
                    holder["value"] = func()
                except Exception as exc:  # pragma: no cover - UI callback
                    holder["error"] = exc

            instance.Invoke(Func[Type](_work))
            if "error" in holder:
                raise holder["error"]
            return holder.get("value")
    except ImportError:
        pass
    return func()


def browse_file(window) -> str:
    selection = run_on_gui(
        window,
        lambda: window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(VIDEO_FILTER, ALL_FILTER),
        ),
    )
    if not selection:
        return ""
    return str(selection[0])


def browse_folder(window) -> str:
    selection = run_on_gui(
        window,
        lambda: window.create_file_dialog(
            webview.FileDialog.FOLDER, allow_multiple=False
        ),
    )
    if not selection:
        return ""
    return str(selection[0])
