---
name: subagents
description: Choose the register subagents and workflow agents write in. Use when asked about agents writing in the plugin style.
argument-hint: [mirror|on|max|off|status]
allowed-tools: Bash
---

Choose what register subagents and workflow agents use. The argument
is $ARGUMENTS (default: status).

- `mirror`: agents use whatever register the session is in. Default.
- `on`: agents always use the plain style, whatever the session uses.
- `max`: agents always use the max style.
- `off`: agents write in their default register, and their answers
  are not linted. Files they write are still checked.
- `status`: report the setting, changing nothing.

Run exactly this, with VALUE replaced by mirror, on, max, or off:

    ROOT="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/unclaudish/* 2>/dev/null | sort -V | tail -1)}"
    python3 "$ROOT/scripts/subagent_style.py" set VALUE

For `status`, use `status` as the whole command instead of `set VALUE`.

Report its output in one sentence. The change applies to agents
started after it, and agents already running keep the register they
began with. A structured return value, such as JSON a workflow
expects, is never overridden. Turning the session off with
`/unclaudish:mode off` silences agents too, whatever this is set to.
