import unittest

from agency_guardrails import registry
from agency_guardrails.model import ERROR, Rule, RuleContext


class RegistryValidationTest(unittest.TestCase):
    def test_rejects_bad_id(self):
        class Bad(Rule):
            id = "EU-1"
            title = "x"
            pack = "p"
            rationale = "r"
            citation = "https://example.org"

        with self.assertRaises(ValueError):
            registry.register(Bad)

    def test_rejects_missing_citation(self):
        class NoCite(Rule):
            id = "GR-TST-999"
            title = "x"
            pack = "p"
            rationale = "r"

        with self.assertRaises(ValueError):
            registry.register(NoCite)

    def test_every_registered_rule_is_documented(self):
        for rule in registry.all_rules():
            self.assertTrue(rule.citation.startswith("https://"), rule.id)
            self.assertTrue(rule.rationale, rule.id)
            self.assertTrue(rule.fix, rule.id)


class RuleContextTest(unittest.TestCase):
    def test_option_default_and_override(self):
        class Opt(Rule):
            id = "GR-TST-001"
            title = "t"
            pack = "test"
            severity = ERROR
            rationale = "r"
            citation = "https://example.org"
            options = {"limit": (3, "a limit")}

        class FakeConfig:
            rule_options = {}
            pack_options = {"test": {"limit": 5}}
            root = "."

        rule = Opt()
        self.assertEqual(RuleContext(rule).option("limit"), 3)
        cfg = FakeConfig()
        self.assertEqual(RuleContext(rule, cfg).option("limit"), 5)
        cfg.rule_options = {"GR-TST-001": {"limit": 7}}
        self.assertEqual(RuleContext(rule, cfg).option("limit"), 7)
        with self.assertRaises(KeyError):
            RuleContext(rule).option("nope")


if __name__ == "__main__":
    unittest.main()
