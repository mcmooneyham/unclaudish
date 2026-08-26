#!/usr/bin/env python3
"""Generate the ablation arm plugin variants from the canonical plugin.

Each variant is a full standalone plugin directory under
eval/arm-plugins/ containing only the components its arm enables.
Run: python3 eval/build_arms.py
"""

import json
import os
import shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "eval", "arm-plugins")

# arm -> (style_file, remind, stop); style_file None = no style
PLAIN = "unclaudish.md"
MAX = "unclaudish-max.md"
VARIANTS = {
    "style-only": (PLAIN, False, False),
    "remind-only": (None, True, False),
    "stop-only": (None, False, True),
    "style-remind": (PLAIN, True, False),
    "full": (PLAIN, True, True),
    "style-only-max": (MAX, False, False),
    "style-remind-max": (MAX, True, False),
    "full-max": (MAX, True, True),
}


def build_variant(name, style, remind, stop):
    root = os.path.join(OUT, name)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, ".claude-plugin"))

    manifest = {
        "name": "unclaudish-" + name,
        "description": "Ablation variant: " + name,
        "version": "0.1.0",
        "license": "MIT",
    }
    if style:
        os.makedirs(os.path.join(root, "output-styles"))
        style_src = open(os.path.join(REPO, "output-styles",
                                      style)).read()
        if "force-for-plugin" not in style_src:
            style_src = style_src.replace(
                "keep-coding-instructions: true",
                "keep-coding-instructions: true\nforce-for-plugin: true")
        with open(os.path.join(root, "output-styles", style), "w") as f:
            f.write(style_src)
        manifest["outputStyles"] = "./output-styles/"
    if remind or stop:
        shutil.copytree(os.path.join(REPO, "scripts"),
                        os.path.join(root, "scripts"))
        hooks = {"description": "Ablation variant hooks", "hooks": {}}
        if stop:
            hooks["hooks"]["Stop"] = [{"hooks": [{
                "type": "command",
                "command": "\"${CLAUDE_PLUGIN_ROOT}\"/scripts/lint_stop.py",
                "timeout": 15,
            }]}]
        if remind:
            hooks["hooks"]["UserPromptSubmit"] = [{"hooks": [{
                "type": "command",
                "command": "\"${CLAUDE_PLUGIN_ROOT}\"/scripts/remind.py",
                "timeout": 10,
            }]}]
        os.makedirs(os.path.join(root, "hooks"))
        with open(os.path.join(root, "hooks", "hooks.json"), "w") as f:
            json.dump(hooks, f, indent=2)
        manifest["hooks"] = "./hooks/hooks.json"

    with open(os.path.join(root, ".claude-plugin", "plugin.json"),
              "w") as f:
        json.dump(manifest, f, indent=2)
    print("built", root)


def main():
    for name, (style, remind, stop) in VARIANTS.items():
        build_variant(name, style, remind, stop)


if __name__ == "__main__":
    main()
