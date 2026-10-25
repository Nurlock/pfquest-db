"""pfQuest DB: SQLite database management and bidirectional pfQuest / Questie converter."""

import sys
from .cli import main

__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
