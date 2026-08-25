# Unclaudish

A Claude Code plugin that makes Claude write plain natural language
instead of "claudish": the register full of em-dashes, "not X, but Y"
framing, engineering jargon, and 700-word answers to yes-or-no
questions.

Without the plugin:

> Alice's approval is the hard gate here; skip it and you've built a
> footgun into the load-bearing part of your release process.

With it:

> Do not release until Alice approves it.

## Measured results

From a 7-arm ablation (45 runs per arm per model, 15 task types,
paired prompts, harness in `eval/`):

| Sonnet 5 | Replies with blockable claudish | Mean claudish score | Output tokens |
|---|---|---|---|
| No plugin | 80% | 9.36 | 1178 |
| One-line "write plainly" instruction | 51% | 6.66 | 1208 |
| Full plugin (unclaudish style) | **0%** | 0.61 | 347 |
| Full plugin (unclaudish-max style) | **0%** | 0.23 | 282 |

On Opus 5 the baseline was worse (93% of replies contained blockable
claudish) and the results held: the style cut it to 7% and the
linter removed the rest. Answer quality was judged separately and
did not drop; output and thinking tokens fell by half or more
because answers got shorter and deliberation shrank with them.

## What it does

1. **Two output styles.** `unclaudish` (applied automatically):
   plain language at answer length, markdown only where it helps
   readability. `unclaudish-max` (switch via `/output-style`):
   extreme brevity, the answer plus one reason plus an offer of
   more.
2. **A style linter on the Stop hook.** A dependency-free Python
   script checks every final message for seven high-precision
   patterns (em-dashes, flattery openers, "here's the thing", and
   similar). On a hit it blocks once with specific feedback, so
   Claude rewrites before you see it. It fails open: a linter error
   never blocks your session.
3. **A per-turn reminder** so the style holds in long sessions
   (about 35 tokens per turn).
4. **`/unclaudish:rewrite`**, a skill that rewrites existing text or
   files into plain English without changing meaning.

## Install

    /plugin marketplace add mcmooneyham/unclaudish
    /plugin install unclaudish@unclaudish

Or try it without installing:

    claude --plugin-dir /path/to/unclaudish

## Live demo

    python3 demo/serve.py

Opens a local page: pick a task (or write one) and see it answered
three ways side by side (no plugin, unclaudish, unclaudish-max) with
detected-pattern chips, token counts, and cost. Runs on your own
Claude Code login.

## Turn it off

- Pause everything: `touch ~/.claude/unclaudish-off` (delete to
  resume)
- Or set `UNCLAUDISH_DISABLE=1`
- Or disable the plugin in `/plugin`

## How it was validated

- 700+ measured eval runs across Sonnet 5 and Opus 5, with a
  one-line-instruction control arm (the plugin has to beat "just ask
  it to write plainly", and it does)
- An adversarial review pass: 44 findings hunted, 12 confirmed, all
  fixed with regression tests
- 67 unit tests; zero false-positive blocks across 714 real
  assistant messages
- A 10-case meaning-preservation suite for the rewrite skill
  (negations, conditions, numbers, and stated uncertainty all
  survive)

The linter deliberately blocks on only seven patterns. About 30 more
scored patterns (from "the real problem" to "survives scrutiny")
affect a claudish score used in evals but never block, because one
wrong block is worse than a missed claudism. Code blocks, tables,
quoted text, and non-English prose are never linted.

## Development

- Tests: `python3 tests/test_core.py`
- Score any text: `python3 scripts/claudish_core.py < file.md`
- Ablation eval: `python3 eval/build_arms.py`, then
  `python3 eval/run_eval.py`, then
  `python3 eval/analyze.py eval/results/main`

## Credits

The rewrite rules and parts of the pattern catalog are adapted from
the MIT-licensed specs in
[programasweights/claudish](https://github.com/programasweights/claudish).
The per-turn reinforcement pattern follows
[JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman)
(MIT for the files used). Pattern research also drew on the
MIT-licensed
[claude-slop-detector](https://github.com/aplaceforallmystuff/claude-slop-detector).

MIT license.
