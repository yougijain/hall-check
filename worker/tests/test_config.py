from __future__ import annotations

import pytest

from hallcheck.config import ConfigError, Settings, load_settings

BASE_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SERVICE_KEY": "service-key",
}


class TestLoadSettings:
    def test_defaults_apply_when_nothing_is_set(self):
        settings = load_settings(BASE_ENV)
        assert settings.model == "yolo11n.pt"
        assert settings.conf_threshold == 0.35
        assert settings.interval_seconds == 120

    def test_environment_overrides_defaults(self):
        settings = load_settings(
            {**BASE_ENV, "HALLCHECK_MODEL": "yolo11s.pt", "HALLCHECK_CONF_THRESHOLD": "0.5"}
        )
        assert settings.model == "yolo11s.pt"
        assert settings.conf_threshold == 0.5

    def test_every_missing_required_variable_is_reported_at_once(self):
        with pytest.raises(ConfigError) as caught:
            load_settings({})
        message = str(caught.value)
        assert "SUPABASE_URL" in message
        assert "SUPABASE_SERVICE_KEY" in message

    def test_a_non_numeric_value_names_the_variable(self):
        with pytest.raises(ConfigError, match="HALLCHECK_CONF_THRESHOLD"):
            load_settings({**BASE_ENV, "HALLCHECK_CONF_THRESHOLD": "high"})

    def test_does_not_touch_the_process_environment(self, monkeypatch):
        monkeypatch.delenv("HALLCHECK_MODEL", raising=False)
        load_settings({**BASE_ENV, "HALLCHECK_MODEL": "yolo11x.pt"})
        import os

        assert "HALLCHECK_MODEL" not in os.environ

    def test_stream_overrides_are_collected_by_hall_id(self):
        settings = load_settings(
            {
                **BASE_ENV,
                "HALLCHECK_STREAM_WORCESTER": "https://cdn.example.edu/w.m3u8",
                "HALLCHECK_STREAM_FRANKLIN": "",
            }
        )
        assert settings.stream_overrides == {"worcester": "https://cdn.example.edu/w.m3u8"}

    def test_override_wins_over_the_database_value(self):
        settings = load_settings(
            {**BASE_ENV, "HALLCHECK_STREAM_WORCESTER": "https://override.example/w.m3u8"}
        )
        assert settings.stream_url_for("worcester", "https://db.example/w.m3u8") == (
            "https://override.example/w.m3u8"
        )
        assert settings.stream_url_for("franklin", "https://db.example/f.m3u8") == (
            "https://db.example/f.m3u8"
        )


class TestValidation:
    @pytest.mark.parametrize("threshold", [0.0, 1.0, -0.2, 1.5])
    def test_confidence_must_be_a_strict_probability(self, threshold):
        with pytest.raises(ConfigError, match="strictly between 0 and 1"):
            Settings(supabase_url="u", supabase_service_key="k", conf_threshold=threshold)

    def test_capture_timeout_must_fit_inside_the_interval(self):
        # A 120s timeout on a 120s interval means one dead camera consumes the
        # entire tick and the halls behind it are never reached.
        with pytest.raises(ConfigError, match="must be shorter than"):
            Settings(
                supabase_url="u",
                supabase_service_key="k",
                interval_seconds=120,
                capture_timeout=120,
            )


class TestModelVersion:
    def test_includes_the_threshold(self):
        settings = Settings(supabase_url="u", supabase_service_key="k", conf_threshold=0.4)
        assert settings.model_version == "yolo11n.pt@conf0.4"

    def test_service_key_is_kept_out_of_the_repr(self):
        settings = Settings(supabase_url="u", supabase_service_key="super-secret")
        assert "super-secret" not in repr(settings)
