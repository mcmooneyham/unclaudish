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
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATE_DIR = os.path.join(tempfile.gettempdir(), "unclaudish-state")
MAX_DENIALS_PER_CONTENT = 2

# A note to whoever edits this file next, not prose an audience reads.
INTERNAL_MARKER_RE = re.compile(r"^\s*(?:TODO|FIXME|XXX|HACK|NOTE)\b",
                                re.I)


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


def read_file(file_path):
    """The file as it stands, or empty when it cannot be read."""
    try:
        if file_path and os.path.isfile(file_path) and \
                os.path.getsize(file_path) < 2 * 1024 * 1024:
            return open(file_path, encoding="utf-8",
                        errors="replace").read()
    except OSError:
        pass
    return ""


def projected_file(existing, tool_input):
    """The file as it would read after this edit, or None.

    An edit sends one fragment, and a fragment does not parse, so a
    docstring inside it cannot be told apart from a data literal.
    Applying the edit in memory gives the parser a whole file to read.
    """
    old_string = tool_input.get("old_string")
    new_string = tool_input.get("new_string")
    if not existing or not isinstance(old_string, str) \
            or not isinstance(new_string, str) or not old_string:
        return None
    if old_string not in existing:
        return None
    count = -1 if tool_input.get("replace_all") else 1
    return existing.replace(old_string, new_string, count)


def main():
    import unclaudish_config
    if unclaudish_config.disabled():
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

    existing = read_file(file_path)

    if ext in PROSE_EXTS:
        prose = text
    else:
        # Read the comments out of the finished file where possible, so
        # the parser sees real code rather than a fragment, then keep
        # only the comments this edit introduces.
        projected = projected_file(existing, tool_input)
        source = projected if projected is not None else text
        before = set()
        if projected is not None:
            before = {c.strip() for c in extract_comments(existing, ext)}
        comments = [c for c in extract_comments(source, ext)
                    if c.strip() not in before
                    and not INTERNAL_MARKER_RE.match(c)]
        if not comments:
            return
        prose = "\n".join(comments)

    result = lint_hard(prose)
    if result["verdict"] != "block":
        return

    # Only newly written claudish counts. A violation whose exact text
    # already exists in the on-disk file is being moved, not authored
    # (third-party docstrings, refactors), and must not be denied.
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
    from claudish_core import format_violations
    reason = format_violations(
        result["hard_violations"],
        "The %s in this %s contain writing patterns this project"
        " forbids:" % (where, file_path or "file"),
        "Revise only the flagged wording and retry the same edit."
        " Keep the code and all facts identical. Do not mention"
        " this check.",
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open, always
    sys.exit(0)
