"""The queue region, and the question of who is standing in it.

Counting every person in the frame is the wrong measurement. A dining hall
camera sees the servery, the seating, and people walking past to somewhere
else. Most of them are not waiting for anything. A count over the whole frame
correlates with queue length, which is exactly enough to be misleading.

So each hall carries a polygon over the region where its queue forms, and only
detections anchored inside it are counted.

Coordinates are normalised to [0, 1] against frame width and height rather than
stored in pixels. Streams change resolution - a provider re-encodes, a camera
is swapped for a different sensor - and a pixel polygon silently shifts to a
different part of the room when they do. A normalised polygon does not.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

Point = tuple[float, float]

# Below this, the polygon is almost certainly a data entry mistake - three
# collinear points, or a box drawn and abandoned - and every count it produces
# would be zero. Fail loudly at load rather than quietly forever.
MIN_ROI_AREA = 1e-4


class InvalidRoi(ValueError):
    """The polygon could not be used as a queue region."""


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A detection, in normalised frame coordinates.

    Deliberately not an image, a crop, or a tracking id. This is the widest
    the detector's output is ever allowed to get, and it exists only between
    inference and the count.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def anchor(self) -> Point:
        """The point that decides whether this detection is in the queue.

        Bottom-centre: where the person's feet are.

        The obvious choice is the box centre, and it is wrong. A person
        standing just outside the ROI who leans over the boundary gets counted;
        a tall person standing inside it near the edge does not. Worse, boxes
        clipped by the frame edge have centres that drift toward the middle of
        the frame, so the bias is not even uniform. Someone occupies the floor
        they stand on, so the floor is what gets tested.
        """
        return ((self.x1 + self.x2) / 2.0, self.y2)


@dataclass(frozen=True, slots=True)
class Roi:
    """A queue region, and the version tag that identifies this exact shape.

    `version` is stamped onto every count produced under this polygon. Redraw
    the polygon, bump the version: history stays interpretable because a reader
    can tell which counts were measured against which region instead of
    assuming a single unbroken series.
    """

    version: str
    vertices: tuple[Point, ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise InvalidRoi(f"a polygon needs at least 3 vertices, got {len(self.vertices)}")
        for x, y in self.vertices:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise InvalidRoi(
                    f"vertex ({x}, {y}) is outside the normalised frame; "
                    "coordinates are fractions of width and height, not pixels"
                )
        if self.area < MIN_ROI_AREA:
            raise InvalidRoi(
                f"polygon area {self.area:.2e} is degenerate (< {MIN_ROI_AREA:.0e}); "
                "it would count nobody. Check the polygon for this hall."
            )

    @classmethod
    def from_json(cls, raw: str | Sequence[Sequence[float]], version: str) -> Roi:
        """Build an ROI from what `halls.roi_polygon` holds.

        Accepts either the jsonb string or the already-decoded list, because
        which one you get depends on the client library's mood.
        """
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            raise InvalidRoi(f"expected a list of [x, y] pairs, got {type(data).__name__}")
        try:
            vertices = tuple((float(p[0]), float(p[1])) for p in data)
        except (TypeError, IndexError, ValueError) as exc:
            raise InvalidRoi(f"malformed vertex list: {exc}") from exc
        return cls(version=version, vertices=vertices)

    @property
    def area(self) -> float:
        """Polygon area by the shoelace formula, as a fraction of the frame.

        Used to reject degenerate polygons at load time, and useful on its own:
        an ROI covering 0.9 of the frame is not a queue region, it is the whole
        room with extra steps.
        """
        total = 0.0
        n = len(self.vertices)
        for i in range(n):
            x1, y1 = self.vertices[i]
            x2, y2 = self.vertices[(i + 1) % n]
            total += x1 * y2 - x2 * y1
        return abs(total) / 2.0

    def contains(self, point: Point) -> bool:
        """Crossing-number point-in-polygon test.

        Cast a ray in +x from the point and count how many edges it crosses;
        odd means inside. Handles concave polygons, which matters because a
        real queue region bends around a corner more often than not.

        Edges are treated as half-open in y (`y1 > y` vs `y2 > y`) so a vertex
        exactly level with the test point is counted once, not zero or twice.
        The guard also makes the division below safe: the branch is only
        entered when y1 != y2.
        """
        x, y = point
        inside = False
        n = len(self.vertices)
        for i in range(n):
            x1, y1 = self.vertices[i]
            x2, y2 = self.vertices[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                x_crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < x_crossing:
                    inside = not inside
        return inside

    def count_inside(self, boxes: Iterable[BoundingBox]) -> int:
        """Reduce detections to the single integer this project publishes."""
        return sum(1 for box in boxes if self.contains(box.anchor))
