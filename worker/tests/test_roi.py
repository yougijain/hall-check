"""The geometry that decides who is standing in the queue."""

from __future__ import annotations

import pytest

from hallcheck.roi import BoundingBox, InvalidRoi, Roi

# A plain rectangle over the middle-left of the frame.
SQUARE = Roi(version="test-v1", vertices=((0.2, 0.2), (0.6, 0.2), (0.6, 0.8), (0.2, 0.8)))

# An L shape. Real queue regions bend around a corner, and the notch is a place
# a convex-only test would wrongly report as inside.
L_SHAPE = Roi(
    version="test-L",
    vertices=(
        (0.1, 0.1),
        (0.5, 0.1),
        (0.5, 0.5),
        (0.9, 0.5),
        (0.9, 0.9),
        (0.1, 0.9),
    ),
)


def box_at(x: float, y: float, *, width: float = 0.04, height: float = 0.12) -> BoundingBox:
    """A detection whose feet land on (x, y)."""
    return BoundingBox(
        x1=x - width / 2,
        y1=y - height,
        x2=x + width / 2,
        y2=y,
        confidence=0.9,
    )


class TestContains:
    def test_interior_point_is_inside(self):
        assert SQUARE.contains((0.4, 0.5))

    @pytest.mark.parametrize(
        "point",
        [(0.1, 0.5), (0.7, 0.5), (0.4, 0.1), (0.4, 0.9)],
        ids=["left", "right", "above", "below"],
    )
    def test_points_outside_each_edge(self, point):
        assert not SQUARE.contains(point)

    def test_concave_notch_is_outside(self):
        # (0.7, 0.3) sits in the bite taken out of the L. A convex hull test
        # would call this inside, and it would count people at the tables.
        assert not L_SHAPE.contains((0.7, 0.3))

    def test_concave_arms_are_inside(self):
        assert L_SHAPE.contains((0.3, 0.3))
        assert L_SHAPE.contains((0.7, 0.7))

    def test_point_level_with_a_vertex_is_counted_once(self):
        # Rays through a vertex are the classic way this algorithm double
        # counts and reports an interior point as outside.
        diamond = Roi(
            version="diamond",
            vertices=((0.5, 0.2), (0.8, 0.5), (0.5, 0.8), (0.2, 0.5)),
        )
        assert diamond.contains((0.5, 0.5))
        assert not diamond.contains((0.05, 0.5))

    def test_is_stable_under_winding_direction(self):
        reversed_square = Roi(version="test-v1", vertices=tuple(reversed(SQUARE.vertices)))
        for point in [(0.4, 0.5), (0.05, 0.05), (0.61, 0.5)]:
            assert reversed_square.contains(point) == SQUARE.contains(point)


class TestAnchor:
    def test_anchor_is_bottom_centre(self):
        box = BoundingBox(x1=0.2, y1=0.1, x2=0.4, y2=0.7, confidence=0.8)
        assert box.anchor == (pytest.approx(0.3), pytest.approx(0.7))

    def test_person_leaning_over_the_boundary_is_not_counted(self):
        # Feet at y=0.85, below the ROI's bottom edge at 0.8, but the box
        # spans up into the region. Counting by box centre would include them.
        leaning = BoundingBox(x1=0.35, y1=0.55, x2=0.45, y2=0.85, confidence=0.9)
        centre_y = (leaning.y1 + leaning.y2) / 2
        assert SQUARE.contains((0.4, centre_y)), "precondition: centre falls inside"
        assert not SQUARE.contains(leaning.anchor)


class TestCountInside:
    def test_counts_only_anchors_in_the_region(self):
        boxes = [box_at(0.4, 0.5), box_at(0.4, 0.6), box_at(0.9, 0.5), box_at(0.4, 0.95)]
        assert SQUARE.count_inside(boxes) == 2

    def test_empty_detection_list_is_zero(self):
        assert SQUARE.count_inside([]) == 0


class TestArea:
    def test_rectangle_area(self):
        assert SQUARE.area == pytest.approx(0.4 * 0.6)

    def test_l_shape_area(self):
        # 0.8 x 0.8 outer square minus the 0.4 x 0.4 notch.
        assert L_SHAPE.area == pytest.approx(0.64 - 0.16)


class TestValidation:
    def test_rejects_fewer_than_three_vertices(self):
        with pytest.raises(InvalidRoi, match="at least 3 vertices"):
            Roi(version="v", vertices=((0.1, 0.1), (0.5, 0.5)))

    def test_rejects_pixel_coordinates(self):
        with pytest.raises(InvalidRoi, match="outside the normalised frame"):
            Roi(version="v", vertices=((100, 200), (400, 200), (400, 500)))

    def test_rejects_a_degenerate_polygon(self):
        with pytest.raises(InvalidRoi, match="degenerate"):
            Roi(version="v", vertices=((0.1, 0.1), (0.2, 0.2), (0.3, 0.3)))


class TestFromJson:
    def test_parses_a_json_string(self):
        roi = Roi.from_json("[[0.2,0.2],[0.6,0.2],[0.6,0.8],[0.2,0.8]]", version="v3")
        assert roi.vertices == SQUARE.vertices
        assert roi.version == "v3"

    def test_parses_a_decoded_list(self):
        roi = Roi.from_json([[0.2, 0.2], [0.6, 0.2], [0.6, 0.8], [0.2, 0.8]], version="v3")
        assert roi.vertices == SQUARE.vertices

    def test_rejects_a_malformed_payload(self):
        with pytest.raises(InvalidRoi):
            Roi.from_json("[[0.2],[0.6,0.2],[0.6,0.8]]", version="v")
