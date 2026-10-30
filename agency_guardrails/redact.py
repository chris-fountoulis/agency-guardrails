"""Credential detection and redaction shared by the secrets pack and ``guardrails redact``.

Patterns follow the publicly documented token formats of each provider.
They are written so that this file itself contains nothing that looks like a
real credential.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Optional, Pattern, Tuple


@dataclass(frozen=True)
class Shape:
    kind: str
    label: str
    pattern: Pattern[str]
    group: int = 0  # which group holds the secret value


def _c(p: str, flags: int = 0) -> Pattern[str]:
    return re.compile(p, flags)


# The private key header is assembled so the source never contains it verbatim.
_PEM_BEGIN = "-----" + "BEGIN"
_PEM_END = "-----" + "END"

SHAPES: Tuple[Shape, ...] = (
    Shape("anthropic-api-key", "an Anthropic API key", _c(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    Shape("openai-api-key", "an OpenAI API key", _c(r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}")),
    Shape("github-token", "a GitHub token", _c(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255}\b")),
    Shape("github-pat", "a GitHub fine-grained token", _c(r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b")),
    Shape("aws-access-key-id", "an AWS access key id", _c(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    Shape(
        "aws-secret-access-key",
        "an AWS secret access key",
        _c(r"(?i)\baws_?secret_?access_?key\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])"),
        1,
    ),
    Shape("stripe-secret-key", "a Stripe secret key", _c(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    Shape("stripe-webhook-secret", "a Stripe webhook secret", _c(r"\bwhsec_[A-Za-z0-9]{24,}\b")),
    Shape("slack-token", "a Slack token", _c(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    Shape("slack-webhook", "a Slack webhook URL", _c(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}")),
    Shape("google-api-key", "a Google API key", _c(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
)

PRIVATE_KEY = Shape(
    "private-key",
    "a private key block",
    _c(
        re.escape(_PEM_BEGIN)
        + r"[ A-Z0-9_-]{0,40}PRIVATE KEY(?: BLOCK)?-----"
        + r"(?:[\s\S]*?"
        + re.escape(_PEM_END)
        + r"[ A-Z0-9_-]{0,40}PRIVATE KEY(?: BLOCK)?-----|[\s\S]*\Z)"
    ),
)

KEY_NAMES = (
    "api_key", "apikey", "api-key", "secret", "secret_key", "client_secret", "token", "access_token",
    "auth_token", "refresh_token", "password", "passwd", "pwd", "private_key", "access_key", "bearer",
)

_PLACEHOLDER = re.compile(
    r"x{4,}|\*{3,}|example|changeme|change_me|placeholder|your[_-]|<[^>]*>|\$\{|\{\{|redacted|dummy|sample|"
    r"^(?:true|false|null|none)$|process\.env|os\.environ|getenv",
    re.I,
)


def generic_pattern(key_names: Iterable[str] = KEY_NAMES) -> Pattern[str]:
    names = "|".join(re.escape(k).replace(r"_", r"[_-]?") for k in sorted(set(key_names), key=len, reverse=True))
    return re.compile(
        r"(?i)(?<![A-Za-z0-9])(?P<key>[A-Za-z0-9_.-]*(?:%s))[\"']?\s*(?::=|=>|[:=])\s*(?P<q>[\"'`]?)"
        r"(?P<val>[^\s\"'`;,)}\]]{12,})(?P=q)" % names
    )


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_random(value: str, min_entropy: float = 3.5) -> bool:
    if _PLACEHOLDER.search(value):
        return False
    if len(set(value)) < 6:
        return False
    if re.fullmatch(r"[a-z]+(?:[_-][a-z]+)*", value):  # an ordinary identifier
        return False
    return shannon_entropy(value) >= min_entropy


@dataclass
class Hit:
    kind: str
    label: str
    start: int
    end: int

    def preview(self, text: str) -> str:
        value = text[self.start : self.end]
        return value[:4] + "..." if len(value) > 8 else "..."


def scan(
    text: str,
    shapes: bool = True,
    private_keys: bool = True,
    generic: bool = True,
    min_entropy: float = 3.5,
    key_names: Iterable[str] = KEY_NAMES,
    allow: Optional[Iterable[str]] = None,
) -> List[Hit]:
    """Find credentials in ``text``. Overlapping hits keep the most specific one."""
    hits: List[Hit] = []
    allow_rx = [re.compile(a) for a in (allow or [])]

    def taken(a: int, b: int) -> bool:
        return any(h.start < b and a < h.end for h in hits)

    def add(kind: str, label: str, a: int, b: int) -> None:
        value = text[a:b]
        if any(rx.search(value) for rx in allow_rx):
            return
        if not taken(a, b):
            hits.append(Hit(kind, label, a, b))

    if private_keys:
        for m in PRIVATE_KEY.pattern.finditer(text):
            add(PRIVATE_KEY.kind, PRIVATE_KEY.label, m.start(), m.end())
    if shapes:
        for shape in SHAPES:
            for m in shape.pattern.finditer(text):
                add(shape.kind, shape.label, m.start(shape.group), m.end(shape.group))
    if generic:
        for m in generic_pattern(key_names).finditer(text):
            if looks_random(m.group("val"), min_entropy):
                add("generic-secret", "a hard-coded secret in '%s'" % m.group("key"), m.start("val"), m.end("val"))
    hits.sort(key=lambda h: h.start)
    return hits


def redact(text: str, **kwargs) -> Tuple[str, List[Hit]]:
    """Return ``text`` with every credential replaced by ``[REDACTED:kind]``."""
    hits = scan(text, **kwargs)
    out = []
    pos = 0
    for h in hits:
        out.append(text[pos : h.start])
        out.append("[REDACTED:%s]" % h.kind)
        pos = h.end
    out.append(text[pos:])
    return "".join(out), hits
