"""The ``guardrails`` command line."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from agency_guardrails import __version__, catalog, output, registry
from agency_guardrails.config import FAIL_ON, ConfigError, load
from agency_guardrails.engine import check_paths, failed
from agency_guardrails.redact import redact
from agency_guardrails.starter import STARTER_CONFIG, STARTER_CONSENT

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _use_color(stream, flag: Optional[bool]) -> bool:
    if flag is not None:
        return flag
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _write(path: Optional[str], text: str) -> None:
    if path in (None, "-"):
        sys.stdout.write(text)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def cmd_check(args: argparse.Namespace) -> int:
    paths = args.paths or ["."]
    try:
        cfg = load(args.config, start=paths[0])
    except ConfigError as exc:
        sys.stderr.write("guardrails: config error: %s\n" % exc)
        return EXIT_USAGE
    if args.pack:
        unknown = [p for p in args.pack if p not in registry.packs()]
        if unknown:
            sys.stderr.write("guardrails: unknown pack: %s (known: %s)\n" % (", ".join(unknown), ", ".join(registry.packs())))
            return EXIT_USAGE
        cfg.packs = list(args.pack)
        cfg.enable = []
    try:
        result = check_paths(paths, cfg)
    except FileNotFoundError as exc:
        sys.stderr.write("guardrails: no such file or directory: %s\n" % exc)
        return EXIT_USAGE
    findings = result.findings
    rules = cfg.enabled_rules()
    if args.format == "sarif":
        _write(args.output, output.render_sarif(findings, rules))
    elif args.format == "text":
        stream_is_stdout = args.output in (None, "-")
        color = _use_color(sys.stdout, args.color) if stream_is_stdout else False
        _write(args.output, output.render_text(findings, result.files_checked, color=color))
    else:
        _write(args.output, output.FORMATS[args.format](findings, result.files_checked))
    if args.sarif_file:
        _write(args.sarif_file, output.render_sarif(findings, rules))
    fail_on = args.fail_on or cfg.fail_on
    return EXIT_FINDINGS if failed(findings, fail_on) else EXIT_OK


def cmd_rules(args: argparse.Namespace) -> int:
    rules = registry.all_rules()
    if args.pack:
        rules = [r for r in rules if r.pack in args.pack]
    if args.format == "json":
        sys.stdout.write(catalog.rules_json(rules))
    elif args.format == "markdown":
        sys.stdout.write(catalog.rules_markdown(rules))
    else:
        sys.stdout.write(catalog.rules_text(rules))
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    try:
        rule = registry.get(args.rule_id)
    except KeyError:
        sys.stderr.write("guardrails: unknown rule %s (see `guardrails rules`)\n" % args.rule_id)
        return EXIT_USAGE
    sys.stdout.write(catalog.explain(rule))
    return EXIT_OK


def cmd_init(args: argparse.Namespace) -> int:
    target = os.path.join(args.dir, "guardrails.toml")
    if os.path.exists(target) and not args.force:
        sys.stderr.write("guardrails: %s already exists (use --force to overwrite)\n" % target)
        return EXIT_USAGE
    os.makedirs(args.dir, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(STARTER_CONFIG)
    written = [target]
    consent = os.path.join(args.dir, "consent", "approved.txt")
    if not args.no_consent and not os.path.exists(consent):
        os.makedirs(os.path.dirname(consent), exist_ok=True)
        with open(consent, "w", encoding="utf-8") as fh:
            fh.write(STARTER_CONSENT)
        written.append(consent)
    for path in written:
        sys.stdout.write("wrote %s\n" % path)
    sys.stdout.write("next: edit watch_names and protected_hosts, then run `guardrails check .`\n")
    return EXIT_OK


def cmd_redact(args: argparse.Namespace) -> int:
    text = sys.stdin.read()
    clean, hits = redact(text, generic=not args.no_generic)
    sys.stdout.write(clean)
    if args.report:
        counts = {}
        for h in hits:
            counts[h.kind] = counts.get(h.kind, 0) + 1
        for kind in sorted(counts):
            sys.stderr.write("redacted %d %s\n" % (counts[kind], kind))
    if args.check and hits:
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_hook(args: argparse.Namespace) -> int:
    from agency_guardrails import hooks

    return hooks.run(args.event, sys.stdin, sys.stdout, sys.stderr, config_path=args.config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guardrails",
        description="Lint your marketing like you lint your code: business, legal and house-style rules "
        "for content written and shipped by AI agents.",
        epilog="Engineering tooling, not legal advice. Docs: https://github.com/chris-fountoulis/agency-guardrails",
    )
    parser.add_argument("--version", action="version", version="guardrails %s" % __version__)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("check", help="check files and directories")
    p.add_argument("paths", nargs="*", help="files or directories (default: .)")
    p.add_argument("-c", "--config", help="path to guardrails.toml (default: discovered from the first path)")
    p.add_argument("-f", "--format", choices=["text", "json", "sarif", "github"], default="text")
    p.add_argument("-o", "--output", help="write the report to a file instead of stdout")
    p.add_argument("--sarif-file", help="also write a SARIF report to this file")
    p.add_argument("--fail-on", choices=FAIL_ON, help="lowest severity that fails the run (default: config, else error)")
    p.add_argument("--pack", action="append", help="only run this pack (repeatable)")
    color = p.add_mutually_exclusive_group()
    color.add_argument("--color", dest="color", action="store_true", default=None)
    color.add_argument("--no-color", dest="color", action="store_false")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("rules", help="list every rule with its citation")
    p.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    p.add_argument("--pack", action="append", help="only this pack (repeatable)")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("explain", help="explain one rule: why, fix, source and options")
    p.add_argument("rule_id", metavar="RULE", help="rule id, for example GR-EU-001")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("init", help="write a starter guardrails.toml and consent registry")
    p.add_argument("--dir", default=".", help="directory to write into (default: .)")
    p.add_argument("--force", action="store_true", help="overwrite an existing guardrails.toml")
    p.add_argument("--no-consent", action="store_true", help="do not create consent/approved.txt")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("redact", help="redact credentials from stdin to stdout")
    p.add_argument("--report", action="store_true", help="print what was redacted to stderr")
    p.add_argument("--check", action="store_true", help="exit 1 if anything was redacted")
    p.add_argument("--no-generic", action="store_true", help="only redact known token shapes and private keys")
    p.set_defaults(func=cmd_redact)

    p = sub.add_parser("hook", help="run as a Claude Code hook (reads the hook JSON on stdin)")
    p.add_argument("event", choices=["pre-tool-use", "post-tool-use", "stop"])
    p.add_argument("-c", "--config", help="path to guardrails.toml (default: discovered from the hook cwd)")
    p.set_defaults(func=cmd_hook)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except BrokenPipeError:  # pragma: no cover - e.g. piping into head
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
