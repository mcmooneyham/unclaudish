---
name: stats
description: Toggle the per-reply stats footer. Use when asked to turn unclaudish stats on or off.
argument-hint: [on|off|status]
allowed-tools: Bash
---

Toggle the stats footer flag. The argument is $ARGUMENTS (default:
status).

The footer itself is produced by a display hook that runs outside
the model. NEVER write a stats line, footer, or pattern report
yourself, in this reply or any later reply; doing so would show fake
numbers next to the real ones. Your only job is the flag file:

- `on`: run `echo on > ~/.claude/unclaudish-stats`
- `off`: run `echo off > ~/.claude/unclaudish-stats`
- `status`: read that file (missing means off)

Then confirm in one sentence and stop. The real footer appears
automatically under replies while the flag is on.
