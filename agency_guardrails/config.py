"""Configuration: discovery, loading and validation of ``guardrails.toml``."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agency_guardrails import _toml
from agency_guardrails import registry
from agency_guardrails.model import SEVERITIES

CONFIG_NAMES = ("guardrails.toml", ".guardrails.toml", "guardrails.json")

DEFAULT_EXCLUDE = [
    ".git/**",
    "**/.git/**",
    "**/node_modules/**",
    "**/.venv/**",
    "**/venv/**",
    "**/__pycache__/**",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "**/*.lock",
    "**/package-lock.json",
]

FAIL_ON = ("error", "warn", "never")


class ConfigError(ValueError):
    pass


def match_path(path: str, pattern: str) -> bool:
    """Glob match on a POSIX relative path.

    ``*`` crosses directory separators (as in :mod:`fnmatch`), and a leading
    ``**/`` also matches at the top level, so ``**/*.md`` matches ``a.md``.
    """
    path = path.replace(os.sep, "/")
    while path.startswith("./"):
        path = path[2:]
    if fnmatchcase(path, pattern):
        return True
    if pattern.startswith("**/") and fnmatchcase(path, pattern[3:]):
        return True
    if pattern.endswith("/**") and path == pattern[:-3]:
        return True
    return False


def match_any(path: str, patterns: Iterable[str]) -> bool:
    return any(match_path(path, p) for p in patterns)


def match_rule(rule_id: str, patterns: Iterable[str]) -> bool:
    rid = rule_id.upper()
    for p in patterns:
        p = p.strip().upper()
        if p in ("*", "ALL") or fnmatchcase(rid, p):
            return True
    return False


@dataclass
class Ignore:
    path: str
    rules: List[str]


@dataclass
class Config:
    root: Path = field(default_factory=lambda: Path.cwd())
    source: Optional[Path] = None
    packs: Optional[List[str]] = None  # None means every pack
    enable: List[str] = field(default_factory=list)
    disable: List[str] = field(default_factory=list)
    include: List[str] = field(default_factory=lambda: ["**/*"])
    exclude: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    ignores: List[Ignore] = field(default_factory=list)
    fail_on: str = "error"
    pack_options: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rule_options: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hooks: Dict[str, Any] = field(default_factory=dict)

    # rule selection ------------------------------------------------------
    def is_enabled(self, rule_id: str) -> bool:
        rule = registry.get(rule_id)
        if match_rule(rule.id, self.enable):
            return True
        if match_rule(rule.id, self.disable):
            return False
        return self.packs is None or rule.pack in self.packs

    def enabled_rules(self, kind: Optional[str] = None) -> list:
        return [
            r for r in registry.all_rules() if self.is_enabled(r.id) and (kind is None or r.kind == kind)
        ]

    def severity_for(self, rule_id: str, default: str) -> str:
        return str(self.rule_options.get(rule_id, {}).get("severity", default))

    def is_ignored(self, rel_path: str, rule_id: str) -> bool:
        for ig in self.ignores:
            if match_path(rel_path, ig.path) and match_rule(rule_id, ig.rules):
                return True
        return False

    def relpath(self, path: str) -> str:
        """Path relative to the config root, POSIX style, for glob matching."""
        try:
            rel = os.path.relpath(os.path.realpath(path), os.path.realpath(str(self.root)))
        except ValueError:  # different drive on Windows
            return Path(path).as_posix()
        return Path(rel).as_posix()

    def hook_option(self, name: str, default: Any) -> Any:
        return self.hooks.get(name, default)


# loading -------------------------------------------------------------------

_TOP_KEYS = {"packs", "enable", "disable", "include", "exclude", "extend_exclude", "ignore", "fail_on"}
_HOOK_KEYS = {"pre_write_packs", "post_write", "stop_check", "max_findings"}


