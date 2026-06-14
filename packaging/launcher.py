"""PyInstaller entry point — imported as a top-level script in the frozen build.

Kept separate from the package so it can be run without a parent-package
context (which would break the relative imports in ``__main__.py``).
"""

import sys

from ytdownloader.main import main

if __name__ == "__main__":
    sys.exit(main())
