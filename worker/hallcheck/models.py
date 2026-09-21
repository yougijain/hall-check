"""Domain types shared by the worker's modules.

These mirror the database schema closely, but they are not an ORM. They exist
so that the pipeline passes around something with named, typed fields instead
of dictionaries whose keys are only checked at the moment they are wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from hallcheck.roi import Roi


@dataclass(frozen=True, slots=True)
class Hall:
    hall_id: str
    name: str
    stream_url: str
    roi: Roi
    camera_epoch: int
    opens_at: time | None = None
    closes_at: time | None = None
    active: bool = True

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Hall:
        return cls(
            hall_id=row["hall_id"],
            name=row["name"],
            stream_url=row.get("stream_url") or "",
            roi=Roi.from_json(row["roi_polygon"], version=row.get("roi_version") or "v1"),
            camera_epoch=int(row.get("camera_epoch") or 1),
            opens_at=_parse_time(row.get("opens_at")),
            closes_at=_parse_time(row.get("closes_at")),
            active=bool(row.get("active", True)),
        )


@dataclass(frozen=True, slots=True)
class CountRecord:
    """One reading. The unit this whole project produces.

    `count` of zero means the camera looked and saw nobody. A missing row means
    the camera was not looked at. Conflating the two turns an outage into a
    quiet dining hall, so a failed capture writes nothing at all rather than
    writing a zero.
    """

    hall_id: str
    ts: datetime
    count: int
    model_version: str
    conf_threshold: float
    roi_version: str
    camera_epoch: int
    latency_ms: int | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "hall_id": self.hall_id,
            "ts": self.ts.isoformat(),
            "count": self.count,
            "model_version": self.model_version,
            "conf_threshold": self.conf_threshold,
            "roi_version": self.roi_version,
            "camera_epoch": self.camera_epoch,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True, slots=True)
class LabelRecord:
    hall_id: str
    ts: datetime
    human_count: int
    model_count: int | None
    meal: str
    lighting: str
    model_version: str | None = None
    conf_threshold: float | None = None
    roi_version: str | None = None
    camera_epoch: int | None = None
    notes: str | None = None

    @property
    def error(self) -> int | None:
        if self.model_count is None:
            return None
        return self.model_count - self.human_count

    def to_row(self) -> dict[str, Any]:
        return {
            "hall_id": self.hall_id,
            "ts": self.ts.isoformat(),
            "human_count": self.human_count,
            "model_count": self.model_count,
            "meal": self.meal,
            "lighting": self.lighting,
            "model_version": self.model_version,
            "conf_threshold": self.conf_threshold,
            "roi_version": self.roi_version,
            "camera_epoch": self.camera_epoch,
            "notes": self.notes,
        }


def _parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    # Postgres hands back "HH:MM:SS", sometimes with a fractional part.
    return time.fromisoformat(str(value))
