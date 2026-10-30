"""Run rules over files, text and tool calls."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from agency_guardrails.config import Config, match_any, match_rule
from agency_guardrails.document import Document
from agency_guardrails.model import ACTION, CONTENT, Action, Finding, RuleContext, iter_unique

MAX_BYTES = 2_000_000

_IGNORE_LINE = re.compile(r"guardrails-ignore(?:-next-line)?:\s*([A-Za-z0-9*,\s-]+)")
_IGNORE_FILE = re.compile(r"guardrails-ignore-file:\s*([A-Za-z0-9*,\s-]+)")


def _ids(spec: str) -> List[str]:
    return [p for p in re.split(r"[\s,]+", spec.strip()) if re.match(r"^(GR-[A-Za-z0-9*-]+|\*|all)$", p, re.I)]


@dataclass
class InlineIgnores:
    """``guardrails-ignore: GR-XXX`` on a line silences that line and the next one.

    ``guardrails-ignore-file: GR-XXX`` anywhere silences the whole file.
    """

    file_rules: List[str] = field(default_factory=list)
    lines: Dict[int, List[str]] = field(default_factory=dict)

    @classmethod
    def scan(cls, raw: str) -> "InlineIgnores":
        out = cls()
        if "guardrails-ignore" not in raw:
            return out
        for number, line in enumerate(raw.splitlines(), start=1):
            m = _IGNORE_FILE.search(line)
            if m:
                out.file_rules.extend(_ids(m.group(1)))
                continue
            m = _IGNORE_LINE.search(line)
            if m:
                ids = _ids(m.group(1))
                for n in (number, number + 1):
                    out.lines.setdefault(n, []).extend(ids)
        return out

    def covers(self, finding: Finding) -> bool:
        if match_rule(finding.rule_id, self.file_rules):
            return True
        return match_rule(finding.rule_id, self.lines.get(finding.line, []))


@dataclass
class Result:
    findings: List[Finding] = field(default_factory=list)
    files_checked: int = 0
    rules_run: Set[str] = field(default_factory=set)

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return True
    return b"\0" in chunk


def display_path(path: str, cwd: Optional[str] = None) -> str:
    cwd = os.path.realpath(cwd or os.getcwd())
    try:
        rel = os.path.relpath(os.path.realpath(path), cwd)
    except ValueError:
        return Path(path).as_posix()
    if rel.startswith(".."):
        return Path(os.path.abspath(path)).as_posix()
    return Path(rel).as_posix()


def discover(paths: Iterable[str], config: Config) -> List[str]:
    """Expand files and directories into the list of files to check.

    Directories are walked and filtered by ``include``/``exclude``. A file named
    explicitly is checked unless it matches ``exclude``.
    """
    found: List[str] = []
    seen = set()
    for raw_path in paths:
        p = Path(raw_path)
        if p.is_file():
            candidates = [p]
            explicit = True
        elif p.is_dir():
            explicit = False
            candidates = []
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if not match_any(config.relpath(os.path.join(dirpath, d)) + "/x", config.exclude)
                )
                candidates.extend(Path(dirpath) / f for f in sorted(filenames))
        else:
            raise FileNotFoundError(raw_path)
        for c in candidates:
            rel = config.relpath(str(c))
            if match_any(rel, config.exclude):
                continue
            if not explicit and not match_any(rel, config.include):
                continue
            key = os.path.abspath(str(c))
            if key in seen:
                continue
            seen.add(key)
            found.append(str(c))
    return found


def check_document(doc: Document, config: Config, rel_path: Optional[str] = None) -> List[Finding]:
    """Run every enabled content rule that applies to ``doc``."""
    rel = rel_path if rel_path is not None else doc.path
    ignores = InlineIgnores.scan(doc.raw)
    out: List[Finding] = []
    for rule in config.enabled_rules(CONTENT):
        if doc.kind not in rule.applies_to and "*" not in rule.applies_to:
            continue
        if config.is_ignored(rel, rule.id):
            continue
        ctx = RuleContext(rule, config)
        for f in rule.check(doc, ctx):
            f.severity = config.severity_for(rule.id, f.severity)
            if not ignores.covers(f):
                out.append(f)
    return sorted(iter_unique(out), key=Finding.sort_key)


def check_text(text: str, path: str, config: Config) -> List[Finding]:
    """Check text that is not (yet) on disk, such as content an agent is about to write."""
    doc = Document(display_path(path), text)
    return check_document(doc, config, config.relpath(path))


def check_paths(paths: Iterable[str], config: Config, cwd: Optional[str] = None) -> Result:
    result = Result()
    result.rules_run = {r.id for r in config.enabled_rules(CONTENT)}
    for path in discover(paths, config):
        p = Path(path)
        try:
            if p.stat().st_size > MAX_BYTES or _is_binary(p):
                continue
            doc = Document.from_path(path, display=display_path(path, cwd))
        except OSError:
            continue
        result.files_checked += 1
        result.findings.extend(check_document(doc, config, config.relpath(path)))
    result.findings.sort(key=Finding.sort_key)
    return result


def check_action(action: Action, config: Config) -> List[Finding]:
    """Run every enabled action rule on a tool call (PreToolUse)."""
    out: List[Finding] = []
    for rule in config.enabled_rules(ACTION):
        ctx = RuleContext(rule, config)
        for f in rule.check_action(action, ctx):
            f.severity = config.severity_for(rule.id, f.severity)
            out.append(f)
    return list(iter_unique(out))


def failed(findings: Iterable[Finding], fail_on: str) -> bool:
    if fail_on == "never":
        return False
    levels = {"error"} if fail_on == "error" else {"error", "warn"}
    return any(f.severity in levels for f in findings)
