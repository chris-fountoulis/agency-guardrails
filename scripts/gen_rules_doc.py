#!/usr/bin/env python3
"""Generate docs/rules.md from the rule registry.

    python scripts/gen_rules_doc.py           # rewrite docs/rules.md
    python scripts/gen_rules_doc.py --check   # exit 1 if docs/rules.md is stale (used in CI)
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agency_guardrails.catalog import all_rules_markdown  # noqa: E402

TARGET = ROOT / "docs" / "rules.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/rules.md is out of date")
    args = parser.parse_args()
    fresh = all_rules_markdown()
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if args.check:
        if current != fresh:
            sys.stderr.write("docs/rules.md is out of date: run python scripts/gen_rules_doc.py\n")
            return 1
        print("docs/rules.md is up to date")
        return 0
    TARGET.write_text(fresh, encoding="utf-8")
    print("wrote %s" % TARGET.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
