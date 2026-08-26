# Unclaudish

### A Claude Code plugin that makes Claude write plain natural language

### No Plugin (the opening of a 653-word answer):

> Recommendation: move the queue into Postgres. It is the only
> option of the three that fixes both failure modes you have
> actually experienced, and it does so with infrastructure you
> already operate well. [...]
>
> [The full response is below]

### Unclaudish Plugin (Yes, this really is the entire reply):

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


<strong>The full prompt</strong>

> We need a decision on our job queue. Recommend one option.
>
> Current state: a Redis list consumed by 6 worker pods with BRPOP. About 2,000 jobs/hour average, 6,000/hour peak on Monday mornings. Job types: order confirmation emails, invoice PDF generation, webhook fan-out to customer endpoints, and a nightly export. Jobs must not be lost; last month a Redis restart during a maintenance window dropped roughly 400 acknowledged jobs and two customers noticed missing invoices before we did.
>
> Constraints: team of 4 backend engineers, none with deep Redis operational experience. We already run Postgres 16 (RDS, multi-AZ) for the application database, with tested backups and point-in-time recovery. The checkout path writes an orders row and then enqueues the confirmation job as two separate operations, and we have seen the row-committed-but-job-missing case in the wild. Latency requirement: jobs should start within 5 seconds of enqueue; nothing is real-time. Budget pressure means we would rather not add a managed queue service (SQS was vetoed by finance last quarter for procurement reasons, revisitable next year).
>
> Options on the table: keep Redis and harden it (AOF always, replica, runbooks), move the queue into Postgres, or adopt RabbitMQ on a small cluster. Pick one and justify it against these specific constraints.


<details>
<summary><strong>No plugin (653 words)</strong></summary>

> Recommendation: move the queue into Postgres. It is the only option of the three that fixes both failure modes you have actually experienced, and it does so with infrastructure you already operate well.
>
> Why Postgres wins against your specific constraints
>
> It's the only option that fixes the dual-write bug. The row-committed-but-job-missing case at checkout exists because the order INSERT and the enqueue are separate operations against separate systems. With the queue in Postgres, the enqueue becomes an INSERT into a jobs table inside the same transaction as the orders row. Either both commit or neither does. Hardened Redis and RabbitMQ both leave this bug in place; the standard fix for it (a transactional outbox) is a Postgres job table anyway, at which point the broker behind it is redundant at your scale.
>
> Durability is inherited, not built. You already have RDS multi-AZ, tested backups, and point-in-time recovery. A committed job row has the same durability guarantees as an order. Compare that to hardening Redis: appendfsync always narrows the loss window but Redis replica failover can still drop acknowledged writes, and BRPOP itself is at-most-once (a worker that pops and then crashes loses the job). To get reliable delivery you would need LMOVE with per-worker processing lists plus a reaper for orphaned jobs, which means your team of four, with no deep Redis experience, would be building and operating a bespoke reliable-queue layer on the system that already burned you.
>
> The scale makes this easy. 6,000 jobs/hour peak is under 2 jobs/second. SELECT ... FOR UPDATE SKIP LOCKED comfortably handles hundreds of jobs/second; your 6 workers polling at 1-second intervals meet the 5-second start-latency requirement with a wide margin. Completed rows at roughly 50k/day are trivial to prune with a nightly DELETE, so autovacuum and table bloat are non-issues at this volume.
>
> It fits the team and the budget. Zero new stateful systems, zero procurement, and the operational skills required (Postgres monitoring, backups, query plans) are ones you already have. RabbitMQ would genuinely solve broker durability via quorum queues and publisher confirms, but it adds an Erlang-based cluster for four engineers to learn, patch, and page on, and it still would not fix the checkout dual-write without an outbox. That is a lot of operational surface to buy capabilities you do not need below 2 jobs/second.
>
> How to do it
>
> Use an existing Postgres-backed job library rather than hand-rolling: pg-boss (Node), Oban (Elixir), Solid Queue (Rails), River (Go), or Procrastinate (Python), depending on your stack. They already implement the pattern you need:
>
>     -- Claim the next runnable job without blocking other workers
>     SELECT id FROM jobs
>     WHERE state = 'available' AND run_at <= now()
>     ORDER BY run_at
>     FOR UPDATE SKIP LOCKED
>     LIMIT 1;
>
> Three things to get right, all of which the libraries above handle:
>
> Claim, then release the lock, then work. Mark the job as running with a locked_by and locked_at, commit, and execute the handler outside any transaction. This matters for the webhook fan-out, where a slow customer endpoint should not hold a row lock or a long transaction open.
>
> Lease expiry for crashed workers. A sweeper re-enqueues jobs whose locked_at is stale. The nightly export just needs a longer lease or a heartbeat that extends it.
>
> Retries with backoff and a dead-letter state, so a persistently failing webhook target does not retry forever.
>
> One caveat to monitor rather than pre-engineer: the queue shares the application database, so a runaway job-table query could affect checkout. At your volume this is a theoretical risk, but put the job tables in their own schema, alert on queue depth and oldest-available-job age, and you will see any problem long before customers do. If volume ever grows 50x, revisit SQS when procurement reopens next year; the enqueue-in-transaction pattern converts cleanly to an outbox that relays into an external queue, so nothing about this choice paints you into a corner.
</details>

