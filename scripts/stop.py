#!/usr/bin/env python3
"""Stop layer.

When the session is in Korean mode and the finished answer is essentially
English prose, block the stop once and ask for a Korean rewrite. Code, URLs
and paths are excluded before measuring, so mixed technical text passes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hk_core as core  # noqa: E402


def main():
    data = core.read_input()
    if not data or data.get("stop_hook_active") or core.disabled():
        return
    cfg = core.load_config()
    if not core.layer_on(cfg, "stop"):
        return
    if core.get_mode(data.get("session_id"), cfg) != "ko":
        return
    text = data.get("last_assistant_message")
    if not isinstance(text, str):
        return
    block, ratio = core.judge_answer(text, cfg)
    if not block:
        return
    pct = int(round(ratio * 100))
    core.log("stop", {"session": data.get("session_id"), "ratio": round(ratio, 3),
                      "head": text[:120]})
    core.emit({"decision": "block",
               "reason": cfg.get("stop_reason", "").format(pct=pct)})


if __name__ == "__main__":
    main()
