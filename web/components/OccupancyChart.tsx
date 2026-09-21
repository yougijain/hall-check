import { buildGeometry } from "@/lib/chart";
import { CAMPUS_TIMEZONE } from "@/lib/hours";
import type { CountPoint } from "@/lib/types";

const WIDTH = 640;
const HEIGHT = 190;
const PADDING_LEFT = 28;
const PADDING_BOTTOM = 22;
// The topmost axis label sits on the y=0 gridline. Without headroom its text
// box extends above the viewBox and the number is sliced in half.
const PADDING_TOP = 8;

function hourLabel(at: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: CAMPUS_TIMEZONE,
    hour: "numeric",
    hour12: true,
  }).format(at);
}

/**
 * Today's curve.
 *
 * Server-rendered SVG with no charting dependency: the whole chart is one path
 * per unbroken run of readings, and the geometry is computed by pure functions
 * in lib/chart.ts that are unit tested.
 *
 * The line breaks wherever the worker missed several captures in a row, rather
 * than interpolating across the hole. An outage drawn as a smooth curve is
 * indistinguishable from measured data, which is the one thing a chart of
 * measurements must not do.
 */
export function OccupancyChart({
  points,
  start,
  end,
}: {
  points: CountPoint[];
  start: Date;
  end: Date;
}) {
  const plotWidth = WIDTH - PADDING_LEFT;
  const plotHeight = HEIGHT - PADDING_BOTTOM - PADDING_TOP;

  const geometry = buildGeometry(points, {
    width: plotWidth,
    height: plotHeight,
    start: start.getTime(),
    end: end.getTime(),
  });

  if (points.length === 0) {
    return (
      <div
        className="flex h-[190px] items-center justify-center rounded-xl border text-sm"
        style={{ borderColor: "var(--border)", color: "var(--text-soft)" }}
      >
        No readings yet today.
      </div>
    );
  }

  const hourTicks: { x: number; label: string }[] = [];
  const span = end.getTime() - start.getTime();
  for (let hour = 0; hour <= 24; hour += 4) {
    const at = new Date(start.getTime() + hour * 3_600_000);
    if (at > end) break;
    hourTicks.push({
      x: ((at.getTime() - start.getTime()) / span) * plotWidth,
      label: hourLabel(at),
    });
  }

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full"
      role="img"
      aria-label={`Occupancy today, peaking at about ${Math.max(
        ...points.map((p) => p.count),
      )} people`}
    >
      <g transform={`translate(${PADDING_LEFT}, ${PADDING_TOP})`}>
        {geometry.yTicks.map((tick) => {
          const y = plotHeight - (tick / geometry.yMax) * plotHeight;
          return (
            <g key={tick}>
              <line
                x1={0}
                x2={plotWidth}
                y1={y}
                y2={y}
                stroke="var(--border)"
                strokeWidth={1}
              />
              <text
                x={-6}
                y={y + 3}
                textAnchor="end"
                fontSize={10}
                fill="var(--text-soft)"
                className="tnum"
              >
                {tick}
              </text>
            </g>
          );
        })}

        {geometry.areas.map((path, index) => (
          <path key={`area-${index}`} d={path} fill="var(--color-quiet)" opacity={0.18} />
        ))}

        {geometry.segments.map((path, index) => (
          <path
            key={`line-${index}`}
            d={path}
            fill="none"
            stroke="var(--color-quiet)"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}

        {hourTicks.map((tick) => (
          <text
            key={tick.label}
            x={tick.x}
            // Relative to the plot, not the viewBox: this text lives inside
            // the translated group, so measuring from HEIGHT pushes it out
            // the bottom by exactly PADDING_TOP.
            y={plotHeight + 16}
            textAnchor="middle"
            fontSize={10}
            fill="var(--text-soft)"
          >
            {tick.label}
          </text>
        ))}
      </g>
    </svg>
  );
}
