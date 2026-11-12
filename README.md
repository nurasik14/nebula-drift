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

## In-message widget (Bot API 10.4)

`widget.html` is a cut-down version (about 3.8 KB compressed, limit 4 KB) that runs **inside the chat bubble** as a [Telegram widget](https://core.telegram.org/bots/widgets). The orb moves only left and right, because vertical drags always scroll the chat. The widget asks the bot for the leaderboard and submits scores with `TelegramWidget.request()`. The bot answers with `answerWidgetQuery` and keeps each player's best in the widget's chat state.

Widgets run in Telegram's QuickJS sandbox, and the Telegram app replays every canvas call. So the widget pre-renders its sprites and starfield into offscreen canvases, draws each frame with about 40 calls, and runs at 30 fps while playing (about 8 fps when idle).
