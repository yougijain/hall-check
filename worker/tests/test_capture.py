"""Capture mechanics, with ffmpeg and the network stubbed out."""

from __future__ import annotations

import numpy as np
import pytest

from hallcheck import capture
from hallcheck.capture import CaptureError, capture_frame, resolve_stream_url


@pytest.fixture(autouse=True)
def _clear_cache():
    capture.clear_resolution_cache()
    yield
    capture.clear_resolution_cache()


@pytest.fixture
def stub_grab(monkeypatch):
    """Replace ffmpeg and image decoding with a frame of known content."""

    def _install(frame: np.ndarray):
        monkeypatch.setattr(capture, "_grab_encoded", lambda url, timeout: b"encoded-bmp")
        monkeypatch.setattr(capture, "_decode", lambda buffer: frame)
        return frame

    return _install


class TestResolveStreamUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://cdn.example.edu/worcester/index.m3u8",
            "https://cdn.example.edu/live/stream.mp4",
            "rtsp://camera.example.edu/worcester",
        ],
    )
    def test_direct_media_urls_are_passed_straight_through(self, url):
        # No yt_dlp stub is installed here on purpose: if resolution were
        # attempted, the import inside resolve_stream_url would fail and this
        # test would error rather than pass.
        assert resolve_stream_url(url) == url
        assert capture._resolved_cache == {}, "a direct URL should not be cached"

    def test_page_urls_are_resolved_and_cached(self, monkeypatch):
        calls = []

        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def extract_info(self, url, download):
                calls.append(url)
                return {"url": "https://cdn.example.edu/resolved.m3u8"}

        monkeypatch.setitem(
            __import__("sys").modules, "yt_dlp", type("m", (), {"YoutubeDL": FakeYoutubeDL})
        )

        page = "https://www.example.edu/dining/worcester-live"
        assert resolve_stream_url(page, now=0.0) == "https://cdn.example.edu/resolved.m3u8"
        assert resolve_stream_url(page, now=10.0) == "https://cdn.example.edu/resolved.m3u8"
        assert calls == [page], "second call should have been served from the cache"

    def test_cache_expires(self, monkeypatch):
        seen = []

        class FakeYoutubeDL:
            def __init__(self, options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def extract_info(self, url, download):
                seen.append(url)
                return {"url": f"https://cdn.example.edu/{len(seen)}.m3u8"}

        monkeypatch.setitem(
            __import__("sys").modules, "yt_dlp", type("m", (), {"YoutubeDL": FakeYoutubeDL})
        )

        page = "https://www.example.edu/dining/franklin-live"
        first = resolve_stream_url(page, now=0.0)
        second = resolve_stream_url(page, now=capture.RESOLVE_TTL_SECONDS + 1)
        assert first != second
        assert len(seen) == 2


class TestCaptureFrame:
    def test_yields_the_decoded_frame(self, stub_grab):
        stub_grab(np.full((4, 4, 3), 200, dtype=np.uint8))
        with capture_frame("https://cdn.example.edu/a.m3u8") as captured:
            assert captured.shape == (4, 4, 3)
            assert int(captured.max()) == 200

    def test_frame_is_zeroed_on_exit(self, stub_grab):
        """The privacy rule, at the level of the actual bytes."""
        frame = stub_grab(np.full((8, 8, 3), 255, dtype=np.uint8))
        with capture_frame("https://cdn.example.edu/a.m3u8"):
            assert frame.any(), "precondition: the frame has content inside the block"
        assert not frame.any(), "pixels survived the context manager"

    def test_frame_is_zeroed_even_when_the_body_raises(self, stub_grab):
        frame = stub_grab(np.full((8, 8, 3), 255, dtype=np.uint8))
        with pytest.raises(ZeroDivisionError), capture_frame("https://cdn.example.edu/a.m3u8"):
            _ = 1 / 0
        assert not frame.any(), "a failure inside the block must not leave pixels behind"

    def test_undecodable_data_raises(self, monkeypatch):
        monkeypatch.setattr(capture, "_grab_encoded", lambda url, timeout: b"not-an-image")
        with (
            pytest.raises(CaptureError, match="could not be decoded"),
            capture_frame("https://cdn.example.edu/a.m3u8"),
        ):
            pass


class TestGrabEncoded:
    def test_missing_ffmpeg_is_a_clear_error(self, monkeypatch):
        monkeypatch.setattr(capture.shutil, "which", lambda _name: None)
        with pytest.raises(CaptureError, match="ffmpeg is not on PATH"):
            capture._grab_encoded("https://cdn.example.edu/a.m3u8", timeout=5)

    def test_ffmpeg_failure_surfaces_stderr(self, monkeypatch):
        class Completed:
            returncode = 1
            stdout = b""
            stderr = b"Server returned 404 Not Found"

        monkeypatch.setattr(capture.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(capture.subprocess, "run", lambda *a, **k: Completed())
        with pytest.raises(CaptureError, match="404 Not Found"):
            capture._grab_encoded("https://cdn.example.edu/a.m3u8", timeout=5)

    def test_empty_output_is_an_error_not_an_empty_frame(self, monkeypatch):
        class Completed:
            returncode = 0
            stdout = b""
            stderr = b""

        monkeypatch.setattr(capture.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(capture.subprocess, "run", lambda *a, **k: Completed())
        with pytest.raises(CaptureError, match="no frame data"):
            capture._grab_encoded("https://cdn.example.edu/a.m3u8", timeout=5)

    def test_timeout_is_reported_with_the_limit(self, monkeypatch):
        import subprocess

        def timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30)

        monkeypatch.setattr(capture.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(capture.subprocess, "run", timeout)
        with pytest.raises(CaptureError, match="within 30s"):
            capture._grab_encoded("https://cdn.example.edu/a.m3u8", timeout=30)
