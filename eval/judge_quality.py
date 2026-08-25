#!/usr/bin/env python3
"""Task-quality judge for ablation eval outputs.

A style win is worthless if answers got worse, so every run is scored
for key-fact coverage against its prompt's rubric by a cheap LLM
judge. Results are written next to the run files as
<run>.quality.json and summarized per arm.

Usage: python3 eval/judge_quality.py eval/results/main [--workers 4]
"""

import argparse
import concurrent.futures
import glob
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_HOME = os.path.join(REPO, "eval", "home-sandbox")
WORKDIR = os.path.join(REPO, "eval", "workdir")


def load_rubrics():
    with open(os.path.join(REPO, "eval", "prompts.json"),
              encoding="utf-8") as f:
        prompts = json.load(f)["prompts"]
    return {p["id"]: p for p in prompts}


def judge_one(path, rubrics):
    quality_path = path.replace(".json", ".quality.json")
    if quality_path.endswith(".quality.quality.json"):
        return None
    if os.path.exists(quality_path):
        return "skip"
    with open(path, encoding="utf-8") as f:
        record = json.load(f)
    text = record.get("response", {}).get("result")
    rubric = rubrics.get(record.get("prompt_id"))
    if not isinstance(text, str) or rubric is None:
        return "error"
    prompt = (
        "Judge whether this answer covers the required facts.\n"
        "TASK GIVEN TO THE ASSISTANT:\n%s\n\nANSWER:\n%s\n\n"
        "REQUIRED FACTS:\n%s\n\nReply with ONLY JSON: "
        '{"facts_present": <int>, "facts_total": <int>, '
        '"missing": ["..."]}'
        % (rubric["prompt"], text, json.dumps(rubric["key_facts"]))
    )
    env = dict(os.environ)
    # Bill via the keychain OAuth session, never an API key
    for key_var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key_var, None)
    # Judging needs no isolation, only auth: use the real HOME.
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", "haiku", "--tools", "",
             "--output-format", "json"],
            input=prompt.encode(), capture_output=True, env=env,
            timeout=180, cwd=WORKDIR,
        )
        reply = json.loads(proc.stdout).get("result", "")
        start, end = reply.find("{"), reply.rfind("}")
        verdict = json.loads(reply[start:end + 1])
    except Exception as error:
        return "error: %s" % error
    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2)
    return "ok"


def summarize(results_dir):
    by_arm = defaultdict(list)
    for path in glob.glob(os.path.join(results_dir, "*",
                                       "*.quality.json")):
        run_path = path.replace(".quality.json", ".json")
        with open(run_path, encoding="utf-8") as f:
            arm = json.load(f)["arm"]
        with open(path, encoding="utf-8") as f:
            verdict = json.load(f)
        if verdict.get("facts_total"):
            by_arm[arm].append(
                verdict["facts_present"] / verdict["facts_total"])
    print("%-16s %4s %s" % ("arm", "n", "fact coverage mean"))
    for arm, ratios in sorted(by_arm.items()):
        print("%-16s %4d %.3f" % (arm, len(ratios),
                                  statistics.mean(ratios)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    rubrics = load_rubrics()
    paths = [p for p in glob.glob(
        os.path.join(args.results_dir, "*", "*.json"))
        if not p.endswith(".quality.json")]
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        statuses = list(pool.map(
            lambda p: judge_one(p, rubrics), paths))
    print("judged:", len([s for s in statuses if s == "ok"]),
          "skipped:", len([s for s in statuses if s == "skip"]),
          "errors:", len([s for s in statuses
                          if s and s.startswith("error")]))
    summarize(args.results_dir)


if __name__ == "__main__":
    main()
