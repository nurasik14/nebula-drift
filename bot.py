#!/usr/bin/env python3
"""Telegram bot for ORBIT (in-message widget) and Nebula Drift (Mini App). Long polling, stdlib only.

    python3 bot.py        # reads BOT_TOKEN, GAME_URL[, GAME_SHORT_NAME] from env or ./.env

Ways to play:
  - In the message: /start or /play sends widget.html (ORBIT) as a Bot API 10.4 widget,
    a one-tap game that runs inside the chat bubble.
  - Full screen: the menu button and /full open index.html (Nebula Drift) as a Mini App.
  - /game posts a classic game card if GAME_SHORT_NAME is set (@BotFather /newgame).
/start c<score> (from a challenge link) sends a widget whose chat state carries "beat <score>".

Widget -> bot requests (TelegramWidget.request data, at most 64 bytes):
  h                                  hello: load the leaderboard
  s:<m>:<yyyymmdd>:<score>:<near>    submit a finished run
                                     m: d = daily (seeded by the UTC date), e = endless
                                     yyyymmdd: today or yesterday (UTC)
                                     0 <= score <= MAX_SCORE, near * 25 <= score

Bot -> widget answer (answerWidgetQuery data, JSON, at most 1024 bytes):
  t  today's daily top 5: [[name (cut to 12 chars), score], ...]
  n  players on today's daily board
  r  the user's rank on today's daily board (0 = no daily run today)
  d  the user's daily best today
  b  the user's all-time best (both modes)
  k  the user's play streak: consecutive UTC days with a submitted run (0 once broken)
  e  only when a request was refused: "bad" (malformed) | "date" | "score"

Chat state written by the bot (sendWidget / editMessageWidgetData chat_data):
  {"best": all-time best, "streak": streak[, "c": challenge target]}

scores.json:
  {"o": {"u": {uid: {"n": name, "b": best, "k": streak, "l": last play day yyyymmdd}},
         "d": {yyyymmdd: {uid: daily best}}},     # only the last few days are kept
   "msgs": {"chat:msg": challenge target},
   "users": {...}}                                # legacy Nebula Drift widget bests, untouched
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env() -> None:
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


TOKEN = GAME_URL = GAME_SHORT_NAME = API = ""


def configure() -> None:
    global TOKEN, GAME_URL, GAME_SHORT_NAME, API
    load_env()
    TOKEN = os.environ.get("BOT_TOKEN", "")
    GAME_URL = os.environ.get("GAME_URL", "")
    GAME_SHORT_NAME = os.environ.get("GAME_SHORT_NAME", "")
    if not TOKEN or not GAME_URL:
        sys.exit("BOT_TOKEN and GAME_URL are required (env or .env)")
    API = f"https://api.telegram.org/bot{TOKEN}/"


WIDGET_HTML = (HERE / "widget.html").read_text(encoding="utf-8")
DB_PATH = HERE / "scores.json"
MAX_SCORE = 100_000   # far above any real run (a run lasts 30-120 s)
KEEP_DAYS = 3         # daily boards kept in scores.json
SUBMIT = re.compile(r"s:([de]):(\d{8}):(\d{1,7}):(\d{1,5})", re.ASCII)
BOT_USERNAME = "fameOfBot"


def call(method: str, **params):
    data = json.dumps(params).encode()
    req = urllib.request.Request(API + method, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.load(r).get("result")
    except urllib.error.HTTPError as e:
        print(f"[{method}] HTTP {e.code}: {e.read().decode(errors='replace')[:300]}", flush=True)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[{method}] network: {e}", flush=True)
    return None


def today() -> date:
    return datetime.now(timezone.utc).date()


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


# ---------------- scores ----------------
def load_db() -> dict:
    try:
        db = json.loads(DB_PATH.read_text())
    except (OSError, ValueError):
        db = {}
    db.setdefault("msgs", {})
    o = db.setdefault("o", {})
    o.setdefault("u", {})
    o.setdefault("d", {})
    return db


DB = load_db()


def save_db() -> None:
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(DB, ensure_ascii=False))
    tmp.replace(DB_PATH)


def user(uid: int) -> dict:
    return DB["o"]["u"].get(str(uid), {})


def streak(u: dict) -> int:
    """The streak as it stands today: it survives until the end of the day after the last run."""
    t = today()
    return u.get("k", 0) if u.get("l") in (ymd(t), ymd(t - timedelta(days=1))) else 0


def name_of(uid: str) -> str:
    return DB["o"]["u"].get(uid, {}).get("n", "?")[:12]


def board(uid: int) -> dict:
    day = DB["o"]["d"].get(ymd(today()), {})
    me = str(uid)
    ranked = sorted(day.items(), key=lambda kv: -kv[1])  # stable: earlier submitters win ties
    rank = 1 + sum(1 for v in day.values() if v > day[me]) if me in day else 0
    u = user(uid)
    return {"t": [[name_of(k), v] for k, v in ranked[:5]], "n": len(day), "r": rank,
            "d": day.get(me, 0), "b": u.get("b", 0), "k": streak(u)}


def all_time(n: int = 5) -> list:
    ranked = sorted(DB["o"]["u"].items(), key=lambda kv: -kv[1].get("b", 0))
    return [[v.get("n", "?")[:12], v["b"]] for _, v in ranked[:n] if v.get("b", 0) > 0]


def submit(uid: int, name: str, mode: str, day: str, score: int) -> bool:
    """Record a validated run. Returns True if it is a new all-time best."""
    o, me = DB["o"], str(uid)
    u = o["u"].setdefault(me, {"n": name, "b": 0, "k": 0, "l": ""})
    u["n"] = name[:12]
    new_best = score > u.get("b", 0)
    if new_best:
        u["b"] = score
    last = u.get("l", "")
    if day > last:  # a run on a later day than any before: extend or restart the streak
        prev = ymd(datetime.strptime(day, "%Y%m%d").date() - timedelta(days=1))
        u["k"] = u.get("k", 0) + 1 if last == prev else 1
        u["l"] = day
    if mode == "d":
        d = o["d"].setdefault(day, {})
        if score > d.get(me, -1):
            d[me] = score
    oldest = ymd(today() - timedelta(days=KEEP_DAYS - 1))
    for k in [k for k in o["d"] if k < oldest]:
        del o["d"][k]
    save_db()
    return new_best


def answer(data: dict) -> str:
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    while len(s.encode()) > 1024 and data.get("t"):  # never happens with 12-char names, but stay legal
        data["t"].pop()
        s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return s


def widget_state(uid: int, challenge: int = 0) -> str:
    u = user(uid)
    state = {"best": u.get("b", 0), "streak": streak(u)}
    if challenge:
        state["c"] = challenge
    return json.dumps(state)


# ---------------- sending ----------------
def play_kb() -> dict:
    return {"inline_keyboard": [[{"text": "Nebula Drift (full screen)", "web_app": {"url": GAME_URL}}]]}


CAPTION = ("ORBIT · tap anywhere to switch rings. Dodge the red, collect sparks, "
           "skim hazards for near misses. Daily mode: one run for everyone, new every day (UTC).")


def send_widget(chat_id: int, uid: int, challenge: int = 0) -> None:
    msg = call("sendWidget", chat_id=chat_id, html=WIDGET_HTML, chat_data=widget_state(uid, challenge),
               caption=CAPTION + (f"\nFriend's challenge: beat {challenge}!" if challenge else ""),
               allow_queries=True, reply_markup=play_kb())
    if msg is None:  # widgets refused: fall back to the Mini App
        call("sendMessage", chat_id=chat_id, text="Play Nebula Drift:", reply_markup=play_kb())
    elif challenge:
        DB["msgs"][f"{chat_id}:{msg['message_id']}"] = challenge
        save_db()


def send_game_card(chat_id: int) -> None:
    if not GAME_SHORT_NAME:
        call("sendMessage", chat_id=chat_id, text="Game cards aren't set up yet (needs /newgame in @BotFather).",
             reply_markup=play_kb())
        return
    call("sendGame", chat_id=chat_id, game_short_name=GAME_SHORT_NAME)


def top_text(uid: int) -> str:
    b = board(uid)
    day = "\n".join(f"{i + 1}. {n} — {s}" for i, (n, s) in enumerate(b["t"])) or "No daily runs yet today."
    best = "\n".join(f"{i + 1}. {n} — {s}" for i, (n, s) in enumerate(all_time())) or "No scores yet."
    me = []
    if b["r"]:
        me.append(f"you are #{b['r']} of {b['n']} today")
    if b["k"]:
        me.append(f"{b['k']}-day streak")
    return (f"ORBIT daily · {today().isoformat()} (UTC)\n{day}\n\nAll-time\n{best}"
            + (f"\n\n{', '.join(me)}" if me else "")
            + f"\n\nChallenge a friend: https://t.me/{BOT_USERNAME}?start=c{b['b']}")


def setup() -> None:
    call("setMyCommands", commands=[
        {"command": "play", "description": "Play ORBIT in the chat"},
        {"command": "full", "description": "Nebula Drift, full screen (Mini App)"},
        {"command": "top", "description": "Today's board and all-time top"},
    ])
    call("setChatMenuButton", menu_button={"type": "web_app", "text": "Play", "web_app": {"url": GAME_URL}})
    call("setMyShortDescription", short_description="ORBIT: a one-tap orbit game that runs right inside the chat.")
    call("setMyDescription", description="ORBIT: a one-tap arcade game inside the message. Tap to switch rings, "
         "dodge hazards, chase the daily board and keep your streak. The menu button opens Nebula Drift, full screen.")


# ---------------- updates ----------------
def handle_query(q: dict) -> tuple[dict, bool]:
    """Validate one widget request. Returns the answer and whether the user set a new all-time best."""
    uid, data = q["from"]["id"], q.get("data") or ""
    if data == "h":
        return board(uid), False
    m = SUBMIT.fullmatch(data)
    if not m:
        return {"e": "bad", **board(uid)}, False
    mode, day, score, near = m[1], m[2], int(m[3]), int(m[4])
    t = today()
    if day not in (ymd(t), ymd(t - timedelta(days=1))):
        return {"e": "date", **board(uid)}, False
    if score > MAX_SCORE or near * 25 > score:
        return {"e": "score", **board(uid)}, False
    new_best = submit(uid, q["from"].get("first_name") or "?", mode, day, score)
    return board(uid), new_best


def on_widget_query(q: dict) -> None:
    ans, new_best = handle_query(q)
    call("answerWidgetQuery", widget_query_id=q["id"], data=answer(ans))
    if not new_best:
        return
    uid = q["from"]["id"]
    if "chat" in q:  # keep the best in this message's state (survives device switches)
        challenge = DB["msgs"].get(f"{q['chat']['id']}:{q['message_id']}", 0)
        call("editMessageWidgetData", chat_id=q["chat"]["id"], message_id=q["message_id"],
             chat_data=widget_state(uid, challenge))
    elif "inline_message_id" in q:
        call("editMessageWidgetData", inline_message_id=q["inline_message_id"], chat_data=widget_state(uid))


def handle(u: dict) -> None:
    if "widget_query" in u or "shared_widget_query" in u:
        on_widget_query(u.get("widget_query") or u["shared_widget_query"])
        return
    if "callback_query" in u:
        q = u["callback_query"]
        extra = {"url": GAME_URL} if q.get("game_short_name") else {}
        call("answerCallbackQuery", callback_query_id=q["id"], **extra)
        return

    msg = u.get("message")
    if not msg or "text" not in msg:
        return
    chat, uid = msg["chat"]["id"], msg["from"]["id"]
    parts = msg["text"].split()
    cmd = parts[0].split("@")[0].lower()
    private = msg["chat"]["type"] == "private"

    if cmd in ("/start", "/play"):
        arg = parts[1] if len(parts) > 1 else ""
        challenge = int(arg[1:]) if arg[:1] == "c" and arg[1:].isdecimal() and len(arg) < 9 else 0
        if private:
            send_widget(chat, uid, min(challenge, MAX_SCORE))
        else:  # widgets are private-chat only in production for now
            send_game_card(chat)
    elif cmd == "/full":
        call("sendMessage", chat_id=chat, text="Full-screen Nebula Drift:", reply_markup=play_kb())
    elif cmd == "/game":
        send_game_card(chat)
    elif cmd == "/top":
        call("sendMessage", chat_id=chat, text=top_text(uid))


def main() -> None:
    configure()
    me = call("getMe")
    print(f"running as @{me and me.get('username')} -> {GAME_URL}", flush=True)
    setup()
    offset = 0
    while True:
        updates = call("getUpdates", offset=offset, timeout=50,
                       allowed_updates=["message", "callback_query", "widget_query", "shared_widget_query"])
        if updates is None:
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                handle(u)
            except Exception as e:  # one bad update must not kill the bot
                print(f"update {u.get('update_id')}: {e!r}", flush=True)


if __name__ == "__main__":
    main()
