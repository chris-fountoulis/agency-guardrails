import json
import unittest

from tests.helpers import run_rule

ANSWER = (
    "A bakery website should load in under two seconds on a mid-range phone, because most visitors decide "
    "within that window whether to stay. Compress photos, serve them in modern formats, cache pages and "
    "keep third-party scripts to a minimum so the menu and opening hours appear first."
)


def md(first=ANSWER, extra="", front=None):
    front = front or {
        "title": "Bakery website speed: how fast is fast enough",
        "description": "How fast should a bakery website load? Bakery website speed targets and fixes.",
        "focus_keyword": "bakery website speed",
    }
    fm = "".join("%s: %s\n" % kv for kv in front.items())
    return "---\n%s---\n\n# Bakery website speed in 2026\n\n%s\n\n## Why bakery website speed matters\n\nMore.\n%s" % (
        fm,
        first.replace("A bakery website", "Bakery website speed matters: a bakery website", 1),
        extra,
    )


class AnswerFirstTest(unittest.TestCase):
    RULE = "GR-SEO-001"

    def test_good_opening_passes(self):
        self.assertEqual(run_rule(self.RULE, md()), [])

    def test_filler_and_question(self):
        text = md(first="Have you ever wondered how fast your bakery website should be? It depends on many things.")
        messages = [f.message for f in run_rule(self.RULE, text)]
        self.assertTrue(any("filler" in m for m in messages), messages)
        self.assertTrue(any("question" in m for m in messages), messages)

    def test_long_rambling_opening(self):
        long_sentence = " ".join(["word"] * 80) + "."
        found = run_rule(self.RULE, md(first=long_sentence))
        self.assertIn("80 words", found[0].message)

    def test_thin_opening(self):
        found = run_rule(self.RULE, md(first="It depends."))
        self.assertIn("too thin", found[0].message)

    def test_non_article_is_skipped(self):
        self.assertEqual(run_rule(self.RULE, "Just a note without headings.\n"), [])


class FocusKeywordTest(unittest.TestCase):
    RULE = "GR-SEO-002"

    def test_all_places_pass(self):
        self.assertEqual(run_rule(self.RULE, md()), [])

    def test_missing_places(self):
        text = md(front={"title": "Fast sites", "focus_keyword": "bakery website speed"})
        text = text.replace("Bakery website speed matters: ", "")
        found = run_rule(self.RULE, text)
        messages = sorted(f.message for f in found)
        self.assertEqual(len(found), 3, messages)
        self.assertTrue(any("missing from the title" in m for m in messages))
        self.assertTrue(any("missing from the first paragraph" in m for m in messages))
        self.assertTrue(any("No meta description" in m for m in messages))

    def test_h2_optional_requirement(self):
        text = md().replace("## Why bakery website speed matters", "## Why it matters")
        self.assertEqual(run_rule(self.RULE, text), [])
        found = run_rule(self.RULE, text, options={"require_in": ["h2"]})
        self.assertEqual(len(found), 1)

    def test_html_meta_keyword(self):
        html = (
            "<html><head><title>Roof repair costs</title>"
            '<meta name="description" content="Roof repair costs explained.">'
            '<meta name="focus-keyword" content="roof repair costs"></head>'
            "<body><h1>Roof Repair Costs</h1><p>Roof repair costs depend on the damage.</p></body></html>"
        )
        self.assertEqual(run_rule(self.RULE, html, path="a.html"), [])
        found = run_rule(self.RULE, html.replace("<h1>Roof Repair Costs", "<h1>Roofs"), path="a.html")
        self.assertEqual(len(found), 1)
        self.assertIn("H1", found[0].message)

    def test_require_keyword(self):
        text = md(front={"title": "x"})
        self.assertEqual(run_rule(self.RULE, text), [])
        self.assertEqual(len(run_rule(self.RULE, text, options={"require_keyword": True})), 1)


