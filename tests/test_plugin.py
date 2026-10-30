import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PluginPackagingTest(unittest.TestCase):
    def test_manifest_matches_package_version(self):
        from agency_guardrails import __version__

        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "agency-guardrails")
        self.assertEqual(manifest["version"], __version__)
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(market["plugins"][0]["source"], "./")

    def test_hooks_json_shape(self):
        data = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        events = data["hooks"]
        self.assertEqual(sorted(events), ["PostToolUse", "PreToolUse", "Stop"])
        for event, groups in events.items():
            for group in groups:
                for hook in group["hooks"]:
                    self.assertEqual(hook["type"], "command")
                    self.assertIn('"${CLAUDE_PLUGIN_ROOT}/hooks/guardrails_hook.py"', hook["command"])
        self.assertIn("Bash", events["PreToolUse"][0]["matcher"])

    def test_hook_script_runs_without_install(self):
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(ROOT),
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        }
        env = dict(os.environ, PYTHONPATH="")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "guardrails_hook.py"), "pre-tool-use"],
            input=json.dumps(payload), capture_output=True, text=True, cwd="/", env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("GR-DEP-003", out["hookSpecificOutput"]["permissionDecisionReason"])


class GeneratedDocsTest(unittest.TestCase):
    def test_rules_md_is_current(self):
        from agency_guardrails.catalog import all_rules_markdown

        current = (ROOT / "docs" / "rules.md").read_text(encoding="utf-8")
        self.assertEqual(current, all_rules_markdown(), "run python scripts/gen_rules_doc.py")


if __name__ == "__main__":
    unittest.main()
