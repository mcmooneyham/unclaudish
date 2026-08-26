#!/usr/bin/env python3
"""Ablation eval runner.

Runs every (arm, prompt, trial) cell as an isolated headless Claude
Code session with a sandboxed HOME (keychain still authenticates, so
no user CLAUDE.md, settings, or plugins leak into any arm), captures
the reply plus token usage, and stores one JSON file per run.

Usage:
  python3 eval/run_eval.py --trials 3 --out eval/results/main
  python3 eval/run_eval.py --pilot          (3 prompts, A0/A2/A6 only)

Requires eval/build_arms.py to have been run first.
"""

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import claudish_core  # noqa: E402

ARM_PLUGINS = os.path.join(REPO, "eval", "arm-plugins")
SANDBOX_HOME = os.path.join(REPO, "eval", "home-sandbox")
# Neutral cwd: no CLAUDE.md, no .claude/, so no project context leaks.
WORKDIR = os.path.join(REPO, "eval", "workdir")
DEFAULT_MODEL = "claude-sonnet-5"
CHEAP_INSTRUCTION = (
    "Write in plain natural language: no em dashes, no 'not X, but Y'"
    " framing, no flattery, no dramatic fragments."
)

ARMS = {
    "A0-baseline": {},
    "A1-cheap": {"append": CHEAP_INSTRUCTION},
    "A2-style": {"plugin": "style-only"},
    "A3-remind": {"plugin": "remind-only"},
    "A4-stop": {"plugin": "stop-only"},
    "A5-style-remind": {"plugin": "style-remind"},
    "A6-full": {"plugin": "full"},
    "M2-style-max": {"plugin": "style-only-max"},
    "M5-style-remind-max": {"plugin": "style-remind-max"},
    "M6-full-max": {"plugin": "full-max"},
}

PILOT_ARMS = ["A0-baseline", "A2-style", "A6-full"]
PILOT_PROMPTS = ["bug-explain", "arch-opinion", "correction-turn"]


def check_prompt_purity(prompts):
    dirty = []
    for prompt in prompts:
        result = claudish_core.evaluate(prompt["prompt"])
        if result["hard_violations"]:
            dirty.append((prompt["id"], result["hard_violations"]))
    if dirty:
        raise SystemExit("claudish in eval prompts: %s" % dirty)


def run_cell(arm_name, arm_config, prompt, trial, out_dir, model,
             real_home=False):
    out_path = os.path.join(
        out_dir, arm_name, "%s-r%d.json" % (prompt["id"], trial)
    )
    if os.path.exists(out_path):
        return "skip"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    disabled = {}
    registry = os.path.expanduser(
        "~/.claude/plugins/installed_plugins.json")
    try:
        for name in json.load(open(registry)).get("plugins", {}):
            disabled[name] = False
    except (OSError, ValueError):
        pass
    command = ["claude", "-p", "--model", model,
               "--output-format", "json", "--tools", "",
               "--settings", json.dumps({"enabledPlugins": disabled})]
    if "plugin" in arm_config:
        command += ["--plugin-dir",
                    os.path.join(ARM_PLUGINS, arm_config["plugin"])]
    if "append" in arm_config:
        command += ["--append-system-prompt", arm_config["append"]]

    # Fresh unique cwd per run: harness memory is keyed by project
    # path, so this prevents any cross-run memory contamination.
    cell_workdir = os.path.join(WORKDIR, uuid.uuid4().hex[:12])
    os.makedirs(cell_workdir, exist_ok=True)
    env = dict(os.environ)
    # Bill via the keychain OAuth session, never an API key
    for key_var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key_var, None)
    if not real_home:
        env["HOME"] = SANDBOX_HOME
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, input=prompt["prompt"].encode(),
            capture_output=True, env=env, timeout=300,
            cwd=cell_workdir,
        )
        payload = json.loads(proc.stdout)
    except Exception as error:
        payload = {"harness_error": str(error)}
    finally:
        shutil.rmtree(cell_workdir, ignore_errors=True)
    record = {
        "arm": arm_name,
        "prompt_id": prompt["id"],
        "trial": trial,
        "model": model,
        "wall_seconds": round(time.monotonic() - started, 1),
        "response": payload,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return "ok" if "result" in payload else "error"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", default=None)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--arms", default=None,
                        help="comma-separated arm names to run")
    parser.add_argument("--real-home", action="store_true",
                        help="OAuth subscription billing; caller must "
                             "neutralize ~/.claude/CLAUDE.md first")
    args = parser.parse_args()

    with open(os.path.join(REPO, "eval", "prompts.json"),
              encoding="utf-8") as f:
        prompts = json.load(f)["prompts"]
    check_prompt_purity(prompts)

    arms = dict(ARMS)
    if args.arms:
        wanted = set(args.arms.split(","))
        arms = {k: v for k, v in arms.items() if k in wanted}
    if args.pilot:
        arms = {k: ARMS[k] for k in PILOT_ARMS}
        prompts = [p for p in prompts if p["id"] in PILOT_PROMPTS]
        args.trials = 5

    out_dir = args.out or os.path.join(
        REPO, "eval", "results", "pilot" if args.pilot else "main")
    os.makedirs(SANDBOX_HOME, exist_ok=True)
    os.makedirs(WORKDIR, exist_ok=True)

    cells = [
        (arm_name, arm_config, prompt, trial)
        for arm_name, arm_config in arms.items()
        for prompt in prompts
        for trial in range(1, args.trials + 1)
    ]
    print("running %d cells with %d workers -> %s"
          % (len(cells), args.workers, out_dir))

    counts = {"ok": 0, "error": 0, "skip": 0}
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = {
            pool.submit(run_cell, a, c, p, t, out_dir,
                        args.model, args.real_home): (a, p["id"], t)
            for a, c, p, t in cells
        }
        for future in concurrent.futures.as_completed(futures):
            status = future.result()
            counts[status] += 1
            arm, pid, trial = futures[future]
            done = sum(counts.values())
            print("[%d/%d] %s %s r%d: %s"
                  % (done, len(cells), arm, pid, trial, status),
                  flush=True)
    print("done:", counts)


if __name__ == "__main__":
    main()
