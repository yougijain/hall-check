import type { Metadata, Viewport } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Hall Check — live dining hall occupancy",
  description:
    "How busy each UMass Amherst dining hall is right now, estimated from the public video streams. Counts only; frames are never stored.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh">
        <div className="mx-auto flex min-h-dvh max-w-3xl flex-col px-4 py-8 sm:px-6">
          <header className="mb-6">
            <Link href="/" className="inline-block">
              <h1 className="text-2xl font-semibold tracking-tight">Hall Check</h1>
            </Link>
            <p className="mt-1 text-sm" style={{ color: "var(--text-soft)" }}>
              How busy each dining hall is right now.
            </p>
          </header>

          <main className="flex-1">{children}</main>

          <footer
            className="mt-12 border-t pt-6 text-xs"
            style={{ borderColor: "var(--border)", color: "var(--text-soft)" }}
          >
            <p>
              Counts are estimated from public video with a person detector. They are
              approximate, and they under-count at peak when people stand behind each other.
            </p>
            <p className="mt-2">
              <Link href="/privacy" className="underline underline-offset-2">
                Privacy
              </Link>
              <span className="mx-2">·</span>
              <a
                href="https://github.com/yougijain/hall-check"
                className="underline underline-offset-2"
              >
                Source
              </a>
            </p>
          </footer>
        </div>
      </body>
    </html>
  );
}
