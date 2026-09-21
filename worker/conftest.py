"""Make `hallcheck` importable when the package has not been installed.

Keeps `pytest` working from a bare checkout, which is what a reviewer does
first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
