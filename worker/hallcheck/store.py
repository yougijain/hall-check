"""Persistence.

A narrow protocol with two implementations: Supabase for real, and an in-memory
one for tests. The protocol is what the pipeline depends on, so none of the
pipeline's logic needs a network to be exercised.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol

from hallcheck.models import CountRecord, Hall, LabelRecord

log = logging.getLogger(__name__)


class StoreError(RuntimeError):
    """A database operation failed."""


class Store(Protocol):
    def active_halls(self) -> list[Hall]: ...

    def record_count(self, record: CountRecord) -> None: ...

    def counts_between(
        self, hall_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]: ...


class SupabaseStore:
    """Supabase Postgres, reached with the service role key.

    This key bypasses row level security, which is why it lives only in the
    worker's environment. Nothing in `web/` ever sees it.
    """

    def __init__(self, url: str, service_key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, service_key)

    def active_halls(self) -> list[Hall]:
        try:
            response = self._client.table("halls").select("*").eq("active", True).execute()
        except Exception as exc:
            raise StoreError(f"could not load halls: {exc}") from exc

        halls: list[Hall] = []
        for row in response.data or []:
            try:
                halls.append(Hall.from_row(row))
            except Exception as exc:
                # One hall with a broken polygon should not take the other
                # three offline. Log it loudly and keep serving the rest.
                log.error("skipping hall %s: %s", row.get("hall_id"), exc)
        return halls

    def record_count(self, record: CountRecord) -> None:
        try:
            # Upsert rather than insert: a retried tick replays the same
            # (hall_id, ts) and must not produce a second reading.
            self._client.table("counts").upsert(record.to_row(), on_conflict="hall_id,ts").execute()
        except Exception as exc:
            raise StoreError(f"could not write count for {record.hall_id}: {exc}") from exc

    def counts_between(self, hall_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        try:
            response = (
                self._client.table("counts")
                .select("*")
                .eq("hall_id", hall_id)
                .gte("ts", start.isoformat())
                .lt("ts", end.isoformat())
                .order("ts")
                .execute()
            )
        except Exception as exc:
            raise StoreError(f"could not read counts for {hall_id}: {exc}") from exc
        return list(response.data or [])

    def record_label(self, record: LabelRecord) -> None:
        try:
            # Same slot, same label: re-labelling an instant corrects it
            # rather than adding a second opinion of it.
            self._client.table("labels").upsert(record.to_row(), on_conflict="hall_id,ts").execute()
        except Exception as exc:
            raise StoreError(f"could not write label for {record.hall_id}: {exc}") from exc

    def all_labels(self) -> list[dict[str, Any]]:
        try:
            response = self._client.table("labels").select("*").order("ts").execute()
        except Exception as exc:
            raise StoreError(f"could not read labels: {exc}") from exc
        return list(response.data or [])


class InMemoryStore:
    """Test double. Same protocol, no network, keeps what it was given."""

    def __init__(self, halls: list[Hall] | None = None) -> None:
        self.halls = halls or []
        self.records: list[CountRecord] = []
        self.labels: list[LabelRecord] = []

    def active_halls(self) -> list[Hall]:
        return [hall for hall in self.halls if hall.active]

    def record_count(self, record: CountRecord) -> None:
        # Mirror the unique (hall_id, ts) constraint so tests see upsert
        # semantics rather than a growing pile of duplicates.
        self.records = [
            existing
            for existing in self.records
            if not (existing.hall_id == record.hall_id and existing.ts == record.ts)
        ]
        self.records.append(record)

    def counts_between(self, hall_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return [
            record.to_row()
            for record in sorted(self.records, key=lambda r: r.ts)
            if record.hall_id == hall_id and start <= record.ts < end
        ]

    def record_label(self, record: LabelRecord) -> None:
        self.labels = [
            existing
            for existing in self.labels
            if not (existing.hall_id == record.hall_id and existing.ts == record.ts)
        ]
        self.labels.append(record)

    def all_labels(self) -> list[dict[str, Any]]:
        return [label.to_row() for label in sorted(self.labels, key=lambda r: r.ts)]
