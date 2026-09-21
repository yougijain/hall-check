"""Runtime configuration, read once from the environment at startup."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONF_THRESHOLD = 0.35
DEFAULT_INTERVAL_SECONDS = 120
DEFAULT_CAPTURE_TIMEOUT = 30


class ConfigError(RuntimeError):
    """Configuration is missing or unusable. Raised at startup, never later."""


@dataclass(frozen=True, slots=True)
class Settings:
    supabase_url: str
    supabase_service_key: str = field(repr=False)

    model: str = DEFAULT_MODEL
    conf_threshold: float = DEFAULT_CONF_THRESHOLD
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    capture_timeout: int = DEFAULT_CAPTURE_TIMEOUT

    #: Per-hall stream URL overrides from HALLCHECK_STREAM_<HALL_ID>.
    stream_overrides: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 < self.conf_threshold < 1.0:
            raise ConfigError(
                f"HALLCHECK_CONF_THRESHOLD must be strictly between 0 and 1, "
                f"got {self.conf_threshold}"
            )
        if self.interval_seconds < 1:
            raise ConfigError(
                f"HALLCHECK_INTERVAL_SECONDS must be at least 1, got {self.interval_seconds}"
            )
        if self.capture_timeout < 1:
            raise ConfigError(
                f"HALLCHECK_CAPTURE_TIMEOUT must be at least 1, got {self.capture_timeout}"
            )
        if self.capture_timeout >= self.interval_seconds:
            # Otherwise a hall that is timing out eats the whole tick and the
            # halls after it in the list never get captured at all - a silent
            # partial outage that looks like a dead camera.
            raise ConfigError(
                f"HALLCHECK_CAPTURE_TIMEOUT ({self.capture_timeout}s) must be shorter than "
                f"HALLCHECK_INTERVAL_SECONDS ({self.interval_seconds}s), or a slow hall "
                "starves the ones captured after it"
            )

    @property
    def model_version(self) -> str:
        """What gets stamped on every count, so a reading can be traced back.

        Includes the threshold because the same weights at a different
        confidence cutoff are, for our purposes, a different model: the counts
        are not comparable and pretending otherwise corrupts the history.
        """
        return f"{self.model}@conf{self.conf_threshold:g}"

    def stream_url_for(self, hall_id: str, configured: str) -> str:
        return self.stream_overrides.get(hall_id, "") or configured


def _env_float(source: Mapping[str, str], name: str, default: float) -> float:
    raw = source.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_int(source: Mapping[str, str], name: str, default: int) -> int:
    raw = source.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from exc


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from the environment.

    Every missing required variable is reported at once. Discovering them one
    redeploy at a time is how a ten minute setup becomes an afternoon.

    `env` exists so tests can supply an environment without touching the
    process-wide one.
    """
    source: Mapping[str, str] = os.environ if env is None else env

    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not source.get(k)]
    if missing:
        raise ConfigError(
            "missing required environment variables: "
            + ", ".join(missing)
            + ". See worker/.env.example."
        )

    prefix = "HALLCHECK_STREAM_"
    overrides = {
        key[len(prefix) :].lower(): value
        for key, value in source.items()
        if key.startswith(prefix) and value
    }

    return Settings(
        supabase_url=source["SUPABASE_URL"],
        supabase_service_key=source["SUPABASE_SERVICE_KEY"],
        model=source.get("HALLCHECK_MODEL") or DEFAULT_MODEL,
        conf_threshold=_env_float(source, "HALLCHECK_CONF_THRESHOLD", DEFAULT_CONF_THRESHOLD),
        interval_seconds=_env_int(source, "HALLCHECK_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS),
        capture_timeout=_env_int(source, "HALLCHECK_CAPTURE_TIMEOUT", DEFAULT_CAPTURE_TIMEOUT),
        stream_overrides=overrides,
    )
