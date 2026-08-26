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
- `off`: turns off the register: the linters stop checking, the
  reminder stops, and the output style is countermanded each turn.
  The stats footer keeps its own switch (/unclaudish:stats).
  Disable the plugin in /plugin to remove everything.
- `status`: report the current mode without changing it.

Treat a flag value of `unclaudish` as `on`.

To set a mode, write the flag file and confirm:

    echo MODE > ~/.claude/unclaudish-mode

For status, read that file (missing file means `unclaudish`).

The mode takes effect on the next message. Also adopt the chosen
register yourself immediately, from this reply onward. Confirm the
change in one sentence.
