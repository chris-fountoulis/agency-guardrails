"""The sample site is part of the contract: bad has findings from every content pack, fixed is clean."""

import unittest
from pathlib import Path

from agency_guardrails.config import load
from agency_guardrails.engine import check_paths

SITE = Path(__file__).resolve().parent.parent / "examples" / "site"


class ExamplesTest(unittest.TestCase):
    def test_bad_triggers_every_content_rule(self):
        cfg = load(start=str(SITE / "bad"))
        rules = {f.rule_id for f in check_paths([str(SITE / "bad")], cfg).findings}
        expected = {
            "GR-EU-001", "GR-EU-002", "GR-EU-003", "GR-EU-004",
            "GR-SEO-001", "GR-SEO-002", "GR-SEO-003", "GR-SEO-004", "GR-SEO-005",
            "GR-STY-001", "GR-STY-002",
        }
        self.assertEqual(rules, expected)

    def test_fixed_is_clean(self):
        cfg = load(start=str(SITE / "fixed"))
        result = check_paths([str(SITE / "fixed")], cfg)
        self.assertEqual(result.findings, [], [f.message for f in result.findings])
        self.assertEqual(result.files_checked, 2)


if __name__ == "__main__":
    unittest.main()
