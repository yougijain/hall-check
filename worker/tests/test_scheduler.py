"""Scheduler wiring: the settings that carry the operational behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hallcheck.drift import DriftStatus
from hallcheck.models import CountRecord
from hallcheck.scheduler import build_scheduler, run_drift_check
from hallcheck.store import InMemoryStore, StoreError
from tests.conftest import FakeDetector

NOW = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)


class TestBuildScheduler:
    @pytest.fixture
    def scheduler(self, settings, hall):
        return build_scheduler(FakeDetector(), InMemoryStore([hall]), settings)

    def test_registers_capture_and_drift(self, scheduler):
        assert {job.id for job in scheduler.get_jobs()} == {"capture", "drift"}

    def test_capture_runs_at_the_configured_interval(self, scheduler, settings):
        capture = scheduler.get_job("capture")
        assert capture.trigger.interval.total_seconds() == settings.interval_seconds

    def test_a_tick_cannot_start_underneath_the_previous_one(self, scheduler):
        # Two concurrent passes fight over ffmpeg and the CPU, and both take
        # longer than one would.
        assert scheduler.get_job("capture").max_instances == 1

    def test_a_backlog_runs_once_rather_than_replaying_every_missed_tick(self, scheduler):
        # After a redeploy those frames are gone. Replaying the schedule would
        # write the current count under a dozen past timestamps.
        assert scheduler.get_job("capture").coalesce is True

    def test_drift_runs_daily(self, scheduler):
        # More often would re-report the same drift every hour until someone
        # acts on it, which is how an alert gets muted.
        drift = scheduler.get_job("drift")
        fields = {field.name: str(field) for field in drift.trigger.fields}
        assert fields["hour"] == "8"
        assert fields["day"] == "*"


class TestRunDriftCheck:
    def _store_with_history(self, *, moved: bool) -> InMemoryStore:
        store = InMemoryStore()
        for day in range(20, -1, -1):
            for minute in range(7 * 60, 21 * 60, 2):
                ts = (NOW - timedelta(days=day)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + timedelta(minutes=minute)
                if ts > NOW:
                    continue
                recent = (NOW - ts) < timedelta(hours=24)
                count = 20
                if moved and recent:
                    count = 6
                store.record_count(
                    CountRecord(
                        hall_id="worcester",
                        ts=ts,
                        count=count,
                        model_version="m",
                        conf_threshold=0.35,
                        roi_version="v1",
                        camera_epoch=1,
                    )
                )
        return store

    def test_logs_an_error_when_a_camera_has_drifted(self, caplog, monkeypatch):
        monkeypatch.setattr(
            "hallcheck.scheduler.check_all",
            lambda readings, now: _signals(DriftStatus.ALERT),
        )
        with caplog.at_level("ERROR"):
            run_drift_check(self._store_with_history(moved=True))

        assert any("DRIFT" in record.message for record in caplog.records)

    def test_is_quiet_when_every_camera_is_steady(self, caplog):
        with caplog.at_level("ERROR"):
            run_drift_check(self._store_with_history(moved=False))

        assert not [r for r in caplog.records if "DRIFT" in r.message]

    def test_a_database_failure_does_not_take_the_capture_loop_down(self, caplog):
        """A drift check is diagnostics. The capture loop is the product.

        Letting this raise would stop collecting counts because a secondary
        report could not run.
        """

        class BrokenStore(InMemoryStore):
            def counts_since(self, start):
                raise StoreError("connection refused")

        with caplog.at_level("ERROR"):
            run_drift_check(BrokenStore())  # must not raise

        assert any("could not read counts" in r.message for r in caplog.records)


def _signals(status):
    from hallcheck.drift import DriftSignal, SlotComparison

    return [
        DriftSignal(
            "worcester",
            1,
            status,
            comparisons=(SlotComparison(720, 6.0, 20.0),) * 6,
        )
    ]
