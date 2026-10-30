## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] New or changed rules have positive and negative tests and cite a primary source
- [ ] `python scripts/gen_rules_doc.py --check` passes (regenerate `docs/rules.md` if not)
- [ ] `guardrails check .` is clean (no em or en dashes, no credentials)
- [ ] CHANGELOG.md has an entry under Unreleased if users will notice the change
