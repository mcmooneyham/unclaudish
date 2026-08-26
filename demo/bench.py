#!/usr/bin/env python3
"""Benchmark dashboard for the unclaudish plugin.

Runs a matrix of (prompt x model x effort x N runs), each cell
answered three ways (no plugin, unclaudish, unclaudish-max), with a
live dashboard: aggregate statistics, filterable comparison panels,
and a run list whose entries open into the same per-run view as the
demo. Results are appended to demo/bench-results/ as JSONL.

Usage: python3 demo/bench.py [--port 8766] [--no-browser]
"""

import argparse
import glob
import json
import os
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DEMO_DIR)
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "unclaudish_demo", os.path.join(DEMO_DIR, "serve.py"))
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

ARMS = ("baseline", "unclaudish", "max")


def run_style_streaming(style, text, model, effort, on_partial):
    """Like demo.run_style but streams; on_partial(text_so_far,
    thinking_chars) fires as deltas arrive."""
    import subprocess
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    env.pop("CLAUDE_EFFORT", None)
    if effort != "default":
        env["CLAUDE_EFFORT"] = effort
    command = ["claude", "-p", "--model", model,
               "--output-format", "stream-json",
               "--include-partial-messages", "--verbose",
               "--tools", "", "--disallowedTools", "mcp__*"]
    if demo.STYLE_PACKS[style]:
        command += ["--plugin-dir", demo.STYLE_PACKS[style]]
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env, cwd=demo.WORKDIR)
    proc.stdin.write(text.encode())
    proc.stdin.close()
    accumulated, thinking_chars, final = [], 0, None
    last_push = 0.0
    for raw in proc.stdout:
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if event.get("type") == "stream_event":
            delta = (event.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta":
                accumulated.append(delta.get("text", ""))
            elif delta.get("type") == "thinking_delta":
                thinking_chars += len(delta.get("thinking", ""))
            now = time.time()
            if now - last_push > 0.5:
                last_push = now
                on_partial("".join(accumulated), thinking_chars)
        elif event.get("type") == "result":
            final = event
    proc.wait(timeout=30)
    if final is None or final.get("is_error") or not isinstance(
            final.get("result"), str):
        raise RuntimeError(
            (final or {}).get("result", "model call failed"))
    rewritten = final["result"]
    usage = final.get("usage", {})
    return {"text": rewritten,
            "html": demo.render_markdown(rewritten),
            **demo.profile(rewritten),
            "output_tokens": usage.get("output_tokens"),
            "thinking_tokens": usage.get(
                "output_tokens_details", {}).get("thinking_tokens"),
            "seconds": round(final.get("duration_ms", 0) / 1000, 1),
            "cost_usd": final.get("total_cost_usd")}
MODELS = ("claude-sonnet-5", "claude-opus-5", "claude-fable-5", "haiku")
RESULTS_DIR = os.path.join(DEMO_DIR, "bench-results")

STATE_LOCK = threading.Lock()
STATE = {"status": "idle", "config": None, "cells": {}, "started": None}
STOP_FLAG = threading.Event()


def load_presets():
    presets = json.load(open(os.path.join(DEMO_DIR,
                                          "presets.json")))["presets"]
    return {p["id"]: p for p in presets}


def cell_public(cell, include_detail=False):
    out = {k: cell[k] for k in ("id", "prompt_id", "model", "effort",
                                "run", "status", "error")}
    if include_detail:
        out["live"] = {arm: dict(cell["live"][arm])
                       for arm in cell["live"]}
    else:
        out["live"] = {
            arm: {"status": live["status"],
                  "partial_words": len(live["partial"].split()),
                  "thinking_chars": live["thinking_chars"]}
            for arm, live in cell["live"].items()}
    out["arms"] = {}
    for arm, r in cell["arms"].items():
        if r is None:
            out["arms"][arm] = None
            continue
        summary = {k: r.get(k) for k in
                   ("patterns", "hard_violations", "words",
                    "output_tokens", "thinking_tokens", "seconds",
                    "cost_usd", "score")}
        if include_detail:
            summary["html"] = r.get("html")
            summary["text"] = r.get("text")
            summary["breakdown"] = r.get("breakdown")
        out["arms"][arm] = summary
    return out


def worker(queue, presets, results_path):
    while not STOP_FLAG.is_set():
        try:
            cell_id = queue.pop(0)
        except IndexError:
            return
        with STATE_LOCK:
            cell = STATE["cells"][cell_id]
            cell["status"] = "running"
        prompt = presets[cell["prompt_id"]]["prompt"]
        failures = []

        # All three arms run concurrently, exactly like the demo page:
        # cell wall time is the slowest arm, and every panel streams
        # at the same time.
        def run_arm(arm):
            with STATE_LOCK:
                cell["live"][arm]["status"] = "running"

            def on_partial(partial, thinking_chars):
                with STATE_LOCK:
                    cell["live"][arm]["partial"] = partial
                    cell["live"][arm]["thinking_chars"] = \
                        thinking_chars

            try:
                result = run_style_streaming(
                    arm, prompt, cell["model"], cell["effort"],
                    on_partial)
            except Exception as error:
                with STATE_LOCK:
                    failures.append("%s: %s" % (arm, error))
                    cell["live"][arm]["status"] = "failed"
                return
            with STATE_LOCK:
                cell["arms"][arm] = result
                cell["live"][arm]["status"] = "completed"
                cell["live"][arm]["partial"] = ""

        arm_threads = [threading.Thread(target=run_arm, args=(arm,))
                       for arm in ARMS]
        for thread in arm_threads:
            thread.start()
        for thread in arm_threads:
            thread.join()
        failed = bool(failures)
        with STATE_LOCK:
            if failures:
                cell["error"] = "; ".join(failures)
        with STATE_LOCK:
            cell["status"] = "failed" if failed else "completed"
            record = cell_public(cell, include_detail=True)
        with open(results_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def start_bench(config):
    presets = load_presets()
    prompt_ids = config["prompts"] or list(presets)
    cells = {}
    queue = []
    for pid in prompt_ids:
        if pid not in presets:
            raise ValueError("unknown prompt: " + pid)
        for model in config["models"]:
            for effort in config["efforts"]:
                for run in range(1, config["runs"] + 1):
                    cid = "%s|%s|%s|%d" % (pid, model, effort, run)
                    cells[cid] = {
                        "id": cid, "prompt_id": pid, "model": model,
                        "effort": effort, "run": run,
                        "status": "pending", "error": None,
                        "arms": {arm: None for arm in ARMS},
                        "live": {arm: {"status": "pending",
                                       "partial": "",
                                       "thinking_chars": 0}
                                 for arm in ARMS},
                    }
                    queue.append(cid)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    results_path = os.path.join(
        RESULTS_DIR, "bench-%s.jsonl" % uuid.uuid4().hex[:8])
    with STATE_LOCK:
        STATE.update({"status": "running", "config": config,
                      "cells": cells, "started": time.time(),
                      "results_path": results_path})
    STOP_FLAG.clear()
    # Each worker holds one cell = 3 concurrent model calls.
    workers = max(1, min(int(config.get("workers", 2)), 4))
    threads = [threading.Thread(target=worker,
                                args=(queue, presets, results_path),
                                daemon=True)
               for _ in range(workers)]
    for thread in threads:
        thread.start()

    def finisher():
        for thread in threads:
            thread.join()
        with STATE_LOCK:
            if STATE["status"] == "running":
                STATE["status"] = "done"
    threading.Thread(target=finisher, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = open(os.path.join(DEMO_DIR, "bench.html"),
                        "rb").read()
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/presets":
            self.send_json(list(load_presets().values()))
        elif self.path == "/state":
            with STATE_LOCK:
                cells = [cell_public(c)
                         for c in STATE["cells"].values()]
                self.send_json({"status": STATE["status"],
                                "config": STATE["config"],
                                "cells": cells})
        elif self.path.startswith("/run/"):
            cid = self.path[len("/run/"):].replace("%7C", "|")
            with STATE_LOCK:
                cell = STATE["cells"].get(cid)
                if cell is None:
                    self.send_json({"error": "no such run"}, 404)
                    return
                detail = cell_public(cell, include_detail=True)
                detail["prompt"] = load_presets()[
                    cell["prompt_id"]]["prompt"]
            self.send_json(detail)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            request = json.loads(self.rfile.read(length))
        except ValueError:
            self.send_json({"error": "bad json"}, 400)
            return
        if self.path == "/start":
            with STATE_LOCK:
                if STATE["status"] == "running":
                    self.send_json({"error": "already running"}, 409)
                    return
            try:
                config = {
                    "prompts": list(request.get("prompts") or []),
                    "models": [m for m in request.get("models", [])
                               if m in MODELS],
                    "efforts": [e for e in request.get("efforts", [])
                                if e in demo.EFFORTS],
                    "runs": max(1, min(int(request.get("runs", 1)),
                                       20)),
                    "workers": request.get("workers", 3),
                }
                if not config["models"] or not config["efforts"]:
                    raise ValueError("pick at least one model and "
                                     "one effort level")
                start_bench(config)
            except ValueError as error:
                self.send_json({"error": str(error)}, 400)
                return
            self.send_json({"ok": True})
        elif self.path == "/stop":
            STOP_FLAG.set()
            with STATE_LOCK:
                STATE["status"] = "stopped"
                for cell in STATE["cells"].values():
                    if cell["status"] == "pending":
                        cell["status"] = "skipped"
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "not found"}, 404)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://127.0.0.1:%d/" % args.port
    print("unclaudish benchmark at", url, "(Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
