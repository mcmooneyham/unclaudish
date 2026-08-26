---
name: mode
description: Switch the unclaudish register for every future turn. Use when asked to change unclaudish mode, go max, or turn the reminder off.
argument-hint: [on|max|off|status]
allowed-tools: Bash
---

Set the unclaudish mode. The argument is $ARGUMENTS (default:
status).

- `on`: the standard plain register (default).
- `max`: extreme brevity. The answer, one reason, an offer of more.
- `off`: no per-turn reinforcement (the output style and linter
  stay active; disable the plugin in /plugin for a full off).
- `status`: report the current mode without changing it.

Treat a flag value of `unclaudish` as `on`.

To set a mode, write the flag file and confirm:

    echo MODE > ~/.claude/unclaudish-mode

For status, read that file (missing file means `unclaudish`).

The mode takes effect on the next message. Also adopt the chosen
register yourself immediately, from this reply onward. Confirm the
change in one sentence.
