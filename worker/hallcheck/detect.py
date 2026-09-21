"""Person detection, reduced to a count before it can become anything else.

YOLO11n, COCO class 0, on CPU. Pretrained and never fine-tuned, which is a
deliberate choice rather than a shortcut: the labels collected in M2 are spent
on measuring how wrong the detector is under real lighting and real occlusion,
not on training it. A hundred and fifty labels is a good evaluation set and a
useless training set.

The public surface of this module is an integer. `_detect_boxes` produces
bounding boxes and `count_in_roi` consumes them in the same call, so boxes are
never returned to a caller that could log, store or accumulate them. A sequence
of positions through a public room is behavioural data about people who did not
agree to be measured; a scalar occupancy figure is not. See docs/privacy.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from hallcheck.roi import BoundingBox, Roi

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

log = logging.getLogger(__name__)

#: COCO class index for "person". The only class this project looks at.
PERSON_CLASS = 0


class DetectionError(RuntimeError):
    """Inference failed. The tick is skipped; nothing is written."""


class Detector(Protocol):
    """What the pipeline needs. Narrow on purpose, and trivial to fake in tests."""

    @property
    def model_version(self) -> str: ...

    def count_in_roi(self, frame: np.ndarray, roi: Roi) -> int: ...


class YoloPersonDetector:
    """Ultralytics YOLO, pinned to people and to never touching the filesystem."""

    def __init__(
        self,
        model: str = "yolo11n.pt",
        conf_threshold: float = 0.35,
        device: str = "cpu",
    ) -> None:
        self._model_name = model
        self._conf_threshold = conf_threshold
        self._device = device
        self._model: Any | None = None

    @property
    def model_version(self) -> str:
        return f"{self._model_name}@conf{self._conf_threshold:g}"

    def load(self) -> None:
        """Load weights.

        Called explicitly at startup so a bad model name fails the deploy
        rather than the first capture, and so the several-second first-call
        penalty is paid before the scheduler starts timing ticks.
        """
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise DetectionError("ultralytics is not installed") from exc

        log.info("loading detector %s on %s", self._model_name, self._device)
        try:
            self._model = YOLO(self._model_name)
        except Exception as exc:
            raise DetectionError(f"could not load model {self._model_name}: {exc}") from exc

    def _detect_boxes(self, frame: np.ndarray) -> list[BoundingBox]:
        """Run inference and return normalised person boxes.

        Private, and it stays private. Every `save*` argument is pinned off
        explicitly: Ultralytics reads persisted global settings for some of
        these, so relying on the library default means relying on a file we do
        not control staying the way we found it.
        """
        if self._model is None:
            self.load()
        assert self._model is not None

        try:
            results = self._model.predict(
                frame,
                classes=[PERSON_CLASS],
                conf=self._conf_threshold,
                device=self._device,
                verbose=False,
                save=False,
                save_txt=False,
                save_conf=False,
                save_crop=False,
                show=False,
                stream=False,
            )
        except Exception as exc:
            raise DetectionError(f"inference failed: {exc}") from exc

        boxes: list[BoundingBox] = []
        for result in results:
            detected = getattr(result, "boxes", None)
            if detected is None or len(detected) == 0:
                continue
            # xyxyn is already normalised to the frame, which is the coordinate
            # system the ROI polygon lives in.
            coordinates = detected.xyxyn.tolist()
            confidences = detected.conf.tolist()
            for (x1, y1, x2, y2), confidence in zip(coordinates, confidences, strict=True):
                boxes.append(
                    BoundingBox(
                        x1=float(x1),
                        y1=float(y1),
                        x2=float(x2),
                        y2=float(y2),
                        confidence=float(confidence),
                    )
                )
        return boxes

    def count_in_roi(self, frame: np.ndarray, roi: Roi) -> int:
        """The only thing this class is for.

        Boxes are created and discarded inside this call. What leaves is an int.
        """
        boxes = self._detect_boxes(frame)
        count = roi.count_inside(boxes)
        log.debug("detected %d people, %d inside roi %s", len(boxes), count, roi.version)
        return count
