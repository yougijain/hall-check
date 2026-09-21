/**
 * Deciding whether a count is still worth showing.
 *
 * The failure mode this exists to prevent: the worker dies at 12:05 with a
 * count of 3, a student opens the page at 12:40, sees "3 people", and walks
 * into a queue out the door. A number with a stale timestamp behind it is
 * worse than no number, because it is confidently wrong and the page gives
 * the reader no way to tell.
 *
 * So the count is only rendered while it is recent enough to still be about
 * the room. Past that it is withheld and the page says it does not know.
 */

/** Seconds between captures. Mirrors HALLCHECK_INTERVAL_SECONDS in the worker. */
export const CAPTURE_INTERVAL_SECONDS = 120;

/**
 * One missed tick is normal - a dropped frame, a slow stream, a redeploy - so
 * a reading stays "live" through a single gap before it is flagged.
 */
export const LIVE_MAX_AGE_SECONDS = CAPTURE_INTERVAL_SECONDS * 2;

/**
 * Past this the count is not shown at all.
 *
 * Fifteen minutes is roughly how long it takes a lunch queue to go from empty
 * to out the door, which makes it the point where a count stops describing the
 * room it was measured in.
 */
export const UNKNOWN_AFTER_SECONDS = 15 * 60;

export type FreshnessState = "live" | "stale" | "unknown";

export interface Freshness {
  state: FreshnessState;
  ageSeconds: number | null;
  /** Whether the count may be shown as a number. False means say "unknown". */
  showCount: boolean;
}

export function freshnessOf(
  observedAt: string | Date | null | undefined,
  now: Date = new Date(),
): Freshness {
  if (!observedAt) {
    return { state: "unknown", ageSeconds: null, showCount: false };
  }

  const observed = observedAt instanceof Date ? observedAt : new Date(observedAt);
  if (Number.isNaN(observed.getTime())) {
    return { state: "unknown", ageSeconds: null, showCount: false };
  }

  // Clamp at zero. A row timestamped slightly in the future means clock skew
  // between the worker and this renderer, not a reading from the future, and
  // a negative age would render as "in 3 seconds".
  const ageSeconds = Math.max(0, Math.round((now.getTime() - observed.getTime()) / 1000));

  if (ageSeconds > UNKNOWN_AFTER_SECONDS) {
    return { state: "unknown", ageSeconds, showCount: false };
  }
  if (ageSeconds > LIVE_MAX_AGE_SECONDS) {
    return { state: "stale", ageSeconds, showCount: true };
  }
  return { state: "live", ageSeconds, showCount: true };
}

/** "just now", "4 min ago", "2 hr ago" - short enough to sit next to a number. */
export function describeAge(ageSeconds: number | null): string {
  if (ageSeconds === null) return "never";
  if (ageSeconds < 60) return "just now";

  const minutes = Math.floor(ageSeconds / 60);
  if (minutes < 60) return `${minutes} min ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;

  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
