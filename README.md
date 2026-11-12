# Nebula Drift

A neon one-thumb arcade game that runs inside Telegram as a Mini App. Play it with [@fameOfBot](https://t.me/fameOfBot).

The orb follows your finger by relative drag, so your thumb never covers it. On phones you can also steer by tilting.
- Cyan shards give points, and grabbing them in quick succession builds a combo.
- Red mines cost a life.
- Power-ups: Shield blocks one hit, Magnet pulls shards in, Chrono slows time.
- PULSE clears nearby mines and has a 6-second cooldown.

## Files

- `index.html`: the whole game in one file (HTML, CSS and JS). It runs in Telegram and in an ordinary browser.
- `bot.py`: the bot, using long polling and the standard library only. It sets the chat menu button, answers `/play` with a Mini App button, and answers `/game` with a game card if `GAME_SHORT_NAME` is set.

## Telegram features used

Each feature is turned on only after a version check, so older clients still work:

- Bottom buttons: MainButton and SecondaryButton.
- BackButton pauses the game. SettingsButton opens a popup with settings.
- HapticFeedback on game events.
- CloudStorage holds the best score, games played and day streak. DeviceStorage holds settings.
- Fullscreen, with orientation lock.
- Tilt steering through DeviceOrientation.
- Safe-area insets.
- The game auto-pauses when Telegram goes to the background (`deactivated` event). While you play, it asks before closing and turns off vertical swipes.
- It offers a home-screen shortcut, hides the keyboard, and sets header and bottom-bar colours.

## Run the bot

```sh
cp .env.example .env   # fill in BOT_TOKEN
python3 bot.py
```

## In-message widget: ORBIT (Bot API 10.4)

`widget.html` is **ORBIT**, a one-tap game that runs **inside the chat bubble** as a [Telegram widget](https://core.telegram.org/bots/widgets).

- You orbit a small star, and a tap switches between two rings to dodge shards, comets and flares.
- Sparks build a combo, and near misses score bonus points.
- The orbit reverses every 20 s.
- **Daily** mode is seeded by the UTC date, so everyone plays the same run that day and shares a daily leaderboard. **Endless** mode uses a random seed.
- It is drawn in the chat's own theme colours.

Widget limits and budgets:
- Size: 4096 bytes after zlib-9. The widget sits at about 4.0 KB.
- Sandbox: QuickJS, with no network access.
- Drawing: at most ~22 canvas calls per frame at 30 fps, with static geometry pre-rendered offscreen.

How it talks to the bot:
- The widget sends `h` (load the board) and `s:<mode>:<yyyymmdd>:<score>:<near>` (submit a run) through `TelegramWidget.request()`.
- `bot.py` validates each request, keeps daily boards, all-time bests and play streaks in `scores.json`, and answers with `answerWidgetQuery`.
- On a new best, the bot writes `{best, streak}` into the message's chat state with `editMessageWidgetData`.

Checks:

```sh
python3 tests/check_widget.py        # size + out-of-profile features
python3 -m unittest discover -s tests
node tests/sim_widget.mjs            # headless runs, determinism, canvas calls/frame
# visual: serve the repo and open /tests/harness.html?theme=dark|light
```
