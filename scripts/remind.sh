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
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"Mode: unclaudish-max. Reply like a sharp colleague in chat: the answer, one deciding reason, then offer more in one line. Under 60 words of prose; code and tables do not count. No em dashes, no flattery, no (not X, but Y) framing, no dramatic fragments. Never mention this reminder."}}';;
  *)
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"Reminder: plain natural language, at answer length. Give the answer and the deciding reason, then stop. No em dashes, no (not X, but Y) framing, no flattery, no dramatic fragments. Never mention this reminder."}}';;
esac
exit 0
