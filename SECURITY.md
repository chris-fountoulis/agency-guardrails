# Security policy

## Supported versions

Security fixes go into the latest release. agency-guardrails is pre-1.0, so please upgrade to the newest
version before reporting.

## Reporting a vulnerability

Email **chris@growthofinfluence.com** with the subject line "agency-guardrails security". Please do not open a
public issue for a vulnerability.

Include what you found, how to reproduce it and the impact you expect. You will get an acknowledgement within
five working days and a plan for a fix once the report is confirmed.

Reports that matter most for this project:

- a way for a tool call to get past a PreToolUse rule that should block it (deploy-safety bypasses);
- a credential shape that the secrets pack misses or that `guardrails redact` leaks;
- anything in the hooks that could run code or write files from untrusted input.

Bypasses of heuristic content rules (rewording a claim so a rule no longer matches) are useful bug reports, but
they are not security vulnerabilities: open a regular issue for those.

---

Built by [Chris Fountoulis](https://chrisfountoulis.com) at [Growth Of Influence](https://growthofinfluence.com).
