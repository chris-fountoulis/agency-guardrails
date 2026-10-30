"""house-style: the characters and words your brand never ships."""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Tuple

from agency_guardrails.document import Document
from agency_guardrails.model import ERROR, WARN, Finding, Rule, RuleContext
from agency_guardrails.registry import register

PACK = "house-style"
EM_DASH = "\N{EM DASH}"
EN_DASH = "\N{EN DASH}"


def char_label(ch: str) -> str:
    try:
        name = unicodedata.name(ch).lower()
    except ValueError:
        name = "character"
    return "U+%04X (%s)" % (ord(ch), name)


@register
class BannedCharacters(Rule):
    id = "GR-STY-001"
    title = "Banned character"
    pack = PACK
    severity = ERROR
    rationale = (
        "Some characters are a tell. Language models reach for the em dash far more often than most human "
        "writers, so a house rule against it keeps AI-drafted copy from reading as machine-written. The list "
        "is configurable for any character your style guide bans."
    )
    fix = "Use a comma, a period, a colon or a plain hyphen instead."
    citation = "https://www.unicode.org/charts/PDF/U2000.pdf"
    options = {
        "banned_chars": ([EM_DASH, EN_DASH], "Characters that must not appear in prose."),
        "exempt_quotes": (True, "Skip text inside quotation marks, <q> and <blockquote>: never edit a quote."),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        banned = [c for c in ctx.option("banned_chars") if c]
        if not banned:
            return
        exempt = bool(ctx.option("exempt_quotes"))
        rx = re.compile("|".join(re.escape(c) for c in sorted(banned, key=len, reverse=True)))
        for m in rx.finditer(doc.text):
            if exempt and doc.in_quote(m.start()):
                continue
            label = char_label(m.group(0)) if len(m.group(0)) == 1 else repr(m.group(0))
            raw = doc.raw[m.start() : m.start() + 8]
            shown = raw.split(";", 1)[0] + ";" if raw.startswith("&") else ""
            message = "Banned character %s%s" % (label, " written as %s" % shown if shown else "")
            yield self.finding(doc, m.start(), message, shown or label)


def parse_banned_words(entries: Iterable[str]) -> List[Tuple[str, str]]:
    """Entries are 'phrase' or 'phrase => suggestion'."""
    out = []
    for entry in entries:
        phrase, _, suggestion = str(entry).partition("=>")
        phrase = phrase.strip()
        if phrase:
            out.append((phrase, suggestion.strip()))
    return out


@register
class BannedWords(Rule):
    id = "GR-STY-002"
    title = "Banned word or phrase"
    pack = PACK
    severity = WARN
    rationale = (
        "Every brand has words it does not use: inflated claims, jargon, competitor names or phrases that "
        "mark copy as generic. Listing them once in config stops every agent from reintroducing them."
    )
    fix = "Replace the phrase with the suggested wording, or rewrite the sentence in plain words."
    citation = "https://developers.google.com/style/word-list"
    options = {
        "banned_words": ([], "Phrases to flag, optionally 'phrase => suggestion'. Case-insensitive, whole words."),
        "exempt_quotes": (True, "Skip text inside quotation marks, <q> and <blockquote>."),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        exempt = bool(ctx.option("exempt_quotes"))
        for phrase, suggestion in parse_banned_words(ctx.option("banned_words")):
            body = r"\s+".join(re.escape(w) for w in phrase.split())
            rx = re.compile(r"(?<![\w-])%s(?![\w-])" % body, re.I)
            for m in rx.finditer(doc.text):
                if exempt and doc.in_quote(m.start()):
                    continue
                found = re.sub(r"\s+", " ", m.group(0))
                msg = "Banned phrase '%s'" % found
                if suggestion:
                    msg += ": use '%s'" % suggestion
                yield self.finding(doc, m.start(), msg, found)