<details>
<summary><strong>unclaudish (223 words)</strong></summary>

> Move the queue into Postgres.
>
> The deciding constraints are durability and the dual-write bug. In Postgres, the checkout path can insert the orders row and the job row in one transaction, which eliminates the row-committed-but-job-missing case, and jobs inherit the durability you already trust: multi-AZ RDS, tested backups, point-in-time recovery. A Redis restart cannot lose them.
>
> The load is small. Peak of 6,000 jobs/hour is under 2 jobs/second. Six workers polling with SELECT ... FOR UPDATE SKIP LOCKED every second meets the 5-second start requirement with a large margin, and LISTEN/NOTIFY can cut that further if you want.
>
> Against the alternatives: hardened Redis still needs Redis operational skill your team lacks, and AOF plus a replica narrows the loss window without closing it or fixing the dual-write problem. RabbitMQ adds a new cluster for 4 engineers to run and still leaves enqueue outside the order transaction. Both add operational surface; neither adds durability beyond what Postgres already gives you.
</details>

<details>
<summary><strong>unclaudish-max (63 words)</strong></summary>

> Move the queue into Postgres. Enqueueing the confirmation job in the same transaction as the orders row eliminates both failure modes you hit: the dropped acknowledged jobs and the row-without-job case. Your multi-AZ RDS with tested PITR already provides the durability, and 6,000 jobs/hour against a 5-second start budget is trivial for FOR UPDATE SKIP LOCKED polling. Want the schema and worker loop?
</details>


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
    /reload-plugins

`/reload-plugins` activates it in the session you are already in, so
you can install mid-project without `/clear` and without losing
context. The style applies from your next message.

Or try it without installing:

    claude --plugin-dir /path/to/unclaudish

## Modes and styles

The plain style turns itself on at install and writes `outputStyle`
into `~/.claude/settings.json`, so every project uses it. Switch
registers any time:

    /unclaudish:mode max
    /unclaudish:mode on
    /unclaudish:mode off

A switch is in force from your next message, with no `/clear` and
no lost context: the turn hook injects the whole style into the
running session. `/config` catches up in your next session. Picking
a style in `/config` works too, and the plugin follows it.

`off` turns the register off: linters stop, the reminder stops, and
the style is countermanded each turn.

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

    /unclaudish:mode off

That also clears the `outputStyle` setting, so run it before you
uninstall to leave no trace in `~/.claude/settings.json`. Uninstalling
first is harmless: the leftover style name stops resolving and Claude
Code falls back to its default style.

Other switches:

- `touch ~/.claude/unclaudish-off` (delete to resume)
- `UNCLAUDISH_DISABLE=1`, or disable in `/plugin`

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
