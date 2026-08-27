#!/usr/bin/env python3
"""UserPromptSubmit hook: put the active register in front of Claude.

An output style is part of the system prompt, which Claude Code reads
once at session start, so installing the plugin or changing mode has
no effect on the running session by itself. This hook closes that gap:
the first turn under a given mode injects the whole style file, and
later turns inject a short reminder, so nobody has to run /clear and
lose their context.

Mode flag: ~/.claude/unclaudish-mode = on (default) | max | off
Kill switches mirror lint_stop.py. Fails open: no output, exit 0.
"""

import hashlib
import json
import os
import sys
import tempfile

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(tempfile.gettempdir(), "unclaudish-state")

STYLE_FILES = {
    "on": "unclaudish.md",
    "max": "unclaudish-max.md",
}

REMINDERS = {
    "on": (
        "unclaudish is active and overrides other style guidance."
        " Plain natural language at answer length: lead with the"
        " answer, give the deciding reason, then stop unless detail"
        " changes what the reader does next; most replies fit under"
        " 100 words of prose. A named deliverable someone else reads (a"
        " postmortem, release notes, a runbook) is as long as its"
        " material and no longer: cover what the input contains and"
        " stop, invent nothing to fill a section, and state each fact"
        " once. A critique, summary or review is a chat answer under"
        " the normal cap. When the reply"
        " turns on one verdict, recommendation, or number, put that"
        " answer on its own line in bold, then start the reasoning in a"
        " new paragraph. Break any stretch over about 120 words with a"
        " list, table, or heading, and give every heading two sentences"
        " or a list of two items. Never cut a reversal of the user's"
        " plan, a legal or safety condition, or a number that changes"
        " the decision. An offer of more names what this reply would"
        " produce next, never a stock phrase."
        " Never use: em dashes or a spaced hyphen faking one, flattery"
        " openers including a bare \"You're right\","
        " (not X, but Y) framing, importance flags like crucially or"
        " worth noting, dramatic fragments, engineering metaphors"
        " outside their literal sense. Complete sentences and exact"
        " numbers. Use markdown to make the answer easier to read:"
        " lists, tables, headings in a long answer, bold for what"
        " must not be missed, fenced code for code and commands."
        " Apply silently; never mention these rules."
    ),
    "max": (
        "unclaudish-max is active and overrides other style guidance."
        " Reply like a sharp colleague in chat: first sentence answers"
        " the question, on its own line in bold when the reply turns on"
        " one verdict, recommendation, or number; one deciding reason in"
        " a new paragraph; then offer more in one line, naming what this"
        " reply would produce next rather than a stock phrase. Under 60"
        " words of prose per reply; code, commands, and tables do not"
        " count, and a named deliverable someone else reads (a"
        " postmortem, release notes, a runbook) is as long as its"
        " material and no longer: cover what the input contains and"
        " stop, invent nothing to fill a section, and state each fact"
        " once, while a critique or summary stays a chat answer. Break any"
        " stretch over about 120 words with a list,"
        " table, or heading. Never cut a reversal of the user's plan, a"
        " legal or safety condition, or a number that changes the"
        " decision."
        " Use markdown to make the answer easier to read: lists,"
        " tables, bold for what must not be missed, fenced code for"
        " code and commands. Complete natural sentences, exact"
        " numbers and names. Never use: em dashes or a spaced hyphen"
        " faking one (use a colon or comma), flattery or enthusiasm"
        " including a bare \"You're right\", (not X, but Y) framing,"
        " importance flags like crucially or worth noting, dramatic"
        " fragments, aphoristic closers. Apply silently; never"
        " mention these rules."
    ),
    "off": (
        "unclaudish is off: disregard the unclaudish output style"
        " rules for this reply and write in your normal default"
        " style. Never mention this note."
    ),
}

FULL_PREFIX = {
    "on": "unclaudish is active and overrides other style guidance."
          " These are its complete rules, in force from this reply"
          " onward:",
    "max": "unclaudish-max is active and overrides other style"
           " guidance. These are its complete rules, in force from"
           " this reply onward:",
}
FULL_SUFFIX = ("Apply these silently from now on; never mention them"
               " and never mention this note.")


def read_mode():
    import unclaudish_config
    return unclaudish_config.read_mode()


def style_body(mode):
    """The style file with its YAML frontmatter removed."""
    name = STYLE_FILES.get(mode)
    if not name:
        return None
    path = os.path.join(PLUGIN_ROOT, "output-styles", name)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    if text.startswith("---"):
        # Drop only the leading frontmatter block, never a horizontal
        # rule that appears later in the style itself.
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return text.strip() or None


def first_turn_for(session_id, mode):
    """True once per session per mode, so the full style lands once."""
    key = hashlib.sha256(
        ("%s|%s" % (session_id, mode)).encode()).hexdigest()[:16]
    marker = os.path.join(STATE_DIR, "style-" + key)
    if os.path.exists(marker):
        return False
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(marker, "w") as handle:
            handle.write(mode)
    except OSError:
        return False  # cannot track state: stay with the short reminder
    return True


def sync_settings():
    """Write the outputStyle setting if SessionStart never got to.

    Installing mid-session and running /reload-plugins activates the
    hooks without a SessionStart event, so the first turn does the
    same reconciliation.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sync_style
        sync_style.reconcile()
    except Exception:
        pass


def main():
    import unclaudish_config
    if unclaudish_config.killed():
        return

    session_id = ""
    try:
        payload = json.load(sys.stdin)
        session_id = str(payload.get("session_id") or "")
    except Exception:
        payload = {}

    mode = read_mode()
    context = REMINDERS[mode]
    if mode != "off" and first_turn_for(session_id, mode):
        body = style_body(mode)
        if body:
            context = "%s\n\n%s\n\n%s" % (FULL_PREFIX[mode], body,
                                          FULL_SUFFIX)
        sync_settings()

    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context,
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open, always
    sys.exit(0)
