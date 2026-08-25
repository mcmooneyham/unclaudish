#!/usr/bin/env python3
"""Fidelity suite for the /unclaudish:rewrite skill.

For each case: run the skill on the claudish text in a sandboxed
headless session, then verify (a) the claudish score dropped and the
hard verdict is pass, and (b) an LLM checker confirms every must_keep
fact survives and no must_not distortion appears.

Usage: python3 eval/run_fidelity.py [--cases id1,id2]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import claudish_core  # noqa: E402

SANDBOX_HOME = os.path.join(REPO, "eval", "home-sandbox")
WORKDIR = os.path.join(REPO, "eval", "workdir")
OUT_DIR = os.path.join(REPO, "eval", "results", "fidelity")


def run_claude(prompt, extra_args, timeout=300):
    env = dict(os.environ)
    # Bill via the keychain OAuth session, never an API key
    for key_var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key_var, None)
    env["HOME"] = SANDBOX_HOME
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json"] + extra_args,
        input=prompt.encode(), capture_output=True, env=env,
        timeout=timeout, cwd=WORKDIR,
    )
    return json.loads(proc.stdout)


def rewrite(case):
    prompt = ("/unclaudish:rewrite Rewrite this passage. After any "
              "verification, end your reply with the line "
              "FINAL REWRITE: followed by the complete rewrite and "
              "nothing after it.\n\n" + case["text"])
    response = run_claude(
        prompt,
        ["--model", "claude-sonnet-5", "--plugin-dir", REPO],
    )
    text = response.get("result", "")
    marker = "FINAL REWRITE:"
    if marker in text:
        text = text.split(marker)[-1].strip()
    return text


def judge(case, rewritten):
    checklist = {
        "must_keep": case["must_keep"],
        "must_not": case["must_not"],
    }
    prompt = (
        "You are checking a rewrite for meaning preservation.\n"
        "ORIGINAL:\n%s\n\nREWRITE:\n%s\n\nCHECKLIST:\n%s\n\n"
        "keep_ok = how many must_keep items are present and unchanged "
        "in strength in the rewrite (0 to keep_total). "
        "not_ok = how many must_not items the rewrite successfully "
        "AVOIDS, meaning the bad reading does NOT appear (0 to "
        "not_total; a perfect rewrite scores not_ok == not_total). "
        "List in failures every item that failed, quoting the "
        "problematic rewrite text. Reply with ONLY JSON: "
        '{"keep_ok": <int>, "keep_total": <int>, '
        '"not_ok": <int>, "not_total": <int>, "failures": ["..."]}'
        % (case["text"], rewritten, json.dumps(checklist))
    )
    response = run_claude(prompt, ["--model", "haiku", "--tools", ""])
    text = response.get("result", "")
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=None)
    args = parser.parse_args()

    with open(os.path.join(REPO, "eval", "fidelity_cases.json"),
              encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    os.makedirs(OUT_DIR, exist_ok=True)
    passed = 0
    for case in cases:
        before = claudish_core.evaluate(case["text"])
        try:
            rewritten = rewrite(case)
            after = claudish_core.evaluate(rewritten)
            verdict = judge(case, rewritten)
        except Exception as error:
            print("%-22s ERROR %s" % (case["id"], error))
            continue
        def total_matches(result):
            return sum(m["count"] or 0
                       for m in result["metrics"].values())
        # Cases are short, so rate-based scores floor at 0. Require
        # zero hard violations and no regression on match counts or
        # flat/algorithmic points; the facts judge is the main gate.
        score_ok = (not after["hard_violations"]
                    and total_matches(after) <= total_matches(before)
                    and after["score"] <= before["score"])
        facts_ok = (verdict["keep_ok"] == verdict["keep_total"]
                    and verdict["not_ok"] == verdict["not_total"])
        ok = score_ok and facts_ok
        passed += ok
        print("%-22s %s  score %.1f -> %.1f  facts %d/%d  avoid %d/%d %s"
              % (case["id"], "PASS" if ok else "FAIL",
                 before["score"], after["score"],
                 verdict["keep_ok"], verdict["keep_total"],
                 verdict["not_ok"], verdict["not_total"],
                 ("| " + "; ".join(verdict.get("failures", [])))
                 if not ok else ""))
        with open(os.path.join(OUT_DIR, case["id"] + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump({"case": case, "rewritten": rewritten,
                       "before_score": before["score"],
                       "after_score": after["score"],
                       "judge": verdict}, f, indent=2)
    print("\n%d/%d cases passed" % (passed, len(cases)))


if __name__ == "__main__":
    main()
