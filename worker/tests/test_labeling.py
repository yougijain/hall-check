"""Label collection, and the ordering rule the accuracy numbers depend on."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from hallcheck.capture import CaptureError
from hallcheck.labeling import (
    LabelAborted,
    choose,
    infer_meal,
    parse_count,
    run_label_session,
)
from hallcheck.store import InMemoryStore
from tests.conftest import FakeDetector

NOON = datetime(2026, 3, 4, 17, 0, tzinfo=UTC)


class ScriptedOperator:
    """Answers prompts in order, recording what had been printed at each one."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.printed: list[str] = []
        self.seen_before_each_prompt: list[list[str]] = []
        self.prompts: list[str] = []

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        self.seen_before_each_prompt.append(list(self.printed))
        if not self.answers:
            raise AssertionError(f"unexpected prompt: {message!r}")
        return self.answers.pop(0)

    def output(self, message: str) -> None:
        self.printed.append(message)

    @property
    def everything_shown(self) -> str:
        return "\n".join(self.printed + self.prompts)


class TestBlindness:
    def test_the_model_count_is_not_revealed_before_the_human_answers(
        self, hall, settings, stub_capture
    ):
        """The protocol's central rule, enforced rather than remembered.

        A labeller who has already seen 37 writes 37. Every label collected
        that way pulls MAE toward zero, and the published figure becomes a
        measurement of the labeller's suggestibility instead of the detector's
        accuracy. There is no way to detect it after the fact.
        """
        stub_capture()
        operator = ScriptedOperator(["20", "lunch", "daylight", ""])

        run_label_session(
            hall,
            FakeDetector(count=37),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=NOON,
        )

        everything_before_the_answer = "\n".join(
            operator.seen_before_each_prompt[0] + [operator.prompts[0]]
        )
        assert "37" not in everything_before_the_answer

    def test_the_comparison_is_shown_afterwards(self, hall, settings, stub_capture):
        stub_capture()
        operator = ScriptedOperator(["20", "lunch", "daylight", ""])

        run_label_session(
            hall,
            FakeDetector(count=37),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=NOON,
        )

        assert "37" in operator.everything_shown
        assert "+17" in operator.everything_shown


class TestRunLabelSession:
    def test_records_both_counts(self, hall, settings, stub_capture):
        stub_capture()
        operator = ScriptedOperator(["20", "lunch", "daylight", "busy, sunny"])

        record = run_label_session(
            hall,
            FakeDetector(count=17),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=NOON,
        )

        assert record.human_count == 20
        assert record.model_count == 17
        assert record.error == -3
        assert record.notes == "busy, sunny"

    def test_stamps_the_conditions_the_count_was_taken_under(self, hall, settings, stub_capture):
        stub_capture()
        operator = ScriptedOperator(["20", "dinner", "dark", ""])

        record = run_label_session(
            hall,
            FakeDetector(count=17),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=NOON,
        )

        assert record.meal == "dinner"
        assert record.lighting == "dark"
        assert record.roi_version == "test-v1"
        assert record.camera_epoch == 1
        assert record.model_version == "fake@conf0.35"

    def test_timestamp_is_on_the_capture_grid(self, hall, settings, stub_capture):
        stub_capture()
        operator = ScriptedOperator(["20", "lunch", "daylight", ""])

        record = run_label_session(
            hall,
            FakeDetector(count=17),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=datetime(2026, 3, 4, 17, 1, 43, tzinfo=UTC),
        )

        # Aligned so the label can be joined to the count row for the same slot.
        assert record.ts == datetime(2026, 3, 4, 17, 0, tzinfo=UTC)

    def test_a_dead_stream_still_collects_the_human_count(self, hall, settings, stub_capture):
        """The human count is real even when the model's is not.

        Throwing the label away would mean losing the labels collected on
        exactly the days the system was struggling, which is a quietly biased
        way to build an evaluation set.
        """
        stub_capture(error=CaptureError("stream is down"))
        operator = ScriptedOperator(["20", "lunch", "daylight", ""])

        record = run_label_session(
            hall,
            FakeDetector(count=17),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=NOON,
        )

        assert record.human_count == 20
        assert record.model_count is None
        assert record.error is None
        assert "stream is down" in operator.everything_shown

    def test_an_empty_note_is_stored_as_null(self, hall, settings, stub_capture):
        stub_capture()
        operator = ScriptedOperator(["20", "lunch", "daylight", "   "])

        record = run_label_session(
            hall,
            FakeDetector(count=17),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=NOON,
        )
        assert record.notes is None

    def test_supplied_meal_and_lighting_skip_their_prompts(self, hall, settings, stub_capture):
        stub_capture()
        operator = ScriptedOperator(["20", ""])

        record = run_label_session(
            hall,
            FakeDetector(count=17),
            settings,
            prompt=operator.prompt,
            output=operator.output,
            now=NOON,
            meal="breakfast",
            lighting="dark",
        )

        assert record.meal == "breakfast"
        assert record.lighting == "dark"
        assert len(operator.prompts) == 2

    def test_relabelling_the_same_slot_replaces_the_label(self, hall, settings):
        from hallcheck.models import LabelRecord

        store = InMemoryStore([hall])
        for human in (20, 22):
            store.record_label(
                LabelRecord(
                    hall_id="worcester",
                    ts=NOON,
                    human_count=human,
                    model_count=17,
                    meal="lunch",
                    lighting="daylight",
                )
            )

        assert len(store.labels) == 1
        assert store.labels[0].human_count == 22


class TestParseCount:
    @pytest.mark.parametrize("raw,expected", [("0", 0), ("7", 7), ("  23  ", 23)])
    def test_reads_a_count(self, raw, expected):
        assert parse_count(raw) == expected

    @pytest.mark.parametrize("raw", ["q", "quit", "abort", ""])
    def test_aborts(self, raw):
        with pytest.raises(LabelAborted):
            parse_count(raw)

    @pytest.mark.parametrize("raw", ["twelve", "12.5", "-3", "12 people"])
    def test_refuses_anything_that_is_not_a_count(self, raw):
        # Coercing a typo would put a wrong ground truth into the set every
        # accuracy claim rests on, undetectably.
        with pytest.raises(ValueError):
            parse_count(raw)


class TestChoose:
    def test_empty_takes_the_default(self):
        assert choose(lambda _m: "", "Meal", ("breakfast", "lunch"), "lunch") == "lunch"

    def test_accepts_an_exact_answer(self):
        assert choose(lambda _m: "breakfast", "Meal", ("breakfast", "lunch"), "lunch") == (
            "breakfast"
        )

    def test_accepts_an_unambiguous_prefix(self):
        assert choose(lambda _m: "br", "Meal", ("breakfast", "lunch"), "lunch") == "breakfast"

    def test_rejects_an_ambiguous_prefix(self):
        with pytest.raises(ValueError):
            choose(lambda _m: "d", "Meal", ("dinner", "dessert"), "dinner")

    def test_rejects_an_unknown_answer(self):
        with pytest.raises(ValueError):
            choose(lambda _m: "brunch", "Meal", ("breakfast", "lunch"), "lunch")


class TestInferMeal:
    @pytest.mark.parametrize(
        "at,expected",
        [
            (time(8, 0), "breakfast"),
            (time(12, 30), "lunch"),
            (time(18, 0), "dinner"),
            (time(3, 0), "closed"),
            (time(15, 30), "closed"),
        ],
    )
    def test_suggests_from_the_clock(self, at, expected):
        assert infer_meal(at) == expected
