# GitHub Action

[Back to README](../README.md)

`action.yml` at the repository root is a composite action. It installs agency-guardrails from the action
checkout, runs `guardrails check`, annotates the pull request diff with every finding, writes a findings table to
the job summary and , if you ask for it, uploads SARIF to GitHub code scanning.

> [!WARNING]
> Engineering tooling, not legal advice. A green check means no rule matched, not that copy is compliant.

**On this page:** [Quick start](#quick-start) · [Inputs](#inputs) · [Outputs](#outputs) ·
[Annotations](#pull-request-annotations) · [SARIF](#code-scanning-sarif) · [Changed files only](#only-check-what-changed) ·
[Without the action](#without-the-action)

## Quick start

```yaml
# .github/workflows/guardrails.yml
name: guardrails

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  guardrails:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: chris-fountoulis/agency-guardrails@v0.1.0
        with:
          paths: content site
```

A fuller copy-ready file is in [`examples/workflow.yml`](../examples/workflow.yml). Put a `guardrails.toml` at
the root of the repository (run `guardrails init` locally to start one), or point the `config` input at it.

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `paths` | `.` | Files or directories to check, separated by spaces |
| `config` | discovered | Path to `guardrails.toml`; by default the nearest one above the first path |
| `fail-on` | from config, else `error` | Lowest severity that fails the step: `error`, `warn` or `never` |
| `packs` | from config | Only run these packs, separated by spaces |
| `upload-sarif` | `false` | Upload the SARIF report to code scanning |
| `sarif-file` | `guardrails.sarif` | Where the SARIF report is written |
| `setup-python` | `true` | Run `actions/setup-python`; set `false` if the job already has Python 3.9+ |
| `python-version` | `3.12` | Python version for `actions/setup-python` |

## Outputs

| Output | Description |
| --- | --- |
| `errors` | Number of error findings |
| `warnings` | Number of warning findings |
| `exit-code` | `0` clean, `1` findings at or above `fail-on`, `2` usage or config error |
| `sarif-file` | Path of the SARIF report |

## Pull request annotations

The check runs with `--format github`, which prints one workflow command per finding:

```text
::error file=site/pricing.html,line=23,col=45,title=GR-EU-002 Price without a VAT-inclusive figure::Price ...
```

GitHub turns each into an annotation on the changed line in the pull request , with the rule id in the title.

## Code scanning (SARIF)

Set `upload-sarif: "true"` and grant the job `security-events: write`:

```yaml
permissions:
  contents: read
  security-events: write

steps:
  - uses: actions/checkout@v7
  - uses: chris-fountoulis/agency-guardrails@v0.1.0
    with:
      upload-sarif: "true"
```

Every SARIF rule carries the rationale, the fix and the primary source as `helpUri`, so the code scanning alert
links straight to the directive or guideline behind it.

> [!NOTE]
> Code scanning for private repositories needs GitHub Advanced Security. The annotations work everywhere.

## Only check what changed

To lint only the files a pull request touches, compute the list first and pass it as `paths`:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0
- id: changed
  run: |
    files=$(git diff --name-only --diff-filter=AM origin/${{ github.base_ref }}...HEAD -- '*.md' '*.html' | tr '\n' ' ')
    echo "files=$files" >> "$GITHUB_OUTPUT"
- if: steps.changed.outputs.files != ''
  uses: chris-fountoulis/agency-guardrails@v0.1.0
  with:
    paths: ${{ steps.changed.outputs.files }}
```

## Without the action

The action is a thin wrapper. Any CI system can run the same thing:

```bash
pip install git+https://github.com/chris-fountoulis/agency-guardrails
guardrails check --format github --sarif-file guardrails.sarif content site
```

[Back to README](../README.md)

---

Built by [Chris Fountoulis](https://chrisfountoulis.com) at [Growth Of Influence](https://growthofinfluence.com).
