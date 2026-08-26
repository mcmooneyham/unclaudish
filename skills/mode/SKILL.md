---
name: mode
description: Switch the unclaudish register everywhere. Use when asked to change unclaudish mode, go max, or turn unclaudish off.
argument-hint: [on|max|off|status]
allowed-tools: Bash
---

Set the unclaudish mode. The argument is $ARGUMENTS (default:
status).

- `on`: the standard plain register.
- `max`: extreme brevity. The answer, one reason, an offer of more.
- `off`: linters stop, the reminder stops, the style is
  countermanded each turn. Stats keeps its own switch.
- `status`: report the current mode and style, changing nothing.

Run exactly this, with MODE replaced by on, max, off, or status:

    ROOT="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/unclaudish/* 2>/dev/null | sort -V | tail -1)}"
    python3 "$ROOT/scripts/sync_style.py" set MODE

For `status`, use `status` as the whole command instead of `set MODE`.

The script writes the mode flag and the `outputStyle` key in
`~/.claude/settings.json`, so every project picks it up. Report its
output in one sentence. Adopt the chosen register yourself
immediately, from this reply onward.

The register changes with the next message. The full output style
loads after `/clear` or in a new session, which is also when
`/config` shows the change.
