import io
import json
import os
import subprocess
import unittest

from agency_guardrails import hooks

from tests import fakes
from tests.helpers import temp_tree

EM = "\N{EM DASH}"
CONFIG = """
[guardrails]
extend_exclude = ["vendor/**"]

[deploy-safety]
protected_hosts = ["prod.example.com"]
protected_globs = ["dist/**"]
"""


def call(event, payload, raw=None):
    out, err = io.StringIO(), io.StringIO()
    stdin = io.StringIO(raw if raw is not None else json.dumps(payload))
    code = hooks.run(event, stdin, out, err)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None), err.getvalue()


class PreToolUseTest(unittest.TestCase):
    def test_blocks_risky_bash(self):
        with temp_tree({"guardrails.toml": CONFIG}) as root:
            payload = {
                "hook_event_name": "PreToolUse",
                "cwd": str(root),
                "tool_name": "Bash",
                "tool_input": {"command": "scp index.html deploy@prod.example.com:/var/www/"},
            }
            code, out, _ = call("pre-tool-use", payload)
            self.assertEqual(code, 0)
            hso = out["hookSpecificOutput"]
            self.assertEqual(hso["hookEventName"], "PreToolUse")
            self.assertEqual(hso["permissionDecision"], "deny")
            self.assertIn("GR-DEP-001", hso["permissionDecisionReason"])
            self.assertIn("pull request", hso["permissionDecisionReason"])

    def test_allows_safe_bash(self):
        with temp_tree({"guardrails.toml": CONFIG}) as root:
            payload = {"cwd": str(root), "tool_name": "Bash", "tool_input": {"command": "ls -la"}}
            self.assertEqual(call("pre-tool-use", payload), (0, None, ""))

    def test_blocks_secret_in_write_but_not_style(self):
        with temp_tree({"guardrails.toml": CONFIG}) as root:
            path = os.path.join(str(root), "notes.md")
            payload = {"cwd": str(root), "tool_name": "Write",
                       "tool_input": {"file_path": path, "content": "key %s\n" % fakes.anthropic()}}
            code, out, _ = call("pre-tool-use", payload)
            self.assertIn("GR-SEC-001", out["hookSpecificOutput"]["permissionDecisionReason"])
            payload["tool_input"]["content"] = "a %s b\n" % EM
            self.assertEqual(call("pre-tool-use", payload)[1], None)
            payload["tool_input"] = {"file_path": os.path.join(str(root), "dist", "x.js"), "content": "x"}
            self.assertIn("GR-DEP-002", call("pre-tool-use", payload)[1]["hookSpecificOutput"]["permissionDecisionReason"])

    def test_edit_new_string_is_checked(self):
        with temp_tree({"guardrails.toml": CONFIG}) as root:
            payload = {"cwd": str(root), "tool_name": "Edit",
                       "tool_input": {"file_path": os.path.join(str(root), "a.py"), "old_string": "x",
                                      "new_string": "TOKEN = '%s'" % fakes.github()}}
            self.assertEqual(call("pre-tool-use", payload)[1]["hookSpecificOutput"]["permissionDecision"], "deny")


class PostToolUseTest(unittest.TestCase):
    def test_errors_block_with_reason(self):
        files = {"guardrails.toml": CONFIG, "post.md": "# Title\n\nFast %s cheap.\n" % EM}
        with temp_tree(files) as root:
            payload = {"cwd": str(root), "tool_name": "Write",
                       "tool_input": {"file_path": os.path.join(str(root), "post.md")}}
            code, out, _ = call("post-tool-use", payload)
            self.assertEqual(out["decision"], "block")
            self.assertIn("post.md:3:6 GR-STY-001 (error)", out["reason"])
            self.assertIn("guardrails-ignore", out["reason"])

    def test_warnings_are_context(self):
        files = {"guardrails.toml": CONFIG, "post.md": "# Title\n\nShort.\n"}
        with temp_tree(files) as root:
            payload = {"cwd": str(root), "tool_name": "Edit", "tool_input": {"file_path": "post.md"}}
            _, out, _ = call("post-tool-use", payload)
            self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
            self.assertIn("GR-SEO-001", out["hookSpecificOutput"]["additionalContext"])

    def test_clean_excluded_and_other_tools(self):
        files = {"guardrails.toml": CONFIG, "ok.md": "fine\n", "vendor/x.md": "a %s b\n" % EM}
        with temp_tree(files) as root:
            for rel, tool in (("ok.md", "Write"), ("vendor/x.md", "Write"), ("vendor/x.md", "Read")):
                payload = {"cwd": str(root), "tool_name": tool, "tool_input": {"file_path": rel}}
                self.assertEqual(call("post-tool-use", payload)[1], None, rel)


@unittest.skipIf(subprocess.call(["git", "--version"], stdout=subprocess.DEVNULL) != 0, "git not installed")
class StopTest(unittest.TestCase):
    def test_blocks_on_changed_files_once(self):
        files = {"guardrails.toml": CONFIG, "clean.md": "fine\n"}
        with temp_tree(files) as root:
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            payload = {"cwd": str(root), "hook_event_name": "Stop", "stop_hook_active": False}
            self.assertEqual(call("stop", payload)[1], None)
            (root / "new.md").write_text("Bad %s dash\n" % EM)
            _, out, _ = call("stop", payload)
            self.assertEqual(out["decision"], "block")
            self.assertIn("new.md", out["reason"])
            payload["stop_hook_active"] = True
            self.assertEqual(call("stop", payload)[1], None)

    def test_outside_git_is_quiet(self):
        with temp_tree({"a.md": "x %s y\n" % EM}) as root:
            self.assertEqual(call("stop", {"cwd": str(root)})[1], None)


class RobustnessTest(unittest.TestCase):
    def test_bad_input_fails_open(self):
        code, out, err = call("pre-tool-use", None, raw="not json")
        self.assertEqual((code, out), (1, None))
        self.assertIn("not JSON", err)
        self.assertEqual(call("nope", {})[0], 1)

    def test_bad_config_fails_open(self):
        with temp_tree({"guardrails.toml": "[guardrails]\nbogus = 1\n"}) as root:
            code, out, err = call("pre-tool-use", {"cwd": str(root), "tool_name": "Bash", "tool_input": {}})
            self.assertEqual((code, out), (1, None))
            self.assertIn("config error", err)


if __name__ == "__main__":
    unittest.main()
