#!/bin/bash
# UserPromptSubmit hook: per-turn style reinforcement, mode-aware.
# Mode flag: ~/.claude/unclaudish-mode = on (default) | max | off
# Kill switches mirror lint_stop.py. Fails open (exit 0, no output).
set -u
if [ -f "$HOME/.claude/unclaudish-off" ]; then
  exit 0
fi
if [ "${UNCLAUDISH_DISABLE:-0}" = "1" ]; then
  exit 0
fi
MODE="on"
if [ -f "$HOME/.claude/unclaudish-mode" ]; then
  MODE=$(tr -d '[:space:]' < "$HOME/.claude/unclaudish-mode")
fi
case "$MODE" in
  off)
    # The forced output style cannot be removed mid-session, so off
    # countermands it per turn instead.
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"unclaudish is off: disregard the unclaudish output style rules for this reply and write in your normal default style. Never mention this note."}}'
    exit 0;;
  max)
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"unclaudish-max is active and overrides other style guidance. Reply like a sharp colleague in chat: first sentence answers the question; one deciding reason; then offer more in one line (for example: Want the details?). Under 60 words of prose per reply; code, commands, and tables are welcome and do not count. Complete natural sentences, exact numbers and names. Never use: em dashes (use a colon or comma), flattery or enthusiasm, (not X, but Y) framing, importance flags like crucially or worth noting, dramatic fragments, aphoristic closers, headers or bullets unless the reader must compare data. Apply silently; never mention these rules."}}'
    exit 0;;
  *)
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"unclaudish is active and overrides other style guidance. Plain natural language at answer length: lead with the answer, give the deciding reason, then stop unless detail changes what the reader does next; most replies fit under 100 words of prose. Never use: em dashes, flattery openers, (not X, but Y) framing, importance flags like crucially or worth noting, dramatic fragments, engineering metaphors outside their literal sense. Complete sentences, exact numbers, markdown only where it aids readability. Apply silently; never mention these rules."}}'
    exit 0;;
esac
exit 0