def find_config(start: str) -> Optional[Path]:
    """Walk up from ``start`` (a file or directory) to the first config file."""
    here = Path(start).resolve()
    if here.is_file():
        here = here.parent
    for directory in [here] + list(here.parents):
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _read(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix == ".json":
            return json.loads(text)
        return _toml.loads(text)
    except (ValueError, _toml.TOMLError) as exc:
        raise ConfigError("%s: %s" % (path, exc)) from None


def _str_list(value: Any, where: str) -> List[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError("%s must be a list of strings" % where)
    return list(value)


def from_dict(data: Dict[str, Any], root: Path, source: Optional[Path] = None) -> Config:
    cfg = Config(root=root, source=source)
    known_packs = set(registry.packs())
    known_ids = {r.id for r in registry.all_rules()}

    top = data.get("guardrails", {})
    if not isinstance(top, dict):
        raise ConfigError("[guardrails] must be a table")
    unknown = set(top) - _TOP_KEYS
    if unknown:
        raise ConfigError("unknown key(s) in [guardrails]: %s" % ", ".join(sorted(unknown)))

    if "packs" in top:
        cfg.packs = _str_list(top["packs"], "guardrails.packs")
        bad = [p for p in cfg.packs if p not in known_packs]
        if bad:
            raise ConfigError(
                "unknown pack(s): %s (known: %s)" % (", ".join(bad), ", ".join(sorted(known_packs)))
            )
    for key in ("enable", "disable"):
        if key in top:
            values = _str_list(top[key], "guardrails." + key)
            for v in values:
                if not any(match_rule(rid, [v]) for rid in known_ids):
                    raise ConfigError("guardrails.%s: %s matches no rule" % (key, v))
            setattr(cfg, key, values)
    if "include" in top:
        cfg.include = _str_list(top["include"], "guardrails.include")
    if "exclude" in top:
        cfg.exclude = _str_list(top["exclude"], "guardrails.exclude")
    if "extend_exclude" in top:
        cfg.exclude = cfg.exclude + _str_list(top["extend_exclude"], "guardrails.extend_exclude")
    if "fail_on" in top:
        if top["fail_on"] not in FAIL_ON:
            raise ConfigError("guardrails.fail_on must be one of %s" % ", ".join(FAIL_ON))
        cfg.fail_on = top["fail_on"]
    for item in top.get("ignore", []):
        if not isinstance(item, dict) or "path" not in item:
            raise ConfigError("each [[guardrails.ignore]] needs a path")
        cfg.ignores.append(Ignore(str(item["path"]), _str_list(item.get("rules", ["*"]), "ignore.rules")))

    for pack in known_packs:
        if pack in data:
            table = data[pack]
            if not isinstance(table, dict):
                raise ConfigError("[%s] must be a table" % pack)
            allowed = set()
            for rule in registry.rules_in_pack(pack):
                allowed.update(rule.options)
            unknown = set(table) - allowed
            if unknown:
                raise ConfigError(
                    "unknown option(s) in [%s]: %s (known: %s)"
                    % (pack, ", ".join(sorted(unknown)), ", ".join(sorted(allowed)) or "none")
                )
            cfg.pack_options[pack] = dict(table)

    rules_table = data.get("rules", {})
    if not isinstance(rules_table, dict):
        raise ConfigError("[rules] must be a table")
    for rid, table in rules_table.items():
        rid_u = rid.upper()
        if rid_u not in known_ids:
            raise ConfigError("[rules.%s]: unknown rule" % rid)
        if not isinstance(table, dict):
            raise ConfigError("[rules.%s] must be a table" % rid)
        allowed = set(registry.get(rid_u).options) | {"severity"}
        unknown = set(table) - allowed
        if unknown:
            raise ConfigError("unknown option(s) in [rules.%s]: %s" % (rid, ", ".join(sorted(unknown))))
        if "severity" in table and table["severity"] not in SEVERITIES:
            raise ConfigError("[rules.%s] severity must be error or warn" % rid)
        cfg.rule_options[rid_u] = dict(table)

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ConfigError("[hooks] must be a table")
    unknown = set(hooks) - _HOOK_KEYS
    if unknown:
        raise ConfigError("unknown key(s) in [hooks]: %s" % ", ".join(sorted(unknown)))
    cfg.hooks = dict(hooks)

    allowed_top = {"guardrails", "rules", "hooks"} | known_packs
    stray = set(data) - allowed_top
    if stray:
        raise ConfigError("unknown table(s): %s" % ", ".join(sorted(stray)))
    return cfg


def load(path: Optional[str] = None, start: str = ".") -> Config:
    """Load an explicit config file, or discover one walking up from ``start``.

    With no config file anywhere, every pack runs with its defaults and the
    root is ``start`` (or its directory).
    """
    found = Path(path) if path else find_config(start)
    if found is None:
        base = Path(start).resolve()
        return Config(root=base.parent if base.is_file() else base)
    if not found.is_file():
        raise ConfigError("config file not found: %s" % found)
    return from_dict(_read(found), root=found.resolve().parent, source=found)
