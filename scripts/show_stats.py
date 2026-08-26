#!/usr/bin/env python3
"""MessageDisplay hook: append a stats footer to each reply.

Display-only: the transcript keeps the original text. Enabled by
~/.claude/unclaudish-stats containing "on" (default off). Buffers
streamed chunks per message and appends the footer to the final one.
FAIL OPEN: any error shows the original reply unchanged.
"""

import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BUFFER_ROOT = os.path.join(tempfile.gettempdir(), "unclaudish-stats")
BUFFER_MAX_AGE = 6 * 3600


def enabled():
    import unclaudish_config
    return unclaudish_config.stats_enabled()


def safe(name):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(name))[:64] or "x"


def usage_fragment(session_id, text):
    """Tokens out and in, then the session's cost so far.

    Claude Code writes the assistant record after this hook runs, so
    this reply's output is an estimate and the input shown is the last
    turn that finished. The Stop hook records the real numbers.
    """
    import usage
    fragment = " \u00b7 tok: ~%s\u2191" % usage.compact(
        usage.estimate_tokens(text))
    thinking = usage.last_thinking_tokens(session_id)
    if thinking:
        fragment += " \u00b7 %s think" % usage.compact(thinking)
    cost = usage.last_cost(session_id)
    if cost is not None:
        fragment += " \u00b7 %s" % usage.money(cost)
    return fragment


def main():
    if not enabled():
        return
    hook_input = json.load(sys.stdin)
    delta = hook_input.get("delta") or ""
    buffer_dir = os.path.join(
        BUFFER_ROOT, safe(hook_input.get("session_id")),
        safe(hook_input.get("message_id")))
    os.makedirs(buffer_dir, exist_ok=True)
    index = int(hook_input.get("index") or 0)
    with open(os.path.join(buffer_dir, "%06d.part" % index), "w",
              encoding="utf-8") as f:
        f.write(delta)
    if not hook_input.get("final"):
        return

    parts = sorted(p for p in os.listdir(buffer_dir)
                   if p.endswith(".part"))
    full = "".join(
        open(os.path.join(buffer_dir, p), encoding="utf-8").read()
        for p in parts)
    # Keep what was evaluated, so any mismatch with the visible reply
    # can be diagnosed from the buffer directory.
    with open(os.path.join(buffer_dir, "evaluated.txt"), "w",
              encoding="utf-8") as f:
        f.write(full)

    from claudish_core import evaluate
    result = evaluate(full)
    # Algorithmic detections carry no count; each still counts as one
    # pattern so the total always agrees with the detected list.
    patterns = sum(m["count"] or 1 for m in result["metrics"].values())
    blockable = sum(v["count"] for v in result["hard_violations"])
    words = len(full.split())

    tokens_part = usage_fragment(hook_input.get("session_id"), full)
    # Displayed score is a calibrated percentage: raw scores live in
    # roughly 0-20, so a straight inversion would show 96% for a bad
    # reply. 100% is clean; each score point costs 5, each blockable
    # pattern another 10.
    clean_pct = max(0.0, 100.0 - 5.0 * result["score"]
                    - 10.0 * blockable)
    # Zeros carry no information: the pattern names live on the
    # detected line, and blockable is called out only when it happens.
    footer = ("\n\n---\n`unclaudish` %.0f%% \u00b7 %d words%s"
              % (clean_pct, words, tokens_part))
    if blockable:
        footer += " \u00b7 %d blockable" % blockable
    names = sorted(
        ((mid, m["count"]) for mid, m in result["metrics"].items()),
        key=lambda item: -(item[1] or 0))[:6]
    if names:
        footer += "\n`detected` " + ", ".join(
            "%s x%d" % (mid, count) if count else mid
            for mid, count in names)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "MessageDisplay",
        "displayContent": delta + footer,
    }}))

    # Opportunistic cleanup of old message buffers.
    now = time.time()
    try:
        for session in os.listdir(BUFFER_ROOT):
            session_dir = os.path.join(BUFFER_ROOT, session)
            if now - os.path.getmtime(session_dir) > BUFFER_MAX_AGE:
                import shutil
                shutil.rmtree(session_dir, ignore_errors=True)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open: original display is untouched
    sys.exit(0)
