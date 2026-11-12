#!/usr/bin/env python3
"""Telegram bot for Nebula Drift (long polling, standard library only).

    BOT_TOKEN=...  GAME_URL=https://...  [GAME_SHORT_NAME=nebula]  python3 bot.py

Values are read from the environment, falling back to ./.env.

What it does
  - Sets the chat menu button ("Play") so the game opens from the input bar.
  - /start, /play  -> message with an inline "Play" button that opens the Mini App.
  - /game          -> a Telegram game card (needs GAME_SHORT_NAME from @BotFather /newgame);
                      the Play button on the card opens GAME_URL. Game cards also work in groups.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env() -> None:
    env = Path(__file__).with_name(".env")
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


PLAY_KB = {"inline_keyboard": [[{"text": "🚀 Play Nebula Drift", "web_app": {"url": GAME_URL}}]]}

WELCOME = (
    "<b>NEBULA DRIFT</b>\n"
    "Steer a glowing orb through the nebula.\n\n"
    "💎 shards = points (chain them for combos)\n"
    "💥 mines = lose a life\n"
    "🛡 shield · 🧲 magnet · ⏳ chrono power-ups\n"
    "⚡ PULSE blasts nearby mines\n\n"
    "Best score and daily streak sync across your devices."
)


def setup() -> None:
    call("setMyCommands", commands=[
        {"command": "play", "description": "Play Nebula Drift"},
        {"command": "game", "description": "Post a game card (works in groups)"},
    ])
    call("setChatMenuButton", menu_button={"type": "web_app", "text": "Play", "web_app": {"url": GAME_URL}})
    call("setMyShortDescription", short_description="Neon arcade: grab shards, chain combos, dodge mines.")
    call("setMyDescription", description="Nebula Drift: a neon one-thumb arcade game that runs right inside Telegram. Tap Start, then Play.")


def send_game_card(chat_id: int) -> None:
    if not GAME_SHORT_NAME:
        call("sendMessage", chat_id=chat_id, text="Game cards aren't set up yet (needs /newgame in @BotFather). Use the button below:",
             reply_markup=PLAY_KB)
        return
    call("sendGame", chat_id=chat_id, game_short_name=GAME_SHORT_NAME)


def handle(u: dict) -> None:
    if "callback_query" in u:
        q = u["callback_query"]
        if q.get("game_short_name"):
            call("answerCallbackQuery", callback_query_id=q["id"], url=GAME_URL)
        else:
            call("answerCallbackQuery", callback_query_id=q["id"])
        return

    msg = u.get("message")
    if not msg or "text" not in msg:
        return
    chat = msg["chat"]["id"]
    cmd = msg["text"].split()[0].split("@")[0].lower()
    private = msg["chat"]["type"] == "private"

    if cmd in ("/start", "/play"):
        if private:
            call("sendMessage", chat_id=chat, text=WELCOME, parse_mode="HTML", reply_markup=PLAY_KB)
        else:  # web_app inline buttons only work in private chats
            send_game_card(chat)
    elif cmd == "/game":
        send_game_card(chat)


def main() -> None:
    me = call("getMe")
    print(f"running as @{me and me.get('username')} -> {GAME_URL}", flush=True)
    setup()
    offset = 0
    while True:
        updates = call("getUpdates", offset=offset, timeout=50,
                       allowed_updates=["message", "callback_query"])
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
