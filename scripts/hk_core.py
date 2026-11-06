#!/usr/bin/env python3
"""hangul-keeper core.

Two layers use this module:
    prompt.py   UserPromptSubmit  decide the turn language, re-inject the rule
    posttool.py PostToolUse       catch English narration between tool calls
    stop.py     Stop              block a finished answer that came out English

The language decision is stored per session so the Stop layer knows what the
user expected without parsing the transcript.
"""
import json
import os
import re
import sys
import time

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
USER_DIR = os.environ.get("HANGUL_KEEPER_HOME") or os.path.join(
    os.path.expanduser("~"), ".claude", "hangul-keeper")
USER_CONFIG = os.path.join(USER_DIR, "config.json")
PLUGIN_CONFIG = os.path.join(PLUGIN_ROOT, "config.default.json")
STATE_DIR = os.path.join(USER_DIR, "state")
LOG_PATH = os.path.join(USER_DIR, "hits.log")
STATE_TTL = 7 * 24 * 3600

HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
LATIN_RE = re.compile(r"[A-Za-z]")

FENCE_RE = re.compile(r"(^|\n)\s*(```|~~~).*?(\n\s*\2[^\n]*|\Z)", re.S)
INLINE_RE = re.compile(r"`[^`\n]*`")
URL_RE = re.compile(r"\b(?:https?|ftp|file|ssh)://\S+|\bwww\.\S+")
EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
PATH_RE = re.compile(r"(?:~|\.{1,2})?/?(?:[\w.@-]+/)+[\w.@-]*")
FILE_RE = re.compile(r"\b[\w-]+\.(?:py|js|ts|tsx|jsx|json|md|sh|ya?ml|toml|"
                     r"txt|html|css|go|rs|java|kt|swift|sql|lock|env)\b")
HTMLTAG_RE = re.compile(r"</?[A-Za-z][^>\n]*>")
PASTED_RE = re.compile(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", re.S)
SYSREM_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
COMMAND_RE = re.compile(r"<command-(?:name|message)>.*?</command-(?:name|message)>",
                        re.S)
SLASH_RE = re.compile(r"^\s*/[\w:.-]+")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_config():
    cfg = _read_json(PLUGIN_CONFIG)
    user = _read_json(USER_CONFIG)
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = dict(cfg[k], **v)
        else:
            cfg[k] = v
    return cfg


def disabled():
    return os.environ.get("HANGUL_KEEPER_OFF", "") in ("1", "true", "yes")


def layer_on(cfg, name):
    env = os.environ.get("HANGUL_KEEPER_" + name.upper())
    if env is not None:
        return env not in ("0", "false", "no")
    return bool(cfg.get("layers", {}).get(name, True))


def strip_code(text):
    """Remove everything that is legitimately not prose."""
    t = FENCE_RE.sub("\n", text)
    t = INLINE_RE.sub(" ", t)
    t = HTMLTAG_RE.sub(" ", t)
    t = URL_RE.sub(" ", t)
    t = EMAIL_RE.sub(" ", t)
    t = PATH_RE.sub(" ", t)
    t = FILE_RE.sub(" ", t)
    return t


def counts(text):
    """(hangul chars, latin chars) of the prose. Used for prompts."""
    t = strip_code(text)
    return len(HANGUL_RE.findall(t)), len(LATIN_RE.findall(t))


def word_counts(text):
    """(korean words, english words) of the prose.

    Words, not letters: one Hangul syllable carries what several Latin letters
    do, so a letter ratio punishes jargon heavy Korean. A word holding any
    Hangul counts as Korean, which also covers "Stop만" style terms with a
    particle attached.
    """
    ko = en = 0
    for w in strip_code(text).split():
        if HANGUL_RE.search(w):
            ko += 1
        elif LATIN_RE.search(w):
            en += 1
    return ko, en


def prompt_body(prompt):
    """The part of a prompt the user actually typed."""
    t = SYSREM_RE.sub(" ", prompt)
    t = PASTED_RE.sub(" ", t)
    t = COMMAND_RE.sub(" ", t)
    t = SLASH_RE.sub(" ", t)
    return t


def classify_prompt(prompt, cfg):
    """Return "ko", "en" or None (undecided, keep the previous mode)."""
    body = prompt_body(prompt or "")
    low = body.lower()
    for pat in cfg.get("english_request_patterns", []):
        if re.search(pat, low):
            return "en"
    h, l = counts(body)
    if h >= int(cfg.get("prompt_ko_min_hangul", 2)):
        return "ko"
    if h == 0 and l >= int(cfg.get("prompt_en_min_latin", 15)):
        return "en"
    return None


def judge_answer(text, cfg, min_words=None):
    """Return (is_english, ratio). ratio is None when too short to judge."""
    ko, en = word_counts(text or "")
    total = ko + en
    if min_words is None:
        min_words = int(cfg.get("stop_min_words", 12))
    if total < min_words:
        return False, None
    ratio = ko / total
    return ratio < float(cfg.get("stop_min_ratio", 0.2)), ratio


def _state_path(session_id):
    safe = re.sub(r"[^\w.-]", "_", session_id or "default")
    return os.path.join(STATE_DIR, safe + ".json")


def get_mode(session_id, cfg):
    st = _read_json(_state_path(session_id))
    return st.get("mode") or cfg.get("default_mode", "ko")


def set_mode(session_id, mode):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        p = _state_path(session_id)
        st = _read_json(p)
        st.update(mode=mode, at=int(time.time()))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(st, f)
        _prune()
    except OSError:
        pass


def _prune():
    now = time.time()
    try:
        for name in os.listdir(STATE_DIR):
            p = os.path.join(STATE_DIR, name)
            if now - os.path.getmtime(p) > STATE_TTL:
                os.remove(p)
    except OSError:
        pass


def log(event, payload):
    try:
        os.makedirs(USER_DIR, exist_ok=True)
        rec = dict(payload, event=event, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_input():
    try:
        return json.load(sys.stdin)
    except ValueError:
        return None


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def last_narration(transcript_path, tail_bytes=262144):
    """(message id, text) of the newest main thread assistant message.

    Text and tool_use blocks of one message are stored as separate records
    sharing message.id, interleaved with tool_result records when tools run
    in parallel. So: find the newest assistant record, then join every text
    block carrying its id.
    """
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except (OSError, TypeError):
        return None, ""
    recs = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "assistant" and not r.get("isSidechain"):
            recs.append(r.get("message") or {})
    if not recs:
        return None, ""
    mid = recs[-1].get("id")
    parts = []
    for m in recs:
        if m.get("id") != mid:
            continue
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
    return mid, "\n".join(parts)


def mark_flagged(session_id, mid):
    """True the first time a message id is flagged in this session."""
    p = _state_path(session_id)
    st = _read_json(p)
    seen = st.get("flagged") or []
    if mid in seen:
        return False
    st["flagged"] = (seen + [mid])[-50:]
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except OSError:
        pass
    return True
