"""Shared fixtures and test doubles."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import time

import numpy as np
import pytest

from hallcheck.config import Settings
from hallcheck.models import Hall
from hallcheck.roi import Roi

QUEUE_ROI = Roi(
    version="test-v1",
    vertices=((0.2, 0.2), (0.8, 0.2), (0.8, 0.9), (0.2, 0.9)),
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_url="https://test.supabase.co",
        supabase_service_key="service-key",
        model="yolo11n.pt",
        conf_threshold=0.35,
        interval_seconds=120,
        capture_timeout=30,
    )


@pytest.fixture
def hall() -> Hall:
    return Hall(
        hall_id="worcester",
        name="Worcester Commons",
        stream_url="https://cdn.example.edu/worcester.m3u8",
        roi=QUEUE_ROI,
        camera_epoch=1,
        opens_at=time(7, 0),
        closes_at=time(21, 0),
    )


class FakeDetector:
    """Returns whatever it was told to, or raises whatever it was given."""

    def __init__(self, count: int = 0, error: Exception | None = None) -> None:
        self.count = count
        self.error = error
        self.calls = 0
        self.loaded = False

    @property
    def model_version(self) -> str:
        return "fake@conf0.35"

    def load(self) -> None:
        self.loaded = True

    def count_in_roi(self, frame, roi) -> int:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.count


@pytest.fixture
def fake_frame() -> np.ndarray:
    return np.zeros((64, 64, 3), dtype=np.uint8)


@pytest.fixture
def stub_capture(monkeypatch, fake_frame):
    """Replace the frame source. Returns the list of URLs asked for.

    Both `pipeline` and `labeling` do `from hallcheck.capture import
    capture_frame`, which binds the function into each module at import time.
    Patching only one of them leaves the other talking to a real ffmpeg, so
    every consumer's binding is replaced here.
    """
    from hallcheck import labeling, pipeline

    requested: list[str] = []

    def _install(error: Exception | None = None):
        @contextmanager
        def _capture(stream_url, *, timeout=30):
            requested.append(stream_url)
            if error is not None:
                raise error
            yield fake_frame

        for module in (pipeline, labeling):
            monkeypatch.setattr(module, "capture_frame", _capture)
        return requested

    return _install
