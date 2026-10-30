"""The rule registry. Rules register themselves with the :func:`register` decorator."""

from __future__ import annotations

import re
from typing import Dict, List, Type

from agency_guardrails.model import SEVERITIES, Rule

_RULES: Dict[str, Rule] = {}
_ID = re.compile(r"^GR-[A-Z]{2,4}-\d{3}$")
_loaded = False


def register(cls: Type[Rule]) -> Type[Rule]:
    """Class decorator: validate a rule class and add one instance to the registry."""
    rule = cls()
    if not _ID.match(rule.id):
        raise ValueError("rule id %r must look like GR-ABC-001" % rule.id)
    if rule.id in _RULES:
        raise ValueError("duplicate rule id %s" % rule.id)
    if rule.severity not in SEVERITIES:
        raise ValueError("rule %s has unknown severity %r" % (rule.id, rule.severity))
    for attr in ("title", "pack", "rationale", "citation"):
        if not getattr(rule, attr):
            raise ValueError("rule %s is missing %s" % (rule.id, attr))
    if not rule.citation.startswith("https://"):
        raise ValueError("rule %s citation must be an https URL" % rule.id)
    _RULES[rule.id] = rule
    return cls


def _load() -> None:
    global _loaded
    if not _loaded:
        _loaded = True
        import agency_guardrails.rules  # noqa: F401  (registers every pack)


def all_rules() -> List[Rule]:
    _load()
    return [_RULES[k] for k in sorted(_RULES)]


def get(rule_id: str) -> Rule:
    _load()
    try:
        return _RULES[rule_id.upper()]
    except KeyError:
        raise KeyError("unknown rule %s" % rule_id) from None


def packs() -> List[str]:
    return sorted({r.pack for r in all_rules()})


def rules_in_pack(pack: str) -> List[Rule]:
    return [r for r in all_rules() if r.pack == pack]
