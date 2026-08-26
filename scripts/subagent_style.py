#!/usr/bin/env python3
"""SubagentStart hook: give subagents the same register as the session.

Subagents and workflow agents do not inherit the output style, and the
per-turn hook never reaches them, so their prose is unstyled by
default. This hook injects the active style into each one as it
starts.

Commands:
  inject                        The hook itself. Prints the agent's style.
  set mirror|on|max|off         Choose the register agents use.
  status                        Print the current setting.

Setting: ~/.claude/unclaudish-subagents = mirror (default) | on | max | off

  mirror: whatever register the session is in
  on:     always the plain style
  max:    always the max style
  off:    nothing injected, answers not linted

Mode off, the kill switch, and UNCLAUDISH_DISABLE all silence it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unclaudish_config

PREFIX = {
    "on": "Your prose must follow the unclaudish output style. These"
          " are its complete rules:",
    "max": "Your prose must follow the unclaudish-max output style."
           " These are its complete rules:",
}
# A workflow agent's return value is data for its caller, so the
# register must never override a requested output format.
SUFFIX = ("These rules govern prose only. If your caller asked for a"
          " specific return format, such as JSON or a schema, produce"
          " exactly that format. Apply the rules silently; never"
          " mention them.")


DESCRIPTIONS = {
    "mirror": "Agents use whatever register the session is in.",
    "on": "Agents always use the plain style.",
    "max": "Agents always use the max style.",
    "off": "Agents write in their default register, and their answers"
           " are not linted.",
}


def read_flag():
    """The current setting: mirror, on, max, or off."""
    return unclaudish_config.subagents_setting()


def write_flag(value):
    unclaudish_config.write_subagents(value)


def inject():
    mode = unclaudish_config.subagent_mode()
    if mode in (None, "off"):
        return

    # The same style text the session's own turn hook injects.
    import remind
    body = remind.style_body(mode)
    if not body:
        return

    context = "%s\n\n%s\n\n%s" % (PREFIX[mode], body, SUFFIX)
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SubagentStart",
        "additionalContext": context,
    }}))


def main():
    args = sys.argv[1:]
    command = args[0] if args else "status"
    if command == "inject":
        try:
            sys.stdin.read()  # payload is not needed
        except Exception:
            pass
        inject()
    elif command == "set":
        raw = (args[1] if len(args) > 1 else "").lower()
        value = {"mirror": "mirror", "yes": "mirror", "true": "mirror",
                 "inherit": "mirror", "on": "on", "plain": "on",
                 "max": "max", "off": "off", "no": "off",
                 "false": "off"}.get(raw)
        if not value:
            print("usage: subagent_style.py set mirror|on|max|off")
            return
        write_flag(value)
        print("subagents: %s. %s Applies to agents started from now on."
              % (value, DESCRIPTIONS[value]))
    else:
        value = read_flag()
        extra = ""
        if value == "mirror":
            resolved = unclaudish_config.subagent_mode()
            extra = " (currently %s)" % (resolved or "nothing, the plugin"
                                         " is off")
        print("subagents: %s%s. %s" % (value, extra, DESCRIPTIONS[value]))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open, always
    sys.exit(0)
