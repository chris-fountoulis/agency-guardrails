# Contributing

[Back to README](README.md)

Thanks for helping make agency content safer to ship. Bug reports, false positives, new rules and better
citations are all welcome.

**On this page:** [Development setup](#development-setup) · [Before you open a pull request](#before-you-open-a-pull-request) ·
[Scope](#scope)

## Development setup

```bash
git clone https://github.com/chris-fountoulis/agency-guardrails
cd agency-guardrails
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -t .
```

There are no runtime dependencies and no test dependencies. Code must run on Python 3.9 to 3.13 using only the
standard library.

## Before you open a pull request

Run what CI runs (the full list of checks is in [docs/methodology.md](docs/methodology.md#continuous-integration)):

```bash
python -m unittest discover -s tests -t .
python scripts/gen_rules_doc.py --check
guardrails check examples/site/fixed
guardrails check .
```

- **New or changed rule:** add positive and negative tests, cite the primary source (the directive, the
  standard or the official documentation, not a blog post), then regenerate `docs/rules.md` with
  `python scripts/gen_rules_doc.py`. See [docs/writing-rules.md](docs/writing-rules.md).
- **False positive:** the most useful report is the smallest text that triggers it. Add it as a negative test.
- **Credentials in tests:** build them at runtime from fragments, as `tests/fakes.py` does. Never commit a literal
  token, even a revoked one.
- **House style for this repo:** no em or en dashes anywhere (CI checks), Conventional Commit messages
  (`feat(rules): ...`, `fix(hooks): ...`, `docs: ...`).

## Scope

Rules belong here when they encode a widely applicable business, legal or publishing rule that agents get wrong,
with a citable source. Client-specific or brand-specific rules belong in your own plugin module (see
`examples/custom-rule/`).

> [!IMPORTANT]
> Rules are engineering heuristics, not legal advice. Phrase rationales accordingly: what the rule protects against
> and where the requirement comes from, not a conclusion that something is or is not lawful.

By contributing you agree that your contributions are licensed under the MIT License and that you follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

[Back to README](README.md)

---

Built by [Chris Fountoulis](https://chrisfountoulis.com) at [Growth Of Influence](https://growthofinfluence.com).
