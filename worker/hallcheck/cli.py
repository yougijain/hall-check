"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from hallcheck.config import ConfigError, load_settings
from hallcheck.detect import YoloPersonDetector
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
