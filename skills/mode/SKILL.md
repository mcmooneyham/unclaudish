---
name: mode
description: Switch the unclaudish register for every future turn. Use when asked to change unclaudish mode, go max, or turn the reminder off.
argument-hint: [on|max|off|status]
allowed-tools: Bash
---

Set the unclaudish mode. The argument is $ARGUMENTS (default:
status). Treat a flag value of `unclaudish` as `on`.

- `on`: the standard plain register.
- `max`: extreme brevity. The answer, one reason, an offer of more.
- `off`: linters stop, the reminder stops, the style is
  countermanded each turn. Stats keeps its own switch.
- `status`: report the current mode without changing anything.

To set a mode, do BOTH steps, then confirm in one sentence:

1. Write the flag file (drives the hooks, effective next message):

       echo MODE > ~/.claude/unclaudish-mode

2. Write the output style setting so /config shows it and the full
   style loads in future sessions. Set STYLE to `unclaudish` for
   on, `unclaudish-max` for max; for off, use `Default`:

       python3 -c "
       import json, os
       p = '.claude/settings.local.json'
       os.makedirs('.claude', exist_ok=True)
       s = json.load(open(p)) if os.path.exists(p) else {}
       s['outputStyle'] = 'STYLE'
       json.dump(s, open(p, 'w'), indent=2)"

For status, read the flag file (missing means on) and report it.
Also adopt the chosen register yourself immediately, from this
reply onward.
