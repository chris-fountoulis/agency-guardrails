import unittest

from agency_guardrails import redact

from tests import fakes
from tests.helpers import run_rule


class ShapesTest(unittest.TestCase):
    def test_each_provider_is_detected(self):
        cases = {
            "anthropic-api-key": fakes.anthropic(),
            "openai-api-key": fakes.openai(),
            "github-token": fakes.github(),
            "github-pat": fakes.github_pat(),
            "aws-access-key-id": fakes.aws_id(),
            "stripe-secret-key": fakes.stripe(),
            "slack-token": fakes.slack(),
            "slack-webhook": fakes.slack_webhook(),
            "google-api-key": fakes.google(),
        }
        for kind, value in cases.items():
            hits = redact.scan("config: %s\n" % value, generic=False)
            self.assertEqual([h.kind for h in hits], [kind], value)

    def test_aws_secret_needs_context(self):
        value = fakes.aws_secret()
        self.assertEqual([h.kind for h in redact.scan("aws_secret_access_key = %s\n" % value, generic=False)],
                         ["aws-secret-access-key"])

    def test_ordinary_text_is_clean(self):
        text = "The sk-learn docs, AKIA in prose, ghp_short and a sk_live_ mention are fine.\n"
        self.assertEqual(redact.scan(text), [])

    def test_rule_reports_preview_not_secret(self):
        value = fakes.anthropic()
        found = run_rule("GR-SEC-001", "key: %s\n" % value, path="notes.txt")
        self.assertEqual(len(found), 1)
        self.assertNotIn(value, found[0].message)
        self.assertIn("Anthropic", found[0].message)

    def test_rule_runs_on_any_file_type(self):
        found = run_rule("GR-SEC-001", "TOKEN = '%s'\n" % fakes.github(), path="settings.py")
        self.assertEqual(len(found), 1)

    def test_allow_patterns(self):
        value = fakes.stripe()
        found = run_rule("GR-SEC-001", value, path="a.txt", options={"allow_patterns": ["^sk_live_"]})
        self.assertEqual(found, [])


class PrivateKeyTest(unittest.TestCase):
    def test_block_and_redaction(self):
        text = "before\n%s\nafter\n" % fakes.private_key()
        found = run_rule("GR-SEC-002", text, path="id.txt")
        self.assertEqual([f.line for f in found], [2])
        out, hits = redact.redact(text)
        self.assertEqual(out, "before\n[REDACTED:private-key]\nafter\n")

    def test_header_without_end_still_redacts_rest(self):
        text = fakes.private_key().split("\n")[0] + "\nAAAA\n"
        out, _ = redact.redact(text)
        self.assertEqual(out, "[REDACTED:private-key]")


class GenericTest(unittest.TestCase):
    RULE = "GR-SEC-003"

    def test_random_assignment(self):
        value = fakes.random_value()
        found = run_rule(self.RULE, 'client_secret = "%s"\n' % value, path="app.py")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, "warn")
        found = run_rule(self.RULE, '{"apiKey": "%s"}' % value, path="c.json")
        self.assertEqual(len(found), 1)

    def test_placeholders_and_words_pass(self):
        for value in ("your_api_key_here", "changeme-please-now", "${API_TOKEN_VALUE}", "xxxxxxxxxxxxxxxx",
                      "password_reset_token_field", "os.environ.get('TOKEN')"):
            self.assertEqual(run_rule(self.RULE, "token = %s\n" % value, path="a.py"), [], value)

    def test_not_double_reported(self):
        found = run_rule(self.RULE, "api_key = %s\n" % fakes.openai(), path="a.py")
        self.assertEqual(found, [])

    def test_entropy(self):
        self.assertLess(redact.shannon_entropy("aaaaaaaa"), 1)
        self.assertGreater(redact.shannon_entropy(fakes.random_value()), 4)


class RedactTest(unittest.TestCase):
    def test_redacts_everything_and_keeps_text(self):
        text = "ANTHROPIC=%s\nghtoken: %s\nplain words stay\n" % (fakes.anthropic(), fakes.github())
        out, hits = redact.redact(text)
        self.assertEqual(out, "ANTHROPIC=[REDACTED:anthropic-api-key]\nghtoken: [REDACTED:github-token]\nplain words stay\n")
        self.assertEqual(len(hits), 2)

    def test_generic_redacts_value_only(self):
        out, _ = redact.redact("password: %s\n" % fakes.random_value())
        self.assertEqual(out, "password: [REDACTED:generic-secret]\n")


if __name__ == "__main__":
    unittest.main()
