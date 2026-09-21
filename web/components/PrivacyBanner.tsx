/**
 * The privacy rule, on the first screen.
 *
 * Not in a footer and not behind a link. Someone landing on a page that says
 * it watches the dining hall cameras deserves to learn what it keeps before
 * they scroll, and the answer is short enough to fit.
 */
export function PrivacyBanner() {
  return (
    <div
      className="mb-6 rounded-lg border px-4 py-3 text-sm"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
    >
      <span className="font-medium">Counts only, never frames.</span>{" "}
      <span style={{ color: "var(--text-soft)" }}>
        A frame is read into memory, a detector returns a number, and the frame is
        discarded in the same step. No image is stored, uploaded, or logged — only
        how many people were in the queue area.
      </span>
    </div>
  );
}
