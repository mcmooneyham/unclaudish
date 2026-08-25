#!/usr/bin/env python3
"""Analyze ablation eval results.

Reads run JSONs from a results directory, scores every reply with the
shared engine (all tiers), and reports per-arm statistics plus paired
per-prompt deltas against the baseline arm with bootstrap CIs.

Usage: python3 eval/analyze.py eval/results/main [--json out.json]
"""

import argparse
import glob
import json
import os
import random
import re
import statistics
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import claudish_core  # noqa: E402

BASELINE = "A0-baseline"
# Runs polluted by cross-run memory leakage (fixed by per-cell cwds in
# run_eval); excluded from all statistics.
TAINT_RE = re.compile(
    r"<invoke\b|MEMORY\.md|<function_results|antml|home-sandbox/\.claude")
# Held-out soft metrics: never named in the style/reminder text, so
# improvement here shows real register change, not pattern-dodging.
HELD_OUT = ("rhetorical_pivot", "uniformity", "triads", "exclaim")


def load_runs(results_dir):
    runs = []
    for path in glob.glob(os.path.join(results_dir, "*", "*.json")):
        if path.endswith(".quality.json"):
            continue
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        response = record.get("response", {})
        text = response.get("result")
        if response.get("is_error") or not isinstance(text, str):
            record["error"] = True
            runs.append(record)
            continue
        if TAINT_RE.search(text):
            record["error"] = True
            record["taint"] = True
            runs.append(record)
            continue
        scored = claudish_core.evaluate(text)
        usage = response.get("usage", {})
        details = usage.get("output_tokens_details", {})
        record.update({
            "text": text,
            "score": scored["score"],
            "hard_count": sum(v["count"]
                              for v in scored["hard_violations"]),
            "held_out_points": round(sum(
                scored["metrics"].get(m, {}).get("points", 0.0)
                for m in HELD_OUT), 2),
            "metrics": {k: v["points"]
                        for k, v in scored["metrics"].items()},
            "output_tokens": usage.get("output_tokens"),
            "thinking_tokens": details.get("thinking_tokens"),
            "cost_usd": response.get("total_cost_usd"),
            "num_turns": response.get("num_turns"),
        })
        runs.append(record)
    return runs


def arm_stats(runs):
    by_arm = defaultdict(list)
    for run in runs:
        if not run.get("error"):
            by_arm[run["arm"]].append(run)
    stats = {}
    for arm, arm_runs in sorted(by_arm.items()):
        scores = [r["score"] for r in arm_runs]
        stats[arm] = {
            "n": len(arm_runs),
            "score_mean": round(statistics.mean(scores), 2),
            "score_median": round(statistics.median(scores), 2),
            "score_sd": round(statistics.pstdev(scores), 2),
            "hard_violation_runs": sum(
                1 for r in arm_runs if r["hard_count"] > 0),
            "held_out_mean": round(statistics.mean(
                [r["held_out_points"] for r in arm_runs]), 2),
            "output_tokens_mean": round(statistics.mean(
                [r["output_tokens"] or 0 for r in arm_runs])),
            "thinking_tokens_mean": round(statistics.mean(
                [r["thinking_tokens"] or 0 for r in arm_runs])),
            "cost_usd_mean": round(statistics.mean(
                [r["cost_usd"] or 0 for r in arm_runs]), 4),
            "extra_turns": sum(
                (r["num_turns"] or 1) - 1 for r in arm_runs),
        }
    return stats


def paired_deltas(runs, arm, seed=7, resamples=2000):
    """Per (prompt, trial) score deltas: arm minus baseline."""
    baseline = {(r["prompt_id"], r["trial"]): r["score"]
                for r in runs
                if r["arm"] == BASELINE and not r.get("error")}
    deltas = [
        r["score"] - baseline[(r["prompt_id"], r["trial"])]
        for r in runs
        if (r["arm"] == arm and not r.get("error")
            and (r["prompt_id"], r["trial"]) in baseline)
    ]
    if not deltas:
        return None
    rng = random.Random(seed)
    medians = sorted(
        statistics.median(rng.choices(deltas, k=len(deltas)))
        for _ in range(resamples)
    )
    return {
        "n_pairs": len(deltas),
        "median_delta": round(statistics.median(deltas), 2),
        "ci95": [round(medians[int(resamples * 0.025)], 2),
                 round(medians[int(resamples * 0.975)], 2)],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    runs = load_runs(args.results_dir)
    errors = [r for r in runs if r.get("error")]
    tainted = [r for r in runs if r.get("taint")]
    if tainted:
        print("excluded %d memory-tainted runs" % len(tainted))
    stats = arm_stats(runs)
    report = {"arms": stats, "errors": len(errors), "deltas": {}}
    for arm in stats:
        if arm != BASELINE:
            report["deltas"][arm] = paired_deltas(runs, arm)

    header = ("arm", "n", "score med", "sd", "hardN", "heldout",
              "out-tok", "think-tok", "cost$", "xturns")
    print("%-16s %4s %10s %6s %6s %8s %8s %10s %8s %7s" % header)
    for arm, s in stats.items():
        print("%-16s %4d %10.2f %6.2f %6d %8.2f %8d %10d %8.4f %7d"
              % (arm, s["n"], s["score_median"], s["score_sd"],
                 s["hard_violation_runs"], s["held_out_mean"],
                 s["output_tokens_mean"], s["thinking_tokens_mean"],
                 s["cost_usd_mean"], s["extra_turns"]))
    print("\npaired median deltas vs %s (negative = less claudish):"
          % BASELINE)
    for arm, delta in report["deltas"].items():
        if delta:
            print("  %-16s %6.2f  CI95 %s  (n=%d)"
                  % (arm, delta["median_delta"], delta["ci95"],
                     delta["n_pairs"]))
    if errors:
        print("\nERRORS: %d runs failed" % len(errors))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print("wrote", args.json)


if __name__ == "__main__":
    main()
