import json
import os
import tempfile
import unittest
from pathlib import Path

from agency_guardrails import config


class MatchPathTest(unittest.TestCase):
    def test_globs(self):
        self.assertTrue(config.match_path("a.md", "**/*.md"))
        self.assertTrue(config.match_path("docs/a.md", "**/*.md"))
        self.assertTrue(config.match_path("./docs/a.md", "docs/**"))
        self.assertTrue(config.match_path("docs", "docs/**"))
        self.assertFalse(config.match_path("docs/a.md", "*.html"))

    def test_rule_globs(self):
        self.assertTrue(config.match_rule("GR-STY-001", ["GR-STY-*"]))
        self.assertTrue(config.match_rule("GR-STY-001", ["all"]))
        self.assertTrue(config.match_rule("GR-STY-001", ["gr-sty-001"]))
        self.assertFalse(config.match_rule("GR-EU-001", ["GR-STY-*"]))


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_config_uses_defaults(self):
        cfg = config.load(start=str(self.root))
        self.assertIsNone(cfg.source)
        self.assertIsNone(cfg.packs)
        self.assertEqual(cfg.fail_on, "error")

    def test_discovery_walks_up(self):
        (self.root / "guardrails.toml").write_text('[guardrails]\nfail_on = "warn"\n')
        sub = self.root / "a" / "b"
        sub.mkdir(parents=True)
        cfg = config.load(start=str(sub))
        self.assertEqual(cfg.fail_on, "warn")
        self.assertEqual(cfg.root, self.root.resolve())

    def test_json_config(self):
        p = self.root / "guardrails.json"
        p.write_text(json.dumps({"guardrails": {"exclude": ["drafts/**"]}}))
        cfg = config.load(str(p))
        self.assertEqual(cfg.exclude, ["drafts/**"])

    def test_ignores_and_relpath(self):
        data = {"guardrails": {"ignore": [{"path": "legal/**", "rules": ["GR-STY-*"]}]}}
        cfg = config.from_dict(data, root=self.root)
        self.assertTrue(cfg.is_ignored("legal/terms.md", "GR-STY-001"))
        self.assertFalse(cfg.is_ignored("blog/post.md", "GR-STY-001"))
        self.assertEqual(cfg.relpath(os.path.join(str(self.root), "x", "y.md")), "x/y.md")

    def test_errors(self):
        bad = [
            {"guardrails": {"nope": 1}},
            {"guardrails": {"packs": ["not-a-pack"]}},
            {"guardrails": {"fail_on": "sometimes"}},
            {"guardrails": {"ignore": [{"rules": ["*"]}]}},
            {"rules": {"GR-ZZ-999": {}}},
            {"hooks": {"bogus": True}},
            {"mystery": {}},
        ]
        for data in bad:
            with self.assertRaises(config.ConfigError, msg=repr(data)):
                config.from_dict(data, root=self.root)

    def test_bad_toml_is_config_error(self):
        p = self.root / "guardrails.toml"
        p.write_text("[guardrails\n")
        with self.assertRaises(config.ConfigError):
            config.load(str(p))


if __name__ == "__main__":
    unittest.main()
