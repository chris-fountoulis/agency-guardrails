# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-30

First public release.

### Added

- Rule engine with self-registering rules: id, title, severity, rationale, fix and a citation to the primary
  source, validated at import time.
- `guardrails.toml` configuration with pack selection, enable and disable lists, include and exclude globs,
  per-path ignores, per-rule severity and options, and strict validation. Works on Python 3.9 and 3.10 through a
  built-in TOML fallback parser; JSON configs are accepted too.
- Inline `guardrails-ignore: GR-XXX` (line and next line) and `guardrails-ignore-file: GR-XXX` comments.
- HTML and Markdown parsing into an offset-stable prose view, so findings point at exact lines and columns.
- `eu-marketing` pack: GR-EU-001 conditional free claims, GR-EU-002 prices without a VAT-inclusive figure,
  GR-EU-003 uptime, guarantee and 24/7 wording, GR-EU-004 client names or logos without a consent record.
- `aeo-seo` pack: GR-SEO-001 answer-first opening, GR-SEO-002 focus keyword placement, GR-SEO-003 FAQ sections
  with matching FAQPage JSON-LD, GR-SEO-004 image alt text, GR-SEO-005 `target=_blank` without noopener.
- `house-style` pack: GR-STY-001 banned characters, GR-STY-002 banned words, with quotations exempt.
- `secrets` pack: GR-SEC-001 provider token shapes, GR-SEC-002 private key blocks, GR-SEC-003 high-entropy
  credential assignments.
- `deploy-safety` pack of PreToolUse action rules: GR-DEP-001 writes to protected hosts or paths, GR-DEP-002
  edits to protected files, GR-DEP-003 force or direct pushes to protected branches.
- CLI: `guardrails check` (text, JSON, SARIF 2.1.0, GitHub annotations), `rules`, `explain`, `init`, `redact`
  and `hook`.
- Claude Code PreToolUse, PostToolUse and Stop hooks, packaged as a plugin and a one-plugin marketplace.
- Composite GitHub Action with PR annotations, job summary, outputs and optional SARIF upload.
- Custom rule packs through `plugins` in `guardrails.toml`, with an example in `examples/custom-rule/`.
- pre-commit hook definition.
- Sample site in `examples/site/` with a bad and a fixed version, used by the README demo and CI.

[Unreleased]: https://github.com/chris-fountoulis/agency-guardrails/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/chris-fountoulis/agency-guardrails/releases/tag/v0.1.0
