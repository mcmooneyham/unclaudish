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

FLAG = os.path.expanduser("~/.claude/unclaudish-stats")
KILL_SWITCH = os.path.expanduser("~/.claude/unclaudish-off")
BUFFER_ROOT = os.path.join(tempfile.gettempdir(), "unclaudish-stats")
BUFFER_MAX_AGE = 6 * 3600


def enabled():
    if os.path.exists(KILL_SWITCH):
        return False
    if os.environ.get("UNCLAUDISH_DISABLE") == "1":
        return False
    try:
        with open(FLAG) as f:
            return f.read().strip() == "on"
    except OSError:
        return False


def safe(name):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(name))[:64] or "x"


# Anthropic first-party rates per million tokens (input, output);
# cost shown as an estimate, cache reads at a tenth of input rate.
RATES = {"fable": (10.0, 50.0), "opus": (5.0, 25.0),
         "sonnet": (2.0, 10.0), "haiku": (1.0, 5.0)}


def turn_usage(transcript_path):
    """Sum this turn's token usage from the transcript tail; returns
    a footer fragment, or empty when the transcript lags."""
    try:
        if not transcript_path or not os.path.isfile(transcript_path):
            return ""
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - 2 * 1024 * 1024))
            lines = f.read().decode("utf-8", "replace").split("\n")
        if size > 2 * 1024 * 1024:
            lines = lines[1:]
        out_tokens = think = in_tokens = cache_read = 0
        model = ""
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") == "user":
                content = entry.get("message", {}).get("content")
                if isinstance(content, str):
                    break
                continue
            if entry.get("type") != "assistant":
                continue
            usage = entry.get("message", {}).get("usage") or {}
            out_tokens += usage.get("output_tokens") or 0
            think += (usage.get("output_tokens_details") or {}).get(
                "thinking_tokens") or 0
            in_tokens += usage.get("input_tokens") or 0
            cache_read += usage.get("cache_read_input_tokens") or 0
            model = entry.get("message", {}).get("model") or model
        if not out_tokens:
            return ""
        fragment = " | %d tok out (%d think)" % (out_tokens, think)
        for key, (in_rate, out_rate) in RATES.items():
            if key in model:
                cost = (in_tokens * in_rate
                        + cache_read * in_rate * 0.1
                        + out_tokens * out_rate) / 1e6
                fragment += " | ~$%.4f" % cost
                break
        return fragment
    except Exception:
        return ""


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

    tokens_part = turn_usage(hook_input.get("transcript_path"))
    # Displayed score is a calibrated percentage: raw scores live in
    # roughly 0-20, so a straight inversion would show 96% for a bad
    # reply. 100% is clean; each score point costs 5, each blockable
    # pattern another 10.
    clean_pct = max(0.0, 100.0 - 5.0 * result["score"]
                    - 10.0 * blockable)
    footer = (
        "\n\n---\n`unclaudish` %d pattern%s (%d blockable) | "
        "%d words | score %.0f%%%s"
        % (patterns, "" if patterns == 1 else "s", blockable, words,
           clean_pct, tokens_part))
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
