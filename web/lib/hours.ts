/**
 * Service hours, in the dining halls' own timezone.
 *
 * A closed hall showing "0 people" is technically true and completely useless:
 * it reads as "no queue, go now". Knowing the hall is shut is the answer to
 * the question the reader is actually asking.
 *
 * Everything here works in America/New_York rather than the server's timezone
 * or the browser's. The server is wherever Vercel put it, and a student
 * checking the page from home over break should still see Amherst's hours.
 */

export const CAMPUS_TIMEZONE = "America/New_York";

/** Minutes since local midnight, for the campus timezone. */
export function minutesSinceMidnight(at: Date, timeZone: string = CAMPUS_TIMEZONE): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(at);

  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? "0");

  // Intl renders midnight as "24" in some ICU versions under hour12: false.
  return (hour % 24) * 60 + minute;
}

/** Parse "07:00" or "07:00:00" into minutes since midnight. */
export function parseClockTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = /^(\d{1,2}):(\d{2})(?::\d{2})?/.exec(value.trim());
  if (!match) return null;

  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;

  return hours * 60 + minutes;
}

export type OpenState = "open" | "closed" | "unknown";

export function openStateAt(
  opensAt: string | null | undefined,
  closesAt: string | null | undefined,
  now: Date = new Date(),
): OpenState {
  const open = parseClockTime(opensAt);
  const close = parseClockTime(closesAt);
  if (open === null || close === null) return "unknown";

  const nowMinutes = minutesSinceMidnight(now);

  // A hall closing after midnight (07:00 to 01:00) wraps around, so the
  // interval is the union of two ranges rather than one. Treating it as
  // open <= now < close would report such a hall shut all day.
  if (close <= open) {
    return nowMinutes >= open || nowMinutes < close ? "open" : "closed";
  }
  return nowMinutes >= open && nowMinutes < close ? "open" : "closed";
}

/** "7:00 AM" from "07:00:00", for display. */
export function formatClockTime(value: string | null | undefined): string | null {
  const minutes = parseClockTime(value);
  if (minutes === null) return null;

  const hours24 = Math.floor(minutes / 60);
  const mins = minutes % 60;
  const suffix = hours24 >= 12 ? "PM" : "AM";
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;

  return `${hours12}:${String(mins).padStart(2, "0")} ${suffix}`;
}

/**
 * Offset of a timezone from UTC, in minutes, at a given instant.
 *
 * Derived by formatting the instant in the target zone and reading the result
 * back as if it were UTC; the difference is the offset. Doing it this way
 * rather than hard-coding -05:00 means daylight saving is handled by ICU
 * instead of by us.
 */
export function timeZoneOffsetMinutes(at: Date, timeZone: string = CAMPUS_TIMEZONE): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(at);

  const read = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((p) => p.type === type)?.value ?? "0");

  const asIfUtc = Date.UTC(
    read("year"),
    read("month") - 1,
    read("day"),
    read("hour") % 24,
    read("minute"),
    read("second"),
  );

  return (asIfUtc - at.getTime()) / 60_000;
}

/**
 * The instant at which the current campus day began.
 *
 * "Today's curve" has to mean today in Amherst, not today wherever Vercel
 * scheduled the render. On the two days a year the offset changes, the offset
 * at midnight differs from the offset now, so the first result is corrected
 * once against the offset actually in effect at that instant.
 */
export function startOfCampusDay(now: Date = new Date(), timeZone: string = CAMPUS_TIMEZONE): Date {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);

  const [year, month, day] = parts.split("-").map(Number);
  const midnightAsUtc = Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1);

  const firstGuess = new Date(midnightAsUtc - timeZoneOffsetMinutes(now, timeZone) * 60_000);
  const corrected = new Date(
    midnightAsUtc - timeZoneOffsetMinutes(firstGuess, timeZone) * 60_000,
  );
  return corrected;
}
