"""Unit tests for the ORBIT widget protocol in bot.py (stdlib unittest, no network).

    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot  # noqa: E402

DAY = date(2026, 11, 12)


def ymd(d):
    return d.strftime("%Y%m%d")


class BotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = (bot.DB_PATH, bot.DB, bot.call, bot.today)
        self.addCleanup(self.restore)
        bot.DB_PATH = Path(self.tmp.name) / "scores.json"
        bot.DB = bot.load_db()
        self.calls = []
        bot.call = lambda method, **p: self.calls.append((method, p)) or {"message_id": 77}
        self.day = DAY
        bot.today = lambda: self.day

    def restore(self):
        bot.DB_PATH, bot.DB, bot.call, bot.today = self.saved

    # helpers
    def query(self, data, uid=1, name="Alice", chat=True, msg_id=42):
        q = {"id": f"q{len(self.calls)}", "from": {"id": uid, "is_bot": False, "first_name": name}, "data": data}
        if chat:
            q.update(chat={"id": uid, "type": "private"}, message_id=msg_id, chat_instance="1")
        self.calls.clear()
        bot.handle({"update_id": 1, "widget_query": q})
        answers = [p for m, p in self.calls if m == "answerWidgetQuery"]
        self.assertEqual(len(answers), 1, "every query gets exactly one answer")
        self.assertEqual(answers[0]["widget_query_id"], q["id"])
        raw = answers[0]["data"]
        self.assertLessEqual(len(raw.encode()), 1024)
        return json.loads(raw)

    def edits(self):
        return [p for m, p in self.calls if m == "editMessageWidgetData"]

    def submit(self, score, uid=1, name="Alice", mode="d", day=None, near=0):
        return self.query(f"s:{mode}:{ymd(day or self.day)}:{score}:{near}", uid=uid, name=name)

    # tests
    def test_hello(self):
        a = self.query("h")
        self.assertEqual(a, {"t": [], "n": 0, "r": 0, "d": 0, "b": 0, "k": 0})
        self.assertEqual(self.edits(), [])
        self.assertLessEqual(len("s:d:20261112:100000:4000"), 64)

    def test_valid_submit(self):
        a = self.submit(500, near=3)
        self.assertNotIn("e", a)
        self.assertEqual((a["r"], a["n"], a["d"], a["b"], a["k"]), (1, 1, 500, 500, 1))
        self.assertEqual(a["t"], [["Alice", 500]])
        stored = json.loads(bot.DB_PATH.read_text())
        self.assertEqual(stored["o"]["u"]["1"]["b"], 500)
        self.assertEqual(stored["o"]["d"][ymd(DAY)]["1"], 500)
        self.assertFalse(bot.DB_PATH.with_suffix(".tmp").exists(), "atomic write leaves no temp file")

    def test_yesterday_accepted(self):
        a = self.submit(120, day=DAY - timedelta(days=1))
        self.assertNotIn("e", a)
        self.assertEqual(a["b"], 120)
        self.assertEqual(a["d"], 0, "yesterday's daily run is not on today's board")

    def test_rejects_stale_date(self):
        for d in (DAY - timedelta(days=2), DAY + timedelta(days=1)):
            a = self.submit(300, day=d)
            self.assertEqual(a["e"], "date")
            self.assertEqual(a["b"], 0)
            self.assertEqual(self.edits(), [])
        self.assertNotIn("1", bot.DB["o"]["u"])

    def test_rejects_huge_score(self):
        a = self.submit(999_999)
        self.assertEqual(a["e"], "score")
        self.assertEqual(self.submit(bot.MAX_SCORE + 1)["e"], "score")
        self.assertEqual(self.submit(100, near=5)["e"], "score", "each near miss is worth at least 25")
        self.assertEqual(bot.DB["o"]["u"], {})
        self.assertEqual(self.edits(), [])

    def test_rejects_malformed(self):
        for data in ("s:x:20261112:5:0", "s:d:2026111:5:0", "s:d:20261112:-5:0", "s:d:20261112:5",
                     "s:d:20261112:12345678901:0", "s:d:20261112:5:0:9", "hello", "s:d:20261112:٣:0"):
            self.assertEqual(self.query(data)["e"], "bad", data)
        self.assertEqual(bot.DB["o"]["u"], {})

    def test_daily_rank_ordering(self):
        self.submit(300, uid=1, name="Alice")
        self.submit(700, uid=2, name="Bob")
        self.submit(500, uid=3, name="Carol")
        self.submit(900, uid=4, name="Dave", mode="e")  # endless: all-time only
        a = self.query("h", uid=3)
        self.assertEqual(a["t"], [["Bob", 700], ["Carol", 500], ["Alice", 300]])
        self.assertEqual((a["r"], a["n"], a["d"]), (2, 3, 500))
        self.assertEqual(self.query("h", uid=4)["r"], 0)
        self.assertEqual(self.query("h", uid=4)["b"], 900)
        # a lower daily run does not replace the daily best, a higher one moves the rank
        self.submit(100, uid=1, name="Alice")
        self.assertEqual(self.query("h", uid=1)["d"], 300)
        a = self.submit(800, uid=1, name="Alice")
        self.assertEqual((a["r"], a["t"][0]), (1, ["Alice", 800]))

    def test_top5_and_name_cut(self):
        for i in range(8):
            self.submit(100 + i, uid=10 + i, name="A very long first name " + str(i))
        a = self.query("h", uid=10)
        self.assertEqual(len(a["t"]), 5)
        self.assertEqual(a["t"][0], ["A very long ", 107])
        self.assertEqual((a["r"], a["n"]), (8, 8))

    def test_streak_increment_and_reset(self):
        self.assertEqual(self.submit(10)["k"], 1)
        self.assertEqual(self.submit(20)["k"], 1, "a second run on the same day keeps the streak")
        self.day = DAY + timedelta(days=1)
        self.assertEqual(self.submit(10)["k"], 2)
        self.day = DAY + timedelta(days=2)
        self.assertEqual(self.query("h")["k"], 2, "the streak survives until the end of the next day")
        self.assertEqual(self.submit(10)["k"], 3)
        self.day = DAY + timedelta(days=4)
        self.assertEqual(self.query("h")["k"], 0, "a missed day breaks the streak")
        self.assertEqual(self.submit(10)["k"], 1, "and the next run starts a new one")
        # a late submission for yesterday does not move the streak backwards
        self.assertEqual(self.submit(10, day=self.day - timedelta(days=1))["k"], 1)

    def test_edit_only_on_new_best(self):
        self.submit(500)
        e = self.edits()
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]["chat_id"], e[0]["message_id"]), (1, 42))
        self.assertEqual(json.loads(e[0]["chat_data"]), {"best": 500, "streak": 1})
        self.submit(400)
        self.assertEqual(self.edits(), [])
        self.query("h")
        self.assertEqual(self.edits(), [])
        self.submit(600, mode="e")
        self.assertEqual(json.loads(self.edits()[0]["chat_data"])["best"], 600)

    def test_edit_keeps_challenge(self):
        bot.DB["msgs"]["1:42"] = 250
        self.submit(300)
        self.assertEqual(json.loads(self.edits()[0]["chat_data"]), {"best": 300, "streak": 1, "c": 250})

    def test_answer_before_edit(self):
        self.submit(50)
        methods = [m for m, _ in self.calls]
        self.assertLess(methods.index("answerWidgetQuery"), methods.index("editMessageWidgetData"))

    def test_old_daily_boards_pruned(self):
        self.submit(10)
        self.day = DAY + timedelta(days=5)
        self.submit(20)
        self.assertEqual(list(bot.DB["o"]["d"]), [ymd(self.day)])

    def test_start_sends_widget_with_state(self):
        self.submit(300)
        self.calls.clear()
        bot.handle({"update_id": 2, "message": {"text": "/start c120", "chat": {"id": 1, "type": "private"},
                                                "from": {"id": 1, "first_name": "Alice"}}})
        sent = [p for m, p in self.calls if m == "sendWidget"]
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0]["allow_queries"])
        self.assertEqual(json.loads(sent[0]["chat_data"]), {"best": 300, "streak": 1, "c": 120})
        self.assertEqual(bot.DB["msgs"]["1:77"], 120)

    def test_top_command(self):
        self.submit(300, uid=1, name="Alice")
        self.submit(900, uid=2, name="Bob", mode="e")
        self.calls.clear()
        bot.handle({"update_id": 3, "message": {"text": "/top", "chat": {"id": 1, "type": "private"},
                                                "from": {"id": 1, "first_name": "Alice"}}})
        text = [p for m, p in self.calls if m == "sendMessage"][0]["text"]
        self.assertIn("1. Alice — 300", text)
        self.assertIn("All-time\n1. Bob — 900\n2. Alice — 300", text)
        self.assertIn("t.me/fameOfBot?start=c300", text)


if __name__ == "__main__":
    unittest.main()
