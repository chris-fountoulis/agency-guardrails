import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agency_guardrails.config import from_dict
from agency_guardrails.engine import check_action
from agency_guardrails.model import Action
from agency_guardrails.rules.deploy_safety import _segments

PACK = {
    "protected_hosts": ["prod.example.com", "prod-alias"],
    "protected_paths": ["/srv/www/acme/public_html"],
    "protected_globs": ["dist/**", ".github/workflows/*.yml"],
}


def cfg(extra=None, root="."):
    data = {"guardrails": {"packs": ["deploy-safety"]}, "deploy-safety": dict(PACK, **(extra or {}))}
    return from_dict(data, root=Path(root).resolve())


def bash(command, config=None, cwd="."):
    return check_action(Action("Bash", {"command": command}, cwd=cwd), config or cfg())


class DirectRemoteWriteTest(unittest.TestCase):
    def ids(self, command, config=None):
        return [f.rule_id for f in bash(command, config)]

    def test_blocks_writes(self):
        blocked = [
            "scp index.php deploy@prod.example.com:/srv/www/acme/public_html/",
            "rsync -avz build/ prod-alias:/srv/www/acme/public_html/",
            "ssh -p 2222 deploy@prod.example.com \"sed -i 's/a/b/' /srv/www/acme/public_html/x.php\"",
            "ssh prod.example.com 'rm -rf /tmp/cache'",
            "ssh prod-alias mkdir /srv/www/acme/public_html/new",
            "cp theme.css /srv/www/acme/public_html/theme.css",
            "echo hi > /srv/www/acme/public_html/test.txt",
            "cd /tmp && sudo tee /srv/www/acme/public_html/robots.txt < robots.txt",
            "sftp deploy@prod.example.com",
        ]
        for command in blocked:
            self.assertEqual(self.ids(command), ["GR-DEP-001"], command)

    def test_allows_reads(self):
        allowed = [
            "ssh prod.example.com 'cat /srv/www/acme/public_html/index.php'",
            "ssh prod.example.com ls -la /srv/www/acme/public_html 2>/dev/null",
            "scp prod.example.com:/srv/www/acme/public_html/wp-config.php ./backup/",
            "rsync -av prod-alias:/srv/www/acme/public_html/ ./mirror/",
            "ssh prod.example.com cat /srv/www/acme/public_html/x > local-copy.txt",
            "grep -r title /srv/www/acme/public_html",
            "scp index.php staging.example.com:/var/www/",
            "echo prod.example.community",
        ]
        for command in allowed:
            self.assertEqual(self.ids(command), [], command)

    def test_override_and_message(self):
        command = "scp a prod.example.com:/srv/www/acme/public_html/"
        findings = bash(command)
        self.assertIn("open a pull request", findings[0].message)
        self.assertIn("GUARDRAILS_OVERRIDE=1", findings[0].message)
        self.assertEqual(bash("GUARDRAILS_OVERRIDE=1 " + command), [])
        self.assertEqual(bash("GUARDRAILS_OVERRIDE=1 " + command, cfg({"override": ""}))[0].rule_id, "GR-DEP-001")

    def test_nothing_configured_nothing_blocked(self):
        empty = from_dict({}, root=Path(".").resolve())
        self.assertEqual(bash("scp a prod.example.com:/x", empty), [])

    def test_segments_respect_quotes(self):
        self.assertEqual(_segments("a 'b; c' && d | e"), [["a", "b; c"], ["d"], ["e"]])


class ProtectedFileEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, path, tool="Write"):
        return check_action(Action(tool, {"file_path": path, "content": "x"}, cwd=self.root), cfg(root=self.root))

    def test_globs_and_paths(self):
        self.assertEqual(len(self.edit(os.path.join(self.root, "dist", "app.js"))), 1)
        self.assertEqual(len(self.edit(os.path.join(self.root, ".github", "workflows", "deploy.yml"), "Edit")), 1)
        self.assertEqual(len(self.edit("/srv/www/acme/public_html/index.php")), 1)
        self.assertEqual(self.edit(os.path.join(self.root, "src", "app.js")), [])
        self.assertEqual(self.edit("/srv/www/acme/public_html_old/index.php"), [])

    def test_relative_path_uses_cwd(self):
        self.assertEqual(len(self.edit("dist/app.js", "MultiEdit")), 1)


@unittest.skipIf(subprocess.call(["git", "--version"], stdout=subprocess.DEVNULL) != 0, "git not installed")
class PushTest(unittest.TestCase):
    def ids(self, command, extra=None, cwd="."):
        return [f.rule_id for f in bash(command, cfg(extra), cwd=cwd)]

    def test_force_push_to_protected(self):
        for command in ("git push --force origin main", "git push -f origin HEAD:main", "git push origin +main",
                        "git push --force-with-lease origin feature:master", "git -C repo push --mirror -f"):
            self.assertEqual(self.ids(command), ["GR-DEP-003"], command)

    def test_safe_pushes(self):
        for command in ("git push origin feature/x", "git push -f origin feature/x", "git push origin main",
                        "echo git push --force origin main is bad"):
            self.assertEqual(self.ids(command), [], command)

    def test_direct_push_opt_in(self):
        self.assertEqual(self.ids("git push origin main", {"block_direct_push": True}), ["GR-DEP-003"])

    def test_bare_push_uses_current_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", "-b", "main", tmp], check=True)
            self.assertEqual(self.ids("git push", {"block_direct_push": True}, cwd=tmp), ["GR-DEP-003"])
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-b", "feature"], check=True)
            self.assertEqual(self.ids("git push -f", cwd=tmp), [])


if __name__ == "__main__":
    unittest.main()
