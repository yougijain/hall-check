"""Turning labels into the accuracy claim, and checking it is allowed to be made.

The claim this project makes on a resume is a single MAE figure. A single MAE
figure is only honest if the labels behind it span the conditions the system
runs in, so this module reports coverage as prominently as it reports error.

An MAE measured entirely at lunch in daylight says nothing about dinner in
January, and quoting it as though it did is the failure mode this exists to
prevent. Missing strata are listed in the report rather than left for the
reader to notice by their absence.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from hallcheck.metrics import (
    MIN_STRATUM_SIZE,
    Metrics,
    Observation,
    group_by,
    summarise,
)

#: The protocol's target range. Fewer than the floor and the overall figure is
#: not worth quoting.
TARGET_LABELS_MIN = 150
TARGET_LABELS_MAX = 250

#: Conditions the labels have to cover before the headline number is reportable.
REQUIRED_MEALS = ("breakfast", "lunch", "dinner")
REQUIRED_LIGHTING = ("daylight", "dark")


@dataclass(frozen=True, slots=True)
class Report:
    overall: Metrics
    by_hall: dict[str, Metrics]
    by_lighting: dict[str, Metrics]
    by_meal: dict[str, Metrics]
    coverage_gaps: list[str] = field(default_factory=list)

    @property
    def reportable(self) -> bool:
        """Whether the headline MAE may be quoted without an asterisk."""
        return not self.coverage_gaps and self.overall.n >= TARGET_LABELS_MIN


def to_observations(rows: Iterable[dict[str, Any]]) -> list[Observation]:
    """Map `labels` rows to observations, dropping the ones that are not pairs.

    A label whose `model_count` is null was captured while the worker was down.
    It is a valid row - the human count is real and can be paired up later -
    but it is not an observation of the model and must not be averaged into
    one.
    """
    observations = []
    for row in rows:
        model_count = row.get("model_count")
        if model_count is None:
            continue
        observations.append(
            Observation(
                human_count=int(row["human_count"]),
                model_count=int(model_count),
                hall_id=str(row.get("hall_id") or ""),
                meal=str(row.get("meal") or ""),
                lighting=str(row.get("lighting") or ""),
            )
        )
    return observations


def find_coverage_gaps(
    observations: Sequence[Observation], *, known_halls: Sequence[str] = ()
) -> list[str]:
    """Everything standing between these labels and a quotable number."""
    gaps: list[str] = []

    if len(observations) < TARGET_LABELS_MIN:
        gaps.append(
            f"only {len(observations)} paired labels; the protocol asks for "
            f"{TARGET_LABELS_MIN} to {TARGET_LABELS_MAX}"
        )

    by_meal = group_by(observations, "meal")
    for meal in REQUIRED_MEALS:
        count = len(by_meal.get(meal, []))
        if count == 0:
            gaps.append(f"no labels at {meal}")
        elif count < MIN_STRATUM_SIZE:
            gaps.append(f"only {count} labels at {meal} (want at least {MIN_STRATUM_SIZE})")

    by_lighting = group_by(observations, "lighting")
    for lighting in REQUIRED_LIGHTING:
        count = len(by_lighting.get(lighting, []))
        if count == 0:
            gaps.append(f"no labels in {lighting}")
        elif count < MIN_STRATUM_SIZE:
            gaps.append(f"only {count} labels in {lighting} (want at least {MIN_STRATUM_SIZE})")

    by_hall = group_by(observations, "hall_id")
    for hall_id in known_halls:
        count = len(by_hall.get(hall_id, []))
        if count == 0:
            gaps.append(f"no labels for {hall_id}")
        elif count < MIN_STRATUM_SIZE:
            gaps.append(f"only {count} labels for {hall_id} (want at least {MIN_STRATUM_SIZE})")

    return gaps


def build_report(observations: Sequence[Observation], *, known_halls: Sequence[str] = ()) -> Report:
    return Report(
        overall=summarise(observations),
        by_hall={key: summarise(group) for key, group in group_by(observations, "hall_id").items()},
        by_lighting={
            key: summarise(group) for key, group in group_by(observations, "lighting").items()
        },
        by_meal={key: summarise(group) for key, group in group_by(observations, "meal").items()},
        coverage_gaps=find_coverage_gaps(observations, known_halls=known_halls),
    )


def _row(label: str, metrics: Metrics) -> str:
    if metrics.n == 0:
        return f"| {label} | 0 | — | — | — |"

    flag = " ⚠" if metrics.underpowered else ""
    interval = f" {metrics.mae_interval}" if metrics.mae_interval else ""
    return (
        f"| {label} | {metrics.n}{flag} | {metrics.mae:.2f}{interval} "
        f"| {metrics.bias:+.2f} | {metrics.rmse:.2f} |"
    )


def render_markdown(report: Report) -> str:
    """The table that goes in the README, generated rather than typed.

    A hand-copied accuracy table drifts from the data the first time the
    numbers are regenerated and nobody remembers to update it.
    """
    lines: list[str] = []

    if report.coverage_gaps:
        lines.append("> **Not yet reportable.** These labels do not cover the required")
        lines.append("> conditions, so the overall figure below should not be quoted:")
        lines.append(">")
        for gap in report.coverage_gaps:
            lines.append(f"> - {gap}")
        lines.append("")

    header = "| Stratum | n | MAE (95% CI) | Bias | RMSE |\n|---|---|---|---|---|"

    lines.append(header)
    lines.append(_row("**Overall**", report.overall))

    for title, group in (
        ("By hall", report.by_hall),
        ("By lighting", report.by_lighting),
        ("By meal", report.by_meal),
    ):
        if not group:
            continue
        lines.append(f"| *{title}* | | | | |")
        for key, metrics in group.items():
            lines.append(_row(f"&nbsp;&nbsp;{key}", metrics))

    lines.append("")
    lines.append(
        f"Bias is model minus human: positive means the detector over-counts. "
        f"⚠ marks a stratum with fewer than {MIN_STRATUM_SIZE} labels, where the "
        f"figure is an anecdote rather than an estimate."
    )
    return "\n".join(lines)
