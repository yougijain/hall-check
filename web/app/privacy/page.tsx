import Link from "next/link";

export const metadata = { title: "Privacy — Hall Check" };

export default function PrivacyPage() {
  return (
    <article className="text-sm leading-relaxed">
      <Link href="/" className="underline underline-offset-2">
        ← Back
      </Link>

      <h2 className="mt-4 text-xl font-semibold">Privacy</h2>

      <p className="mt-4 text-base font-medium">Hall Check stores counts, never frames.</p>

      <p className="mt-4" style={{ color: "var(--text-soft)" }}>
        A frame is read from the university&apos;s public stream into memory, passed to a
        person detector, and discarded in the same step that produced it. What is kept is
        a single number per hall per reading, plus the information needed to interpret it:
        which hall, when, which detector version, which confidence threshold, which queue
        region, and which camera placement.
      </p>

      <h3 className="mt-6 font-medium">What is never stored</h3>
      <p className="mt-2" style={{ color: "var(--text-soft)" }}>
        Images, video, crops, thumbnails, embeddings, bounding boxes, tracks, or face data
        of any kind.
      </p>
      <p className="mt-2" style={{ color: "var(--text-soft)" }}>
        Bounding boxes get their own sentence because they are the tempting exception. A
        box is a position, a sequence of positions is a trajectory, and a trajectory
        through a public room is behavioural data about someone who never agreed to be
        measured. The detector&apos;s output is reduced to a count inside the same function
        call that produced it.
      </p>

      <h3 className="mt-6 font-medium">How that is enforced</h3>
      <ul className="mt-2 list-disc pl-5" style={{ color: "var(--text-soft)" }}>
        <li>
          The frame is held by a context manager that overwrites it before returning, so
          there is no code path that hands pixels to a caller.
        </li>
        <li>
          A test parses every module in the worker and fails the build if a call that
          could write image data appears in it.
        </li>
        <li>Every change is reviewed against a checklist that asks this specifically.</li>
      </ul>

      <p className="mt-6" style={{ color: "var(--text-soft)" }}>
        The code is public. If you find a path that contradicts any of this, it is a bug of
        the highest severity in the project —{" "}
        <a
          href="https://github.com/yougijain/hall-check/issues"
          className="underline underline-offset-2"
        >
          please open an issue
        </a>
        .
      </p>
    </article>
  );
}
