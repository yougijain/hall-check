"""What the detector asks Ultralytics for, with the model faked out.

CI does not install ultralytics (see requirements-ci.txt), so the real model
never runs here; publish-worker.yml runs it. What can be checked without it is
that the settings stamped onto every count are the settings actually passed to
inference.
"""

from __future__ import annotations

import numpy as np

from hallcheck.detect import PERSON_CLASS, YoloPersonDetector


class RecordingModel:
    def __init__(self):
        self.calls: list[dict] = []

    def predict(self, frame, **kwargs):
        self.calls.append(kwargs)
        return []


def _detector_with_fake(**kwargs) -> tuple[YoloPersonDetector, RecordingModel]:
    detector = YoloPersonDetector(**kwargs)
    fake = RecordingModel()
    detector._model = fake
    return detector, fake


def test_inference_runs_at_the_input_size_in_the_model_version():
    detector, fake = _detector_with_fake(conf_threshold=0.35, imgsz=1280)
    detector._detect_boxes(np.zeros((720, 1280, 3), dtype=np.uint8))

    (call,) = fake.calls
    assert call["imgsz"] == 1280
    assert call["conf"] == 0.35
    assert call["classes"] == [PERSON_CLASS]
    assert detector.model_version == "yolo11n.pt@conf0.35@imgsz1280"


def test_default_input_size_is_the_stream_resolution_not_ultralytics_640():
    detector, fake = _detector_with_fake()
    detector._detect_boxes(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert fake.calls[0]["imgsz"] == 1280
