#!/usr/bin/env python3
"""Stop-hook entry point: block once per turn on hard claudish patterns.

Contract (verified by probes, see experiments/probe-results.md):
- stdin: hook JSON with last_assistant_message, transcript_path,
  prompt_id, stop_hook_active
- block: print {"decision": "block", "reason": ...} and exit 0
- allow: exit 0 with no output
- FAIL OPEN: any internal error allows the stop. A broken linter must
  never trap a session.
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATE_DIR = os.path.join(tempfile.gettempdir(), "unclaudish-state")
STATE_MAX_AGE_SECONDS = 24 * 3600


def read_final_turn_text(transcript_path, last_assistant_message,
                         skip_sidechain=True):
    """Full final-turn text: assistant text blocks collected backward
    until a real user prompt (string content). Falls back to
    last_assistant_message, which probes showed holds only the segment
    after the last tool call.

    A subagent's own transcript marks its entries as sidechain, so the
    subagent linter passes skip_sidechain=False to read them."""
    collected = []
    try:
        # Bounded tail read: transcripts can reach tens of MB, and the
        # hook has a 15s budget. 2MB comfortably covers a final turn.
        if not os.path.isfile(transcript_path):
            raise OSError("not a regular file")
        size = os.path.getsize(transcript_path)
        tail_bytes = 2 * 1024 * 1024
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            data = f.read(tail_bytes)
        lines = data.decode("utf-8", errors="replace").split("\n")
        if size > tail_bytes:
            lines = lines[1:]  # drop the partial first line
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if skip_sidechain and entry.get("isSidechain"):
                continue
            entry_type = entry.get("type")
            if entry_type == "user":
                content = entry.get("message", {}).get("content")
                if isinstance(content, str):
                    break
                continue
            if entry_type != "assistant":
                continue
            blocks = entry.get("message", {}).get("content") or []
            texts = [b.get("text", "") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                collected.insert(0, "\n".join(texts))
    except Exception:
        collected = []

    turn_text = "\n\n".join(collected).strip()
    fallback = (last_assistant_message or "").strip()
    if not turn_text:
        return fallback
    # Async transcript writes can lag; make sure the visible final
    # segment is included.
    if fallback and fallback not in turn_text:
        turn_text = turn_text + "\n\n" + fallback
    return turn_text


def already_blocked(prompt_id):
    marker = os.path.join(STATE_DIR, "blocked-%s" % prompt_id)
    return os.path.exists(marker)


def mark_blocked(prompt_id):
    os.makedirs(STATE_DIR, exist_ok=True)
    # Opportunistic cleanup of stale markers.
    now = time.time()
    try:
        for name in os.listdir(STATE_DIR):
            path = os.path.join(STATE_DIR, name)
            if now - os.path.getmtime(path) > STATE_MAX_AGE_SECONDS:
                os.remove(path)
    except OSError:
        pass
    with open(os.path.join(STATE_DIR, "blocked-%s" % prompt_id), "w"):
        pass


def build_reason(violations):
    from claudish_core import format_violations
    return format_violations(
        violations,
        "Your final message contains writing patterns this project"
        " forbids. Rewrite the message in plain natural language,"
        " keeping every fact, number, name, and caveat unchanged:",
        "Only restyle the same content. Do not add or drop information,"
        " and do not mention this check or that you rewrote anything.",
    )


def main():
    import unclaudish_config
    if unclaudish_config.disabled():
        return

    hook_input = json.load(sys.stdin)
    if hook_input.get("stop_hook_active"):
        return
    prompt_id = str(hook_input.get("prompt_id") or "unknown")
    if already_blocked(prompt_id):
        return

    text = read_final_turn_text(
        hook_input.get("transcript_path", ""),
        hook_input.get("last_assistant_message", ""),
    )
    if not text:
        return

    from claudish_core import lint_hard

    result = lint_hard(text)
    if result["verdict"] != "block":
        return

    mark_blocked(prompt_id)
    print(json.dumps({
        "decision": "block",
        "reason": build_reason(result["hard_violations"]),
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail open, always.
        pass
    sys.exit(0)
