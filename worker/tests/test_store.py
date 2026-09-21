"""The in-memory store has to behave like the real schema, or tests that use it lie."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hallcheck.models import CountRecord
from hallcheck.store import InMemoryStore

START = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)


def record_at(minutes: int, count: int, hall_id: str = "worcester") -> CountRecord:
    return CountRecord(
        hall_id=hall_id,
        ts=START + timedelta(minutes=minutes),
        count=count,
        model_version="m",
        conf_threshold=0.35,
        roi_version="v1",
        camera_epoch=1,
    )


class TestInMemoryStore:
    def test_active_halls_filters_inactive_ones(self, hall):
        from dataclasses import replace

        store = InMemoryStore([hall, replace(hall, hall_id="closed_hall", active=False)])
        assert [h.hall_id for h in store.active_halls()] == ["worcester"]

    def test_writing_the_same_slot_twice_replaces_it(self):
        """Mirrors the unique (hall_id, ts) constraint in 0001_init.sql."""
        store = InMemoryStore()
        store.record_count(record_at(0, 5))
        store.record_count(record_at(0, 8))

        assert len(store.records) == 1
        assert store.records[0].count == 8

    def test_different_halls_at_the_same_instant_coexist(self):
        store = InMemoryStore()
        store.record_count(record_at(0, 5, hall_id="worcester"))
        store.record_count(record_at(0, 9, hall_id="franklin"))
        assert len(store.records) == 2

    def test_counts_between_is_half_open_and_ordered(self):
        store = InMemoryStore()
        for minutes, count in [(4, 3), (0, 1), (2, 2), (6, 4)]:
            store.record_count(record_at(minutes, count))

        rows = store.counts_between("worcester", START, START + timedelta(minutes=6))

        assert [r["count"] for r in rows] == [1, 2, 3], "start inclusive, end exclusive, ascending"

    def test_counts_between_is_scoped_to_one_hall(self):
        store = InMemoryStore()
        store.record_count(record_at(0, 1, hall_id="worcester"))
        store.record_count(record_at(0, 2, hall_id="franklin"))

        rows = store.counts_between("worcester", START, START + timedelta(hours=1))
        assert [r["count"] for r in rows] == [1]
