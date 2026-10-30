import unittest

from agency_guardrails.document import Document, normalize, words

EM = "\N{EM DASH}"

HTML = """<!DOCTYPE html>
<html><head>
<title>Bakery Website Speed Guide</title>
<meta name="description" content="How fast should a bakery website load?">
<meta name="focus-keyword" content="bakery website speed">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"FAQPage","mainEntity":[]}]}</script>
<style>p { color: red }</style>
</head><body>
<h1>Bakery website speed</h1>
<p>A bakery website should load in under <b>two seconds</b>.</p>
<p>Price: &euro;15&nbsp;a month &mdash; see <a href="https://example.org/x" target="_blank">docs</a>.</p>
<blockquote>Quoted words</blockquote>
<img src="/a.png">
<!-- a comment with words -->
</body></html>
"""

MD = """---
title: "Bakery website speed"
description: A short guide.
focus_keyword: bakery website speed
---

# Bakery website speed

A bakery website should load in under **two seconds**, see [the guide](https://example.org/guide).
It is a [linked](#x) second line.

```python
price = "\N{EURO SIGN}15"
```

> a quoted line

## FAQ

**How fast is fast?**

![](/img.png)
![Alt text](/b.png "title")
"""


class HtmlDocumentTest(unittest.TestCase):
    def setUp(self):
        self.doc = Document("page.html", HTML)

    def test_kind_and_structure(self):
        d = self.doc
        self.assertEqual(d.kind, "html")
        self.assertEqual(d.title, "Bakery Website Speed Guide")
        self.assertEqual(d.meta_description, "How fast should a bakery website load?")
        self.assertEqual(d.focus_keyword, "bakery website speed")
        self.assertEqual(d.h1.text, "Bakery website speed")
        self.assertEqual(d.first_paragraph.text, "A bakery website should load in under two seconds.")
        self.assertEqual(len(d.images), 1)
        self.assertEqual(d.links[0].attrs["target"], "_blank")
        self.assertEqual(d.jsonld[0].items()[1]["@type"], "FAQPage")

    def test_prose_view_keeps_offsets(self):
        d = self.doc
        self.assertEqual(len(d.text), len(d.raw))
        self.assertNotIn("color: red", d.text)
        self.assertNotIn("a comment", d.text)
        self.assertNotIn("example.org", d.text)
        self.assertRegex(d.text, "\N{EURO SIGN}\\s+15")
        idx = d.text.index(EM)
        line, col = d.position(idx)
        self.assertIn("&mdash;", d.line(line))
        self.assertEqual(d.raw[idx:idx + 7], "&mdash;")

    def test_quotes(self):
        d = self.doc
        self.assertTrue(d.in_quote(d.raw.index("Quoted words")))
        self.assertFalse(d.in_quote(d.raw.index("two seconds")))

    def test_passage_stops_at_blocks(self):
        d = self.doc
        a, b = d.passage(d.raw.index("&euro;"))
        self.assertNotIn("two seconds", d.text[a:b])


class MarkdownDocumentTest(unittest.TestCase):
    def setUp(self):
        self.doc = Document("post.md", MD)

    def test_front_matter(self):
        d = self.doc
        self.assertEqual(d.kind, "markdown")
        self.assertEqual(d.title, "Bakery website speed")
        self.assertEqual(d.meta_description, "A short guide.")
        self.assertEqual(d.focus_keyword, "bakery website speed")
        self.assertIn("Bakery website speed", d.text[: d.raw.index("description")])
        self.assertNotIn("focus_keyword", d.text)

    def test_structure(self):
        d = self.doc
        self.assertEqual([h.level for h in d.headings], [1, 2])
        self.assertEqual(
            d.first_paragraph.text,
            "A bakery website should load in under two seconds, see the guide. It is a linked second line.",
        )
        self.assertEqual(len(d.paragraphs), 1)
        self.assertEqual(d.questions[0].text, "How fast is fast?")
        self.assertEqual([i.attrs["alt"] for i in d.images], ["", "Alt text"])

    def test_code_and_urls_masked(self):
        d = self.doc
        self.assertEqual(len(d.text), len(d.raw))
        self.assertNotIn("\N{EURO SIGN}15", d.text)
        self.assertNotIn("example.org", d.text)
        self.assertTrue(d.in_quote(d.raw.index("a quoted line")))
        line, _ = d.position(d.raw.index("## FAQ"))
        self.assertEqual(d.line(line), "## FAQ")


class HelpersTest(unittest.TestCase):
    def test_words_and_normalize(self):
        self.assertEqual(words("It's a well-known fact, 24 times."), ["It's", "a", "well-known", "fact", "24", "times"])
        self.assertEqual(normalize("Bakery\N{EN DASH}Website  Speed!"), "bakery website speed")

    def test_other_kind(self):
        d = Document("app.py", "x = 1\n")
        self.assertEqual(d.kind, "other")
        self.assertEqual(d.position(4), (1, 5))


if __name__ == "__main__":
    unittest.main()
