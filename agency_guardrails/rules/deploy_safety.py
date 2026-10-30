"""deploy-safety: keep agents from changing production directly.

These are *action* rules: they read a tool call before it runs (the Claude
Code PreToolUse payload) and block writes to protected hosts, paths and
branches, telling the agent to open a pull request instead. Reads (cat, ls,
grep, diff, downloading with scp) pass.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from agency_guardrails.config import match_any
from agency_guardrails.model import ACTION, ERROR, Action, Finding, Rule, RuleContext
from agency_guardrails.registry import register

PACK = "deploy-safety"

WRITE = re.compile(
    r"\b(scp|rsync|sftp|tee|install|patch|unzip|truncate|dd|wget|curl\s+[^|]*-[oO])\b"
    r"|\bsed\s+(-\w+\s+)*-i|\bperl\s+(-\w+\s+)*-i"
    r"|\b(cp|mv|rm|ln|touch|mkdir|rmdir|chmod|chown)\s"
    r"|\bgit\s+(apply|checkout|reset|pull|merge|stash|clean)\b|\btar\s+-?\w*x"
    r"|\bwp\s+(plugin|theme|core|option|post|db)\s+(install|update|delete|activate|deactivate|import|reset|set|create)\b"
    r"|\bfile_put_contents\b|\bunlink\s*\("
    r"|(?<![0-9&<-])>>?(?!\s*(/dev/null|&))"
)

_WRAPPERS = {"sudo", "time", "nice", "nohup", "command", "env", "exec"}
_SSH_VALUE_OPTS = set("bcDEeFIiJLlmOopQRSWw")
_SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")", ";;"}

SHARED_OPTIONS = {
    "override": ("GUARDRAILS_OVERRIDE=1", "Token that lets an emergency command through. Empty disables overrides."),
    "instead": (
        "Make the change on a branch and open a pull request; let the reviewed merge deploy it.",
        "What the agent is told to do instead.",
    ),
}


def _segments(command: str) -> List[List[str]]:
    """Split a shell command into simple-command token lists, respecting quotes."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: List[List[str]] = [[]]
    try:
        for tok in lexer:
            if tok in _SEPARATORS:
                segments.append([])
            else:
                segments[-1].append(tok)
    except ValueError:  # unbalanced quotes: fall back to a naive split
        segments = [part.split() for part in re.split(r"&&|\|\||[;|\n]", command)]
    return [s for s in segments if s]


def _strip_wrappers(tokens: List[str]) -> List[str]:
    i = 0
    while i < len(tokens) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]) or tokens[i] in _WRAPPERS):
        i += 1
    return tokens[i:]


def _host_regex(hosts: Iterable[str]) -> Optional[re.Pattern]:
    hosts = [h.strip() for h in hosts if h.strip()]
    if not hosts:
        return None
    return re.compile(r"(?<![\w.-])(?:%s)(?![\w-])" % "|".join(re.escape(h) for h in hosts), re.I)


def _norm_paths(paths: Iterable[str]) -> List[str]:
    return [p.rstrip("/") for p in paths if p.strip()]


def _mentions(text: str, host_rx: Optional[re.Pattern], paths: List[str]) -> bool:
    return bool((host_rx and host_rx.search(text)) or any(p and p in text for p in paths))


def _message(ctx: RuleContext, what: str) -> str:
    msg = "BLOCKED: %s. %s" % (what, ctx.option("instead"))
    token = ctx.option("override")
    if token:
        msg += " Emergency only: put %s in the command and record what changed." % token
    return msg


def _overridden(action: Action, ctx: RuleContext) -> bool:
    token = ctx.option("override")
    return bool(token) and token in action.command


