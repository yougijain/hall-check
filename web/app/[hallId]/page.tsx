import Link from "next/link";
import { notFound } from "next/navigation";

import { OccupancyChart } from "@/components/OccupancyChart";
import { describeAge, freshnessOf } from "@/lib/freshness";
import { formatClockTime, openStateAt, startOfCampusDay } from "@/lib/hours";
import { getHallLatest, getHalls, getTodaysCounts } from "@/lib/data";

export const revalidate = 60;

export async function generateStaticParams() {
  const halls = await getHalls();
  return halls.map((hall) => ({ hallId: hall.hall_id }));
}

export default async function HallPage({ params }: { params: Promise<{ hallId: string }> }) {
  const { hallId } = await params;

  const [latestRows, points] = await Promise.all([getHallLatest(), getTodaysCounts(hallId)]);
  const hall = latestRows.find((row) => row.hall_id === hallId);

  if (!hall) notFound();

  const now = new Date();
  const dayStart = startOfCampusDay(now);
  const freshness = freshnessOf(hall.ts, now);
  const closed = openStateAt(hall.opens_at, hall.closes_at, now) === "closed";
  const showNumber = freshness.showCount && !closed;

  const peak = points.reduce((highest, point) => Math.max(highest, point.count), 0);

  return (
    <>
      <Link href="/" className="text-sm underline underline-offset-2">
        ← All halls
      </Link>

      <h2 className="mt-4 text-xl font-semibold">{hall.name}</h2>

      <div className="mt-3 flex items-baseline gap-2">
        {showNumber ? (
          <>
            <span className="tnum text-5xl font-semibold">{hall.count}</span>
            <span className="text-sm" style={{ color: "var(--text-soft)" }}>
              {hall.count === 1 ? "person" : "people"} · {describeAge(freshness.ageSeconds)}
            </span>
          </>
        ) : (
          <span className="text-3xl font-medium" style={{ color: "var(--color-unknown)" }}>
            {closed ? "Closed" : "No recent data"}
          </span>
        )}
      </div>

      <section className="mt-8">
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-sm font-medium">Today</h3>
          {peak > 0 ? (
            <span className="text-xs" style={{ color: "var(--text-soft)" }}>
              Peak {peak}
            </span>
          ) : null}
        </div>

        <OccupancyChart points={points} start={dayStart} end={now} />

        {/*
          Gaps in the line are outages, not quiet periods. Saying so removes
          the most likely misreading of the chart.
        */}
        <p className="mt-2 text-xs" style={{ color: "var(--text-soft)" }}>
          A break in the line means no reading was recorded, not that the hall was empty.
        </p>
      </section>

      <section className="mt-8 text-sm" style={{ color: "var(--text-soft)" }}>
        <h3 className="mb-2 font-medium" style={{ color: "var(--text)" }}>
          How this was measured
        </h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt>Hours</dt>
          <dd>
            {formatClockTime(hall.opens_at) && formatClockTime(hall.closes_at)
              ? `${formatClockTime(hall.opens_at)} – ${formatClockTime(hall.closes_at)}`
              : "Not configured"}
          </dd>
          <dt>Detector</dt>
          <dd className="font-mono text-xs">{hall.model_version}</dd>
          <dt>Queue region</dt>
          <dd className="font-mono text-xs">{hall.roi_version}</dd>
          <dt>Camera epoch</dt>
          <dd className="font-mono text-xs">{hall.camera_epoch}</dd>
        </dl>
        <p className="mt-3">
          Counts are only comparable to other counts sharing the same queue region and
          camera epoch. Both change when the camera moves or the region is redrawn, which
          is why they are published alongside the number.
        </p>
      </section>
    </>
  );
}
