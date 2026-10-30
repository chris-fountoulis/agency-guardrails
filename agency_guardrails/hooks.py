"""Claude Code hook handlers.

Each handler reads the hook payload as JSON on stdin and answers on stdout
following the Claude Code hooks contract:

* PreToolUse: ``hookSpecificOutput.permissionDecision = "deny"`` with a reason
  the model reads, so a risky Bash command or a Write that carries a secret
  never runs.
* PostToolUse: ``decision = "block"`` with a reason (errors) or
  ``hookSpecificOutput.additionalContext`` (warnings only), so the agent sees
  the findings for the file it just wrote and fixes them.
* Stop: ``decision = "block"`` with a reason while changed files still have
  errors. ``stop_hook_active`` is honoured, so the agent is never looped.

A hook that crashes exits 1, which Claude Code treats as a non-blocking
error: guardrails fails open rather than wedging a session.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from typing import IO, Any, Dict, List, Optional

from agency_guardrails import output
from agency_guardrails.config import Config, ConfigError, load, match_any
from agency_guardrails.engine import check_action, check_paths, check_text
from agency_guardrails.model import ERROR, Action, Finding

FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
EVENTS = ("pre-tool-use", "post-tool-use", "stop")


def _emit(stdout: IO[str], payload: Dict[str, Any]) -> None:
    stdout.write(json.dumps(payload) + "\n")


def _new_text(tool_name: str, tool_input: Dict[str, Any]) -> str:
    if tool_name == "Write":
        return str(tool_input.get("content") or "")
    if tool_name == "Edit":
        return str(tool_input.get("new_string") or "")
    if tool_name == "MultiEdit":
        return "\n".join(str(e.get("new_string") or "") for e in tool_input.get("edits") or [] if isinstance(e, dict))
    if tool_name == "NotebookEdit":
        return str(tool_input.get("new_source") or "")
    return ""


def _limit(cfg: Config) -> int:
    try:
        return int(cfg.hook_option("max_findings", 20))
    except (TypeError, ValueError):
        return 20


def _in_scope(path: str, cfg: Config) -> bool:
    rel = cfg.relpath(path)
    if rel.startswith(".."):
        return False
    return not match_any(rel, cfg.exclude) and match_any(rel, cfg.include)


def pre_tool_use(data: Dict[str, Any], cfg: Config, stdout: IO[str]) -> int:
    tool = str(data.get("tool_name") or "")
    tool_input = data.get("tool_input") or {}
    cwd = str(data.get("cwd") or os.getcwd())
    action = Action(tool, tool_input, cwd=cwd)
    findings: List[Finding] = [f for f in check_action(action, cfg) if f.severity == ERROR]

    if tool in FILE_TOOLS and action.file_path:
        target = action.file_path if os.path.isabs(action.file_path) else os.path.join(cwd, action.file_path)
        packs = cfg.hook_option("pre_write_packs", ["secrets"])
        text = _new_text(tool, tool_input)
        if packs and text and _in_scope(target, cfg):
            scoped = dataclasses.replace(cfg, packs=list(packs), enable=[])
            for f in check_text(text, target, scoped):
                if f.severity == ERROR:
                    f.message += " (in the text about to be written)"
                    findings.append(f)

    if not findings:
        return 0
    reason = "agency-guardrails blocked this %s call:\n%s" % (tool, output.for_agent(findings, _limit(cfg)))
    _emit(
        stdout,
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
    )
    return 0


def post_tool_use(data: Dict[str, Any], cfg: Config, stdout: IO[str]) -> int:
    tool = str(data.get("tool_name") or "")
    if tool not in FILE_TOOLS or not cfg.hook_option("post_write", True):
        return 0
    tool_input = data.get("tool_input") or {}
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    cwd = str(data.get("cwd") or os.getcwd())
    if not path:
        return 0
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    if not os.path.isfile(path) or not _in_scope(path, cfg):
        return 0
    findings = check_paths([path], cfg, cwd=cwd).findings
    if not findings:
        return 0
    errors = [f for f in findings if f.severity == ERROR]
    shown = findings[0].path
    msg = (
        "agency-guardrails found %d issue%s in %s:\n%s\n"
        "Fix them now. If a finding is wrong, add a comment with `guardrails-ignore: <RULE-ID> <reason>` on that line."
        % (len(findings), "" if len(findings) == 1 else "s", shown, output.for_agent(findings, _limit(cfg)))
    )
    if errors:
        _emit(stdout, {"decision": "block", "reason": msg})
    else:
        _emit(stdout, {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}})
    return 0


def changed_files(cwd: str) -> Optional[List[str]]:
    """Files modified, added or untracked in the git work tree at ``cwd`` (None outside git)."""
    try:
        top = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5, check=False
        )
        if top.returncode != 0:
            return None
        root = top.stdout.strip()
        status = subprocess.run(
            ["git", "-C", root, "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if status.returncode != 0:
        return None
    entries = status.stdout.split("\0")
    out = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1  # the next entry is the original name
        if "D" in code:
            continue
        full = os.path.join(root, path)
        if os.path.isfile(full):
            out.append(full)
    return sorted(out)


def stop(data: Dict[str, Any], cfg: Config, stdout: IO[str]) -> int:
    if data.get("stop_hook_active") or not cfg.hook_option("stop_check", True):
        return 0
    cwd = str(data.get("cwd") or os.getcwd())
    files = changed_files(cwd)
    if not files:
        return 0
    files = [f for f in files if _in_scope(f, cfg)]
    if not files:
        return 0
    findings = [f for f in check_paths(files, cfg, cwd=cwd).findings if f.severity == ERROR]
    if not findings:
        return 0
    msg = (
        "agency-guardrails: %d error%s in files changed this session. Fix them before finishing:\n%s"
        % (len(findings), "" if len(findings) == 1 else "s", output.for_agent(findings, _limit(cfg)))
    )
    _emit(stdout, {"decision": "block", "reason": msg})
    return 0


HANDLERS = {"pre-tool-use": pre_tool_use, "post-tool-use": post_tool_use, "stop": stop}


def run(event: str, stdin: IO[str], stdout: IO[str], stderr: IO[str], config_path: Optional[str] = None) -> int:
    if event not in HANDLERS:
        stderr.write("agency-guardrails: unknown hook event %r (use one of %s)\n" % (event, ", ".join(EVENTS)))
        return 1
    try:
        raw = stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        stderr.write("agency-guardrails: hook input is not JSON; skipping\n")
        return 1
    if not isinstance(data, dict):
        return 1
    cwd = str(data.get("cwd") or os.getcwd())
    try:
        cfg = load(config_path or os.environ.get("GUARDRAILS_CONFIG"), start=cwd)
    except ConfigError as exc:
        stderr.write("agency-guardrails: config error: %s\n" % exc)
        return 1
    try:
        return HANDLERS[event](data, cfg, stdout)
    except Exception as exc:  # fail open: never wedge the session on a bug
        stderr.write("agency-guardrails: hook error (%s): %s\n" % (type(exc).__name__, exc))
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write("usage: guardrails hook {%s}\n" % ",".join(EVENTS))
        return 1
    return run(argv[0], sys.stdin, sys.stdout, sys.stderr)
