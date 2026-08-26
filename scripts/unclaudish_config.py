#!/usr/bin/env python3
"""Shared configuration for every unclaudish hook and skill.

One place decides what is on, so the main session and its subagents
always answer to the same switches:

  ~/.claude/unclaudish-mode        on (default) | max | off
  ~/.claude/unclaudish-subagents   mirror (default) | on | max | off
  ~/.claude/unclaudish-stats       on | off (default)
  ~/.claude/unclaudish-off         kill switch, presence disables all
  UNCLAUDISH_DISABLE=1             same kill switch, per process
"""

import os

CLAUDE_DIR = os.path.expanduser("~/.claude")
MODE_FILE = os.path.join(CLAUDE_DIR, "unclaudish-mode")
SUBAGENT_FILE = os.path.join(CLAUDE_DIR, "unclaudish-subagents")
STATS_FILE = os.path.join(CLAUDE_DIR, "unclaudish-stats")
KILL_SWITCH = os.path.join(CLAUDE_DIR, "unclaudish-off")

MODES = ("on", "max", "off")
SUBAGENT_SETTINGS = ("mirror", "on", "max", "off")
OFF_WORDS = ("off", "no", "false", "0")


def _read(path):
    try:
        with open(path) as handle:
            return handle.read().strip().lower()
    except OSError:
        return None


def _write(path, value):
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    with open(path, "w") as handle:
        handle.write(value + "\n")


def read_mode(default="on"):
    """Current mode. Returns default when no flag file exists."""
    raw = _read(MODE_FILE)
    if raw is None:
        return default
    if raw == "unclaudish":  # legacy spelling of "on"
        return "on"
    return raw if raw in MODES else default


def write_mode(mode):
    _write(MODE_FILE, mode)


def killed():
    """True when a kill switch is set, whatever the mode says."""
    return (os.path.exists(KILL_SWITCH)
            or os.environ.get("UNCLAUDISH_DISABLE") == "1")


def disabled():
    """True when nothing that changes the register should run."""
    return killed() or read_mode() == "off"


def subagents_setting():
    """How subagents pick a register.

    mirror: whatever the session is using (the default)
    on:     always the plain style, whatever the session uses
    max:    always the max style
    off:    nothing injected, and their answers are not linted
    """
    raw = _read(SUBAGENT_FILE)
    if raw is None:
        return "mirror"
    if raw in OFF_WORDS:
        return "off"
    if raw in ("yes", "true", "1"):
        return "mirror"
    return raw if raw in SUBAGENT_SETTINGS else "mirror"


def subagents_enabled():
    """Whether subagents follow the plugin at all."""
    return subagents_setting() != "off"


def subagent_mode():
    """The style a subagent should be given, or None for nothing."""
    if disabled() or not subagents_enabled():
        return None
    setting = subagents_setting()
    return read_mode() if setting == "mirror" else setting


def write_subagents(value):
    _write(SUBAGENT_FILE, value)


def stats_enabled():
    """The stats footer keeps its own switch, independent of mode."""
    if killed():
        return False
    return _read(STATS_FILE) == "on"
