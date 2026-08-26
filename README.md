# Unclaudish

A Claude Code plugin that makes Claude write plain natural language
instead of "claudish": the register full of em-dashes, "not X, but Y"
framing, engineering jargon, and 650-word answers to questions that
needed 80.

Without the plugin (the opening of a 653-word answer):

> Recommendation: move the queue into Postgres. It is the only
> option of the three that fixes both failure modes you have
> actually experienced, and it does so with infrastructure you
> already operate well.
>
> **Why Postgres wins against your specific constraints** ...

With it, the whole answer:

> Move the queue into Postgres. Enqueueing the confirmation job in
> the same transaction as the orders row eliminates both failure
> modes you hit: the dropped acknowledged jobs and the
> row-without-job case. Your multi-AZ RDS with tested PITR already
> provides the durability, and 6,000 jobs/hour against a 5-second
> start budget is trivial for FOR UPDATE SKIP LOCKED polling. Want
> the schema and worker loop?

## Measured results

One benchmark run, same prompt and model, three configurations:

| Answer | Words | Output tokens | Thinking tokens | Seconds | Cost |
|---|---|---|---|---|---|
| No plugin | 653 | 2854 | 1439 | 43.5 | $0.1490 |
| unclaudish | 223 (-66%) | 1127 (-61%) | 616 (-57%) | 16.6 (-62%) | $0.0641 (-57%) |
| unclaudish-max | 63 **(-90%)** | 690 **(-76%)** | 537 **(-63%)** | 10.1 **(-77%)** | $0.0414 **(-72%)** |

Across the full ablation in `eval/` (45 runs per arm per model), 80%
of no-plugin Sonnet 5 replies contained a pattern the linter blocks;
with the plugin, 0%, with no loss in separately judged answer
quality.

## What it does

1. **Two output styles.** `unclaudish`: plain language at answer
   length. `unclaudish-max`: the answer, one reason, an offer of
   more.
2. **A style linter.** Seven precise patterns (em-dashes, flattery
   openers, "here's the thing", and similar) are rejected before
   they reach your screen or your files, with feedback so Claude
   rewrites. Pure regex, fails open, zero false positives across
   714 real messages.
3. **A per-turn reminder** so the style holds in long sessions.
4. **`/unclaudish:rewrite`**, a skill that rewrites existing text
   into plain English without changing meaning.

## Install

    /plugin marketplace add mcmooneyham/unclaudish
    /plugin install unclaudish@unclaudish

Or try it without installing:

    claude --plugin-dir /path/to/unclaudish

## Modes and styles

The `unclaudish` style applies automatically. Switch instantly,
mid-session:

    /unclaudish:mode max
    /unclaudish:mode on
    /unclaudish:mode off

`off` turns the register off: linters stop, the reminder stops, and
the style is countermanded each turn. You can also pick styles the
standard way via `/config` (takes effect after `/clear`).

## Stats footer

    /unclaudish:stats on

Appends a footer under each reply: pattern counts, words, a
cleanliness percentage, the turn's tokens, and estimated cost.
Display only.

## Demo and benchmark

    python3 demo/serve.py
    python3 demo/bench.py

The demo answers any task three ways side by side. The benchmark
runs a matrix of tasks across models and effort levels with a live
dashboard; results persist to `demo/bench-results/`. Both run on
your own Claude Code login.

## Turn it off

- `touch ~/.claude/unclaudish-off` (delete to resume)
- or `UNCLAUDISH_DISABLE=1`, or disable in `/plugin`

## Development

- Tests: `python3 tests/test_core.py`
- Score any text: `python3 scripts/claudish_core.py < file.md`
- Ablation eval: `python3 eval/build_arms.py`, then
  `python3 eval/run_eval.py`, then
  `python3 eval/analyze.py eval/results/main`

## Credits

Rewrite rules and parts of the pattern catalog adapted from
MIT-licensed [programasweights/claudish](https://github.com/programasweights/claudish);
the per-turn reinforcement pattern follows
[JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman);
research also drew on
[claude-slop-detector](https://github.com/aplaceforallmystuff/claude-slop-detector).

Released under the MIT license; the full text is in `LICENSE`.
