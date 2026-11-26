from __future__ import annotations

import math
import os
import tempfile
import threading
from array import array
from dataclasses import dataclass, field
from typing import Callable

from .ffmpeg import FFMpeg, FFMpegError
from .utils import human_time, image_data_url

AUDIO_RATE = 8000
AUDIO_BUCKET = 0.25
MOTION_FPS = 2
MOTION_W = 96
MOTION_H = 54


@dataclass
class Moment:
    index: int
    start: float
    end: float
    duration: float
    score: int
    reasons: list[str] = field(default_factory=list)
    thumbnail: str = ""
    audio_score: float = 0.0
    motion_score: float = 0.0

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "duration": round(self.duration, 2),
            "start_text": human_time(self.start),
            "end_text": human_time(self.end),
            "score": self.score,
            "reasons": self.reasons,
            "thumbnail": self.thumbnail,
            "filename": f"clip_{self.index:02d}_{int(self.start):04d}s.mp4",
        }


class HighlightAnalyzer:
    """Find the most eventful moments using audio energy and visual motion."""

    def __init__(
        self,
        ffmpeg: FFMpeg,
        cancel: threading.Event,
        on_progress: Callable[[int, str], None],
    ):
        self.ffmpeg = ffmpeg
        self.cancel = cancel
        self.on_progress = on_progress

    def analyze(
        self,
        source: str,
        duration: float,
        has_audio: bool,
        clip_length: float,
        max_clips: int,
        sensitivity: float,
        thumbnails: bool = True,
    ) -> list[Moment]:
        if duration <= 0:
            raise FFMpegError("Could not determine the video duration.")

        clip_length = min(max(2.0, float(clip_length)), duration)
        max_clips = max(1, int(max_clips))
        sensitivity = min(1.0, max(0.0, float(sensitivity)))

        self.on_progress(4, "Scanning audio energy…")
        audio_db = (
            self._audio_profile(source, duration) if has_audio else None
        )
        if self.cancel.is_set():
            raise InterruptedError("cancelled")

        self.on_progress(48, "Scanning visual motion…")
        motion = self._motion_profile(source, duration)
        if self.cancel.is_set():
            raise InterruptedError("cancelled")

        audio_norm = _normalize(audio_db, 3.0) if audio_db else None
        motion_norm = _normalize(motion, 0.02)

        self.on_progress(78, "Scoring highlight candidates…")
        moments = self._select(
            duration=duration,
            clip_length=clip_length,
            max_clips=max_clips,
            sensitivity=sensitivity,
            audio_norm=audio_norm,
            motion_norm=motion_norm,
        )

        if thumbnails:
            self.on_progress(90, "Generating preview thumbnails…")
            for moment in moments:
                if self.cancel.is_set():
                    raise InterruptedError("cancelled")
                moment.thumbnail = self._thumbnail(source, moment)

        self.on_progress(100, "Done")
        return moments

    # ------------------------------------------------------------------
    # Signal extraction
    # ------------------------------------------------------------------
    def _audio_profile(self, source: str, duration: float) -> list[float]:
        expected = max(1.0, duration) * AUDIO_RATE * 2
        samples_per_bucket = int(AUDIO_RATE * AUDIO_BUCKET)
        buckets: list[float] = []
        total = 0
        bucket_sum = 0.0
        in_bucket = 0

        def consume(chunk: bytes) -> None:
            nonlocal total, bucket_sum, in_bucket
            if len(chunk) % 2:
                chunk = chunk[:-1]
            values = array("h")
            values.frombytes(chunk)
            for value in values:
                bucket_sum += float(value * value)
                in_bucket += 1
                total += 1
                if in_bucket >= samples_per_bucket:
                    rms = math.sqrt(bucket_sum / samples_per_bucket) / 32768.0
                    buckets.append(20.0 * math.log10(rms + 1e-8))
                    bucket_sum = 0.0
                    in_bucket = 0
            self.on_progress(min(47, int(total * 2 / max(expected, 1) * 44) + 4), "Scanning audio energy…")

        args = [
            "-i", source, "-vn", "-ac", "1", "-ar", str(AUDIO_RATE),
            "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
        ]
        self.ffmpeg.run_stream(args, chunk_size=32000, on_bytes=consume)
        if in_bucket:
            rms = math.sqrt(bucket_sum / in_bucket) / 32768.0
            buckets.append(20.0 * math.log10(rms + 1e-8))
        return buckets

    def _motion_profile(self, source: str, duration: float) -> list[float]:
        frame_size = MOTION_W * MOTION_H
        expected_frames = max(1.0, duration) * MOTION_FPS
        results: list[float] = []
        previous: bytes | None = None
        seen = 0
        pending = b""

        def consume(chunk: bytes) -> None:
            nonlocal previous, seen, pending
            pending += chunk
            while len(pending) >= frame_size:
                frame = pending[:frame_size]
                pending = pending[frame_size:]
                seen += 1
                if previous is None:
                    results.append(0.0)
                else:
                    diff = sum(abs(a - b) for a, b in zip(frame, previous)) / frame_size
                    results.append(diff / 255.0)
                previous = frame
            self.on_progress(
                min(77, 48 + int(seen / max(expected_frames, 1) * 29)),
                "Scanning visual motion…",
            )

        args = [
            "-i", source, "-an",
            "-vf", f"fps={MOTION_FPS},scale={MOTION_W}:{MOTION_H}:flags=area,format=gray",
            "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
        ]
        self.ffmpeg.run_stream(args, chunk_size=frame_size * 8, on_bytes=consume)
        return results

    # ------------------------------------------------------------------
    # Scoring & selection
    # ------------------------------------------------------------------
    def _select(
        self,
        duration: float,
        clip_length: float,
        max_clips: int,
        sensitivity: float,
        audio_norm: list[float] | None,
        motion_norm: list[float],
    ) -> list[Moment]:
        max_start = max(0.0, duration - clip_length)
        step = 1.0
        min_gap = clip_length * (0.12 + 0.55 * (1.0 - sensitivity))
        min_score = 0.10 + 0.30 * (1.0 - sensitivity)

        candidates: list[dict] = []
        start = 0.0
        while start <= max_start + 0.001:
            a_start = int(start / AUDIO_BUCKET)
            a_end = max(a_start + 1, int((start + clip_length) / AUDIO_BUCKET))
            m_start = int(start * MOTION_FPS)
            m_end = max(m_start + 1, int((start + clip_length) * MOTION_FPS))

            audio_score = (
                _window_score(audio_norm, a_start, a_end) if audio_norm else 0.0
            )
            motion_score = _window_score(motion_norm, m_start, m_end)
            scene_count = sum(
                1 for value in motion_norm[m_start:m_end] if value > 1.0
            )
            scene_score = min(1.0, scene_count / 3.0)

            if audio_norm:
                base = 0.55 * audio_score + 0.30 * motion_score + 0.15 * scene_score
            else:
                base = 0.72 * motion_score + 0.28 * scene_score

            # Avoid leading titles / trailing credits when possible.
            if start < 6.0 or start + clip_length > duration - 6.0:
                base *= 0.88

            candidates.append(
                {
                    "start": start,
                    "score": base,
                    "audio": audio_score,
                    "motion": motion_score,
                    "scenes": scene_count,
                }
            )
            start += step

        # Map scores onto a readable 0-100 range relative to this video's own
        # baseline, so the "best" moment is still meaningful in a uniformly
        # energetic recording.
        raw_scores = [item["score"] for item in candidates]
        baseline = _percentile(raw_scores, 0.50)
        peak = _percentile(raw_scores, 0.95)
        span = max(peak - baseline, 0.02)
        for item in candidates:
            relative = max(0.0, min(1.0, (item["score"] - baseline) / span))
            item["score"] = (0.25 + 0.75 * relative) ** (1.35 - 0.5 * sensitivity)

        candidates.sort(key=lambda item: item["score"], reverse=True)
        chosen: list[dict] = []
        for candidate in candidates:
            if len(chosen) >= max_clips:
                break
            if candidate["score"] < min_score and chosen:
                continue
            if any(
                abs(candidate["start"] - other["start"]) < (clip_length + min_gap)
                for other in chosen
            ):
                continue
            chosen.append(candidate)

        # If the video only has a few eventful sections, still fill the list
        # with the strongest remaining non-overlapping moments.
        if len(chosen) < max_clips:
            for candidate in candidates:
                if len(chosen) >= max_clips:
                    break
                if candidate in chosen:
                    continue
                if any(
                    abs(candidate["start"] - other["start"]) < (clip_length + min_gap)
                    for other in chosen
                ):
                    continue
                if candidate["score"] <= 0.015:
                    continue
                chosen.append(candidate)

        chosen.sort(key=lambda item: item["start"])
        moments: list[Moment] = []
        for rank, candidate in enumerate(chosen, start=1):
            reasons: list[str] = []
            if candidate["audio"] >= 0.55:
                reasons.append("Audio peak")
            if candidate["motion"] >= 0.50:
                reasons.append("Fast action")
            if candidate["scenes"] >= 2:
                reasons.append("Scene change")
            if not reasons:
                reasons.append("Steady highlight")
            if rank == 1:
                reasons.insert(0, "Top moment")

            moments.append(
                Moment(
                    index=rank,
                    start=candidate["start"],
                    end=min(duration, candidate["start"] + clip_length),
                    duration=min(clip_length, duration - candidate["start"]),
                    score=max(1, min(99, int(round(candidate["score"] * 100)))),
                    reasons=reasons[:3],
                    audio_score=candidate["audio"],
                    motion_score=candidate["motion"],
                )
            )
        return moments

    def _thumbnail(self, source: str, moment: Moment) -> str:
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        path = handle.name
        handle.close()
        try:
            self.ffmpeg.thumbnail(source, moment.start + moment.duration * 0.35, path)
            return image_data_url(path)
        except Exception:
            return ""
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _normalize(values: list[float] | None, floor: float) -> list[float]:
    if not values:
        return []
    midpoint = _percentile(values, 0.50)
    high = _percentile(values, 0.90)
    span = max(high - midpoint, floor)
    return [max(0.0, min(1.3, (value - midpoint) / span)) for value in values]


def _window_score(values: list[float], start: int, end: int) -> float:
    segment = values[max(0, start):max(0, end)]
    if not segment:
        return 0.0
    count = max(1, int(len(segment) * 0.22))
    top = sorted(segment, reverse=True)[:count]
    peak = sum(top) / len(top)
    mean = sum(segment) / len(segment)
    return min(1.35, 0.62 * peak + 0.38 * mean)
