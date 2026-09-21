"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from hallcheck.config import ConfigError, load_settings
from hallcheck.detect import YoloPersonDetector
from hallcheck.evaluate import build_report, render_markdown, to_observations
from hallcheck.labeling import LIGHTING, MEALS, LabelAborted, run_label_session
from hallcheck.pipeline import run_tick
from hallcheck.store import SupabaseStore

log = logging.getLogger("hallcheck")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hallcheck", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="start the capture loop and stay up")
    sub.add_parser("once", help="capture every active hall exactly once, then exit")

    label = sub.add_parser("label", help="record a human count alongside the model's")
    label.add_argument("hall_id", help="which hall you are watching")
    label.add_argument("--meal", choices=MEALS, help="skip the prompt")
    label.add_argument("--lighting", choices=LIGHTING, help="skip the prompt")
    label.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="how many labels to collect before exiting (default 1)",
    )

    evaluate = sub.add_parser("evaluate", help="report accuracy from the collected labels")
    evaluate.add_argument(
        "-o",
        "--out",
        help="write the markdown table here instead of stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_logging(args.verbose)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - convenience only
        pass

    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    detector = YoloPersonDetector(
        model=settings.model,
        conf_threshold=settings.conf_threshold,
    )
    store = SupabaseStore(settings.supabase_url, settings.supabase_service_key)

    if args.command == "label":
        return _label(args, detector, store, settings)

    if args.command == "evaluate":
        return _evaluate(args, store)

    if args.command == "once":
        results = run_tick(detector, store, settings)
        for result in results:
            status = f"count={result.count}" if result.ok else f"FAILED: {result.error}"
            print(f"{result.hall_id:<12} {status} ({result.latency_ms}ms)")
        # Non-zero when every hall failed, so a smoke test in CI or a deploy
        # hook can tell "nothing works" from "one camera is down".
        return 0 if any(r.ok for r in results) else 1

    from hallcheck.scheduler import serve

    serve(detector, store, settings)
    return 0


def _label(args, detector, store, settings) -> int:
    halls = {hall.hall_id: hall for hall in store.active_halls()}
    hall = halls.get(args.hall_id)
    if hall is None:
        log.error("unknown hall %r; known halls: %s", args.hall_id, ", ".join(sorted(halls)))
        return 2

    detector.load()

    collected = 0
    for _ in range(max(1, args.count)):
        try:
            record = run_label_session(
                hall,
                detector,
                settings,
                prompt=input,
                output=print,
                meal=args.meal,
                lighting=args.lighting,
            )
        except LabelAborted as exc:
            print(f"  {exc}. Nothing written.")
            break
        except (ValueError, KeyboardInterrupt) as exc:
            print(f"  {exc or 'interrupted'}. Nothing written.")
            break

        store.record_label(record)
        collected += 1

    print(f"\nStored {collected} label(s).")
    return 0


def _evaluate(args, store) -> int:
    known_halls = [hall.hall_id for hall in store.active_halls()]
    observations = to_observations(store.all_labels())
    report = build_report(observations, known_halls=known_halls)
    markdown = render_markdown(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
        print(f"wrote {args.out}")
    else:
        print(markdown)

    # Non-zero when the labels do not yet support a quotable figure, so this
    # can gate the README table in a script without anyone having to read the
    # output and remember what the coverage rules were.
    return 0 if report.reportable else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
