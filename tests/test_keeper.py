#!/usr/bin/env python3
"""hangul-keeper regression tests.

    python3 tests/test_keeper.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
HOME = tempfile.mkdtemp(prefix="hk-test-")
FAILS = []


def run(script, payload, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("HANGUL_KEEPER")}
    e["HANGUL_KEEPER_HOME"] = HOME
    e["CLAUDE_PLUGIN_ROOT"] = ROOT
    if env:
        e.update(env)
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)],
                       input=json.dumps(payload), capture_output=True,
                       text=True, env=e)
    if p.stderr.strip():
        FAILS.append("stderr from %s: %s" % (script, p.stderr.strip()))
    out = p.stdout.strip()
    return json.loads(out) if out else None


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def prompt(sid, text, **kw):
    return run("prompt.py", {"session_id": sid, "prompt": text}, **kw)


def stop(sid, text, active=False, **kw):
    return run("stop.py", {"session_id": sid, "last_assistant_message": text,
                           "stop_hook_active": active}, **kw)


def blocked(out):
    return bool(out) and out.get("decision") == "block"


ENGLISH = ("I checked the hook configuration and the Stop event receives the "
           "last assistant message directly, so we do not need to parse the "
           "transcript. Next I will add the tests and install the plugin.")

KOREAN_TECH = (
    "Stop 훅에서 transcript를 읽는 방식을 참고하겠습니다. `last_assistant_message` "
    "필드가 있어서 JSONL을 파싱할 필요가 없고, UserPromptSubmit 훅은 "
    "`additionalContext`로 reminder를 주입합니다. hooks.json에는 "
    "${CLAUDE_PLUGIN_ROOT}/scripts/stop.py를 등록합니다.")

KOREAN_HEAVY_JARGON = (
    "결론: PreToolUse, PostToolUse, Stop, SubagentStop, SessionStart, "
    "UserPromptSubmit, MessageDisplay 훅을 모두 확인했고 Stop만 decision block을 "
    "지원합니다. matcher는 Write|Edit|MultiEdit 그대로 두면 됩니다.")

ENGLISH_WITH_CODE = (
    "Here is the fix:\n\n```python\n# 한국어 주석이 잔뜩 있어도\n"
    "print('안녕하세요 반갑습니다 여러분 오늘은 날씨가 좋네요')\n```\n\n"
    "This replaces the old handler and keeps the retry logic intact, "
    "which should resolve the timeout you saw earlier today.")

KOREAN_WITH_ENGLISH_CODE = (
    "수정한 코드입니다.\n\n```ts\nexport async function handler(req: Request) {\n"
    "  const body = await req.json();\n  return Response.json({ ok: true, body });\n"
    "}\n```\n\n이제 요청 본문을 그대로 돌려줍니다.")

ENGLISH_TABLE_QUOTE = (
    "The log says \"인증 실패\" for every request. The token expired yesterday, "
    "so refresh it with the CLI and rerun the deploy. Nothing else changed in "
    "the configuration between the two runs.")


def main():
    # prompt classification and injection
    out = prompt("s1", "이거 왜 안 돼?")
    check("korean prompt injects reminder",
          out and "hangul-keeper" in out["hookSpecificOutput"]["additionalContext"])
    check("korean mode blocks english answer", blocked(stop("s1", ENGLISH)))
    check("stop_hook_active prevents loop", not stop("s1", ENGLISH, active=True))
    check("tech-heavy korean passes", not blocked(stop("s1", KOREAN_TECH)))
    check("jargon-heavy korean passes", not blocked(stop("s1", KOREAN_HEAVY_JARGON)))
    check("korean prose with english code passes",
          not blocked(stop("s1", KOREAN_WITH_ENGLISH_CODE)))
    check("english prose with korean code is blocked",
          blocked(stop("s1", ENGLISH_WITH_CODE)))
    check("english with a korean quote is blocked",
          blocked(stop("s1", ENGLISH_TABLE_QUOTE)))
    check("short english answer passes", not blocked(stop("s1", "Done. All tests pass.")))
    check("block reason carries ratio", "%" in stop("s1", ENGLISH)["reason"])

    # sticky mode on undecided prompts
    check("slash command keeps korean", prompt("s1", "/commit") is not None)
    check("short ok keeps korean", prompt("s1", "ok") is not None)
    check("pasted english only keeps korean",
          prompt("s1", "<pasted_content id=x>" + ENGLISH + "</pasted_content id=x>")
          is not None)
    check("korean around pasted english", prompt("s1", "이 로그 봐줘\n" + ENGLISH) is not None)

    # english
    check("english prompt injects nothing",
          prompt("s2", "Why does the deploy keep failing on staging?") is None)
    check("english mode allows english answer", not blocked(stop("s2", ENGLISH)))
    check("english mode sticks on short prompt", prompt("s2", "ok") is None)
    check("korean prompt flips back", prompt("s2", "다시 한국어로") is not None)
    check("flipped session blocks english", blocked(stop("s2", ENGLISH)))

    # explicit english request in korean
    check("'영어로' request switches to en",
          prompt("s3", "이 문단 영어로 번역해줘") is None)
    check("translation answer allowed", not blocked(stop("s3", ENGLISH)))
    check("next korean prompt returns to ko", prompt("s3", "고마워, 이제 다음 거") is not None)

    # unknown session defaults to korean
    check("default mode is korean", blocked(stop("fresh", ENGLISH)))

    # switches
    check("HANGUL_KEEPER_OFF disables stop",
          not stop("s1", ENGLISH, env={"HANGUL_KEEPER_OFF": "1"}))
    check("HANGUL_KEEPER_STOP=0 disables stop",
          not stop("s1", ENGLISH, env={"HANGUL_KEEPER_STOP": "0"}))
    check("HANGUL_KEEPER_PROMPT=0 disables injection",
          prompt("s1", "안녕", env={"HANGUL_KEEPER_PROMPT": "0"}) is None)

    # user config override
    os.makedirs(HOME, exist_ok=True)
    with open(os.path.join(HOME, "config.json"), "w") as f:
        json.dump({"stop_min_ratio": 0.9}, f)
    check("user config raises threshold", blocked(stop("s1", KOREAN_TECH)))
    os.remove(os.path.join(HOME, "config.json"))

    # posttool narration
    tp = os.path.join(HOME, "t.jsonl")

    def transcript(*recs):
        with open(tp, "w") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def a(mid, block, side=False):
        return {"type": "assistant", "isSidechain": side,
                "message": {"id": mid, "content": [block]}}

    def text(t):
        return {"type": "text", "text": t}

    tool = {"type": "tool_use", "name": "Bash", "input": {}}
    res = {"type": "user", "message": {"content": [{"type": "tool_result"}]}}

    def post(sid, **kw):
        return run("posttool.py", {"session_id": sid, "transcript_path": tp,
                                   "tool_name": "Bash"}, **kw)

    prompt("p1", "프론트 고쳐줘")
    transcript(a("m1", text("Matches the canvas. Now the frontend flow against the test box.")),
               a("m1", tool))
    out = post("p1")
    check("english narration flagged",
          out and "hangul-keeper" in out["hookSpecificOutput"]["additionalContext"])
    check("same message flagged once", post("p1") is None)
    transcript(a("m2", text("캔버스와 일치합니다. 이제 테스트 박스로 프론트 흐름을 봅니다.")),
               a("m2", tool))
    check("korean narration passes", post("p1") is None)
    transcript(a("m3", text("Checking both files now and then the tests.")),
               a("m3", tool), res, a("m3", tool), res)
    check("parallel tools: narration found across records", post("p1") is not None)
    transcript(a("m4", text("Checking both files now and then the tests.")),
               a("m4", tool), res, a("m5", tool))
    check("tool-only newest message is ignored", post("p1") is None)
    transcript(a("m6", text("두 파일을 확인하고 테스트를 돌리겠습니다.")),
               a("m6", tool),
               a("m7", text("Subagent reporting in English as usual here, fine."), side=True))
    check("sidechain records ignored", post("p1") is None)
    check("missing transcript is harmless",
          run("posttool.py", {"session_id": "p1", "transcript_path": "/nope"}) is None)
    prompt("p2", "Please refactor the router module for me.")
    transcript(a("m8", text("Refactoring the router module now, starting with types.")),
               a("m8", tool))
    check("english mode: narration not flagged", post("p2") is None)

    check("log written", os.path.exists(os.path.join(HOME, "hits.log")))

    print("\n%d failure(s)" % len(FAILS))
    for f in FAILS:
        print("  " + f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
