import { describe, expect, it } from "vitest";

import {
  formatClockTime,
  minutesSinceMidnight,
  openStateAt,
  parseClockTime,
  startOfCampusDay,
  timeZoneOffsetMinutes,
} from "./hours";

describe("parseClockTime", () => {
  it.each([
    ["07:00", 420],
    ["07:00:00", 420],
    ["00:00", 0],
    ["23:59", 1439],
  ])("parses %s", (value, expected) => {
    expect(parseClockTime(value)).toBe(expected);
  });

  it.each([null, undefined, "", "nonsense", "25:00", "07:99"])(
    "returns null for %s",
    (value) => {
      expect(parseClockTime(value)).toBeNull();
    },
  );
});

describe("minutesSinceMidnight", () => {
  it("uses the campus timezone, not UTC", () => {
    // 17:00 UTC is 12:00 in Amherst during EST.
    expect(minutesSinceMidnight(new Date("2026-01-15T17:00:00Z"))).toBe(12 * 60);
  });

  it("follows daylight saving", () => {
    // The same UTC instant in July is 13:00 in Amherst, not 12:00.
    expect(minutesSinceMidnight(new Date("2026-07-15T17:00:00Z"))).toBe(13 * 60);
  });

  it("reports local midnight as zero, not 1440", () => {
    expect(minutesSinceMidnight(new Date("2026-01-15T05:00:00Z"))).toBe(0);
  });
});

describe("openStateAt", () => {
  const lunchtime = new Date("2026-01-15T17:00:00Z"); // 12:00 EST
  const lateNight = new Date("2026-01-15T05:30:00Z"); // 00:30 EST

  it("is open inside service hours", () => {
    expect(openStateAt("07:00", "21:00", lunchtime)).toBe("open");
  });

  it("is closed outside them", () => {
    expect(openStateAt("07:00", "21:00", lateNight)).toBe("closed");
  });

  it("handles a hall that closes after midnight", () => {
    // 07:00 to 01:00 wraps the day boundary. Treating it as a single
    // open <= now < close range would report the hall shut all day.
    expect(openStateAt("07:00", "01:00", lateNight)).toBe("open");
    expect(openStateAt("07:00", "01:00", lunchtime)).toBe("open");
    expect(openStateAt("07:00", "01:00", new Date("2026-01-15T08:00:00Z"))).toBe("closed");
  });

  it("is exclusive at closing time", () => {
    expect(openStateAt("07:00", "12:00", lunchtime)).toBe("closed");
  });

  it("is inclusive at opening time", () => {
    expect(openStateAt("12:00", "21:00", lunchtime)).toBe("open");
  });

  it("says unknown when hours are not configured", () => {
    expect(openStateAt(null, "21:00", lunchtime)).toBe("unknown");
    expect(openStateAt("07:00", null, lunchtime)).toBe("unknown");
  });
});

describe("timeZoneOffsetMinutes", () => {
  it("is -300 during eastern standard time", () => {
    expect(timeZoneOffsetMinutes(new Date("2026-01-15T17:00:00Z"))).toBe(-300);
  });

  it("is -240 during eastern daylight time", () => {
    expect(timeZoneOffsetMinutes(new Date("2026-07-15T17:00:00Z"))).toBe(-240);
  });
});

describe("startOfCampusDay", () => {
  it("returns local midnight in Amherst, not UTC midnight", () => {
    const start = startOfCampusDay(new Date("2026-01-15T17:00:00Z"));
    expect(start.toISOString()).toBe("2026-01-15T05:00:00.000Z");
  });

  it("is correct in summer too", () => {
    const start = startOfCampusDay(new Date("2026-07-15T17:00:00Z"));
    expect(start.toISOString()).toBe("2026-07-15T04:00:00.000Z");
  });

  it("is correct on the day the clocks go forward", () => {
    // 2026-03-08 is the US spring transition. Midnight that day is still EST,
    // so the correction pass has to land on -05:00 and not on the -04:00 that
    // is in effect by the afternoon.
    const start = startOfCampusDay(new Date("2026-03-08T18:00:00Z"));
    expect(start.toISOString()).toBe("2026-03-08T05:00:00.000Z");
  });

  it("does not skip into the previous day late at night", () => {
    // 04:00 UTC is 23:00 the previous evening in Amherst, so the campus day
    // that is currently running began that morning.
    const start = startOfCampusDay(new Date("2026-01-16T04:00:00Z"));
    expect(start.toISOString()).toBe("2026-01-15T05:00:00.000Z");
  });
});

describe("formatClockTime", () => {
  it.each([
    ["07:00:00", "7:00 AM"],
    ["12:00", "12:00 PM"],
    ["00:00", "12:00 AM"],
    ["21:30", "9:30 PM"],
  ])("renders %s as %s", (value, expected) => {
    expect(formatClockTime(value)).toBe(expected);
  });

  it("returns null when there is nothing to format", () => {
    expect(formatClockTime(null)).toBeNull();
  });
});
