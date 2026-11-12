#!/usr/bin/env python3
"""Telegram bot for Nebula Drift (long polling, standard library only).

    python3 bot.py        # reads BOT_TOKEN, GAME_URL[, GAME_SHORT_NAME] from env or ./.env

Two ways to play:
  - In the message: /start or /play sends widget.html as a Bot API 10.4 widget,
    a game that runs inside the chat bubble. The widget asks the bot for the
    leaderboard ("hi") and submits scores ("s:<n>"); the bot keeps them in
    scores.json and writes the player's best into the widget's chat state.
  - Full screen: the menu button and /full open index.html as a Mini App.
  - /game posts a classic game card if GAME_SHORT_NAME is set (@BotFather /newgame).

/start c<score> (from a "Challenge" share link) sends a widget that shows
"beat <score>".
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env() -> None:
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


load_env()
TOKEN = os.environ.get("BOT_TOKEN", "")
GAME_URL = os.environ.get("GAME_URL", "")
GAME_SHORT_NAME = os.environ.get("GAME_SHORT_NAME", "")
if not TOKEN or not GAME_URL:
    sys.exit("BOT_TOKEN and GAME_URL are required (env or .env)")
API = f"https://api.telegram.org/bot{TOKEN}/"
WIDGET_HTML = (HERE / "widget.html").read_text(encoding="utf-8")
DB_PATH = HERE / "scores.json"
MAX_SCORE = 200_000  # anything above is not a real run


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


# ---------------- scores ----------------
def load_db() -> dict:
    try:
        return json.loads(DB_PATH.read_text())
    except (OSError, ValueError):
        return {}


DB = load_db()
DB.setdefault("users", {})  # uid -> {"n": first name, "b": best}
DB.setdefault("msgs", {})   # "chat:msg" -> challenge score shown in that widget


def save_db() -> None:
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(DB))
    tmp.replace(DB_PATH)


def user_best(uid: int) -> int:
    return DB["users"].get(str(uid), {}).get("b", 0)


def board(uid: int) -> str:
    ranked = sorted(DB["users"].items(), key=lambda kv: -kv[1]["b"])
    rank = next((i + 1 for i, (k, _) in enumerate(ranked) if k == str(uid)), 0)
    top = [[v["n"][:12], v["b"]] for _, v in ranked[:5] if v["b"] > 0]
    return json.dumps({"b": user_best(uid), "r": rank, "t": top}, ensure_ascii=False)


# ---------------- sending ----------------
PLAY_KB = {"inline_keyboard": [[{"text": "⛶ Full-screen version", "web_app": {"url": GAME_URL}}]]}
CAPTION = "NEBULA DRIFT · drag ←→ to steer, grab 💎, dodge 💥, ⚡ blasts mines."


def send_widget(chat_id: int, uid: int, challenge: int = 0) -> None:
    state = {"b": user_best(uid)}
    if challenge:
        state["c"] = challenge
    msg = call("sendWidget", chat_id=chat_id, html=WIDGET_HTML, chat_data=json.dumps(state),
               caption=CAPTION + (f"\nFriend's challenge: beat {challenge}!" if challenge else ""),
               allow_queries=True, reply_markup=PLAY_KB)
    if msg is None:  # widgets refused: fall back to the Mini App
        call("sendMessage", chat_id=chat_id, text="Play Nebula Drift:", reply_markup=PLAY_KB)
    elif challenge:
        DB["msgs"][f"{chat_id}:{msg['message_id']}"] = challenge
        save_db()


def send_game_card(chat_id: int) -> None:
    if not GAME_SHORT_NAME:
        call("sendMessage", chat_id=chat_id, text="Game cards aren't set up yet (needs /newgame in @BotFather).",
             reply_markup=PLAY_KB)
        return
    call("sendGame", chat_id=chat_id, game_short_name=GAME_SHORT_NAME)


def setup() -> None:
    call("setMyCommands", commands=[
        {"command": "play", "description": "Play in the chat (widget)"},
        {"command": "full", "description": "Full-screen version (Mini App)"},
        {"command": "top", "description": "Leaderboard"},
    ])
    call("setChatMenuButton", menu_button={"type": "web_app", "text": "Play", "web_app": {"url": GAME_URL}})
    call("setMyShortDescription", short_description="Neon arcade you play right inside the chat.")
    call("setMyDescription", description="Nebula Drift: a neon arcade game that runs inside the message. "
         "Tap Start, then drag left and right.")


# ---------------- updates ----------------
def on_widget_query(q: dict) -> None:
    uid, data = q["from"]["id"], q.get("data", "")
    if data.startswith("s:") and data[2:].isdigit():
        score = int(data[2:])
        if user_best(uid) < score <= MAX_SCORE:
            DB["users"][str(uid)] = {"n": q["from"].get("first_name", "?"), "b": score}
            save_db()
            call("answerWidgetQuery", widget_query_id=q["id"], data=board(uid))
            if "chat" in q:  # keep the best in this message's state (survives device switches)
                state = {"b": score}
                ch = DB["msgs"].get(f"{q['chat']['id']}:{q['message_id']}")
                if ch:
                    state["c"] = ch
                call("editMessageWidgetData", chat_id=q["chat"]["id"], message_id=q["message_id"],
                     chat_data=json.dumps(state))
            return
    call("answerWidgetQuery", widget_query_id=q["id"], data=board(uid))


def handle(u: dict) -> None:
    if "widget_query" in u:
        on_widget_query(u["widget_query"])
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
        challenge = int(arg[1:]) if arg[:1] == "c" and arg[1:].isdigit() else 0
        if private:
            send_widget(chat, uid, min(challenge, MAX_SCORE))
        else:  # widgets are private-chat only in production for now
            send_game_card(chat)
    elif cmd == "/full":
        call("sendMessage", chat_id=chat, text="Full-screen Nebula Drift:", reply_markup=PLAY_KB)
    elif cmd == "/game":
        send_game_card(chat)
    elif cmd == "/top":
        b = json.loads(board(uid))
        lines = [f"{i + 1}. {n} — {s}" for i, (n, s) in enumerate(b["t"])] or ["No scores yet."]
        call("sendMessage", chat_id=chat, text="🏆 Nebula Drift\n" + "\n".join(lines))


def main() -> None:
    me = call("getMe")
    print(f"running as @{me and me.get('username')} -> {GAME_URL}", flush=True)
    setup()
    offset = 0
    while True:
        updates = call("getUpdates", offset=offset, timeout=50,
                       allowed_updates=["message", "callback_query", "widget_query"])
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
