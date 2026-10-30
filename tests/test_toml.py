import unittest

from agency_guardrails import _toml

SAMPLE = r'''
# a guardrails config
[guardrails]
packs = ["eu-marketing", "house-style"]  # trailing comment
fail_on = "error"
disable = [
  "GR-SEO-001",
  "GR-SEO-002",
]

[[guardrails.ignore]]
path = "legal/**"
rules = ["GR-STY-*"]

[[guardrails.ignore]]
path = 'drafts/*.md'
rules = ["*"]

[eu-marketing]
vat_rate = 24
ratio = 0.5
big = 1_000
strict = true
loose = false
watch_names = ["Acme Bakery", "Caf\u00e9 \"Nord\""]

[house-style]
banned_chars = ["\u2014", "\u2013"]

[rules.GR-EU-002]
severity = "warn"
point = { x = 1, y = "two" }
"quoted key" = 3
a.b = 4
'''


class FallbackParserTest(unittest.TestCase):
    def test_sample(self):
        data = _toml.parse(SAMPLE)
        g = data["guardrails"]
        self.assertEqual(g["packs"], ["eu-marketing", "house-style"])
        self.assertEqual(g["disable"], ["GR-SEO-001", "GR-SEO-002"])
        self.assertEqual(len(g["ignore"]), 2)
        self.assertEqual(g["ignore"][1]["path"], "drafts/*.md")
        eu = data["eu-marketing"]
        self.assertEqual(eu["vat_rate"], 24)
        self.assertEqual(eu["ratio"], 0.5)
        self.assertEqual(eu["big"], 1000)
        self.assertIs(eu["strict"], True)
        self.assertIs(eu["loose"], False)
        self.assertEqual(eu["watch_names"][1], "Caf\u00e9 \"Nord\"")
        self.assertEqual(data["house-style"]["banned_chars"], [chr(0x2014), chr(0x2013)])
        r = data["rules"]["GR-EU-002"]
        self.assertEqual(r["point"], {"x": 1, "y": "two"})
        self.assertEqual(r["quoted key"], 3)
        self.assertEqual(r["a"], {"b": 4})

    def test_matches_stdlib_when_available(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")
        self.assertEqual(_toml.parse(SAMPLE), tomllib.loads(SAMPLE))

    def test_errors_are_clear(self):
        for bad in ('a = "open', "a = 1\na = 2", "[t]\n[t]", 'a = """x"""', "a = @", "a = 1 b"):
            with self.assertRaises(_toml.TOMLError, msg=bad):
                _toml.parse(bad)

    def test_loads_uses_some_backend(self):
        self.assertEqual(_toml.loads('x = "y"'), {"x": "y"})
        name, _ = _toml.backend()
        self.assertTrue(name)


if __name__ == "__main__":
    unittest.main()
