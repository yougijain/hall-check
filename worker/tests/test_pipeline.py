"""Tick behaviour: what gets written, and more importantly what does not."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from hallcheck.capture import CaptureError
from hallcheck.detect import DetectionError
from hallcheck.pipeline import align_timestamp, capture_hall, run_tick
from hallcheck.store import InMemoryStore, StoreError
from tests.conftest import FakeDetector

NOON = datetime(2026, 3, 4, 12, 0, 37, 412000, tzinfo=UTC)


class TestAlignTimestamp:
    def test_snaps_down_to_the_interval_grid(self):
        assert align_timestamp(NOON, 120) == datetime(2026, 3, 4, 12, 0, tzinfo=UTC)

    def test_a_late_tick_still_lands_on_its_own_slot(self):
        late = datetime(2026, 3, 4, 12, 3, 58, tzinfo=UTC)
        assert align_timestamp(late, 120) == datetime(2026, 3, 4, 12, 2, tzinfo=UTC)

    def test_alignment_makes_same_slot_lookups_exact(self):
        """The property M4's baselines depend on.

        Two captures a week apart, each jittered by a different number of
        seconds, must land exactly 7 days apart after alignment - otherwise
        "same slot last week" is a range scan instead of a lookup.
        """
        this_week = align_timestamp(datetime(2026, 3, 4, 12, 0, 3, tzinfo=UTC), 120)
        last_week = align_timestamp(datetime(2026, 2, 25, 12, 1, 59, tzinfo=UTC), 120)
        assert (this_week - last_week).total_seconds() == 7 * 24 * 3600

    def test_output_is_always_utc(self):
        assert align_timestamp(NOON, 120).tzinfo is UTC


class TestCaptureHall:
    def test_a_successful_capture_writes_one_row(self, hall, settings, stub_capture):
        stub_capture()
        store = InMemoryStore([hall])
        detector = FakeDetector(count=17)

        result = capture_hall(hall, detector, store, settings, now=NOON)

        assert result.ok
        assert result.count == 17
        assert len(store.records) == 1
        record = store.records[0]
        assert record.count == 17
        assert record.hall_id == "worcester"
        assert record.ts == datetime(2026, 3, 4, 12, 0, tzinfo=UTC)

    def test_the_row_carries_its_provenance(self, hall, settings, stub_capture):
        stub_capture()
        store = InMemoryStore([hall])
        capture_hall(hall, FakeDetector(count=3), store, settings, now=NOON)

        record = store.records[0]
        assert record.model_version == "fake@conf0.35"
        assert record.conf_threshold == 0.35
        assert record.roi_version == "test-v1"
        assert record.camera_epoch == 1
        assert record.latency_ms is not None and record.latency_ms >= 0

    @pytest.mark.parametrize(
        "failure",
        [CaptureError("stream is down"), DetectionError("inference blew up")],
        ids=["capture", "detection"],
    )
    def test_a_failure_writes_nothing_rather_than_a_zero(
        self, hall, settings, stub_capture, failure
    ):
        """The single most important behaviour in this file.

        A fabricated zero is indistinguishable from an empty dining hall. It
        would teach the M4 forecast that occupancy collapses whenever the
        network is bad, and it would show students an empty hall that has a
        queue out the door.
        """
        if isinstance(failure, CaptureError):
            stub_capture(error=failure)
        else:
            stub_capture()
        store = InMemoryStore([hall])
        detector = FakeDetector(error=failure if isinstance(failure, DetectionError) else None)

        result = capture_hall(hall, detector, store, settings, now=NOON)

        assert not result.ok
        assert result.count is None
        assert store.records == []

    def test_a_genuine_zero_is_recorded(self, hall, settings, stub_capture):
        stub_capture()
        store = InMemoryStore([hall])

        result = capture_hall(hall, FakeDetector(count=0), store, settings, now=NOON)

        assert result.ok
        assert store.records[0].count == 0, "an empty hall is a reading, not a gap"

    def test_a_hall_without_a_stream_url_is_skipped_quietly(self, hall, settings, stub_capture):
        requested = stub_capture()
        store = InMemoryStore([hall])
        unconfigured = replace(hall, stream_url="")

        result = capture_hall(unconfigured, FakeDetector(count=5), store, settings, now=NOON)

        assert not result.ok
        assert "no stream URL" in result.error
        assert requested == [], "capture should not have been attempted"

    def test_a_write_failure_is_reported_without_raising(self, hall, settings, stub_capture):
        stub_capture()

        class BrokenStore(InMemoryStore):
            def record_count(self, record):
                raise StoreError("connection refused")

        result = capture_hall(hall, FakeDetector(count=9), BrokenStore([hall]), settings, now=NOON)

        assert not result.ok
        assert "connection refused" in result.error
        # The count was obtained even though it could not be stored; surfacing
        # it separates "the camera is down" from "the database is down".
        assert result.count == 9

    def test_the_stream_override_is_what_gets_captured(self, hall, settings, stub_capture):
        requested = stub_capture()
        overridden = replace(settings, stream_overrides={"worcester": "https://override/w.m3u8"})

        capture_hall(hall, FakeDetector(count=1), InMemoryStore([hall]), overridden, now=NOON)

        assert requested == ["https://override/w.m3u8"]


class TestRunTick:
    def test_captures_every_active_hall(self, hall, settings, stub_capture):
        stub_capture()
        halls = [
            replace(hall, hall_id="worcester"),
            replace(hall, hall_id="franklin"),
            replace(hall, hall_id="hampshire"),
        ]
        store = InMemoryStore(halls)

        results = run_tick(FakeDetector(count=4), store, settings, now=NOON)

        assert len(results) == 3
        assert all(r.ok for r in results)
        assert {r.hall_id for r in store.records} == {"worcester", "franklin", "hampshire"}

    def test_one_dead_hall_does_not_stop_the_others(self, hall, settings, monkeypatch):
        from contextlib import contextmanager

        from hallcheck import pipeline

        @contextmanager
        def flaky(stream_url, *, timeout=30):
            if "franklin" in stream_url:
                raise CaptureError("stream is down")
            yield object()

        monkeypatch.setattr(pipeline, "capture_frame", flaky)

        halls = [
            replace(hall, hall_id="worcester", stream_url="https://cdn/worcester.m3u8"),
            replace(hall, hall_id="franklin", stream_url="https://cdn/franklin.m3u8"),
            replace(hall, hall_id="hampshire", stream_url="https://cdn/hampshire.m3u8"),
        ]
        store = InMemoryStore(halls)

        results = run_tick(FakeDetector(count=6), store, settings, now=NOON)

        assert [r.ok for r in results] == [True, False, True]
        assert {r.hall_id for r in store.records} == {"worcester", "hampshire"}

    def test_a_failure_to_list_halls_skips_the_tick(self, settings, stub_capture):
        stub_capture()

        class BrokenStore(InMemoryStore):
            def active_halls(self):
                raise StoreError("database unreachable")

        assert run_tick(FakeDetector(), BrokenStore(), settings, now=NOON) == []

    def test_replaying_a_tick_does_not_double_count(self, hall, settings, stub_capture):
        stub_capture()
        store = InMemoryStore([hall])

        run_tick(FakeDetector(count=11), store, settings, now=NOON)
        run_tick(FakeDetector(count=12), store, settings, now=NOON)

        assert len(store.records) == 1, "the same slot must upsert, not accumulate"
        assert store.records[0].count == 12
