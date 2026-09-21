import Link from "next/link";

import { describeAge, freshnessOf } from "@/lib/freshness";
import { formatClockTime, openStateAt } from "@/lib/hours";
import type { HallLatest } from "@/lib/types";

/**
 * Magnitude cue, not a verdict.
 *
 * Deliberately not a red/amber/green traffic light: "green" would read as a
 * promise about wait time, and this project measures a proxy for a queue with
 * known error. The scale runs cool to warm so a glance conveys more or fewer
 * people without implying a recommendation.
 */
function busyness(count: number): { label: string; color: string } {
  if (count <= 8) return { label: "Quiet", color: "var(--color-quiet)" };
  if (count <= 25) return { label: "Moderate", color: "var(--color-moderate)" };
  return { label: "Busy", color: "var(--color-busy)" };
}

export function HallCard({ hall, now }: { hall: HallLatest; now: Date }) {
  const freshness = freshnessOf(hall.ts, now);
  const openState = openStateAt(hall.opens_at, hall.closes_at, now);

  // Order matters. A closed hall reporting "0 people" is true and useless - it
  // reads as "no queue, go now". Closed is the answer to the question actually
  // being asked, so it wins over the number.
  const closed = openState === "closed";
  const showNumber = freshness.showCount && !closed;
  const tone = showNumber ? busyness(hall.count) : null;

  const hours =
    formatClockTime(hall.opens_at) && formatClockTime(hall.closes_at)
      ? `${formatClockTime(hall.opens_at)} – ${formatClockTime(hall.closes_at)}`
      : null;

  return (
    <Link
      href={`/${hall.hall_id}`}
      className="block rounded-xl border p-4 transition-colors hover:border-current focus-visible:outline-2 focus-visible:outline-offset-2"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
    >
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-base font-medium">{hall.name}</h2>
        {tone ? (
          <span className="text-xs font-medium" style={{ color: tone.color }}>
            {tone.label}
          </span>
        ) : null}
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        {showNumber ? (
          <>
            <span className="tnum text-4xl font-semibold tabular-nums">{hall.count}</span>
            <span className="text-sm" style={{ color: "var(--text-soft)" }}>
              {hall.count === 1 ? "person" : "people"}
            </span>
          </>
        ) : (
          <span className="text-2xl font-medium" style={{ color: "var(--color-unknown)" }}>
            {closed ? "Closed" : "No recent data"}
          </span>
        )}
      </div>

      <p className="mt-2 text-xs" style={{ color: "var(--text-soft)" }}>
        {closed ? (
          hours ? `Opens ${formatClockTime(hall.opens_at)} · ${hours}` : "Currently closed"
        ) : freshness.state === "unknown" ? (
          // Say why the number is missing. "No recent data" with no
          // explanation looks like the site is broken, which is a different
          // problem from the camera being down.
          <>Last reading {describeAge(freshness.ageSeconds)} — the camera feed may be down</>
        ) : freshness.state === "stale" ? (
          <>Updated {describeAge(freshness.ageSeconds)} — may be behind</>
        ) : (
          <>Updated {describeAge(freshness.ageSeconds)}</>
        )}
      </p>
    </Link>
  );
}
