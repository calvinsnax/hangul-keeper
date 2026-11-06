#!/usr/bin/env python3
"""UserPromptSubmit layer.

Decides the language of this turn from what the user typed and stores it for
the Stop layer. In Korean mode it re-injects the language rule next to the
newest message, where a long context cannot bury it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hk_core as core  # noqa: E402


def main():
    data = core.read_input()
    if not data or core.disabled():
        return
    cfg = core.load_config()
    sid = data.get("session_id")
    decided = core.classify_prompt(data.get("prompt") or "", cfg)
    mode = decided or core.get_mode(sid, cfg)
    core.set_mode(sid, mode)
    if mode != "ko" or not core.layer_on(cfg, "prompt"):
        return
    core.emit({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": cfg.get("reminder", ""),
    }})


if __name__ == "__main__":
    main()
