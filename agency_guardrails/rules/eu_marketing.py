"""eu-marketing: consumer-protection rules for EU-facing marketing copy.

These rules encode engineering heuristics, not legal conclusions. They catch
the patterns that most often slip into AI-written copy and make a human look
before it ships.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from agency_guardrails.document import Document
from agency_guardrails.model import ERROR, WARN, Finding, Rule, RuleContext
from agency_guardrails.registry import register

PACK = "eu-marketing"
UCPD = "https://eur-lex.europa.eu/eli/dir/2005/29/oj"
PID = "https://eur-lex.europa.eu/eli/dir/1998/6/oj"

_GREEK_VAT = "\N{GREEK SMALL LETTER PHI}\N{GREEK SMALL LETTER PI}\N{GREEK SMALL LETTER ALPHA}"


def _phrase_regex(phrases: Iterable[str]) -> Optional[re.Pattern]:
    items = sorted({p.strip().lower() for p in phrases if p.strip()}, key=len, reverse=True)
    if not items:
        return None
    body = "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in items)
    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % body, re.I)


def _contains(text: str, phrases: Iterable[str]) -> Optional[str]:
    rx = _phrase_regex(phrases)
    if rx is None:
        return None
    m = rx.search(text)
    return m.group(0) if m else None


# prices --------------------------------------------------------------------

_NUM = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"


def price_regex(currencies: Iterable[str]) -> re.Pattern:
    syms = sorted({c for c in currencies if c}, key=len, reverse=True)
    sym = "|".join(re.escape(s) for s in syms)
    pattern = r"(?<![\w.,])(?P<pre>%s)\s{0,8}(?P<a>%s)(?![\d])|(?<![\w.,])(?P<b>%s)\s{0,8}(?P<post>%s)(?!\w)" % (
        sym,
        _NUM,
        _NUM,
        sym,
    )
    return re.compile(pattern, re.I)


def parse_amount(text: str) -> float:
    """Parse 15, 15.50, 15,50, 1.200,50 or 1,200.50 into a float."""
    s = text.strip()
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        return float(s.replace(thou, "").replace(dec, "."))
    for sep in (",", "."):
        if sep in s:
            head, _, tail = s.rpartition(sep)
            if len(tail) == 3:  # 1,200 or 1.200: a thousands separator
                return float(s.replace(sep, ""))
            return float(head.replace(sep, "") + "." + tail)
    return float(s)


def format_amount(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return "%d" % round(value)
    return "%.2f" % value


def normalise_rate(rate: float) -> float:
    rate = float(rate)
    return rate / 100.0 if rate >= 1 else rate


def find_prices(text: str, currencies: Iterable[str]) -> List[Tuple[int, int, str, float]]:
    """Return (start, end, symbol, amount) for every price in the prose view."""
    out = []
    for m in price_regex(currencies).finditer(text):
        num = m.group("a") or m.group("b")
        symbol = m.group("pre") or m.group("post")
        try:
            out.append((m.start(), m.end(), symbol, parse_amount(num)))
        except ValueError:
            continue
    return out


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


@register
class ConditionalFreeClaim(Rule):
    id = "GR-EU-001"
    title = "Conditional 'free' claim"
    pack = PACK
    severity = ERROR
    rationale = (
        "Under Annex I point 20 of the Unfair Commercial Practices Directive, describing a product as "
        "'free', 'gratis' or 'without charge' when the customer has to pay anything beyond the unavoidable "
        "cost of responding is one of the practices that are unfair in all circumstances: no case-by-case "
        "test applies. AI-written offers like a no-cost website paid back through a hosting plan are the classic trap."
    )
    fix = (
        "Describe what is actually covered ('we cover 100% of the design and development cost') and state "
        "the recurring price in the same sentence with equal prominence."
    )
    citation = UCPD
    options = {
        "condition_markers": (
            [
                "per month", "/month", "/mo", "a month", "monthly", "per year", "/year", "/yr", "a year",
                "yearly", "annually", "subscription", "subscribe", "plan", "hosting", "retainer", "contract",
                "minimum term", "commitment", "when you", "if you", "as long as", "provided that",
                "in exchange", "you pay", "only pay", "fee", "fees", "billed", "renewal", "renews",
            ],
            "Words that turn 'free' into a conditional offer when they appear in the same passage.",
        ),
        "allowed_phrases": (
            ["feel free", "free software", "free and open source", "free/libre", "free speech", "free will",
             "free time", "toll free", "duty free"],
            "Phrases where 'free' is not a price claim.",
        ),
        "currencies": (["\N{EURO SIGN}", "EUR", "euro", "euros"], "A price in the passage also counts as a condition."),
        "window": (240, "How many characters around 'free' to search, within the same paragraph."),
        "flag_unconditional": (False, "Also warn on 'free' with no condition nearby."),
    }

    _FREE = re.compile(r"(?<![\w-])(?:free of charge|at no cost|no charge|gratis|free)(?![\w-])", re.I)

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        allowed = _phrase_regex(ctx.option("allowed_phrases"))
        markers = _phrase_regex(ctx.option("condition_markers"))
        currencies = ctx.option("currencies")
        window = int(ctx.option("window"))
        text = doc.text
        for m in self._FREE.finditer(text):
            if allowed is not None and any(
                a.start() <= m.start() < a.end() for a in allowed.finditer(text, max(0, m.start() - 40), m.end() + 40)
            ):
                continue
            a, b = doc.passage(m.start(), window)
            passage = text[a:b]
            hit = markers.search(passage) if markers is not None else None
            reason = hit.group(0) if hit else None
            if reason is None:
                prices = find_prices(passage, currencies)
                if prices:
                    reason = passage[prices[0][0] : prices[0][1]].strip()
            if reason:
                yield self.finding(
                    doc,
                    m.start(),
                    "'%s' appears next to a payment or condition (%s): a conditional free claim"
                    % (m.group(0), re.sub(r"\s+", " ", reason)),
                    m.group(0),
                )
            elif ctx.option("flag_unconditional"):
                yield self.finding(
                    doc, m.start(), "'%s' used as a price claim: confirm nothing is payable" % m.group(0),
                    m.group(0), severity=WARN,
                )


@register
class PriceWithoutVat(Rule):
    id = "GR-EU-002"
    title = "Price without a VAT-inclusive figure"
    pack = PACK
    severity = ERROR
    rationale = (
        "The Price Indication Directive requires the selling price shown to consumers to be the final price "
        "including VAT and all other taxes. A net price can appear, but only next to the VAT-inclusive figure. "
        "Copy written for B2B buyers is often reused on consumer pages without the gross figure."
    )
    fix = "Add the VAT-inclusive figure next to the price, for example '15 euro (18.60 euro incl. VAT)'."
    citation = PID
    options = {
        "vat_rate": (24, "VAT rate used to suggest and check the inclusive figure, as a percent (24) or fraction (0.24)."),
        "currencies": (["\N{EURO SIGN}", "EUR", "euro", "euros"], "Currency symbols and words that mark a price."),
        "inclusive_markers": (
            ["incl. VAT", "incl VAT", "including VAT", "inc. VAT", "inc VAT", "VAT included", "VAT incl",
             "VAT-inclusive", "VAT inclusive", "inclusive of VAT", "with VAT", "inkl. MwSt", "TTC",
             "IVA incluido", "IVA inclusa", "\N{GREEK SMALL LETTER MU}\N{GREEK SMALL LETTER EPSILON} " + _GREEK_VAT],
            "Phrases that mark a figure as VAT-inclusive.",
        ),
        "exclusive_markers": (
            ["excl. VAT", "excl VAT", "excluding VAT", "ex. VAT", "ex VAT", "+ VAT", "plus VAT", "before VAT",
             "net of VAT", "exclusive of VAT", "VAT excluded", "zzgl. MwSt",
             "\N{GREEK SMALL LETTER CHI}\N{GREEK SMALL LETTER OMEGA}\N{GREEK SMALL LETTER RHO}"
             "\N{GREEK SMALL LETTER IOTA WITH TONOS}\N{GREEK SMALL LETTER FINAL SIGMA} " + _GREEK_VAT],
            "Phrases that mark a figure as net of VAT.",
        ),
        "window": (160, "How many characters around a price to look for the VAT figure, within the same paragraph."),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        rate = normalise_rate(ctx.option("vat_rate"))
        currencies = ctx.option("currencies")
        incl = _phrase_regex(ctx.option("inclusive_markers"))
        excl = _phrase_regex(ctx.option("exclusive_markers"))
        window = int(ctx.option("window"))
        checked_passages = set()
        for start, end, symbol, amount in find_prices(doc.text, currencies):
            a, b = doc.passage(start, window)
            passage = doc.text[a:b]
            has_incl = bool(incl and incl.search(passage))
            has_excl = bool(excl and excl.search(passage))
            label = re.sub(r"\s+", " ", doc.text[start:end]).strip()
            gross = amount * (1 + rate)
            suggestion = "%s %s incl. VAT" % (format_amount(gross), symbol) if rate else "the VAT-inclusive price"
            if not has_incl:
                why = "is marked as excluding VAT" if has_excl else "has no VAT-inclusive figure next to it"
                yield self.finding(
                    doc,
                    start,
                    "Price %s %s; at %s%% VAT show %s" % (label, why, format_amount(rate * 100), suggestion),
                    label,
                )
                continue
            if has_excl and rate and (a, b) not in checked_passages:
                checked_passages.add((a, b))
                amounts = [p[3] for p in find_prices(passage, currencies)]
                consistent = any(
                    abs(round(x * (1 + rate), 2) - y) <= 0.011 for x in amounts for y in amounts if y > x
                )
                if not consistent:
                    yield self.finding(
                        doc,
                        start,
                        "VAT-inclusive figure near %s does not match %s%% VAT (expected %s)"
                        % (label, format_amount(rate * 100), suggestion),
                        label,
                    )


@register
class UptimeAndGuaranteeClaims(Rule):
    id = "GR-EU-003"
    title = "Uptime SLA, guarantee or 24/7 wording"
    pack = PACK
    severity = ERROR
    rationale = (
        "Promises like '99.9% uptime', 'guaranteed results' or '24/7 support' are claims a trader must be able "
        "to honour. A misleading claim about the nature or availability of a service is a misleading action "
        "under Article 6 of the Unfair Commercial Practices Directive, and a sales page that promises more than "
        "the contract creates liability the terms of service try to exclude."
    )
    fix = (
        "Describe what you actually do ('we monitor the site and respond during business hours') and keep "
        "service levels in the contract, not in marketing copy."
    )
    citation = UCPD
    options = {
        "allowed_phrases": ([], "Exact phrases to allow, for example a product name that contains 'guarantee'."),
        "extra_patterns": ([], "Additional regular expressions to flag."),
    }

    PATTERNS = [
        (r"\b\d{2,3}(?:[.,]\d+)?\s?%\s*(?:uptime|availability|up-time)\b", "an uptime percentage"),
        (r"\b(?:uptime|availability)\s+(?:guarantee|sla|commitment|promise)\w*", "an uptime promise"),
        (r"\bservice[- ]level agreement\b|\bSLA\b", "an SLA"),
        (r"\bservice credits?\b", "service credits"),
        (r"\b(?:money[- ]back\s+)?guarantee(?:d|s)?\b", "a guarantee"),
        (r"(?<![\d/])24\s?/\s?7(?![\d/])|\b24x7\b|\b24 hours a day,? 7 days a week\b", "24/7 availability"),
        (r"\bround[- ]the[- ]clock\b|\baround the clock\b", "round-the-clock availability"),
        (r"\bzero downtime\b|\bnever (?:goes|go) down\b", "a no-downtime promise"),
    ]
    _NEGATION = re.compile(r"\b(?:no|not|never|cannot|can't|can\N{RIGHT SINGLE QUOTATION MARK}t|don't|do not|without|nor)\b[^.!?\n]{0,30}$", re.I)

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        allowed = _phrase_regex(ctx.option("allowed_phrases"))
        patterns = [(re.compile(p, re.I), what) for p, what in self.PATTERNS]
        patterns += [(re.compile(p, re.I), "a configured pattern") for p in ctx.option("extra_patterns")]
        text = doc.text
        taken = []
        for rx, what in patterns:
            for m in rx.finditer(text):
                if any(s <= m.start() < e for s, e in taken):
                    continue
                if allowed is not None and any(
                    a.start() <= m.start() < a.end() for a in allowed.finditer(text, max(0, m.start() - 60), m.end() + 60)
                ):
                    continue
                if what == "a guarantee" and self._NEGATION.search(text[max(0, m.start() - 40) : m.start()]):
                    continue
                taken.append((m.start(), m.end()))
                phrase = re.sub(r"\s+", " ", m.group(0))
                yield self.finding(doc, m.start(), "'%s' promises %s" % (phrase, what), phrase)


def load_consent_registry(path: Path) -> List[str]:
    """Read approved names: one per line, '#' comments, optional '| date | evidence' columns."""
    if not path.is_file():
        return []
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name = line.split("|", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _slug_variants(name: str) -> List[str]:
    parts = re.findall(r"\w+", name.lower())
    if not parts:
        return []
    return ["-".join(parts), "_".join(parts), "".join(parts)]


@register
class ClientNameWithoutConsent(Rule):
    id = "GR-EU-004"
    title = "Client name or logo without a consent record"
    pack = PACK
    severity = ERROR
    rationale = (
        "Showing a client's name or logo implies an endorsement. Claiming approval or endorsement that was not "
        "given is a blacklisted practice (Annex I point 4 of the Unfair Commercial Practices Directive), and "
        "naming individuals needs a lawful basis under the GDPR. Agents happily reuse names from case notes, so "
        "every name on a watch list must have a written consent record before it is published."
    )
    fix = (
        "Get written consent, add the name to the consent registry with the date and where the consent lives, "
        "or anonymise the reference ('a bakery in Lyon')."
    )
    citation = UCPD
    options = {
        "watch_names": ([], "Client names to watch for. Nothing is flagged until you list names here."),
        "consent_registry": ("consent/approved.txt", "File of approved names, relative to the config file."),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        names = [n for n in ctx.option("watch_names") if n.strip()]
        if not names:
            return
        registry_path = Path(ctx.root) / str(ctx.option("consent_registry"))
        approved = {n.lower() for n in load_consent_registry(registry_path)}
        for name in names:
            if name.lower() in approved:
                continue
            rx = re.compile(r"(?<!\w)%s(?!\w)" % r"\s+".join(re.escape(w) for w in name.split()), re.I)
            for m in rx.finditer(doc.text):
                yield self.finding(
                    doc,
                    m.start(),
                    "'%s' is named but has no consent record in %s" % (name, ctx.option("consent_registry")),
                    name,
                )
            slugs = _slug_variants(name)
            for img in doc.images:
                hay = " ".join(str(img.attrs.get(k) or "") for k in ("src", "alt", "title")).lower()
                if any(s in hay for s in slugs) or name.lower() in hay:
                    yield self.finding(
                        doc,
                        img.offset,
                        "Image appears to show '%s' (logo or photo) without a consent record" % name,
                        name,
                    )