@register
class DirectRemoteWrite(Rule):
    id = "GR-DEP-001"
    title = "Direct write to a protected host or path"
    pack = PACK
    kind = ACTION
    severity = ERROR
    applies_to = ("Bash",)
    rationale = (
        "An agent that can reach a production server will eventually fix something there directly: an scp of "
        "one file, a sed -i over ssh. The change skips review, the repository drifts from what is live, and the "
        "next deploy silently reverts it. Changes to protected targets go through a pull request."
    )
    fix = "Change the source in the repository on a branch, open a pull request and let the merge deploy it."
    citation = "https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final"
    options = dict(
        SHARED_OPTIONS,
        protected_hosts=([], "Hostnames (or ssh aliases) that only a reviewed deploy may write to."),
        protected_paths=([], "Absolute paths (remote docroots or local mounts) that only a deploy may write to."),
    )

    def check_action(self, action: Action, ctx: RuleContext) -> Iterable[Finding]:
        if action.tool_name != "Bash" or not action.command.strip():
            return
        host_rx = _host_regex(ctx.option("protected_hosts"))
        paths = _norm_paths(ctx.option("protected_paths"))
        if not (host_rx or paths) or not _mentions(action.command, host_rx, paths) or _overridden(action, ctx):
            return
        for seg in _segments(action.command):
            tokens = _strip_wrappers(seg)
            if not tokens:
                continue
            reason = self._segment_reason(tokens, host_rx, paths)
            if reason:
                yield self.action_finding(_message(ctx, reason), " ".join(tokens)[:200])
                return

    @staticmethod
    def _segment_reason(tokens: List[str], host_rx: Optional[re.Pattern], paths: List[str]) -> Optional[str]:
        prog = os.path.basename(tokens[0])
        args = tokens[1:]
        if prog in ("scp", "rsync", "sftp"):
            positional = [a for a in args if not a.startswith("-")]
            if prog == "sftp":
                return "sftp session to a protected target" if _mentions(" ".join(args), host_rx, paths) else None
            if positional and _mentions(positional[-1], host_rx, paths):
                return "%s copies files onto a protected target (%s)" % (prog, positional[-1])
            return None
        if prog in ("ssh", "mosh"):
            i = 0
            while i < len(args) and args[i].startswith("-"):
                flag = args[i]
                i += 2 if (len(flag) == 2 and flag[1] in _SSH_VALUE_OPTS) else 1
            if i >= len(args):
                return None
            host = args[i]
            remote: List[str] = []
            for tok in args[i + 1 :]:
                if tok in (">", ">>", "<"):
                    break
                remote.append(tok)
            remote_cmd = " ".join(remote)
            if host_rx and host_rx.search(host) and WRITE.search(remote_cmd):
                return "remote command changes files on protected host %s" % host
            if any(p in remote_cmd for p in paths) and WRITE.search(remote_cmd):
                return "remote command changes a protected path"
            return None
        joined = " ".join(tokens)
        for j, tok in enumerate(tokens):
            if tok in (">", ">>") and j + 1 < len(tokens) and _mentions(tokens[j + 1], host_rx, paths):
                return "redirect writes into a protected path (%s)" % tokens[j + 1]
        if _mentions(joined, host_rx, paths) and WRITE.search(joined.replace(">", "")):
            return "%s changes a protected path" % prog
        return None


def _under(path: str, roots: List[str]) -> bool:
    p = os.path.normpath(path)
    for r in roots:
        r = os.path.normpath(r)
        if p == r or p.startswith(r.rstrip(os.sep) + os.sep):
            return True
    return False


