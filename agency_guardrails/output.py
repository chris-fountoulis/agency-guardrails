"""Render findings as text, JSON, SARIF 2.1.0 or GitHub workflow annotations."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from agency_guardrails import __version__, registry
from agency_guardrails.model import ERROR, Finding, Rule

TOOL_URI = "https://github.com/chris-fountoulis/agency-guardrails"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

_COLORS = {"error": "\033[31m", "warn": "\033[33m", "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m"}


def _c(name: str, text: str, color: bool) -> str:
    return "%s%s%s" % (_COLORS[name], text, _COLORS["reset"]) if color else text


def summary_line(findings: List[Finding], files_checked: Optional[int] = None) -> str:
    errors = sum(1 for f in findings if f.severity == ERROR)
    warns = len(findings) - errors
    parts = []
    if files_checked is not None:
        parts.append("%d file%s checked" % (files_checked, "" if files_checked == 1 else "s"))
    parts.append("%d error%s" % (errors, "" if errors == 1 else "s"))
    parts.append("%d warning%s" % (warns, "" if warns == 1 else "s"))
    return ", ".join(parts)


def render_text(findings: List[Finding], files_checked: Optional[int] = None, color: bool = False) -> str:
    lines = []
    current = None
    for f in findings:
        if f.path != current:
            if current is not None:
                lines.append("")
            lines.append(_c("bold", f.path or "(input)", color))
            current = f.path
        sev = _c(f.severity, "%-5s" % f.severity, color)
        lines.append("  %-7s  %s  %-10s  %s" % ("%d:%d" % (f.line, f.column), sev, f.rule_id, f.message))
    if findings:
        lines.append("")
    lines.append(summary_line(findings, files_checked))
    return "\n".join(lines) + "\n"


def render_json(findings: List[Finding], files_checked: Optional[int] = None) -> str:
    errors = sum(1 for f in findings if f.severity == ERROR)
    data = {
        "version": __version__,
        "summary": {
            "files_checked": files_checked,
            "errors": errors,
            "warnings": len(findings) - errors,
        },
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(data, indent=2, ensure_ascii=True) + "\n"


def _camel(title: str) -> str:
    return "".join(w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", title))


def _sarif_rule(rule: Rule) -> Dict[str, Any]:
    return {
        "id": rule.id,
        "name": _camel(rule.title),
        "shortDescription": {"text": rule.title},
        "fullDescription": {"text": rule.rationale},
        "help": {"text": "%s\n\nFix: %s\n\nSource: %s" % (rule.rationale, rule.fix, rule.citation)},
        "helpUri": rule.citation,
        "defaultConfiguration": {"level": "error" if rule.severity == ERROR else "warning"},
        "properties": {"tags": ["agency-guardrails", rule.pack], "pack": rule.pack},
    }


def render_sarif(findings: List[Finding], rules: Optional[Iterable[Rule]] = None) -> str:
    rule_list = list(rules) if rules is not None else registry.all_rules()
    seen = {r.id for r in rule_list}
    for f in findings:  # make sure every referenced rule is described
        if f.rule_id not in seen:
            try:
                rule_list.append(registry.get(f.rule_id))
                seen.add(f.rule_id)
            except KeyError:
                pass
    index = {r.id: i for i, r in enumerate(rule_list)}
    results = []
    for f in findings:
        result: Dict[str, Any] = {
            "ruleId": f.rule_id,
            "level": "error" if f.severity == ERROR else "warning",
            "message": {"text": f.message + (" Fix: %s" % f.fix if f.fix else "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.path, "uriBaseId": "%SRCROOT%"},
                        "region": {"startLine": f.line, "startColumn": f.column},
                    }
                }
            ],
            "partialFingerprints": {"guardrails/v1": "%s:%s:%s" % (f.rule_id, f.path, f.match or f.message)},
        }
        if f.rule_id in index:
            result["ruleIndex"] = index[f.rule_id]
        results.append(result)
    data = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "agency-guardrails",
                        "version": __version__,
                        "semanticVersion": __version__,
                        "informationUri": TOOL_URI,
                        "rules": [_sarif_rule(r) for r in rule_list],
                    }
                },
                "originalUriBaseIds": {"%SRCROOT%": {"uri": "./"}},
                "results": results,
            }
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=True) + "\n"


def _gh_escape_data(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _gh_escape_prop(s: str) -> str:
    return _gh_escape_data(s).replace(":", "%3A").replace(",", "%2C")


def render_github(findings: List[Finding], files_checked: Optional[int] = None) -> str:
    """GitHub Actions workflow commands: each finding becomes a PR annotation."""
    lines = []
    for f in findings:
        level = "error" if f.severity == ERROR else "warning"
        props = "file=%s,line=%d,col=%d,title=%s" % (
            _gh_escape_prop(f.path), f.line, f.column, _gh_escape_prop("%s %s" % (f.rule_id, registry_title(f.rule_id)))
        )
        lines.append("::%s %s::%s" % (level, props, _gh_escape_data(f.message)))
    lines.append(summary_line(findings, files_checked))
    return "\n".join(lines) + "\n"


def registry_title(rule_id: str) -> str:
    try:
        return registry.get(rule_id).title
    except KeyError:
        return ""


def for_agent(findings: List[Finding], limit: int = 20) -> str:
    """Compact, actionable text for a model to read in a hook response."""
    lines = []
    for f in findings[:limit]:
        where = "%s:%d:%d " % (f.path, f.line, f.column) if f.path else ""
        lines.append("- %s%s (%s): %s" % (where, f.rule_id, f.severity, f.message))
        if f.fix:
            lines.append("  Fix: %s" % f.fix)
    if len(findings) > limit:
        lines.append("- ... and %d more (run `guardrails check` to see all)" % (len(findings) - limit))
    return "\n".join(lines)


FORMATS = {
    "text": render_text,
    "json": render_json,
    "github": render_github,
}
