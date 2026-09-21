"""Hall Check worker.

Captures a frame from a public dining hall stream, counts the people standing
in the queue region, writes the number to Postgres, and discards the frame.

The frame never leaves memory. See docs/privacy.md.
"""

__version__ = "0.1.0"