@register
class ProtectedFileEdit(Rule):
    id = "GR-DEP-002"
    title = "Edit to a protected file"
    pack = PACK
    kind = ACTION
    severity = ERROR
    applies_to = ("Write", "Edit", "MultiEdit", "NotebookEdit")
    rationale = (
        "Some files must never be edited by hand: a mounted production docroot, generated bundles, vendored "
        "code, deploy workflows. An agent editing them directly bypasses the pipeline that owns them."
    )
    fix = "Edit the source the file is built or deployed from, on a branch, and open a pull request."
    citation = "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches"
    options = dict(
        SHARED_OPTIONS,
        protected_paths=([], "Absolute paths that only a deploy may write to."),
        protected_globs=([], "Globs, relative to the config file, for files agents must not edit."),
    )

    def check_action(self, action: Action, ctx: RuleContext) -> Iterable[Finding]:
        if action.tool_name not in self.applies_to or not action.file_path:
            return
        target = action.file_path
        if not os.path.isabs(target):
            target = os.path.join(action.cwd or ".", target)
        roots = _norm_paths(ctx.option("protected_paths"))
        globs = ctx.option("protected_globs")
        rel = Path(os.path.relpath(os.path.realpath(target), os.path.realpath(ctx.root))).as_posix()
        if _under(target, roots) or (globs and not rel.startswith("..") and match_any(rel, globs)):
            yield self.action_finding(
                "BLOCKED: %s %s is a protected file. %s" % (action.tool_name, rel if not rel.startswith("..") else target,
                                                           ctx.option("instead")),
                target,
            )


def _current_branch(cwd: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", cwd or ".", "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = out.stdout.strip()
    return branch if out.returncode == 0 and branch else None


def push_targets(args: List[str], cwd: str) -> Tuple[List[str], bool]:
    """Return (target branches, forced) for the arguments after ``git push``."""
    forced = False
    positional = []
    all_refs = False
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in ("-f", "--force") or a.startswith("--force-with-lease") or a == "--force-if-includes":
            forced = True
        elif a in ("--all", "--mirror", "--branches"):
            all_refs = True
        elif a in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            skip = True
        elif a.startswith("-"):
            continue
        else:
            positional.append(a)
    refspecs = positional[1:]
    branches = []
    for spec in refspecs:
        if spec.startswith("+"):
            forced = True
            spec = spec[1:]
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if dst in ("HEAD", "@", ""):
            dst = _current_branch(cwd) or ""
        dst = re.sub(r"^refs/heads/", "", dst)
        if dst:
            branches.append(dst)
    if all_refs:
        branches.append("*")
    elif not refspecs:
        current = _current_branch(cwd)
        if current:
            branches.append(current)
    return branches, forced


@register
class PushToProtectedBranch(Rule):
    id = "GR-DEP-003"
    title = "Push straight to a protected branch"
    pack = PACK
    kind = ACTION
    severity = ERROR
    applies_to = ("Bash",)
    rationale = (
        "Force pushing rewrites shared history, and pushing directly to the deploy branch skips review. "
        "When the merge to main is what deploys, an agent's direct push is a production change nobody reviewed."
    )
    fix = "Push a feature branch and open a pull request; never force push a protected branch."
    citation = "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches"
    options = dict(
        SHARED_OPTIONS,
        protected_branches=(["main", "master", "production"], "Branches only a reviewed merge may update."),
        block_direct_push=(False, "Also block non-force pushes to protected branches."),
    )

    def check_action(self, action: Action, ctx: RuleContext) -> Iterable[Finding]:
        if action.tool_name != "Bash" or "push" not in action.command or _overridden(action, ctx):
            return
        protected = set(ctx.option("protected_branches"))
        for seg in _segments(action.command):
            tokens = _strip_wrappers(seg)
            if len(tokens) < 2 or os.path.basename(tokens[0]) != "git":
                continue
            rest = tokens[1:]
            while rest and rest[0] in ("-C", "-c") and len(rest) > 1:
                rest = rest[2:]
            if not rest or rest[0] != "push":
                continue
            branches, forced = push_targets(rest[1:], action.cwd)
            hit = [b for b in branches if b in protected or b == "*"]
            if not hit:
                continue
            name = ", ".join(sorted(set(hit))).replace("*", "every branch")
            if forced:
                yield self.action_finding(_message(ctx, "force push to protected branch %s" % name), " ".join(tokens))
                return
            if ctx.option("block_direct_push"):
                yield self.action_finding(_message(ctx, "direct push to protected branch %s" % name), " ".join(tokens))
                return
