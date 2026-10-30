import json
import unittest

from agency_guardrails import output, registry
from agency_guardrails.model import Finding

F = [
    Finding("GR-EU-001", "error", "free, with fee", "site/a.md", 3, 7, "free", "Say what is covered."),
    Finding("GR-SEO-001", "warn", "thin: 50%, ok", "site/a.md", 9, 1),
    Finding("GR-STY-001", "error", "dash", "site/b.html", 1, 2),
]


class OutputTest(unittest.TestCase):
    def test_text(self):
        out = output.render_text(F, files_checked=2)
        self.assertIn("site/a.md\n  3:7      error  GR-EU-001   free, with fee\n", out)
        self.assertIn("  9:1      warn   GR-SEO-001", out)
        self.assertTrue(out.endswith("2 files checked, 2 errors, 1 warning\n"))
        self.assertEqual(output.render_text([], 1), "1 file checked, 0 errors, 0 warnings\n")
        self.assertIn("\033[31m", output.render_text(F, color=True))

    def test_json(self):
        data = json.loads(output.render_json(F, 2))
        self.assertEqual(data["summary"], {"files_checked": 2, "errors": 2, "warnings": 1})
        self.assertEqual(data["findings"][0]["rule"], "GR-EU-001")

    def test_sarif(self):
        data = json.loads(output.render_sarif(F))
        self.assertEqual(data["version"], "2.1.0")
        run = data["runs"][0]
        rules = run["tool"]["driver"]["rules"]
        self.assertEqual(len(rules), len(registry.all_rules()))
        res = run["results"][0]
        self.assertEqual(rules[res["ruleIndex"]]["id"], "GR-EU-001")
        self.assertEqual(res["level"], "error")
        self.assertEqual(run["results"][1]["level"], "warning")
        region = res["locations"][0]["physicalLocation"]["region"]
        self.assertEqual((region["startLine"], region["startColumn"]), (3, 7))
        self.assertTrue(rules[0]["helpUri"].startswith("https://"))

    def test_sarif_with_subset_of_rules(self):
        data = json.loads(output.render_sarif(F[:1], rules=[]))
        self.assertEqual([r["id"] for r in data["runs"][0]["tool"]["driver"]["rules"]], ["GR-EU-001"])

    def test_github_annotations_escape(self):
        out = output.render_github(F)
        first, second = out.splitlines()[:2]
        self.assertTrue(first.startswith("::error file=site/a.md,line=3,col=7,title=GR-EU-001 Conditional 'free' claim::"))
        self.assertTrue(second.endswith("::thin: 50%25, ok"), second)

    def test_for_agent(self):
        text = output.for_agent(F, limit=2)
        self.assertIn("- site/a.md:3:7 GR-EU-001 (error): free, with fee\n  Fix: Say what is covered.", text)
        self.assertIn("and 1 more", text)


    def test_for_agent_orders_errors_and_dedupes_fixes(self):
        findings = [
            Finding("GR-SEO-001", "warn", "w", "a.md", 1, 1, fix="fix w"),
            Finding("GR-EU-002", "error", "e1", "a.md", 5, 1, fix="fix e"),
            Finding("GR-EU-002", "error", "e2", "a.md", 9, 1, fix="fix e"),
            Finding("GR-DEP-001", "error", "BLOCKED: no", fix="fix d"),
        ]
        lines = output.for_agent(findings).splitlines()
        self.assertTrue(lines[0].startswith("- GR-DEP-001 (error): BLOCKED"))
        self.assertEqual(lines[1], "- a.md:5:1 GR-EU-002 (error): e1")
        self.assertEqual(lines[2], "  Fix: fix e")
        self.assertEqual(lines[3], "- a.md:9:1 GR-EU-002 (error): e2")
        self.assertEqual(lines[4], "- a.md:1:1 GR-SEO-001 (warn): w")


if __name__ == "__main__":
    unittest.main()
