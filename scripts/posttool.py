#!/usr/bin/env python3
"""PostToolUse layer.

Stop only sees the final answer. The narration written before each tool call
("Now the frontend.") is where English usually starts, and once it does the
rest of the turn follows. This layer reads that narration from the transcript
after the tool ran and, if it was English, tells the model to continue in
Korean. It cannot unsay text already on screen, it only stops the drift.
Each message is flagged at most once.
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
    if not core.layer_on(cfg, "posttool"):
        return
    sid = data.get("session_id")
    if core.get_mode(sid, cfg) != "ko":
        return
    mid, text = core.last_narration(data.get("transcript_path"))
    if not mid or not text.strip():
        return
    english, ratio = core.judge_answer(
        text, cfg, min_words=int(cfg.get("posttool_min_words", 6)))
    if not english or not core.mark_flagged(sid, mid):
        return
    core.log("posttool", {"session": sid, "ratio": round(ratio, 3),
                          "head": text[:120]})
    core.emit({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": cfg.get("posttool_notice", "").format(
            pct=int(round(ratio * 100))),
    }})


if __name__ == "__main__":
    main()
