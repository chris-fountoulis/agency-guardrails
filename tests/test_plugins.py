import sys
import unittest
from pathlib import Path

from agency_guardrails import registry
from agency_guardrails.config import ConfigError, from_dict, load
from agency_guardrails.engine import check_paths

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "custom-rule"


class CustomRulePluginTest(unittest.TestCase):
    def tearDown(self):
        registry._RULES.pop("GR-ACME-001", None)
        for name in [n for n in sys.modules if n.startswith("guardrails_plugin_")]:
            del sys.modules[name]

    def test_example_plugin_registers_and_runs(self):
        cfg = load(start=str(EXAMPLE))
        self.assertIn("GR-ACME-001", [r.id for r in cfg.enabled_rules()])
        findings = check_paths([str(EXAMPLE)], cfg).findings
        self.assertEqual([(f.rule_id, f.line) for f in findings], [("GR-ACME-001", 1), ("GR-ACME-001", 3)])

    def test_missing_plugin_is_config_error(self):
        with self.assertRaises(ConfigError):
            from_dict({"guardrails": {"plugins": ["nope.py"]}}, root=EXAMPLE)
        with self.assertRaises(ConfigError):
            from_dict({"guardrails": {"plugins": ["no_such_module_xyz"]}}, root=EXAMPLE)


if __name__ == "__main__":
    unittest.main()
