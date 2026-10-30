"""secrets: credentials that must never be written into content, config or code."""

from __future__ import annotations

from typing import Iterable

from agency_guardrails import redact
from agency_guardrails.document import Document
from agency_guardrails.model import ERROR, WARN, Finding, Rule, RuleContext
from agency_guardrails.registry import register

PACK = "secrets"
ANY = ("*",)


@register
class KnownTokenShapes(Rule):
    id = "GR-SEC-001"
    title = "Provider API key or token"
    pack = PACK
    severity = ERROR
    applies_to = ANY
    rationale = (
        "Agents paste credentials wherever the conversation already is: a draft article, a config file, a "
        "commit. Provider tokens have documented shapes (AWS, GitHub, Anthropic, OpenAI, Stripe, Slack, Google), "
        "so they can be stopped before they are written, not after they are pushed."
    )
    fix = "Remove the value, load it from an environment variable or a secrets manager, and rotate the key."
    citation = "https://docs.github.com/en/code-security/secret-scanning/introduction/supported-secret-scanning-patterns"
    options = {"allow_patterns": ([], "Regular expressions for values that are known test fixtures.")}

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        for hit in redact.scan(doc.raw, private_keys=False, generic=False, allow=ctx.option("allow_patterns")):
            yield self.finding(doc, hit.start, "Looks like %s (%s)" % (hit.label, hit.preview(doc.raw)), hit.kind)


@register
class PrivateKeyBlock(Rule):
    id = "GR-SEC-002"
    title = "Private key block"
    pack = PACK
    severity = ERROR
    applies_to = ANY
    rationale = (
        "A PEM or OpenSSH private key in a repository or a page gives anyone who reads it the identity the key "
        "stands for: a server login, a signing key or a TLS certificate."
    )
    fix = "Delete the key from the file and its history, store it outside the repository and issue a new key."
    citation = "https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html"
    options = {}

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        for hit in redact.scan(doc.raw, shapes=False, generic=False):
            yield self.finding(doc, hit.start, "Private key block", hit.kind)


@register
class HighEntropyAssignment(Rule):
    id = "GR-SEC-003"
    title = "Hard-coded secret assignment"
    pack = PACK
    severity = WARN
    applies_to = ANY
    rationale = (
        "Not every credential has a known prefix. A random-looking value assigned to a name like token, "
        "secret or password is usually a hard-coded credential (CWE-798)."
    )
    fix = "Read the value from the environment or a secrets manager; if it is a fixture, add it to allow_patterns."
    citation = "https://cwe.mitre.org/data/definitions/798.html"
    options = {
        "min_entropy": (3.5, "Minimum Shannon entropy (bits per character) for a value to count as random."),
        "key_names": (list(redact.KEY_NAMES), "Names that mark an assignment as a credential."),
        "allow_patterns": ([], "Regular expressions for values that are known fixtures."),
    }

    def check(self, doc: Document, ctx: RuleContext) -> Iterable[Finding]:
        known = {(h.start, h.end) for h in redact.scan(doc.raw, generic=False)}
        hits = redact.scan(
            doc.raw,
            shapes=False,
            private_keys=False,
            min_entropy=float(ctx.option("min_entropy")),
            key_names=ctx.option("key_names"),
            allow=ctx.option("allow_patterns"),
        )
        for hit in hits:
            if any(a < hit.end and hit.start < b for a, b in known):
                continue  # already reported by a more specific rule
            yield self.finding(doc, hit.start, "Looks like %s (%s)" % (hit.label, hit.preview(doc.raw)), hit.kind)
