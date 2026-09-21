from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from hallcheck.models import CountRecord, Hall
from hallcheck.roi import InvalidRoi

ROW = {
    "hall_id": "worcester",
    "name": "Worcester Commons",
    "stream_url": "https://cdn.example.edu/worcester.m3u8",
    "roi_polygon": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.9], [0.2, 0.9]],
    "roi_version": "v2",
    "camera_epoch": 3,
    "opens_at": "07:00:00",
    "closes_at": "21:00:00",
    "active": True,
}


class TestHallFromRow:
    def test_maps_a_database_row(self):
        hall = Hall.from_row(ROW)
        assert hall.hall_id == "worcester"
        assert hall.camera_epoch == 3
        assert hall.opens_at == time(7, 0)
        assert hall.closes_at == time(21, 0)

    def test_roi_version_travels_with_the_polygon(self):
        assert Hall.from_row(ROW).roi.version == "v2"

    def test_missing_service_hours_are_allowed(self):
        hall = Hall.from_row({**ROW, "opens_at": None, "closes_at": ""})
        assert hall.opens_at is None
        assert hall.closes_at is None

    def test_a_jsonb_string_polygon_is_accepted(self):
        hall = Hall.from_row({**ROW, "roi_polygon": "[[0.2,0.2],[0.8,0.2],[0.8,0.9]]"})
        assert len(hall.roi.vertices) == 3

    def test_a_broken_polygon_raises_rather_than_counting_the_whole_frame(self):
        with pytest.raises(InvalidRoi):
            Hall.from_row({**ROW, "roi_polygon": [[0.0, 0.0], [1.0, 1.0]]})


class TestCountRecord:
    def test_serialises_timestamps_as_iso_8601(self):
        record = CountRecord(
            hall_id="worcester",
            ts=datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
            count=17,
            model_version="yolo11n.pt@conf0.35",
            conf_threshold=0.35,
            roi_version="v2",
            camera_epoch=3,
            latency_ms=842,
        )
        row = record.to_row()
        assert row["ts"] == "2026-03-04T12:00:00+00:00"
        assert row["count"] == 17
        assert row["camera_epoch"] == 3

    def test_every_column_the_schema_requires_is_present(self):
        record = CountRecord(
            hall_id="franklin",
            ts=datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
            count=0,
            model_version="m",
            conf_threshold=0.35,
            roi_version="v1",
            camera_epoch=1,
        )
        assert set(record.to_row()) == {
            "hall_id",
            "ts",
            "count",
            "model_version",
            "conf_threshold",
            "roi_version",
            "camera_epoch",
            "latency_ms",
        }
