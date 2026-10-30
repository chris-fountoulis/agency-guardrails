"""Core data model: severities, findings and the Rule base class."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, Iterator, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from agency_guardrails.document import Document

ERROR = "error"
WARN = "warn"
SEVERITIES = (ERROR, WARN)
_RANK = {WARN: 1, ERROR: 2}

CONTENT = "content"
ACTION = "action"


def severity_rank(severity: str) -> int:
    """Return a sortable rank for a severity name (higher is worse)."""
    return _RANK.get(severity, 0)


@dataclass
class Finding:
    """One problem found by one rule at one location."""

    rule_id: str
    severity: str
    message: str
    path: str = ""
    line: int = 1
    column: int = 1
    match: str = ""
    fix: str = ""

    def sort_key(self) -> Tuple[str, int, int, str]:
        return (self.path, self.line, self.column, self.rule_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "match": self.match,
            "fix": self.fix,
        }


@dataclass
class Action:
    """A tool call an agent is about to make (the PreToolUse payload)."""

    tool_name: str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    cwd: str = "."

    @property
    def command(self) -> str:
        return str(self.tool_input.get("command") or "")

    @property
    def file_path(self) -> str:
        value = self.tool_input.get("file_path") or self.tool_input.get("notebook_path") or ""
        return str(value)


class RuleContext:
    """Options and settings a rule sees while it runs.

    Lookup order for an option: the rule's own table (``[rules.GR-XXX]``),
    then the pack table (``[eu-marketing]``), then the rule's declared default.
    """

    def __init__(self, rule: "Rule", config: Any = None):
        self.rule = rule
        self.config = config

    def option(self, name: str) -> Any:
        if name not in self.rule.options:
            raise KeyError("rule %s has no option %r" % (self.rule.id, name))
        if self.config is not None:
            rule_table = self.config.rule_options.get(self.rule.id, {})
            if name in rule_table:
                return rule_table[name]
            pack_table = self.config.pack_options.get(self.rule.pack, {})
            if name in pack_table:
                return pack_table[name]
        return self.rule.options[name][0]

    @property
    def root(self) -> str:
        if self.config is not None:
            return str(self.config.root)
        return "."


class Rule:
    """Base class for every rule.

    Subclasses set the class attributes and implement :meth:`check` (content
    rules, run on files) or :meth:`check_action` (action rules, run on tool
    calls before they happen).
    """

    id: str = ""
    title: str = ""
    pack: str = ""
    severity: str = ERROR
    kind: str = CONTENT
    rationale: str = ""
    fix: str = ""
    citation: str = ""
    #: document kinds this rule reads: markdown, html, text, other
    applies_to: Tuple[str, ...] = ("markdown", "html", "text")
    #: option name -> (default value, one line description)
    options: Dict[str, Tuple[Any, str]] = {}

    def check(self, doc: "Document", ctx: RuleContext) -> Iterable[Finding]:
        return ()

    def check_action(self, action: Action, ctx: RuleContext) -> Iterable[Finding]:
        return ()

    def finding(
        self,
        doc: "Document",
        offset: int,
        message: str,
        match: str = "",
        severity: Optional[str] = None,
    ) -> Finding:
        line, column = doc.position(offset)
        return Finding(
            rule_id=self.id,
            severity=severity or self.severity,
            message=message,
            path=doc.path,
            line=line,
            column=column,
            match=match,
            fix=self.fix,
        )

    def action_finding(self, message: str, match: str = "") -> Finding:
        return Finding(
            rule_id=self.id,
            severity=self.severity,
            message=message,
            path="",
            line=1,
            column=1,
            match=match,
            fix=self.fix,
        )

    def describe(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "pack": self.pack,
            "severity": self.severity,
            "kind": self.kind,
            "rationale": self.rationale,
            "fix": self.fix,
            "citation": self.citation,
            "applies_to": list(self.applies_to),
            "options": {k: {"default": v[0], "help": v[1]} for k, v in self.options.items()},
        }


def iter_unique(findings: Iterable[Finding]) -> Iterator[Finding]:
    """Drop exact duplicate findings while keeping order."""
    seen = set()
    for f in findings:
        key = (f.rule_id, f.path, f.line, f.column, f.message)
        if key in seen:
            continue
        seen.add(key)
        yield f
