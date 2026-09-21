import { PrivacyBanner } from "@/components/PrivacyBanner";
import { HallCard } from "@/components/HallCard";
import { getHallLatest } from "@/lib/data";
import { isConfigured } from "@/lib/supabase";

// Captures land every two minutes, so a cached page is at most half an
// interval behind. Rendering on every request would hammer the database for
// a number that has not changed.
export const revalidate = 60;

export default async function HomePage() {
  const halls = await getHallLatest();
  const now = new Date();

  return (
    <>
      <PrivacyBanner />

      {!isConfigured ? (
        <SetupNotice />
      ) : halls.length === 0 ? (
        <EmptyNotice />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {halls.map((hall) => (
            <HallCard key={hall.hall_id} hall={hall} now={now} />
          ))}
        </div>
      )}

      <section className="mt-10 text-sm" style={{ color: "var(--text-soft)" }}>
        <h2 className="mb-2 font-medium" style={{ color: "var(--text)" }}>
          What the number means
        </h2>
        <p>
          It is how many people a person detector found inside a fixed region covering
          each hall&apos;s queue area, from one frame taken a couple of minutes ago. It is
          not a wait time and not a headcount of the building.
        </p>
        <p className="mt-2">
          It under-counts when the line is long, because people stand behind each other
          and the detector only sees the front. That error is largest exactly when the
          number matters most, so treat a high count as &ldquo;at least this many&rdquo;.
        </p>
      </section>
    </>
  );
}

function SetupNotice() {
  return (
    <div
      className="rounded-xl border p-4 text-sm"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
    >
      <p className="font-medium">Not connected to a database.</p>
      <p className="mt-1" style={{ color: "var(--text-soft)" }}>
        Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
        <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code>. See <code>web/.env.example</code>.
      </p>
    </div>
  );
}

function EmptyNotice() {
  return (
    <div
      className="rounded-xl border p-4 text-sm"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
    >
      <p className="font-medium">No readings yet.</p>
      <p className="mt-1" style={{ color: "var(--text-soft)" }}>
        The worker has not recorded a count for any hall. Check that it is running and
        that each hall has a stream URL configured.
      </p>
    </div>
  );
}
