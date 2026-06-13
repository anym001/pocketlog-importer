"""Enable ``python -m pocketlog_importer`` (same as the ``pocketlog-import`` CLI)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
