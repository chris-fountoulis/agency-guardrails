# Writing rules

[Back to README](../README.md)

Every rule is a small Python class. Built-in rules live in `agency_guardrails/rules/`; your own rules can live in
any module and load through `plugins` in `guardrails.toml`. Both kinds get the same config validation , inline and
path ignores, severity overrides, output formats, Claude Code hooks and GitHub Action support.

> [!IMPORTANT]
> Rules are engineering heuristics. Write the rationale so a reader understands what the rule protects against,
> cite the primary source and never present a rule as a legal determination. The reasoning behind that is in
> [methodology.md](methodology.md).

## Contents

- [Anatomy of a content rule](#anatomy-of-a-content-rule)
- [What a rule can read](#what-a-rule-can-read)
- [Action rules](#action-rules)
- [Testing a rule](#testing-a-rule)
- [Contributing a built-in rule](#contributing-a-built-in-rule)

## Anatomy of a content rule

```python
import re

from agency_guardrails.model import WARN, Rule
from agency_guardrails.registry import register


@register
class ProductNameCase(Rule):
    id = "GR-ACME-001"                      # GR-<2 to 4 letters>-<3 digits>, unique
    title = "Product name in the wrong case"
    pack = "acme-brand"                     # rules are switched on and configured per pack
    severity = WARN                         # ERROR or WARN; users can override per rule
    rationale = "The brand book spells the product 'SourDough Pro'."
    fix = "Write it exactly as 'SourDough Pro'."
    citation = "https://www.wipo.int/trademarks/en/"   # https link to the primary source
    applies_to = ("markdown", "html", "text")          # the default; ("*",) means every text file
    options = {"product": ("SourDough Pro", "The exact product spelling.")}

    def check(self, doc, ctx):
        product = ctx.option("product")
        pattern = re.compile(r"\b%s\b" % r"\s+".join(map(re.escape, product.split())), re.I)
        for m in pattern.finditer(doc.text):
            if m.group(0) != product:
                yield self.finding(doc, m.start(), "'%s' should be written '%s'" % (m.group(0), product))
```

This is the rule in [`examples/custom-rule/acme_rules.py`](../examples/custom-rule/acme_rules.py). Load it with:

```toml
[guardrails]
plugins = ["acme_rules.py"]          # a path relative to this file, or an importable module name
packs = ["acme-brand", "house-style"]

[acme-brand]
product = "SourDough Pro"
```

> [!NOTE]
> `@register` validates the class when the module is imported : a rule without a title, rationale, an https
> citation or a well-formed id fails loudly instead of shipping undocumented.

## What a rule can read

`check(doc, ctx)` receives a `Document` (see `agency_guardrails/document.py`):

| Attribute | What it holds |
| --- | --- |
| `doc.raw` | The file exactly as written |
| `doc.text` | The prose view: same length as `raw`, with markup, code, URLs and front-matter keys blanked to spaces and HTML entities decoded in place. Match on this for anything about copy |
| `doc.kind` | `markdown`, `html`, `text` or `other` |
| `doc.title`, `doc.meta_description`, `doc.focus_keyword` | From `<title>`/`<meta>` or Markdown front matter |
| `doc.headings`, `doc.paragraphs`, `doc.questions` | Lists with `.text` and `.offset` (and `.level` for headings) |
| `doc.images`, `doc.links` | Elements with `.attrs` and `.offset`; Markdown images too |
| `doc.jsonld` | Parsed JSON-LD blocks, with `.items()` flattening `@graph` |
| `doc.in_quote(offset)` | True inside quotation marks, `<q>`, `<blockquote>` or Markdown `>` lines |
| `doc.passage(offset)` | The paragraph around an offset, capped to a window |

Because `doc.text` keeps offsets, `self.finding(doc, offset, message)` turns any match position into an exact
line and column in the original file.

`ctx.option(name)` returns the value from `[rules.GR-XXX]`, then the pack table, then the rule's default.
`ctx.root` is the directory of the config file, for rules that read side files (the consent registry does).

## Action rules

Action rules run before a tool call, from the PreToolUse hook. Set `kind = ACTION` and implement
`check_action(action, ctx)`. `action.tool_name`, `action.tool_input`, `action.command`, `action.file_path` and
`action.cwd` describe the call. Return `self.action_finding(message)` to block it. Start the message with what
was blocked and end it with what to do instead; the agent reads it verbatim. See
`agency_guardrails/rules/deploy_safety.py`.

## Testing a rule

Every built-in rule has positive and negative fixtures. The helper `tests.helpers.run_rule` runs one rule on a
string:

```python
import acme_rules  # noqa: F401  (importing the module registers the rule)
from tests.helpers import run_rule

def test_flags_wrong_case():
    found = run_rule("GR-ACME-001", "Try sourdough pro today.\n")
    assert [f.line for f in found] == [1]
```

> [!WARNING]
> Test strings that look like credentials must be built at runtime (see `tests/fakes.py`), so the repository never
> contains a literal that secret scanners flag.

## Contributing a built-in rule

1. Add the class to the right module in `agency_guardrails/rules/` (or a new module imported from
   `agency_guardrails/rules/__init__.py`).
2. Add positive and negative tests.
3. Run `python scripts/gen_rules_doc.py` to regenerate [`rules.md`](rules.md); CI fails if it is stale.
4. If the rule should fire on the sample site, extend `examples/site/bad/` and keep `examples/site/fixed/` clean.

[Back to README](../README.md)

---

Built by [Chris Fountoulis](https://chrisfountoulis.com) at [Growth Of Influence](https://growthofinfluence.com).
