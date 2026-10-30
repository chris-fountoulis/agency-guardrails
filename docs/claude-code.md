# Claude Code integration

[Back to README](../README.md)

agency-guardrails plugs into Claude Code through three hooks. Together they move the rules from "a reviewer
notices later" to "the agent cannot do it, or fixes it in the same turn".

| Hook | Matcher | What it does | How it answers |
| --- | --- | --- | --- |
| `PreToolUse` | `Bash\|Write\|Edit\|MultiEdit\|NotebookEdit` | Runs the action rules (deploy-safety) on the tool call, and the `pre_write_packs` (secrets by default) on the text a Write or Edit is about to write | `hookSpecificOutput.permissionDecision: "deny"` with a reason the model reads |
| `PostToolUse` | `Write\|Edit\|MultiEdit\|NotebookEdit` | Lints the file that was just written with every enabled content rule | `decision: "block"` plus `reason` for errors, `hookSpecificOutput.additionalContext` for warnings only |
| `Stop` | all | Re-checks every modified or untracked file in the git work tree before the agent ends its turn | `decision: "block"` plus `reason` while errors remain |

> [!NOTE]
> The tool call still happens for PostToolUse (the file is written); the block puts the findings next to the tool
> result so the agent fixes them before moving on. The Stop hook honours `stop_hook_active`, so it blocks at most
> once per stop and can never trap the agent in a loop.

> [!WARNING]
> agency-guardrails is engineering tooling, not legal advice. The hooks make an agent stop and look; a person
> still owns what ships.

## Contents

- [Option 1: install the plugin](#option-1-install-the-plugin)
- [Option 2: settings.json with the CLI](#option-2-settingsjson-with-the-cli)
- [Configuration](#configuration)
- [The contract, precisely](#the-contract-precisely)
- [What the agent sees](#what-the-agent-sees)
- [Try a hook by hand](#try-a-hook-by-hand)
- [The emergency override](#the-emergency-override)

## Option 1: install the plugin

The repository is both a Claude Code plugin and a one-plugin marketplace. In Claude Code:

```text
/plugin marketplace add chris-fountoulis/agency-guardrails
/plugin install agency-guardrails@agency-guardrails
```

From a terminal, the `claude` CLI does both steps at once:

```bash
claude plugin install agency-guardrails --marketplace chris-fountoulis/agency-guardrails
```

The plugin needs `python3` (3.9 or newer) on the PATH. It runs the copy of the package bundled in the plugin
directory through `hooks/guardrails_hook.py`, so there is nothing to pip install. The hook definitions live in
[`hooks/hooks.json`](../hooks/hooks.json).

## Option 2: settings.json with the CLI

Install the CLI (`pipx install git+https://github.com/chris-fountoulis/agency-guardrails`) and add this to
`.claude/settings.json` in the project, or `~/.claude/settings.json` for every project:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [{ "type": "command", "command": "guardrails hook pre-tool-use", "timeout": 30 }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [{ "type": "command", "command": "guardrails hook post-tool-use", "timeout": 30 }]
      }
    ],
    "Stop": [
      {
        "hooks": [{ "type": "command", "command": "guardrails hook stop", "timeout": 60 }]
      }
    ]
  }
}
```

> [!TIP]
> Use only the hooks you want. A common start is PreToolUse alone (secrets and deploy safety), then PostToolUse
> once the content rules are tuned for your copy.

## Configuration

Hooks read the same `guardrails.toml` as the CLI, discovered by walking up from the hook's `cwd`. Set
`GUARDRAILS_CONFIG=/path/to/guardrails.toml` in the environment, or pass `--config` in the settings command, to
point every session at one shared file. The `[hooks]` table tunes the hooks:

```toml
[hooks]
pre_write_packs = ["secrets"]  # packs whose errors block a Write or Edit before it happens
post_write = true              # lint each written file and feed findings back
stop_check = true              # re-check changed files before the agent stops
max_findings = 20              # cap on findings in one hook reason
```

Files outside the config root, files matching `exclude` and files not matching `include` are never checked by a
hook. Path ignores and inline `guardrails-ignore` comments apply exactly as they do in the CLI.

## The contract, precisely

Each handler reads the hook payload as JSON on stdin. Fields used:

| Field | Used by | Purpose |
| --- | --- | --- |
| `cwd` | all | Config discovery, relative paths, the git work tree for Stop |
| `tool_name` | PreToolUse, PostToolUse | Which rules apply |
| `tool_input.command` | PreToolUse | Bash command for the action rules |
| `tool_input.file_path`, `content`, `new_string`, `edits`, `new_source` | PreToolUse, PostToolUse | The file and the text being written |
| `stop_hook_active` | Stop | Skip when Claude Code is already continuing because of a Stop hook |

Exit codes: `0` with JSON on stdout when there is a decision, `0` with no output when everything is clean. A hook
that cannot read its input or its config, or hits a bug, writes the reason to stderr and exits `1`, which Claude
Code treats as a non-blocking error. guardrails fails open on its own errors on purpose: a broken config should
show up in the transcript, not freeze a working session. If you want a hard stop on misconfiguration, run
`guardrails check` in CI as well.

## What the agent sees

A blocked deploy, from the sample site config in `examples/site/guardrails.toml`:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "agency-guardrails blocked this Bash call:\n- GR-DEP-001 (error): BLOCKED: scp copies files onto a protected target (deploy@prod.example.com:/srv/www/acme-bakery/public_html/). Make the change on a branch and open a pull request; let the reviewed merge deploy it. Emergency only: put GUARDRAILS_OVERRIDE=1 in the command and record what changed."
  }
}
```

The agent reads the reason, does not retry the scp, and opens a pull request instead. Reads pass: `ssh prod cat
file`, `scp prod:/file ./local` and `rsync prod:/dir ./mirror` are not writes to the protected target.

## Try a hook by hand

```bash
cd examples/site
echo '{"cwd": ".", "tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}}' \
  | guardrails hook pre-tool-use
echo '{"cwd": ".", "tool_name": "Write", "tool_input": {"file_path": "bad/care-plans.md"}}' \
  | guardrails hook post-tool-use
```

## The emergency override

Every deploy-safety block names the override token (`GUARDRAILS_OVERRIDE=1` by default, `override` in the
`[deploy-safety]` table). A command that contains it passes.

> [!CAUTION]
> Keep the override for a site that is down and pair it with a rule in your team docs: whoever uses it syncs the
> repository and posts what changed. Set `override = ""` to remove the escape hatch entirely.

[Back to README](../README.md)

---

Built by [Chris Fountoulis](https://chrisfountoulis.com) at [Growth Of Influence](https://growthofinfluence.com).
