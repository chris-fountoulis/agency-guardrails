"""The starter config written by ``guardrails init``."""

STARTER_CONFIG = r'''# guardrails.toml: agency-guardrails configuration.
# Reference: https://github.com/chris-fountoulis/agency-guardrails/blob/main/docs/rules.md
# These rules are engineering heuristics, not legal advice.

[guardrails]
# Packs to run. Remove one to switch it off.
packs = ["eu-marketing", "aeo-seo", "house-style", "secrets", "deploy-safety"]
# Rules to switch off (globs work: "GR-SEO-*").
disable = []
# Files to check when a directory is given, and files to skip.
include = ["**/*"]
extend_exclude = ["dist/**", "build/**", "vendor/**"]
# Lowest severity that makes `guardrails check` exit 1: error, warn or never.
fail_on = "error"

# Silence rules for whole paths. Prefer inline comments for one-off cases:
#   <!-- guardrails-ignore: GR-EU-003 the contract quotes this wording -->
[[guardrails.ignore]]
path = "legal/**"
rules = ["GR-STY-*", "GR-SEO-*"]

[eu-marketing]
# VAT rate used to suggest and check VAT-inclusive prices (percent or fraction).
vat_rate = 24
# Client names to watch. A name is allowed once it is listed in the consent registry.
watch_names = ["Acme Bakery"]
consent_registry = "consent/approved.txt"

[aeo-seo]
answer_max_words = 70
require_in = ["title", "h1", "first_paragraph", "meta_description"]

[house-style]
# Escapes keep this file itself clean of the characters it bans.
banned_chars = ["\u2014", "\u2013"]
banned_words = ["utilize => use", "game-changer", "synergy"]
exempt_quotes = true

[secrets]
min_entropy = 3.5

[deploy-safety]
# Hosts and paths only a reviewed deploy may write to.
protected_hosts = ["prod.example.com"]
protected_paths = ["/srv/www/example/public_html"]
# Files agents must never edit directly (relative to this file).
protected_globs = ["dist/**", ".github/workflows/deploy*.yml"]
protected_branches = ["main", "master", "production"]
block_direct_push = true
override = "GUARDRAILS_OVERRIDE=1"
instead = "Make the change on a branch and open a pull request; the reviewed merge deploys it."

[hooks]
# PreToolUse: packs whose errors block a Write or Edit before it happens.
pre_write_packs = ["secrets"]
# PostToolUse: lint each file an agent writes and feed findings back to it.
post_write = true
# Stop: check every changed file before the agent finishes its turn.
stop_check = true
max_findings = 20
'''

STARTER_CONSENT = """# Consent registry: one approved client name per line.
# Format: name | date consent was given | where the written consent lives
# Only names listed here may appear in published copy or image file names.
Acme Bakery | 2026-01-15 | signed case study release, shared drive /consent/acme-bakery.pdf
"""
