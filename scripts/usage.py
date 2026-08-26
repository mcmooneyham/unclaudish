#!/usr/bin/env python3
"""Token and cost accounting shared by the stats footer and the ledger.

Two numbers, from two places, because neither one alone can do the job:

- The display hook runs before Claude Code writes the assistant record,
  so the only tokens available there are estimated from the text.
- The Stop hook runs after that record is written, so it can read the
  turn's real usage. It appends to a per-session ledger, and the next
  footer shows the running total from it.

Rates are Anthropic's first-party prices per million tokens as
(input, output). Cache reads bill at a tenth of the input rate.
"""

import json
import os
import re
import tempfile

LEDGER_ROOT = os.path.join(tempfile.gettempdir(), "unclaudish-usage")
LEDGER_MAX_AGE = 7 * 24 * 3600
CHARS_PER_TOKEN = 4.0

RATES = {"fable": (10.0, 50.0), "opus": (5.0, 25.0),
         "sonnet": (2.0, 10.0), "haiku": (1.0, 5.0)}


def safe(name):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(name))[:64] or "x"


def estimate_tokens(text):
    """Rough output-token count for text the model just produced.

    Four characters per token is the usual English approximation. It
    cannot see thinking tokens, so it reads low on reasoning turns.
    """
    return int(round(len(text or "") / CHARS_PER_TOKEN))


def cost_for(model, input_tokens, cache_read_tokens, output_tokens):
    """Dollar estimate, or None when the model is not priced here."""
    for key, (in_rate, out_rate) in RATES.items():
        if key in (model or ""):
            return (input_tokens * in_rate
                    + cache_read_tokens * in_rate * 0.1
                    + output_tokens * out_rate) / 1e6
    return None


def turn_totals(transcript_path):
    """This turn's real usage, read back from the transcript tail.

    Returns None when the transcript has no assistant usage yet, which
    is the normal case while a reply is still being displayed.
    """
    try:
        if not transcript_path or not os.path.isfile(transcript_path):
            return None
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as handle:
            handle.seek(max(0, size - 2 * 1024 * 1024))
            lines = handle.read().decode("utf-8", "replace").split("\n")
        if size > 2 * 1024 * 1024:
            lines = lines[1:]
        totals = {"output_tokens": 0, "thinking_tokens": 0,
                  "input_tokens": 0, "cache_read_tokens": 0,
                  "context_tokens": 0, "model": ""}
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
            message = entry.get("message") or {}
            usage = message.get("usage") or {}
            totals["output_tokens"] += usage.get("output_tokens") or 0
            totals["thinking_tokens"] += (
                usage.get("output_tokens_details") or {}).get(
                    "thinking_tokens") or 0
            totals["input_tokens"] += usage.get("input_tokens") or 0
            totals["cache_read_tokens"] += (
                usage.get("cache_read_input_tokens") or 0)
            # Every call in a turn re-reads the whole conversation, so
            # summing input would multiply the context by the number of
            # calls. The largest single call is the context size.
            totals["context_tokens"] = max(
                totals["context_tokens"],
                (usage.get("input_tokens") or 0)
                + (usage.get("cache_read_input_tokens") or 0)
                + (usage.get("cache_creation_input_tokens") or 0))
            totals["model"] = message.get("model") or totals["model"]
        if not totals["output_tokens"]:
            return None
        totals["cost_usd"] = cost_for(
            totals["model"], totals["input_tokens"],
            totals["cache_read_tokens"], totals["output_tokens"])
        return totals
    except Exception:
        return None


def turn_totals_wait(transcript_path, timeout=2.0, interval=0.025):
    """turn_totals, but wait briefly for the record to be written.

    Stop fires as the turn ends, sometimes a moment before Claude Code
    flushes the assistant record, so reading immediately can miss it.
    This runs after the reply is on screen, so a short wait costs the
    user nothing.
    """
    import time
    deadline = time.monotonic() + timeout
    while True:
        totals = turn_totals(transcript_path)
        if totals or time.monotonic() >= deadline:
            return totals
        time.sleep(interval)


def ledger_path(session_id):
    return os.path.join(LEDGER_ROOT, safe(session_id) + ".json")


def read_ledger(session_id):
    try:
        with open(ledger_path(session_id)) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(session_id, prompt_id, totals):
    """Store one turn's usage, keyed by prompt so a re-fire cannot
    double count."""
    if not totals:
        return {}
    ledger = read_ledger(session_id)
    ledger[safe(prompt_id)] = {
        "output_tokens": totals["output_tokens"],
        "thinking_tokens": totals["thinking_tokens"],
        "context_tokens": totals.get("context_tokens", 0),
        "cost_usd": totals.get("cost_usd"),
    }
    try:
        os.makedirs(LEDGER_ROOT, exist_ok=True)
        temp_path = ledger_path(session_id) + ".tmp"
        with open(temp_path, "w") as handle:
            json.dump(ledger, handle)
        os.replace(temp_path, ledger_path(session_id))
        prune()
    except OSError:
        pass
    return ledger


def last_cost(session_id):
    """Dollar cost of the last completed turn, or None."""
    entry = last_turn(session_id)
    return entry.get("cost_usd") if entry else None


def money(amount):
    """Small turns need more decimals than a session total does."""
    if amount is None:
        return ""
    if amount >= 1:
        return "$%.2f" % amount
    if amount >= 0.01:
        return "$%.3f" % amount
    return "$%.4f" % amount


def session_totals(session_id):
    """Turns, output tokens, and dollars recorded so far this session."""
    ledger = read_ledger(session_id)
    turns = len(ledger)
    tokens = sum(t.get("output_tokens") or 0 for t in ledger.values())
    priced = [t.get("cost_usd") for t in ledger.values()
              if t.get("cost_usd") is not None]
    return {"turns": turns, "output_tokens": tokens,
            "cost_usd": sum(priced) if priced else None}


def last_turn(session_id):
    """The most recent recorded turn, or None."""
    ledger = read_ledger(session_id)
    values = list(ledger.values())
    return values[-1] if values else None


def last_context_tokens(session_id):
    """Conversation size at the last completed turn, or None.

    Read as the context the model works against, not as tokens spent:
    almost all of it is cached and billed at a tenth of the input rate.
    """
    ledger = read_ledger(session_id)
    for entry in reversed(list(ledger.values())):
        tokens = entry.get("context_tokens")
        if tokens:
            return tokens
    return None


def last_thinking_tokens(session_id):
    """Thinking tokens from the last completed turn, or None.

    Thinking is invisible to the display hook, so this is the previous
    turn's figure, one behind the reply it sits under.
    """
    entry = last_turn(session_id)
    if entry is None:
        return None
    return entry.get("thinking_tokens")


def compact(number):
    """5933 becomes 5.9k, 31000 becomes 31k, 800 stays 800."""
    if number is None:
        return ""
    if number < 1000:
        return str(int(number))
    if number < 10000:
        return "%.1fk" % (number / 1000.0)
    if number < 1_000_000:
        return "%dk" % round(number / 1000.0)
    return "%.1fM" % (number / 1_000_000.0)


def prune(now=None):
    """Drop ledgers from sessions that ended a week ago."""
    import time
    now = now or time.time()
    try:
        for name in os.listdir(LEDGER_ROOT):
            path = os.path.join(LEDGER_ROOT, name)
            if now - os.path.getmtime(path) > LEDGER_MAX_AGE:
                os.remove(path)
    except OSError:
        pass
