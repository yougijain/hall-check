import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { HallCard } from "./HallCard";
import type { HallLatest } from "@/lib/types";

const NOON = new Date("2026-01-15T17:00:00Z"); // 12:00 in Amherst, EST
const MIDNIGHT = new Date("2026-01-15T05:30:00Z"); // 00:30 in Amherst

function hall(overrides: Partial<HallLatest> = {}): HallLatest {
  return {
    hall_id: "worcester",
    name: "Worcester Commons",
    ts: new Date(NOON.getTime() - 60_000).toISOString(),
    count: 14,
    model_version: "yolo11n.pt@conf0.35",
    roi_version: "v1",
    camera_epoch: 1,
    opens_at: "07:00:00",
    closes_at: "21:00:00",
    ...overrides,
  };
}

function render(props: Parameters<typeof HallCard>[0]): string {
  return renderToStaticMarkup(<HallCard {...props} />);
}

describe("HallCard", () => {
  it("shows a fresh count", () => {
    const html = render({ hall: hall({ count: 14 }), now: NOON });
    expect(html).toContain("14");
    expect(html).toContain("people");
    expect(html).toContain("Updated");
  });

  it("uses the singular for one person", () => {
    const html = render({ hall: hall({ count: 1 }), now: NOON });
    expect(html).toContain(">person<");
  });

  it("shows a genuine zero while the hall is open", () => {
    // An open, empty hall is a real and useful reading.
    const html = render({ hall: hall({ count: 0 }), now: NOON });
    expect(html).toContain(">0<");
    expect(html).not.toContain("Closed");
  });

  it("says Closed rather than a count outside service hours", () => {
    // The regression this pins: "0 people" at 00:30 reads as "no queue, go
    // now" when the correct answer is that the hall is shut.
    const html = render({
      hall: hall({ count: 0, ts: new Date(MIDNIGHT.getTime() - 60_000).toISOString() }),
      now: MIDNIGHT,
    });
    expect(html).toContain("Closed");
    expect(html).not.toContain("people");
  });

  it("hides a count that has stopped describing the room", () => {
    const html = render({
      hall: hall({ count: 3, ts: new Date(NOON.getTime() - 40 * 60_000).toISOString() }),
      now: NOON,
    });
    expect(html).toContain("No recent data");
    expect(html).not.toContain(">3<");
    // Say why, so a dead camera does not read as a broken site.
    expect(html).toContain("camera feed may be down");
  });

  it("still shows a slightly behind count, but flags it", () => {
    const html = render({
      hall: hall({ count: 9, ts: new Date(NOON.getTime() - 6 * 60_000).toISOString() }),
      now: NOON,
    });
    expect(html).toContain(">9<");
    expect(html).toContain("may be behind");
  });

  it("links to the hall's own page", () => {
    expect(render({ hall: hall(), now: NOON })).toContain('href="/worcester"');
  });

  it("labels busyness without a traffic-light verdict", () => {
    // "Quiet"/"Busy" is a magnitude cue. A green light would read as a promise
    // about wait time that a proxy measurement cannot make.
    expect(render({ hall: hall({ count: 3 }), now: NOON })).toContain("Quiet");
    expect(render({ hall: hall({ count: 40 }), now: NOON })).toContain("Busy");
  });
});
