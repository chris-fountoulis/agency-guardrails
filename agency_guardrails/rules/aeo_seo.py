"""aeo-seo: structure checks for articles that should rank and be quoted by AI answers."""

from __future__ import annotations

import re
from typing import Iterable, Optional, Set

from agency_guardrails.document import Document, normalize, words
from agency_guardrails.model import ERROR, WARN, Finding, Rule, RuleContext
from agency_guardrails.registry import register

PACK = "aeo-seo"
ARTICLE_KINDS = ("markdown", "html")


def _is_article(doc: Document) -> bool:
    return bool(doc.headings) and bool(doc.paragraphs)


@register
class AnswerFirst(Rule):
    id = "GR-SEO-001"
    title = "Answer in the first 50 to 70 words"
    pack = PACK
    severity = WARN
    applies_to = ARTICLE_KINDS
    rationale = (
        "Search features and AI answer engines lift a short, self-contained passage that answers the query. "
        "Articles that open with scene-setting push the answer below the part that gets extracted. The "
        "opening paragraph should be a direct answer that is complete by word 70."
    )
    fix = (
        "Rewrite the first paragraph as a direct, declarative answer of roughly 50 to 70 words, then expand "
        "below it."
    )
    citation = "https://developers.google.com/search/docs/appearance/ai-features"
    options = {
        "answer_min_words": (25, "Opening paragraphs shorter than this are too thin to stand alone."),
        "answer_max_words": (70, "The answer must be complete within this many words."),
        "filler_openers": (
            ["in today's", "in this article", "in this post", "have you ever", "welcome to", "are you looking",
             "when it comes to", "it's no secret", "in the world of", "let's dive", "imagine"],
            "Openings that delay the answer.",
        ),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        if not _is_article(doc):
            return
        first = doc.first_paragraph
        assert first is not None
        text = first.text
        n = len(words(text))
        lowered = text.lower().replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
        for opener in ctx.option("filler_openers"):
            if lowered.startswith(opener.lower()):
                yield self.finding(
                    doc, first.offset, "Opening paragraph starts with filler ('%s'): lead with the answer" % opener
                )
                break
        sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
        if sentence.rstrip().endswith("?"):
            yield self.finding(doc, first.offset, "Opening sentence is a question: answer it instead")
        max_words = int(ctx.option("answer_max_words"))
        min_words = int(ctx.option("answer_min_words"))
        if n > max_words:
            first_sentence_words = len(words(sentence))
            if first_sentence_words > max_words or n > max_words * 2:
                yield self.finding(
                    doc,
                    first.offset,
                    "Opening paragraph is %d words; the answer should be complete by word %d" % (n, max_words),
                )
        elif n < min_words:
            yield self.finding(
                doc, first.offset, "Opening paragraph is only %d words: too thin to stand alone as the answer" % n
            )


def _contains_keyword(text: Optional[str], keyword: str) -> bool:
    if not text:
        return False
    return (" %s " % normalize(keyword)) in (" %s " % normalize(text))


@register
class FocusKeywordPlacement(Rule):
    id = "GR-SEO-002"
    title = "Focus keyword in title, H1, first paragraph and meta description"
    pack = PACK
    severity = WARN
    applies_to = ARTICLE_KINDS
    rationale = (
        "The title link, the main heading, the opening paragraph and the meta description are the places a "
        "search engine and a reader use to decide what a page is about. A declared focus keyword that is "
        "missing from any of them usually means the brief and the copy drifted apart."
    )
    fix = (
        "Use the exact focus keyword in each listed place, or change the declared keyword "
        "(front matter focus_keyword, or <meta name=\"focus-keyword\">)."
    )
    citation = "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"
    options = {
        "require_in": (
            ["title", "h1", "first_paragraph", "meta_description"],
            "Places the keyword must appear: title, h1, first_paragraph, meta_description, h2.",
        ),
        "require_keyword": (False, "Report articles that declare no focus keyword at all."),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        if not _is_article(doc):
            return
        keyword = (doc.focus_keyword or "").strip()
        if not keyword:
            if ctx.option("require_keyword"):
                yield self.finding(doc, 0, "No focus keyword declared")
            return
        first = doc.first_paragraph
        h1 = doc.h1
        places = {
            "title": (doc.title, doc.title_offset, "title"),
            "h1": (h1.text if h1 else None, h1.offset if h1 else 0, "H1"),
            "first_paragraph": (first.text if first else None, first.offset if first else 0, "first paragraph"),
            "meta_description": (doc.meta_description, doc.meta_offset, "meta description"),
        }
        for place in ctx.option("require_in"):
            if place == "h2":
                h2s = [h for h in doc.headings if h.level == 2]
                if not any(_contains_keyword(h.text, keyword) for h in h2s):
                    off = h2s[0].offset if h2s else 0
                    yield self.finding(doc, off, "Focus keyword '%s' is in no H2" % keyword, keyword)
                continue
            if place not in places:
                continue
            value, offset, label = places[place]
            if value is None:
                yield self.finding(doc, offset, "No %s found to carry focus keyword '%s'" % (label, keyword), keyword)
            elif not _contains_keyword(value, keyword):
                yield self.finding(doc, offset, "Focus keyword '%s' is missing from the %s" % (keyword, label), keyword)


_FAQ_HEADING = re.compile(r"\b(?:faqs?|frequently asked questions|questions and answers|q&a)\b", re.I)


def _faq_questions(doc: Document):
    """Return (faq heading, questions) where questions are headings or bold lines ending in '?'."""
    for i, h in enumerate(doc.headings):
        if not _FAQ_HEADING.search(h.text):
            continue
        end = None
        questions = []
        for nxt in doc.headings[i + 1 :]:
            if nxt.level <= h.level:
                end = nxt.offset
                break
            if nxt.text.rstrip().endswith("?"):
                questions.append(nxt)
        for q in doc.questions:
            if q.offset > h.offset and (end is None or q.offset < end) and q.text.rstrip().endswith("?"):
                questions.append(q)
        questions.sort(key=lambda q: q.offset)
        return h, questions
    return None, []


def _jsonld_questions(doc: Document) -> Optional[Set[str]]:
    names: Optional[Set[str]] = None
    for block in doc.jsonld:
        for node in block.items():
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "FAQPage" not in types:
                continue
            names = names or set()
            entities = node.get("mainEntity") or []
            if isinstance(entities, dict):
                entities = [entities]
            for q in entities:
                if isinstance(q, dict) and q.get("name"):
                    names.add(normalize(str(q["name"])))
    return names


@register
class FaqNeedsSchema(Rule):
    id = "GR-SEO-003"
    title = "FAQ section without matching FAQPage JSON-LD"
    pack = PACK
    severity = WARN
    applies_to = ARTICLE_KINDS
    rationale = (
        "An FAQ section is the easiest content for answer engines to quote, and FAQPage structured data "
        "states the question and answer pairs explicitly. The markup must describe questions that are "
        "visible on the page; questions that drift between the two are a structured data quality problem."
    )
    fix = (
        "Add a <script type=\"application/ld+json\"> FAQPage block whose mainEntity names match the visible "
        "FAQ questions one to one."
    )
    citation = "https://developers.google.com/search/docs/appearance/structured-data/faqpage"
    options = {}

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        for block in doc.jsonld:
            if block.error:
                yield self.finding(doc, block.offset, "JSON-LD block is not valid JSON: %s" % block.error)
        heading, questions = _faq_questions(doc)
        schema = _jsonld_questions(doc)
        if heading is None:
            return
        if schema is None:
            yield self.finding(doc, heading.offset, "FAQ section '%s' has no FAQPage JSON-LD" % heading.text)
            return
        visible = set()
        for q in questions:
            key = normalize(q.text)
            visible.add(key)
            if key not in schema:
                yield self.finding(doc, q.offset, "FAQ question missing from FAQPage JSON-LD: '%s'" % q.text, q.text)
        for name in sorted(schema - visible):
            yield self.finding(doc, heading.offset, "FAQPage JSON-LD question not visible on the page: '%s'" % name)


@register
class ImageAltText(Rule):
    id = "GR-SEO-004"
    title = "Image without alt text"
    pack = PACK
    severity = ERROR
    applies_to = ARTICLE_KINDS
    rationale = (
        "WCAG success criterion 1.1.1 requires a text alternative for every non-text content. Alt text is "
        "also what image search and AI models read, so a descriptive alternative helps the image itself rank."
    )
    fix = "Add alt text that describes what the image shows; use alt=\"\" only for purely decorative images."
    citation = "https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html"
    options = {
        "allow_empty_alt": (True, "Accept alt=\"\" on HTML images as an explicit decorative marker."),
        "min_alt_words": (0, "Warn when alt text has fewer words than this (0 disables)."),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        allow_empty = bool(ctx.option("allow_empty_alt"))
        min_words = int(ctx.option("min_alt_words"))
        for img in doc.images:
            src = img.attrs.get("src") or ""
            alt = img.attrs.get("alt")
            is_md = img.attrs.get("_md") == "1"
            if alt is None or (alt.strip() == "" and (is_md or not allow_empty)):
                yield self.finding(doc, img.offset, "Image %s has no alt text" % (src or "(no src)"), src)
            elif min_words and alt.strip() and len(words(alt)) < min_words:
                yield self.finding(
                    doc, img.offset, "Alt text for %s is %d words; describe what it shows" % (src, len(words(alt))),
                    src, severity=WARN,
                )


@register
class TargetBlankNoopener(Rule):
    id = "GR-SEO-005"
    title = "target=_blank link without rel=\"noopener\""
    pack = PACK
    severity = WARN
    applies_to = ARTICLE_KINDS
    rationale = (
        "A page opened with target=_blank can reach back to the opener through window.opener unless the link "
        "carries noopener (or noreferrer). Modern browsers default to noopener, but older ones and some "
        "embedded webviews do not, and many house styles require the attribute on every external link."
    )
    fix = "Add rel=\"noopener\" to every link that opens a new tab."
    citation = "https://html.spec.whatwg.org/multipage/links.html#link-type-noopener"
    options = {}

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        for link in doc.links:
            if (link.attrs.get("target") or "").lower() != "_blank":
                continue
            rel = (link.attrs.get("rel") or "").lower().split()
            if "noopener" in rel or "noreferrer" in rel:
                continue
            href = link.attrs.get("href") or ""
            yield self.finding(doc, link.offset, "Link to %s opens a new tab without rel=\"noopener\"" % href, href)
