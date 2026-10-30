import unittest

from agency_guardrails import registry
from agency_guardrails.config import from_dict
from agency_guardrails.document import Document
from agency_guardrails.engine import InlineIgnores, check_document, check_paths, discover, failed
from agency_guardrails.model import ERROR, WARN, Finding, Rule

from tests.helpers import temp_tree


class _Shout(Rule):
    """Test-only rule: flags the word SHOUT."""

    id = "GR-TST-100"
    title = "No shouting"
    pack = "test-pack"
    severity = ERROR
    rationale = "test"
    fix = "whisper"
    citation = "https://example.org/shout"

    def check(self, doc, ctx):
        idx = doc.text.find("SHOUT")
        while idx != -1:
            yield self.finding(doc, idx, "shouting", "SHOUT")
            idx = doc.text.find("SHOUT", idx + 1)


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        registry.all_rules()
        registry.register(_Shout)

    @classmethod
    def tearDownClass(cls):
        registry._RULES.pop("GR-TST-100", None)

    def cfg(self, data=None, root="."):
        from pathlib import Path

        return from_dict(data or {"guardrails": {"packs": ["test-pack"]}}, root=Path(root).resolve())

    def test_inline_ignore_same_and_next_line(self):
        text = "SHOUT <!-- guardrails-ignore: GR-TST-100 -->\nSHOUT\nSHOUT\n"
        findings = check_document(Document("a.md", text), self.cfg())
        self.assertEqual([f.line for f in findings], [3])

    def test_inline_ignore_file(self):
        text = "<!-- guardrails-ignore-file: GR-TST-* -->\nSHOUT\n"
        self.assertEqual(check_document(Document("a.md", text), self.cfg()), [])

    def test_inline_ignore_other_rule_does_not_apply(self):
        text = "SHOUT <!-- guardrails-ignore: GR-EU-001 -->\n"
        self.assertEqual(len(check_document(Document("a.md", text), self.cfg())), 1)

    def test_scan_ids(self):
        ig = InlineIgnores.scan("x # guardrails-ignore: GR-A-1, GR-B-2 because reasons\n")
        self.assertEqual(ig.lines[1], ["GR-A-1", "GR-B-2"])

    def test_path_ignores_disable_and_severity(self):
        data = {
            "guardrails": {"packs": ["test-pack"], "ignore": [{"path": "legal/**", "rules": ["GR-TST-100"]}]},
            "rules": {"GR-TST-100": {"severity": "warn"}},
        }
        with temp_tree({"legal/terms.md": "SHOUT\n", "blog/post.md": "SHOUT\n", "img.png": "\0\0"}) as root:
            cfg = self.cfg(data, root)
            result = check_paths(["."], cfg, cwd=str(root))
            self.assertEqual([f.path for f in result.findings], ["blog/post.md"])
            self.assertEqual(result.findings[0].severity, WARN)
            cfg2 = self.cfg({"guardrails": {"packs": ["test-pack"], "disable": ["GR-TST-100"]}}, root)
            self.assertEqual(check_paths(["."], cfg2).findings, [])

    def test_discover_excludes(self):
        files = {"a.md": "", "node_modules/x/b.md": "", ".git/c.md": "", "drafts/d.md": "", "e.md": ""}
        with temp_tree(files) as root:
            cfg = self.cfg({"guardrails": {"extend_exclude": ["drafts/**"]}}, root)
            self.assertEqual(sorted(discover(["."], cfg)), ["a.md", "e.md"])
            self.assertEqual(discover(["drafts/d.md"], self.cfg({}, root)), ["drafts/d.md"])

    def test_failed(self):
        w = Finding("GR-X-1", WARN, "m")
        e = Finding("GR-X-1", ERROR, "m")
        self.assertFalse(failed([w], "error"))
        self.assertTrue(failed([w], "warn"))
        self.assertTrue(failed([e], "error"))
        self.assertFalse(failed([e], "never"))


if __name__ == "__main__":
    unittest.main()
