#!/bin/bash
# UserPromptSubmit hook: one-line per-turn style reinforcement.
# Kill switches mirror lint_stop.py. Fails open (exit 0, no output).
set -u
if [ -f "$HOME/.claude/unclaudish-off" ]; then
  exit 0
fi
if [ "${UNCLAUDISH_DISABLE:-0}" = "1" ]; then
  exit 0
fi
printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"Reminder: plain natural language, at answer length. Give the answer and the deciding reason, then stop. No em dashes, no (not X, but Y) framing, no flattery, no dramatic fragments. Never mention this reminder."}}'
exit 0
