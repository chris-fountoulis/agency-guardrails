"""An example custom rule pack, loaded with `plugins = ["acme_rules.py"]` in guardrails.toml.

GR-ACME-001 flags a product name written in the wrong case, a typical brand rule.
"""

import re

from agency_guardrails.model import WARN, Rule
from agency_guardrails.registry import register


@register
class ProductNameCase(Rule):
    id = "GR-ACME-001"
    title = "Product name in the wrong case"
    pack = "acme-brand"
    severity = WARN
    rationale = "The brand book spells the product 'SourDough Pro'. Other spellings dilute the trademark."
    fix = "Write it exactly as 'SourDough Pro'."
    citation = "https://www.wipo.int/trademarks/en/"
    options = {"product": ("SourDough Pro", "The exact product spelling.")}

    def check(self, doc, ctx):
        product = ctx.option("product")
        pattern = re.compile(r"\b%s\b" % r"\s+".join(map(re.escape, product.split())), re.I)
        for m in pattern.finditer(doc.text):
            if m.group(0) != product:
                yield self.finding(doc, m.start(), "'%s' should be written '%s'" % (m.group(0), product), m.group(0))
