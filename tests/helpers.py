"""Shared test helpers."""

import contextlib
import os
import tempfile
from pathlib import Path

from agency_guardrails import config as config_mod
from agency_guardrails import registry
from agency_guardrails.document import Document
from agency_guardrails.engine import check_document


def make_config(data=None, root="."):
    return config_mod.from_dict(data or {}, root=Path(root).resolve())


def run_rule(rule_id, text, path="page.md", options=None, root="."):
    """Run one rule on text and return its findings."""
    rule = registry.get(rule_id)
    data = {"guardrails": {"enable": [rule_id], "packs": []}}
    if options:
        data["rules"] = {rule_id: options}
    cfg = make_config(data, root=root)
    return check_document(Document(path, text), cfg)


@contextlib.contextmanager
def temp_tree(files):
    """Create a temporary directory with {relative path: content} files."""
    with tempfile.TemporaryDirectory() as tmp:
        for rel, content in files.items():
            p = Path(tmp) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        old = os.getcwd()
        os.chdir(tmp)
        try:
            yield Path(tmp)
        finally:
            os.chdir(old)
