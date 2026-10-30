"""Allow ``python -m agency_guardrails``."""

import sys

from agency_guardrails.cli import main

if __name__ == "__main__":
    sys.exit(main())
