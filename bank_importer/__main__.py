"""Enable ``python -m bank_importer`` (equivalent to the ``pocketlog-import`` CLI)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
