#!/usr/bin/env python3
"""PreToolUse hook: lint comments and prose before they reach a file.

Contract (probe-verified): stdin carries tool_name and tool_input;
denying prints {"hookSpecificOutput": {"hookEventName": "PreToolUse",
"permissionDecision": "deny", "permissionDecisionReason": ...}} and
the model revises its edit and retries.

Scope: hard tier only. Code files are linted on their comment text
alone; markdown and plain text are linted whole. Unknown file types
pass untouched. FAIL OPEN: any internal error allows the write, and
the same content is never denied more than twice per prompt, so a
session can never wedge.
"""

import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KILL_SWITCH = os.path.expanduser("~/.claude/unclaudish-off")
STATE_DIR = os.path.join(tempfile.gettempdir(), "unclaudish-state")
MAX_DENIALS_PER_CONTENT = 2


def deny_count_path(prompt_id, digest):
    safe_prompt = "".join(c for c in str(prompt_id) if c.isalnum())
    return os.path.join(STATE_DIR,
                        "file-%s-%s" % (safe_prompt, digest))


def bump_denials(prompt_id, digest):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = deny_count_path(prompt_id, digest)
    count = 0
    if os.path.exists(path):
        with open(path) as f:
            count = int(f.read() or 0)
    count += 1
    with open(path, "w") as f:
        f.write(str(count))
    return count


def main():
    if os.path.exists(KILL_SWITCH):
        return
    if os.environ.get("UNCLAUDISH_DISABLE") == "1":
        return

    hook_input = json.load(sys.stdin)
    tool_input = hook_input.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    text = tool_input.get("content")
    if text is None:
        text = tool_input.get("new_string")
    if not isinstance(text, str) or not text.strip():
        return

    ext = os.path.splitext(file_path)[1].lower()
    from claudish_core import PROSE_EXTS, extract_comments, lint_hard

    if ext in PROSE_EXTS:
        prose = text
    else:
        comments = extract_comments(text, ext)
        if not comments:
            return
        prose = "\n".join(comments)

    result = lint_hard(prose)
    if result["verdict"] != "block":
        return

    # Only newly written claudish counts. A violation whose exact text
    # already exists in the on-disk file is being moved, not authored
    # (third-party docstrings, refactors), and must not be denied.
    existing = ""
    try:
        if file_path and os.path.isfile(file_path) and \
                os.path.getsize(file_path) < 2 * 1024 * 1024:
            existing = open(file_path, encoding="utf-8",
                            errors="replace").read()
    except OSError:
        existing = ""
    if existing:
        fresh = []
        for violation in result["hard_violations"]:
            snippets = [s for s in violation["snippets"]
                        if s not in existing]
            if snippets or not violation["snippets"]:
                violation["snippets"] = snippets
                fresh.append(violation)
        result["hard_violations"] = fresh
        if not fresh:
            return

    digest = hashlib.sha256(
        (file_path + "\x00" + text).encode()).hexdigest()[:16]
    prompt_id = hook_input.get("prompt_id") or "unknown"
    if bump_denials(prompt_id, digest) > MAX_DENIALS_PER_CONTENT:
        return

    where = "comments" if ext not in PROSE_EXTS else "text"
    lines = [
        "The %s in this %s contain writing patterns this project"
        " forbids:" % (where, file_path or "file"),
    ]
    for violation in result["hard_violations"]:
        example = violation["snippets"][0] if violation["snippets"] else ""
        lines.append('- %s (%d): "%s". Fix: %s.'
                     % (violation["id"], violation["count"], example,
                        violation["advice"]))
    lines.append(
        "Revise only the flagged wording and retry the same edit."
        " Keep the code and all facts identical. Do not mention"
        " this check."
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "\n".join(lines),
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open, always
    sys.exit(0)
