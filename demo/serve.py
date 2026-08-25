#!/usr/bin/env python3
"""Local live demo for the unclaudish plugin.

Starts a web page where you paste text and see it rewritten under the
unclaudish and unclaudish-max styles, with claudish scores from
the real lexicon. Rewrites run through your own Claude Code login via
`claude -p`, so this costs your usage, not anyone else's.

Usage: python3 demo/serve.py [--port 8765] [--no-browser]
Requires: Claude Code installed and logged in.
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DEMO_DIR)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import claudish_core  # noqa: E402

MAX_INPUT_CHARS = 8000
WORKDIR = tempfile.mkdtemp(prefix="unclaudish-demo-")


def build_style_packs():
    """Build forced-style plugin packs from the canonical plugin
    sources, so the demo can never drift from what ships."""
    import shutil
    packs = {"baseline": None}
    root = tempfile.mkdtemp(prefix="unclaudish-packs-")
    for name, style_file in (("unclaudish", "unclaudish.md"),
                             ("max", "unclaudish-max.md")):
        pack = os.path.join(root, name)
        os.makedirs(os.path.join(pack, ".claude-plugin"))
        os.makedirs(os.path.join(pack, "output-styles"))
        shutil.copytree(os.path.join(REPO, "scripts"),
                        os.path.join(pack, "scripts"))
        os.makedirs(os.path.join(pack, "hooks"))
        style_src = open(os.path.join(
            REPO, "output-styles", style_file)).read()
        if "force-for-plugin" not in style_src:
            style_src = style_src.replace(
                "keep-coding-instructions: true",
                "keep-coding-instructions: true\n"
                "force-for-plugin: true")
        with open(os.path.join(pack, "output-styles", style_file),
                  "w") as f:
            f.write(style_src)
        with open(os.path.join(pack, "hooks", "hooks.json"), "w") as f:
            json.dump({"hooks": {"Stop": [{"hooks": [{
                "type": "command",
                "command": "\"${CLAUDE_PLUGIN_ROOT}\""
                           "/scripts/lint_stop.py",
                "timeout": 15}]}]}}, f)
        with open(os.path.join(pack, ".claude-plugin", "plugin.json"),
                  "w") as f:
            json.dump({"name": "unclaudish-demo-" + name,
                       "description": "Demo style pack",
                       "version": "0.1.0", "license": "MIT"}, f)
        packs[name] = pack
    return packs


STYLE_PACKS = build_style_packs()





# --- minimal markdown renderer (escapes all text; safe for innerHTML) ---
import html as _html
import re as _re


def _md_inline(text):
    t = _html.escape(text, quote=False)
    t = _re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = _re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", t)
    t = _re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    return t


def render_markdown(text):
    out, fence, fbuf, ltag, tbuf = [], False, [], None, []

    def close_list():
        nonlocal ltag
        if ltag:
            out.append("</%s>" % ltag)
            ltag = None

    def flush_table():
        nonlocal tbuf
        if tbuf:
            rows = []
            for i, cells in enumerate(tbuf):
                tag = "th" if i == 0 else "td"
                rows.append("<tr>" + "".join(
                    "<%s>%s</%s>" % (tag, _md_inline(c.strip()), tag)
                    for c in cells) + "</tr>")
            out.append('<div class="mdt"><table>%s</table></div>'
                       % "".join(rows))
            tbuf = []

    for line in text.split("\n"):
        if _re.match(r"^\s*(`{3,}|~{3,})", line):
            if fence:
                out.append("<pre><code>%s</code></pre>"
                           % _html.escape("\n".join(fbuf), quote=False))
                fbuf, fence = [], False
            else:
                close_list()
                flush_table()
                fence = True
            continue
        if fence:
            fbuf.append(line)
            continue
        if "|" in line and line.count("|") >= 2:
            if _re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*\s*$", line):
                continue
            close_list()
            tbuf.append(line.strip().strip("|").split("|"))
            continue
        flush_table()
        heading = _re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 2, 6)
            out.append("<h%d>%s</h%d>"
                       % (level, _md_inline(heading.group(2)), level))
            continue
        if _re.match(r"^\s*(?:---+|\*\*\*+)\s*$", line):
            close_list()
            out.append("<hr>")
            continue
        item = _re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", line)
        if item:
            tag = "ol" if item.group(1)[0].isdigit() else "ul"
            if ltag != tag:
                close_list()
                out.append("<%s>" % tag)
                ltag = tag
            out.append("<li>%s</li>" % _md_inline(item.group(2)))
            continue
        if not line.strip():
            close_list()
            continue
        close_list()
        out.append("<p>%s</p>" % _md_inline(line))
    if fence and fbuf:
        out.append("<pre><code>%s</code></pre>"
                   % _html.escape("\n".join(fbuf), quote=False))
    close_list()
    flush_table()
    return "".join(out)


def profile(text):
    result = claudish_core.evaluate(text)
    return {
        "score": result["score"],
        "words": len(text.split()),
        "patterns": sum(m["count"] or 0
                        for m in result["metrics"].values()),
        "hard_violations": sum(
            v["count"] for v in result["hard_violations"]),
        "breakdown": [
            {"id": mid, "count": m["count"] or 1,
             "hard": any(v["id"] == mid
                         for v in result["hard_violations"])}
            for mid, m in result["metrics"].items()
        ],
    }


EFFORTS = ("default", "low", "medium", "high", "xhigh")


def run_style(style, text, model, effort="default"):
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    # Never inherit the launching shell's effort silently.
    env.pop("CLAUDE_EFFORT", None)
    if effort != "default":
        env["CLAUDE_EFFORT"] = effort
    command = ["claude", "-p", "--model", model,
               "--output-format", "json", "--tools", "",
               "--disallowedTools", "mcp__*"]
    if STYLE_PACKS[style]:
        command += ["--plugin-dir", STYLE_PACKS[style]]
    proc = subprocess.run(
        command, input=text.encode(),
        capture_output=True, env=env, timeout=240, cwd=WORKDIR,
    )
    payload = json.loads(proc.stdout)
    if payload.get("is_error") or not isinstance(
            payload.get("result"), str):
        raise RuntimeError(payload.get("result", "model call failed"))
    rewritten = payload["result"]
    usage = payload.get("usage", {})
    return {"text": rewritten, "html": render_markdown(rewritten),
            **profile(rewritten),
            "output_tokens": usage.get("output_tokens"),
            "thinking_tokens": usage.get(
                "output_tokens_details", {}).get("thinking_tokens"),
            "seconds": round(payload.get("duration_ms", 0) / 1000, 1),
            "cost_usd": payload.get("total_cost_usd")}


def load_stats():
    stats = {}
    for name in ("main-sonnet-v3", "main-opus-sub", "main-opus", "main"):
        path = os.path.join(REPO, "eval", "results",
                            name + "-final.json")
        if os.path.exists(path):
            stats[name] = json.load(open(path))["arms"]
    return stats


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
            body = open(os.path.join(DEMO_DIR, "demo.html"),
                        "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/presets":
            presets = json.load(open(os.path.join(
                DEMO_DIR, "presets.json")))["presets"]
            self.send_json(presets)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/rewrite":
            self.send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            request = json.loads(self.rfile.read(length))
            text = request["text"].strip()
            model = request.get("model", "claude-sonnet-5")
            if model not in ("claude-sonnet-5", "claude-opus-5",
                             "claude-fable-5", "haiku"):
                raise ValueError("unknown model")
            if not text or len(text) > MAX_INPUT_CHARS:
                raise ValueError(
                    "text must be 1 to %d characters" % MAX_INPUT_CHARS)
        except (ValueError, KeyError) as error:
            self.send_json({"error": str(error)}, 400)
            return
        style = request.get("style")
        effort = request.get("effort", "default")
        if style not in STYLE_PACKS or effort not in EFFORTS:
            self.send_json({"error": "unknown style or effort"}, 400)
            return
        try:
            result = run_style(style, text, model, effort)
        except Exception as error:
            self.send_json({"error": str(error)}, 502)
            return
        self.send_json(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://127.0.0.1:%d/" % args.port
    print("unclaudish demo at", url, "(Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