def faq_jsonld(*questions):
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": "Yes."}} for q in questions
        ],
    }
    return '<script type="application/ld+json">%s</script>' % json.dumps(data)


class FaqSchemaTest(unittest.TestCase):
    RULE = "GR-SEO-003"
    FAQ = "\n## FAQ\n\n### Is two seconds fast enough?\n\nYes.\n\n**Do photos matter?**\n\nYes.\n"

    def test_missing_schema(self):
        found = run_rule(self.RULE, md(extra=self.FAQ))
        self.assertEqual(len(found), 1)
        self.assertIn("no FAQPage JSON-LD", found[0].message)

    def test_matching_schema_passes(self):
        extra = self.FAQ + "\n" + faq_jsonld("Is two seconds fast enough?", "Do photos matter?") + "\n"
        self.assertEqual(run_rule(self.RULE, md(extra=extra)), [])

    def test_mismatched_schema(self):
        extra = self.FAQ + "\n" + faq_jsonld("Is two seconds fast enough?", "Do fonts matter?") + "\n"
        messages = sorted(f.message for f in run_rule(self.RULE, md(extra=extra)))
        self.assertEqual(len(messages), 2, messages)
        self.assertIn("missing from FAQPage JSON-LD: 'Do photos matter?'", messages[0])
        self.assertIn("not visible on the page: 'do fonts matter'", messages[1])

    def test_invalid_json(self):
        extra = '\n<script type="application/ld+json">{"@type": FAQPage}</script>\n'
        found = run_rule(self.RULE, md(extra=extra))
        self.assertIn("not valid JSON", found[0].message)

    def test_no_faq_no_finding(self):
        self.assertEqual(run_rule(self.RULE, md()), [])

    def test_html_graph(self):
        html = (
            "<h1>Guide</h1><p>Answer.</p><h2>Frequently asked questions</h2><h3>Why?</h3><p>Because.</p>"
            '<script type="application/ld+json">{"@graph": [{"@type": ["FAQPage"], "mainEntity": '
            '{"@type": "Question", "name": "Why?"}}]}</script>'
        )
        self.assertEqual(run_rule(self.RULE, html, path="a.html"), [])


class AltTextTest(unittest.TestCase):
    RULE = "GR-SEO-004"

    def test_html(self):
        html = '<h1>T</h1><p>x</p><img src="a.png"><img src="b.png" alt=""><img src="c.png" alt="Chart of load times">'
        found = run_rule(self.RULE, html, path="a.html")
        self.assertEqual([f.match for f in found], ["a.png"])
        found = run_rule(self.RULE, html, path="a.html", options={"allow_empty_alt": False})
        self.assertEqual([f.match for f in found], ["a.png", "b.png"])

    def test_markdown(self):
        text = "# T\n\nx\n\n![](a.png)\n\n![Chart of load times by device](b.png)\n"
        found = run_rule(self.RULE, text)
        self.assertEqual([(f.line, f.match) for f in found], [(5, "a.png")])

    def test_short_alt_warning(self):
        text = "# T\n\nx\n\n![Chart](b.png)\n"
        found = run_rule(self.RULE, text, options={"min_alt_words": 3})
        self.assertEqual([f.severity for f in found], ["warn"])


class NoopenerTest(unittest.TestCase):
    RULE = "GR-SEO-005"

    def test_links(self):
        html = (
            '<h1>T</h1><p><a href="https://a.example" target="_blank">a</a> '
            '<a href="https://b.example" target="_blank" rel="noopener">b</a> '
            '<a href="https://c.example" target="_blank" rel="nofollow noreferrer">c</a> '
            '<a href="/d">d</a></p>'
        )
        found = run_rule(self.RULE, html, path="a.html")
        self.assertEqual([f.match for f in found], ["https://a.example"])

    def test_markdown_raw_html(self):
        text = '# T\n\nSee <a href="https://a.example" target="_blank">this</a>.\n'
        self.assertEqual(len(run_rule(self.RULE, text)), 1)


if __name__ == "__main__":
    unittest.main()
