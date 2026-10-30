import unittest

from tests.helpers import run_rule

EM = "\N{EM DASH}"
EN = "\N{EN DASH}"


class BannedCharactersTest(unittest.TestCase):
    RULE = "GR-STY-001"

    def test_flags_dashes(self):
        text = "Fast sites win %s every time.\nPages 1%s3.\n" % (EM, EN)
        found = run_rule(self.RULE, text)
        self.assertEqual([(f.line, f.column) for f in found], [(1, 16), (2, 8)])
        self.assertIn("U+2014 (em dash)", found[0].message)

    def test_entities_in_html(self):
        found = run_rule(self.RULE, "<p>Fast &mdash; and &#8211; done.</p>", path="a.html")
        self.assertEqual([f.match for f in found], ["&mdash;", "&#8211;"])

    def test_quotes_are_exempt(self):
        text = 'She said "fast %s always" and <q>yes %s no</q>.\n> a quote %s here\n' % (EM, EM, EM)
        self.assertEqual(run_rule(self.RULE, text), [])
        self.assertEqual(len(run_rule(self.RULE, text, options={"exempt_quotes": False})), 3)

    def test_code_and_markup_are_skipped(self):
        text = "```\nx = '%s'\n```\n\n`%s`\n" % (EM, EM)
        self.assertEqual(run_rule(self.RULE, text), [])
        html = '<p title="a %s b">ok</p><script>var a = "%s";</script>' % (EM, EM)
        self.assertEqual(run_rule(self.RULE, html, path="a.html"), [])

    def test_configurable_list(self):
        self.assertEqual(run_rule(self.RULE, "Hey!!\n", options={"banned_chars": []}), [])
        found = run_rule(self.RULE, "Price \N{TRADE MARK SIGN}\n", options={"banned_chars": ["\N{TRADE MARK SIGN}"]})
        self.assertEqual(len(found), 1)


class BannedWordsTest(unittest.TestCase):
    RULE = "GR-STY-002"
    OPTS = {"banned_words": ["utilize => use", "game changer", "synergy"]}

    def test_flags_with_suggestion(self):
        text = "We utilize AI.\nA real Game  Changer.\n"
        found = run_rule(self.RULE, text, options=self.OPTS)
        self.assertEqual([f.message for f in found], ["Banned phrase 'utilize': use 'use'", "Banned phrase 'Game Changer'"])

    def test_whole_words_only_and_quotes(self):
        text = 'Synergystic is not a word. "Synergy" in a quote.\n'
        self.assertEqual(run_rule(self.RULE, text, options=self.OPTS), [])

    def test_empty_by_default(self):
        self.assertEqual(run_rule(self.RULE, "We utilize synergy.\n"), [])


if __name__ == "__main__":
    unittest.main()
