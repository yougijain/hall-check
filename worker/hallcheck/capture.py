"""Pulling one frame out of a live stream, and getting rid of it afterwards.

Everything here is built around a single constraint: the frame exists in memory
for the duration of one inference call and then stops existing. There is no
argument that writes it to disk, no debug flag that dumps it, and no return
path that hands it to a caller outside a context manager that will clean it up.

The mechanism is ffmpeg reading the HLS stream, emitting exactly one frame to
stdout as an uncompressed bitmap, and exiting. Uncompressed because the pipe is
local and free while CPU on a free tier is not - there is no reason to pay for
a PNG deflate we immediately undo.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

log = logging.getLogger(__name__)

#: Resolved stream URLs are signed and expire. Half an hour is well inside the
#: shortest expiry we have seen and long enough that resolution is not on the
#: hot path of every capture.
RESOLVE_TTL_SECONDS = 1800

#: Extensions and schemes ffmpeg can open directly, so yt-dlp is not involved.
_DIRECT_MEDIA_HINTS = (".m3u8", ".mpd", ".mp4", ".ts", "rtsp://", "rtmp://", "udp://")

_resolved_cache: dict[str, tuple[str, float]] = {}


class CaptureError(RuntimeError):
    """A frame could not be obtained. The tick is skipped; nothing is written."""


def _looks_direct(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in _DIRECT_MEDIA_HINTS)


def resolve_stream_url(url: str, *, now: float | None = None) -> str:
    """Turn a watch page into something ffmpeg can open.

    Direct media URLs pass through untouched. Anything else goes through yt-dlp
    once and is cached, because resolution costs a round trip to the host and
    the answer is good for hours.
    """
    if _looks_direct(url):
        return url

    clock = time.monotonic() if now is None else now
    cached = _resolved_cache.get(url)
    if cached is not None and cached[1] > clock:
        return cached[0]

    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise CaptureError(
            f"{url} is not a direct media URL and yt-dlp is not installed to resolve it"
        ) from exc

    options = {"quiet": True, "no_warnings": True, "skip_download": True, "format": "best"}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info: Any = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp raises a wide family of its own errors
        raise CaptureError(f"could not resolve stream URL {url}: {exc}") from exc

    resolved = (info or {}).get("url")
    if not resolved:
        raise CaptureError(f"yt-dlp returned no playable URL for {url}")

    _resolved_cache[url] = (resolved, clock + RESOLVE_TTL_SECONDS)
    return resolved


def clear_resolution_cache() -> None:
    """Drop cached stream URLs. Call after a capture failure that smells like expiry."""
    _resolved_cache.clear()


def _ffmpeg_command(url: str) -> list[str]:
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        # Live HLS: start from the most recent segment rather than replaying
        # the DVR window from its beginning.
        "-fflags",
        "nobuffer",
        "-i",
        url,
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "bmp",
        "pipe:1",
    ]


def _grab_encoded(url: str, timeout: int) -> bytes:
    if shutil.which("ffmpeg") is None:
        raise CaptureError("ffmpeg is not on PATH; the worker cannot capture frames without it")

    try:
        completed = subprocess.run(
            _ffmpeg_command(url),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"ffmpeg did not produce a frame within {timeout}s") from exc

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip() or "no stderr"
        raise CaptureError(f"ffmpeg exited {completed.returncode}: {detail}")
    if not completed.stdout:
        raise CaptureError("ffmpeg exited cleanly but produced no frame data")
    return completed.stdout


def _decode(buffer: bytes) -> np.ndarray:
    import cv2
    import numpy as np

    frame = cv2.imdecode(np.frombuffer(buffer, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise CaptureError("frame data could not be decoded as an image")
    return frame


@contextmanager
def capture_frame(stream_url: str, *, timeout: int = 30) -> Iterator[np.ndarray]:
    """Yield exactly one frame, then destroy it.

    The array is overwritten with zeros on the way out rather than merely
    dereferenced, so the pixels are gone at the moment the block ends instead of
    whenever the allocator gets around to reusing the pages. The encoded buffer
    ffmpeg wrote is immutable and cannot be scrubbed in place; it is dropped
    here and is unreachable once this function returns.

    The frame must not escape the `with` block. Anything the caller needs to
    keep has to be reduced to a number inside it.
    """
    resolved = resolve_stream_url(stream_url)
    encoded = _grab_encoded(resolved, timeout)
    frame = _decode(encoded)
    del encoded

    try:
        yield frame
    finally:
        frame.fill(0)
