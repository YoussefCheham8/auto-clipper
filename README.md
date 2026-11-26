# Auto-Clipper

A Windows desktop app that finds the most exciting moments in a video automatically and exports them as ready-to-share clips.

<img width="2560" height="1440" alt="Capture" src="https://github.com/user-attachments/assets/3eb6702f-6cb7-4433-8324-aecbd029052b" />


![Auto-Clipper](assets/app.ico)

## What it does

1. Drop a video (or click **Choose video**).
2. Adjust clip length, number of clips and sensitivity.
3. Click **Find best moments**. Auto-Clipper scans:
   - audio energy peaks (cheers, outbursts, loud dialogue),
   - visual motion and scene changes (action, cuts),
   - and combines them into a highlight score for every candidate window.
4. Preview the ranked moments with generated thumbnails.
5. Click **Export all clips** to save MP4 files into the output folder.

Everything runs locally. Nothing is uploaded anywhere.

## Download / run

<img width="2560" height="1440" alt="2Capture" src="https://github.com/user-attachments/assets/22dbb88a-01be-4921-b283-08b87bde5956" />

The built executable is at:

```
dist\Auto-Clipper.exe
```

Double-click it to start. On first launch Windows may show a "Windows protected your PC" warning — choose **More info → Run anyway** (the app is unsigned because it was built locally).

## Requirements

- Windows 10/11 with WebView2 (installed by default with Edge).
- **FFmpeg + ffprobe** on `PATH` or installed in a common location. If Auto-Clipper shows "FFmpeg missing", either:
  - install FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html) and add its `bin` folder to `PATH`, or
  - place `ffmpeg.exe` and `ffprobe.exe` in a `bin` folder next to `Auto-Clipper.exe`, or
  - set the full path to `ffmpeg.exe` via the app's log/settings (`%APPDATA%\Auto-Clipper\settings.json`, key `ffmpeg_path`).

## Build from source

```bat
build.bat
```

Or manually:

```bat
pip install -r requirements.txt
pyinstaller --noconfirm --clean Auto-Clipper.spec
```

The installer output is a single file: `dist\Auto-Clipper.exe`.

## Project layout

| Path | Purpose |
| --- | --- |
| `main.py` | Entry point: creates the native window |
| `auto_clipper/api.py` | Python ↔ JavaScript bridge, background jobs, settings |
| `auto_clipper/analyzer.py` | Audio/motion scanning and highlight scoring |
| `auto_clipper/exporter.py` | FFmpeg clip cutting and highlight report |
| `auto_clipper/ffmpeg.py` | Binary discovery, probing and subprocess helpers |
| `ui/` | HTML/CSS/JS interface rendered in WebView2 |
| `tests/` | Headless pipeline and UI bridge tests |

## Settings

Settings are stored in `%APPDATA%\Auto-Clipper\settings.json`:

```json
{
  "clip_length": 20,
  "max_clips": 5,
  "sensitivity": 65,
  "accurate": true,
  "output_dir": "",
  "ffmpeg_path": ""
}
```

- **Precise cuts** re-encodes each clip with `libx264`/`aac` for frame-accurate trims. Turn it off for a much faster stream copy (clip boundaries snap to keyframes).
- **Sensitivity** controls how strict the highlight selection is and how much separation is required between clips.

## Tests

```bat
python tests/smoke_test.py
python tests/ui_bridge_test.py
```
