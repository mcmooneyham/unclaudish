#!/usr/bin/env python3
"""Keep the mode flag and the global outputStyle setting in agreement.

Two facts drive this (both probe-verified on Claude Code 2.1.246):

1. A plugin output style is named `<plugin>:<style>` in the
   `outputStyle` setting. The bare style name silently resolves to no
   style at all.
2. `outputStyle` is part of the system prompt, so a change applies
   after /clear or in the next session. The per-turn hook covers the
   current session.

Modes:
  set on|max|off   Write both the flag file and ~/.claude/settings.json.
  reconcile        SessionStart hook. Fills in a missing outputStyle so
                   a fresh install applies everywhere, and follows a
                   style the user picked in /config.
  status           Print the current mode and style.

The global settings file is the source of truth for which of the two
styles is active; the flag file mirrors it for the other hooks. A style
belonging to someone else is never touched.
"""

import json
import os
import sys

STYLES = {
    "on": "unclaudish:unclaudish",
    "max": "unclaudish:unclaudish-max",
}
OUR_STYLES = {value: key for key, value in STYLES.items()}
CLAUDE_DIR = os.path.expanduser("~/.claude")
MODE_FILE = os.path.join(CLAUDE_DIR, "unclaudish-mode")
SETTINGS_FILE = os.path.join(CLAUDE_DIR, "settings.json")
KILL_SWITCH = os.path.join(CLAUDE_DIR, "unclaudish-off")


def read_mode():
    """Current mode, or None when no flag file exists."""
    try:
        with open(MODE_FILE) as handle:
            raw = handle.read().strip().lower()
    except OSError:
        return None
    if raw == "unclaudish":  # legacy spelling of "on"
        return "on"
    return raw if raw in ("on", "max", "off") else None


def write_mode(mode):
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    with open(MODE_FILE, "w") as handle:
        handle.write(mode + "\n")


def read_settings():
    """Parsed global settings, or None if unreadable or malformed."""
    try:
        with open(SETTINGS_FILE) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_settings(data):
    """Replace the settings file atomically so a crash cannot truncate."""
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    temp_path = SETTINGS_FILE + ".unclaudish.tmp"
    with open(temp_path, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, SETTINGS_FILE)


def set_style(mode):
    """Point both the flag file and the global setting at one mode."""
    write_mode(mode)
    data = read_settings()
    if data is None:
        if os.path.exists(SETTINGS_FILE):
            return None  # malformed settings: leave the file untouched
        data = {}
    current = data.get("outputStyle")
    if mode == "off":
        if current not in OUR_STYLES:
            return current  # already off, or someone else's style
        data.pop("outputStyle")
    else:
        if current == STYLES[mode]:
            return current
        data["outputStyle"] = STYLES[mode]
    write_settings(data)
    return data.get("outputStyle")


def reconcile():
    """Make the flag and the setting agree, preferring the setting."""
    mode = read_mode()
    if mode == "off":
        return
    data = read_settings()
    if data is None and os.path.exists(SETTINGS_FILE):
        return  # malformed: do nothing rather than clobber it
    if data is None:
        data = {}
    current = data.get("outputStyle")
    if current in OUR_STYLES:
        if OUR_STYLES[current] != mode:
            write_mode(OUR_STYLES[current])
        return
    if current is not None:
        return  # a style the user chose for themselves: leave it alone
    data["outputStyle"] = STYLES[mode or "on"]
    write_settings(data)
    if mode is None:
        write_mode("on")


def main():
    args = sys.argv[1:]
    command = args[0] if args else "status"
    if os.path.exists(KILL_SWITCH) or \
            os.environ.get("UNCLAUDISH_DISABLE") == "1":
        if command == "reconcile":
            return
    if command == "set":
        mode = (args[1] if len(args) > 1 else "").lower()
        if mode == "unclaudish":
            mode = "on"
        if mode not in ("on", "max", "off"):
            print("usage: sync_style.py set on|max|off")
            return
        style = set_style(mode)
        print("unclaudish mode: %s | output style: %s"
              % (mode, style or "default (none)"))
        if mode != "off":
            print("Active from your next message; /clear or a new"
                  " session loads the full style everywhere.")
    elif command == "reconcile":
        try:
            sys.stdin.read()  # hook payload is not needed
        except Exception:
            pass
        reconcile()
    else:
        mode = read_mode() or "on"
        data = read_settings() or {}
        print("unclaudish mode: %s | output style: %s"
              % (mode, data.get("outputStyle") or "default (none)"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open: a config sync must never break a session
    sys.exit(0)
