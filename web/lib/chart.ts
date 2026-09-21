/**
 * Geometry for the occupancy curve.
 *
 * Pure functions that turn readings into SVG path strings, kept out of the
 * component so the part that can be wrong is the part that can be tested.
 *
 * The rule that shapes all of it: the chart may not draw anything that was not
 * measured. When the worker misses a run of captures, a line interpolated
 * across the gap invents a smooth curve through an outage and reads as data.
 * The series is split into segments instead, so a gap looks like a gap.
 */

import type { CountPoint } from "./types";

/**
 * A break longer than this starts a new segment.
 *
 * Three capture intervals: one missed tick is ordinary jitter and joining
 * across it is fair, but three in a row means the worker was not running and
 * there is nothing honest to draw between the endpoints.
 */
export const GAP_THRESHOLD_SECONDS = 360;

export interface ChartGeometry {
  /** One path per unbroken run of readings. Empty when there is no data. */
  segments: string[];
  /** Filled counterpart of each segment, closed to the baseline. */
  areas: string[];
  /** Top of the y axis. Always at least 1 so an all-zero day is not a flat line at the top. */
  yMax: number;
  /** Tick values for the y axis, ending at yMax. */
  yTicks: number[];
}

export interface ChartOptions {
  width: number;
  height: number;
  /** Domain start, as epoch milliseconds. */
  start: number;
  /** Domain end, as epoch milliseconds. */
  end: number;
  gapSeconds?: number;
}

/** Round up to something a person would choose for an axis: 5, 10, 25, 50... */
export function niceCeiling(value: number): number {
  if (value <= 5) return 5;
  if (value <= 10) return 10;

  // 4 is in the list so a peak of 36 tops out at 40 rather than jumping to
  // 50 and leaving a third of the chart empty.
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 4, 5, 10]) {
    const candidate = step * magnitude;
    if (value <= candidate) return Math.round(candidate);
  }
  return Math.round(10 * magnitude);
}

export function splitOnGaps(
  points: CountPoint[],
  gapSeconds: number = GAP_THRESHOLD_SECONDS,
): CountPoint[][] {
  const ordered = [...points]
    .filter((p) => !Number.isNaN(Date.parse(p.ts)))
    .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));

  const segments: CountPoint[][] = [];
  let current: CountPoint[] = [];

  for (const point of ordered) {
    const previous = current[current.length - 1];
    if (previous && (Date.parse(point.ts) - Date.parse(previous.ts)) / 1000 > gapSeconds) {
      segments.push(current);
      current = [];
    }
    current.push(point);
  }
  if (current.length > 0) segments.push(current);

  return segments;
}

export function buildGeometry(points: CountPoint[], options: ChartOptions): ChartGeometry {
  const { width, height, start, end } = options;
  const span = Math.max(1, end - start);

  const peak = points.reduce((highest, p) => Math.max(highest, p.count), 0);
  const yMax = niceCeiling(peak);

  const xFor = (ts: string) => ((Date.parse(ts) - start) / span) * width;
  const yFor = (count: number) => height - (Math.min(count, yMax) / yMax) * height;

  const segments: string[] = [];
  const areas: string[] = [];

  for (const run of splitOnGaps(points, options.gapSeconds)) {
    const first = run[0];
    const last = run[run.length - 1];
    if (!first || !last) continue;

    if (run.length === 1) {
      // A lone reading has no line to draw. Emit a zero-length path so the
      // renderer can still mark it with a round line cap rather than dropping
      // the observation entirely.
      const x = xFor(first.ts);
      const y = yFor(first.count);
      segments.push(`M ${x.toFixed(2)} ${y.toFixed(2)} L ${x.toFixed(2)} ${y.toFixed(2)}`);
      continue;
    }

    const line = run
      .map((p, index) => {
        const command = index === 0 ? "M" : "L";
        return `${command} ${xFor(p.ts).toFixed(2)} ${yFor(p.count).toFixed(2)}`;
      })
      .join(" ");

    segments.push(line);
    areas.push(
      `${line} L ${xFor(last.ts).toFixed(2)} ${height.toFixed(2)} ` +
        `L ${xFor(first.ts).toFixed(2)} ${height.toFixed(2)} Z`,
    );
  }

  return { segments, areas, yMax, yTicks: buildTicks(yMax) };
}

/**
 * Axis labels a person would have chosen.
 *
 * Fixed four divisions gives 0, 13, 25, 38, 50 for a max of 50, which is the
 * arithmetic showing through. Pick instead the first division count that
 * divides the max exactly, so the labels land on round numbers.
 */
function buildTicks(yMax: number): number[] {
  const divisions = [4, 5, 2].find((count) => yMax % count === 0) ?? 1;
  const step = yMax / divisions;
  return Array.from({ length: divisions + 1 }, (_, index) => index * step);
}
