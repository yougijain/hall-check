import { describe, expect, it } from "vitest";

import { GAP_THRESHOLD_SECONDS, buildGeometry, niceCeiling, splitOnGaps } from "./chart";
import type { CountPoint } from "./types";

const DAY_START = Date.parse("2026-03-04T05:00:00Z");

function series(offsetsMinutes: number[], counts: number[]): CountPoint[] {
  return offsetsMinutes.map((minutes, index) => ({
    ts: new Date(DAY_START + minutes * 60_000).toISOString(),
    count: counts[index] ?? 0,
  }));
}

describe("niceCeiling", () => {
  it.each([
    [0, 5],
    [3, 5],
    [5, 5],
    [7, 10],
    [10, 10],
    [11, 20],
    [23, 25],
    [36, 40],
    [48, 50],
    [120, 200],
  ])("rounds %i up to %i", (value, expected) => {
    expect(niceCeiling(value)).toBe(expected);
  });
});

describe("splitOnGaps", () => {
  it("keeps a continuous run as one segment", () => {
    const segments = splitOnGaps(series([0, 2, 4, 6], [1, 2, 3, 4]));
    expect(segments).toHaveLength(1);
    expect(segments[0]).toHaveLength(4);
  });

  it("breaks the line where the worker was not running", () => {
    // Four readings, then a 40 minute hole, then two more. Drawing straight
    // through the hole would render an outage as a smooth curve.
    const segments = splitOnGaps(series([0, 2, 4, 6, 46, 48], [1, 2, 3, 4, 9, 8]));
    expect(segments.map((s) => s.length)).toEqual([4, 2]);
  });

  it("joins across a single missed capture", () => {
    const segments = splitOnGaps(series([0, 2, 6], [1, 2, 3]));
    expect(segments).toHaveLength(1);
  });

  it("splits exactly beyond the threshold, not at it", () => {
    const atThreshold = GAP_THRESHOLD_SECONDS / 60;
    expect(splitOnGaps(series([0, atThreshold], [1, 2]))).toHaveLength(1);
    expect(splitOnGaps(series([0, atThreshold + 1], [1, 2]))).toHaveLength(2);
  });

  it("sorts readings that arrive out of order", () => {
    const segments = splitOnGaps(series([4, 0, 2], [3, 1, 2]));
    expect(segments[0]?.map((p) => p.count)).toEqual([1, 2, 3]);
  });

  it("drops unparseable timestamps rather than placing them at epoch zero", () => {
    const points = [...series([0, 2], [1, 2]), { ts: "garbage", count: 99 }];
    expect(splitOnGaps(points).flat()).toHaveLength(2);
  });

  it("returns nothing for an empty series", () => {
    expect(splitOnGaps([])).toEqual([]);
  });
});

describe("buildGeometry", () => {
  const options = {
    width: 600,
    height: 200,
    start: DAY_START,
    end: DAY_START + 12 * 60 * 60_000,
  };

  it("produces one path per unbroken run", () => {
    const geometry = buildGeometry(series([0, 2, 4, 60, 62], [1, 2, 3, 8, 9]), options);
    expect(geometry.segments).toHaveLength(2);
  });

  it("closes each area path back to the baseline", () => {
    const geometry = buildGeometry(series([0, 2, 4], [1, 2, 3]), options);
    expect(geometry.areas[0]).toMatch(/Z$/);
    expect(geometry.areas[0]).toContain(`L ${(0).toFixed(2)}`.slice(0, 2));
  });

  it("scales the peak to the top of the axis", () => {
    const geometry = buildGeometry(series([0, 2], [0, 10]), options);
    expect(geometry.yMax).toBe(10);
    // The 10 sits at y=0, the 0 sits at y=height.
    expect(geometry.segments[0]).toContain("200.00");
    expect(geometry.segments[0]).toContain("0.00");
  });

  it("never collapses an all-zero day onto the top of the chart", () => {
    const geometry = buildGeometry(series([0, 2, 4], [0, 0, 0]), options);
    expect(geometry.yMax).toBeGreaterThan(0);
    expect(geometry.segments[0]).not.toContain(" 0.00 0.00");
  });

  it("still marks a lone reading", () => {
    const geometry = buildGeometry(series([0], [7]), options);
    expect(geometry.segments).toHaveLength(1);
    expect(geometry.areas).toHaveLength(0);
  });

  it("labels the axis on round numbers", () => {
    // 0, 13, 25, 38, 50 is the arithmetic showing through. Readers should see
    // numbers a person would have picked.
    expect(buildGeometry(series([0, 2], [0, 36]), options).yTicks).toEqual([0, 10, 20, 30, 40]);
    expect(buildGeometry(series([0, 2], [0, 18]), options).yTicks).toEqual([0, 5, 10, 15, 20]);
    expect(buildGeometry(series([0, 2], [0, 42]), options).yTicks).toEqual([0, 10, 20, 30, 40, 50]);
  });

  it("returns empty geometry with no data", () => {
    const geometry = buildGeometry([], options);
    expect(geometry.segments).toEqual([]);
    expect(geometry.areas).toEqual([]);
    expect(geometry.yTicks[geometry.yTicks.length - 1]).toBe(geometry.yMax);
  });

  it("keeps every point inside the viewport", () => {
    const geometry = buildGeometry(series([0, 180, 360, 719], [3, 40, 12, 5]), options);
    const coordinates = geometry.segments
      .join(" ")
      .split(/[ML]/)
      .map((pair) => pair.trim())
      .filter(Boolean)
      .map((pair) => pair.split(/\s+/).map(Number));

    for (const [x, y] of coordinates) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(options.width);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(options.height);
    }
  });
});
