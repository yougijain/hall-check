from __future__ import annotations

import pytest

from hallcheck.config import ConfigError, Settings, load_settings
from hallcheck.detect import YoloPersonDetector

BASE_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SERVICE_KEY": "service-key",
}


class TestLoadSettings:
    def test_defaults_apply_when_nothing_is_set(self):
        settings = load_settings(BASE_ENV)
        assert settings.model == "yolo11n.pt"
        assert settings.conf_threshold == 0.35
        assert settings.imgsz == 1280
        assert settings.interval_seconds == 120

    def test_environment_overrides_defaults(self):
        settings = load_settings(
            {
                **BASE_ENV,
                "HALLCHECK_MODEL": "yolo11s.pt",
                "HALLCHECK_CONF_THRESHOLD": "0.5",
                "HALLCHECK_IMGSZ": "640",
            }
        )
        assert settings.model == "yolo11s.pt"
        assert settings.conf_threshold == 0.5
        assert settings.imgsz == 640

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

    @pytest.mark.parametrize("imgsz", [0, -640, 16, 1000, 1281])
    def test_input_size_must_be_a_positive_multiple_of_32(self, imgsz):
        # Ultralytics would silently round these, and the size stamped into
        # model_version would no longer be the size that actually ran.
        with pytest.raises(ConfigError, match="multiple of 32"):
            Settings(supabase_url="u", supabase_service_key="k", imgsz=imgsz)

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
    def test_includes_the_threshold_and_input_size(self):
        settings = Settings(supabase_url="u", supabase_service_key="k", conf_threshold=0.4)
        assert settings.model_version == "yolo11n.pt@conf0.4@imgsz1280"

    def test_a_different_input_size_is_a_different_series(self):
        at_640 = Settings(supabase_url="u", supabase_service_key="k", imgsz=640)
        at_1280 = Settings(supabase_url="u", supabase_service_key="k", imgsz=1280)
        assert at_640.model_version != at_1280.model_version

    def test_matches_what_the_detector_stamps(self):
        # Two properties build this string, one on Settings and one on the
        # detector. Counts carry the detector's; the startup log and anything
        # reading Settings carry the other. They must not drift apart.
        settings = Settings(
            supabase_url="u", supabase_service_key="k", conf_threshold=0.3, imgsz=960
        )
        detector = YoloPersonDetector(
            model=settings.model, conf_threshold=settings.conf_threshold, imgsz=settings.imgsz
        )
        assert detector.model_version == settings.model_version

    def test_service_key_is_kept_out_of_the_repr(self):
        settings = Settings(supabase_url="u", supabase_service_key="super-secret")
        assert "super-secret" not in repr(settings)
