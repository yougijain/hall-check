import { describe, expect, it } from "vitest";

import {
  LIVE_MAX_AGE_SECONDS,
  UNKNOWN_AFTER_SECONDS,
  describeAge,
  freshnessOf,
} from "./freshness";

const NOW = new Date("2026-03-04T17:00:00Z");

function agedBy(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

describe("freshnessOf", () => {
  it("treats a just-captured reading as live", () => {
    const result = freshnessOf(agedBy(30), NOW);
    expect(result.state).toBe("live");
    expect(result.showCount).toBe(true);
  });

  it("tolerates a single missed capture", () => {
    // One dropped frame or a redeploy is ordinary and should not put a
    // warning next to an otherwise good number.
    expect(freshnessOf(agedBy(LIVE_MAX_AGE_SECONDS - 1), NOW).state).toBe("live");
  });

  it("flags a reading that has outlived two intervals", () => {
    const result = freshnessOf(agedBy(LIVE_MAX_AGE_SECONDS + 60), NOW);
    expect(result.state).toBe("stale");
    expect(result.showCount).toBe(true);
  });

  it("withholds the number once it stops describing the room", () => {
    // The failure this guards: the worker dies at 12:05 with a count of 3, a
    // student loads the page at 12:40, and walks into a queue out the door.
    const result = freshnessOf(agedBy(UNKNOWN_AFTER_SECONDS + 1), NOW);
    expect(result.state).toBe("unknown");
    expect(result.showCount).toBe(false);
  });

  it("reports unknown when there has never been a reading", () => {
    expect(freshnessOf(null, NOW)).toEqual({
      state: "unknown",
      ageSeconds: null,
      showCount: false,
    });
  });

  it("reports unknown for an unparseable timestamp", () => {
    expect(freshnessOf("not a date", NOW).showCount).toBe(false);
  });

  it("clamps clock skew instead of rendering a negative age", () => {
    const fromTheFuture = new Date(NOW.getTime() + 5000).toISOString();
    const result = freshnessOf(fromTheFuture, NOW);
    expect(result.ageSeconds).toBe(0);
    expect(result.state).toBe("live");
  });

  it("accepts a Date as well as a string", () => {
    expect(freshnessOf(new Date(NOW.getTime() - 30_000), NOW).state).toBe("live");
  });
});

describe("describeAge", () => {
  it.each([
    [null, "never"],
    [0, "just now"],
    [59, "just now"],
    [60, "1 min ago"],
    [4 * 60, "4 min ago"],
    [60 * 60, "1 hr ago"],
    [3 * 60 * 60, "3 hr ago"],
    [25 * 60 * 60, "yesterday"],
    [72 * 60 * 60, "3 days ago"],
  ])("renders %s seconds as %s", (seconds, expected) => {
    expect(describeAge(seconds)).toBe(expected);
  });
});
