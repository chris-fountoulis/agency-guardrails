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
            self.assertIn("site/bad.md\n  3:6      error  GR-STY-001", out)
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


class StdinCheckTest(unittest.TestCase):
    def test_check_stdin_with_filename(self):
        import sys

        old = sys.stdin
        sys.stdin = io.StringIO("<p>Only &euro;9 a month.</p>")
        try:
            with temp_tree({"guardrails.toml": CONFIG}):
                code, out, _ = run("check", "--no-color", "--stdin-filename", "offer.html", "-")
        finally:
            sys.stdin = old
        self.assertEqual(code, 1)
        self.assertIn("offer.html\n  1:9      error  GR-EU-002", out)


class RulesCommandTest(unittest.TestCase):
    def test_list(self):
        code, out, _ = run("rules")
        self.assertEqual(code, 0)
        self.assertIn("eu-marketing:", out)
        self.assertIn("GR-EU-001", out)
        self.assertIn("https://eur-lex.europa.eu/eli/dir/2005/29/oj", out)

    def test_json_and_markdown(self):
        _, out, _ = run("rules", "--format", "json", "--pack", "secrets")
        self.assertEqual({r["pack"] for r in json.loads(out)}, {"secrets"})
        _, out, _ = run("rules", "--format", "markdown")
        self.assertTrue(out.startswith("# Rule reference"))

    def test_explain(self):
        code, out, _ = run("explain", "gr-eu-002")
        self.assertEqual(code, 0)
        self.assertIn("GR-EU-002  Price without a VAT-inclusive figure", out)
        self.assertIn("vat_rate = 24", out)
        self.assertIn("https://eur-lex.europa.eu/eli/dir/1998/6/oj", out)
        code, _, err = run("explain", "GR-NOPE-001")
        self.assertEqual(code, 2)


class InitCommandTest(unittest.TestCase):
    def test_writes_loadable_config(self):
        from agency_guardrails.config import load

        with temp_tree({}) as root:
            code, out, _ = run("init")
            self.assertEqual(code, 0)
            self.assertIn("wrote ./guardrails.toml", out)
            cfg = load(start=str(root))
            self.assertEqual(cfg.pack_options["house-style"]["banned_chars"], [EM, "\N{EN DASH}"])
            self.assertEqual(cfg.hooks["pre_write_packs"], ["secrets"])
            self.assertTrue((root / "consent" / "approved.txt").is_file())
            self.assertEqual(run("init")[0], 2)
            self.assertEqual(run("init", "--force")[0], 0)
            code, out, _ = run("check", "consent", "guardrails.toml")
            self.assertEqual(code, 0, out)

    def test_starter_has_no_banned_characters(self):
        from agency_guardrails.starter import STARTER_CONFIG

        self.assertNotIn(EM, STARTER_CONFIG)
        self.assertTrue(all(ord(c) < 128 for c in STARTER_CONFIG))


class RedactCommandTest(unittest.TestCase):
    def run_stdin(self, text, *argv):
        import sys

        old = sys.stdin
        sys.stdin = io.StringIO(text)
        try:
            return run("redact", *argv)
        finally:
            sys.stdin = old

    def test_redacts(self):
        from tests import fakes

        text = "token %s and words\n" % fakes.github()
        code, out, err = self.run_stdin(text, "--report")
        self.assertEqual((code, out), (0, "token [REDACTED:github-token] and words\n"))
        self.assertEqual(err, "redacted 1 github-token\n")
        self.assertEqual(self.run_stdin(text, "--check")[0], 1)
        self.assertEqual(self.run_stdin("nothing here\n", "--check"), (0, "nothing here\n", ""))


if __name__ == "__main__":
    unittest.main()
