#!/usr/bin/env python3
"""SubagentStop hook: hold subagents to the same rules as the session.

The main loop is linted on Stop. Subagents and workflow agents end on
SubagentStop, which takes the same block contract, so this mirrors
lint_stop.py for them: block once, quote the patterns, let the agent
rewrite and finish.

A return value that is structured data, such as JSON a workflow
schema expects, is never linted. Blocking it would corrupt the
caller's result.

Payload fields (probe-verified on Claude Code 2.1.246): agent_id,
agent_type, agent_transcript_path, last_assistant_message,
stop_hook_active.

FAIL OPEN: any internal error lets the agent finish.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unclaudish_config


def looks_structured(text):
    """True when the return value is data rather than prose."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
            return True
        except ValueError:
            pass
    # Fenced JSON is still a structured answer to its caller.
    if stripped.startswith("```") and stripped.endswith("```"):
        inner = stripped.strip("`")
        inner = inner.split("\n", 1)[-1].strip()
        if inner[:1] in "{[":
            try:
                json.loads(inner)
                return True
            except ValueError:
                pass
    return False


def build_reason(violations):
    from claudish_core import format_violations
    return format_violations(
        violations,
        "Your answer contains writing patterns this project forbids."
        " Rewrite it in plain natural language, keeping every fact,"
        " number, name, and caveat unchanged:",
        "Only restyle the same content. Do not add or drop"
        " information. If your caller asked for a specific return"
        " format, keep that format exactly. Do not mention this check.",
    )


def main():
    if unclaudish_config.disabled():
        return
    if not unclaudish_config.subagents_enabled():
        return

    hook_input = json.load(sys.stdin)
    if hook_input.get("stop_hook_active"):
        return

    agent_id = str(hook_input.get("agent_id") or "unknown")
    import lint_stop
    if lint_stop.already_blocked("agent-" + agent_id):
        return

    text = lint_stop.read_final_turn_text(
        hook_input.get("agent_transcript_path")
        or hook_input.get("transcript_path", ""),
        hook_input.get("last_assistant_message", ""),
        skip_sidechain=False,
    )
    if not text or looks_structured(text):
        return

    from claudish_core import lint_hard
    result = lint_hard(text)
    if result["verdict"] != "block":
        return

    lint_stop.mark_blocked("agent-" + agent_id)
    print(json.dumps({
        "decision": "block",
        "reason": build_reason(result["hard_violations"]),
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open, always
    sys.exit(0)
