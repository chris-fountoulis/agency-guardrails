#!/usr/bin/env python3
"""Entry point for the Claude Code plugin hooks.

Runs the bundled copy of agency_guardrails from the plugin directory, so the
plugin works without a pip install. Usage: guardrails_hook.py <event>, where
event is pre-tool-use, post-tool-use or stop. The hook JSON arrives on stdin.
"""

import os
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN_ROOT)

from agency_guardrails.hooks import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
