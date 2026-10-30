import contextlib
import io
import json
import unittest

from agency_guardrails import cli

from tests.helpers import temp_tree

EM = "\N{EM DASH}"
CONFIG = """
[guardrails]
packs = ["house-style", "eu-marketing"]

[eu-marketing]
vat_rate = 24
"""


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CheckCommandTest(unittest.TestCase):
    FILES = {
        "guardrails.toml": CONFIG,
        "site/bad.md": "# Offer\n\nFast %s and cheap: 15 euro.\n" % EM,
        "site/good.md": "# Offer\n\nFast and cheap: 15 euro (18.60 euro incl. VAT).\n",
    }

    def test_text_and_exit_codes(self):
        with temp_tree(self.FILES):
            code, out, _ = run("check", "--no-color")
            self.assertEqual(code, 1)
            self.assertIn("site/bad.md\n  3:6  error  GR-STY-001", out)
            self.assertIn("GR-EU-002", out)
            self.assertTrue(out.endswith("3 files checked, 2 errors, 0 warnings\n"), out)
            code, out, _ = run("check", "site/good.md")
            self.assertEqual((code, out), (0, "1 file checked, 0 errors, 0 warnings\n"))

    def test_json_sarif_and_fail_on(self):
        with temp_tree(self.FILES) as root:
            code, out, _ = run("check", "-f", "json", "--sarif-file", "report.sarif", "site")
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["summary"]["errors"], 2)
            sarif = json.loads((root / "report.sarif").read_text())
            self.assertEqual(len(sarif["runs"][0]["results"]), 2)
            code, _, _ = run("check", "--fail-on", "never", "site")
            self.assertEqual(code, 0)
            code, out, _ = run("check", "-f", "sarif", "-o", "out.sarif", "site")
            self.assertEqual((code, out), (1, ""))
            self.assertIn('"version": "2.1.0"', (root / "out.sarif").read_text())

    def test_pack_filter(self):
        with temp_tree(self.FILES):
            code, out, _ = run("check", "--pack", "eu-marketing", "--no-color", "site/bad.md")
            self.assertNotIn("GR-STY-001", out)
            self.assertIn("GR-EU-002", out)
            code, _, err = run("check", "--pack", "nope")
            self.assertEqual(code, 2)
            self.assertIn("unknown pack", err)

    def test_usage_errors(self):
        with temp_tree({"guardrails.toml": "[guardrails]\nbogus = 1\n"}):
            code, _, err = run("check")
            self.assertEqual(code, 2)
            self.assertIn("config error", err)
        with temp_tree({}):
            code, _, err = run("check", "missing.md")
            self.assertEqual(code, 2)
        self.assertEqual(run()[0], 2)


if __name__ == "__main__":
    unittest.main()
