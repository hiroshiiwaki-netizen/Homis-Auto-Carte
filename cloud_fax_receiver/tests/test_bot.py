# -*- coding: utf-8 -*-
"""受け口 v0.4.0〜v0.5.0 の問い合わせの口（POST /bot/receive）のテスト

test_live.py と同じく、偽の metadata・偽の Cloud Tasks・偽の Chat を立て、本物の server.py を別プロセスで動かして
Tukusi WF1133 と同じ形で送る。すべてダミーの値。
使い方: py -3.12 -X utf8 cloud_fax_receiver/tests/test_bot.py
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import server  # noqa: E402
from test_live import LIVE_Q, URL_OK, LiveFlow  # noqa: E402
from test_mirror import WKEY  # noqa: E402

BOT_KEY = "bot-key-dummy-BBQ"
BOT_S = "問い合わせ着信ダミーYYQ\n二行目"


class BotOrderId(unittest.TestCase):
    def test_o1_cases(self):
        f = server.bot_order_id
        self.assertEqual(f("123", "2026-11-02 16:00:00"), ("BOT-123-20261102160000", ""))
        self.assertEqual(f(123, "2026-11-02 16:00:00"), ("BOT-123-20261102160000", ""))        # 数で来ても
        self.assertEqual(f("１２３", "2026-11-02 16:00:00"), ("BOT-123-20261102160000", ""))     # 全角は半角に
        self.assertEqual(f("", "2026-11-02 16:00:00"), ("", "bad_id"))
        self.assertEqual(f(None, "2026-11-02 16:00:00"), ("", "bad_id"))
        self.assertEqual(f("12/3", "2026-11-02 16:00:00"), ("", "bad_id"))                     # 列の名前に使えない字
        self.assertEqual(f("1" * 21, "2026-11-02 16:00:00"), ("", "bad_id"))                   # 長すぎ
        self.assertEqual(f("123", ""), ("", "bad_sent_at"))
        self.assertEqual(f("123", "2026-11-02 16:00"), ("", "bad_sent_at"))                    # 秒が無い
        self.assertEqual(f("123", None), ("", "bad_sent_at"))
        self.assertLessEqual(len(f("1" * 20, "2026-11-02 16:00:00")[0]), 40)
        # 指摘3: ミリ秒・時差が付いても先頭14桁
        self.assertEqual(f("123", "2026-11-02T16:00:00.123+09:00"), ("BOT-123-20261102160000", ""))

    def test_o2_mode(self):
        env = dict(os.environ)
        try:
            for v, want in [("", "off"), ("off", "off"), ("test", "test"), (" LIVE ", "live"), ("on", "off")]:
                os.environ["BOT_MODE"] = v
                self.assertEqual(server.bot_mode(), want, v)
        finally:
            os.environ.clear()
            os.environ.update(env)


class BotFlow(LiveFlow):
    def start_bot(self, **over):
        env = dict(BOT_MODE="live", BOT_RECEIVER_KEY=BOT_KEY, BOT_FIELD_WEBHOOK=self.chat.url + "/bot")
        env.update(over)
        return self.start_live(**env)

    def send_bot(self, port, inquiry="123", sent_at="2026-11-02 16:00:00", url=URL_OK, homis_id="1234567", s=BOT_S,
                 key=BOT_KEY, path="/bot/receive"):
        d = {"id": inquiry, "sent_at": sent_at, "homis_url": url, "homis_id": homis_id, "s": s}
        body = json.dumps(d, ensure_ascii=False).encode("utf-8")
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        t0 = time.time()
        c.request("POST", path, body=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        r = c.getresponse()
        out = (r.status, r.read(), time.time() - t0)
        c.close()
        return out

    def last_bot(self, log):
        return [r for r in self.records(log) if r.get("event") == "bot_receive"][-1]

    def payload(self, i=0):
        return json.loads(base64.b64decode(self.cloud.tasks[i]["task"]["httpRequest"]["body"]).decode("utf-8"))

    def assert_clean_log(self, log):
        with open(log, encoding="utf-8") as f:
            raw = f.read()
        for w in ("YYQ", WKEY, BOT_KEY, "1234567"):
            self.assertNotIn(w, raw)

    # --- 書く ---
    def test_b1_live_task(self):
        port, log = self.start_bot()
        st, _, _ = self.send_bot(port)
        self.assertEqual(st, 200)
        self.assertEqual(len(self.cloud.tasks), 1)
        task = self.cloud.tasks[0]["task"]
        self.assertEqual(task["name"], LIVE_Q + "/tasks/BOT-123-20261102160000")   # FAX と同じ列
        p = self.payload()
        self.assertEqual((p["orderId"], p["homisId"], p["template"], p["sContent"]),
                         ("BOT-123-20261102160000", "1234567", "bot_s_interrupt", BOT_S))
        self.assertNotIn("oContent", p)
        rec = self.last_bot(log)
        self.assertEqual((rec["mode"], rec["result"], rec["patient_check"]), ("live", "queued", "same"))
        self.assertEqual(self.chat.texts, [])
        self.assert_clean_log(log)

    def test_b2_resend_same_time_is_duplicate_quiet(self):
        # GAS の再送（同じ sent_at）は同じ注文番号＝Cloud Tasks が 409
        port, log = self.start_bot()
        self.cloud.mode = "dup"
        self.send_bot(port)
        self.assertEqual(self.last_bot(log)["result"], "duplicate")
        self.assertEqual(self.chat.texts, [])

    def test_b3_correction_resend_is_new_order(self):
        # 直しの再送（同じ id・別の sent_at）は別の注文番号
        port, log = self.start_bot()
        self.send_bot(port)
        self.send_bot(port, sent_at="2026-11-02 16:05:30")
        names = [t["task"]["name"].rsplit("/", 1)[1] for t in self.cloud.tasks]
        self.assertEqual(names, ["BOT-123-20261102160000", "BOT-123-20261102160530"])

    def test_b4_test_mode_goes_to_test_patient(self):
        port, log = self.start_bot(BOT_MODE="test")
        self.send_bot(port)
        p = self.payload()
        self.assertEqual((p["orderId"], p["homisId"]), ("BOT-TEST-123-20261102160000", "2277808"))
        self.assertEqual(p["sContent"], server.BOT_TEST_MARK + BOT_S)

    # --- 書かない ---
    def check_skip(self, log, word):
        rec = self.last_bot(log)
        self.assertEqual(rec["result"], word)
        self.assertEqual(self.cloud.tasks, [])
        self.assertEqual(sorted(p for p, _ in self.chat.texts), ["/bot", "/dx"])
        for _, text in self.chat.texts:
            self.assertIn("問い合わせ", text)
            self.assertNotIn("FAX", text)
            for w in ("YYQ", "1234567"):
                self.assertNotIn(w, text)

    def test_b5_patient_mismatch(self):
        port, log = self.start_bot()
        self.send_bot(port, homis_id="7654321")
        self.check_skip(log, "skip:id_mismatch")
        self.assertEqual(self.last_bot(log)["patient_check"], "mismatch")

    def test_b6_patient_missing(self):
        port, log = self.start_bot()
        self.send_bot(port, homis_id="")
        self.check_skip(log, "skip:id_missing")

    def test_b7_bad_url(self):
        port, log = self.start_bot()
        self.send_bot(port, url="https://example.com/?patient_id=1234567")
        self.check_skip(log, "skip:bad_homis_id")

    def test_b8_bad_id_and_time(self):
        port, log = self.start_bot()
        self.send_bot(port, inquiry="")
        self.check_skip(log, "skip:bad_id")
        self.chat.texts.clear()
        self.send_bot(port, sent_at="")
        self.check_skip(log, "skip:bad_sent_at")

    def test_b9_empty_s(self):
        port, log = self.start_bot()
        self.send_bot(port, s="  ")
        self.check_skip(log, "skip:empty")

    def test_b10_off_mode_records_only(self):
        port, log = self.start_bot(BOT_MODE="")
        st, _, _ = self.send_bot(port, homis_id="7654321")
        self.assertEqual(st, 200)
        rec = self.last_bot(log)
        self.assertEqual((rec["mode"], rec["result"], rec["patient_check"]), ("off", "off", "mismatch"))
        self.assertEqual(self.cloud.tasks, [])
        self.assertEqual(self.chat.texts, [])

    # --- 合言葉 ---
    def test_b11_keys_are_separate(self):
        port, log = self.start_bot()
        self.assertEqual(self.send_bot(port, key="mirror-test-key")[0], 401)    # FAX の合言葉では通らない
        self.assertEqual(self.cloud.tasks, [])
        st, _, _ = self.send_bot(port, key=BOT_KEY, path="/fax/receive")        # 問い合わせの合言葉で FAX の口も通らない
        self.assertEqual(st, 401)

    def test_b12_no_bot_key_is_503(self):
        port, log = self.start_bot(BOT_RECEIVER_KEY="")
        self.assertEqual(self.send_bot(port)[0], 503)

    def test_b13_tasks_down_notifies_and_still_200(self):
        port, log = self.start_bot()
        self.cloud.mode = "down"
        st, _, sec = self.send_bot(port)
        self.assertEqual(st, 200)
        self.assertLess(sec, 6.5)
        self.assertTrue(self.last_bot(log)["result"].startswith("error:"))
        self.assertEqual(len(self.chat.texts), 2)
        self.cloud.mode = "ok"

    def test_b14_fax_route_unchanged(self):
        # 問い合わせの設定があっても FAX の本番はいつもどおり
        port, log = self.start_bot()
        self.send_live(port, ticket="261102090000-1")
        self.assertEqual(self.cloud.tasks[0]["task"]["name"], LIVE_Q + "/tasks/FAX-261102090000-1")
        self.assertEqual(self.payload()["template"], "fax_so")

    # --- v0.5.0: 問い合わせの列を分ける準備 ---
    BOT_Q = "projects/p/locations/asia-northeast1/queues/homis-bot-writer"

    def test_c1_dispatch_deadline_on_every_task(self):
        # FAX・問い合わせとも、仕事の待ちの上限 900s が task の直下に文字列で付く（httpRequest の中ではない）
        port, log = self.start_bot()
        self.send_live(port, ticket="261105090000-1")
        self.send_bot(port)
        self.assertEqual(len(self.cloud.tasks), 2)
        for t in self.cloud.tasks:
            self.assertEqual(t["task"]["dispatchDeadline"], "900s")
            self.assertNotIn("dispatchDeadline", t["task"]["httpRequest"])
        self.assertEqual(server.TASK_DISPATCH_DEADLINE, "900s")

    def test_c2_bot_queue_separates_inquiry_from_fax(self):
        # BOT_QUEUE があれば問い合わせはそちら、FAX は LIVE_QUEUE のまま（列の名前の前後の空白と / も取る）
        port, log = self.start_bot(BOT_QUEUE=" /" + self.BOT_Q + "/ ")
        self.send_bot(port)
        self.send_live(port, ticket="261105090000-2")
        bot, fax = self.cloud.tasks
        self.assertEqual(bot["path"], "/v2/" + self.BOT_Q + "/tasks")
        self.assertEqual(bot["task"]["name"], self.BOT_Q + "/tasks/BOT-123-20261102160000")
        self.assertEqual(fax["path"], "/v2/" + LIVE_Q + "/tasks")
        self.assertEqual(fax["task"]["name"], LIVE_Q + "/tasks/FAX-261105090000-2")
        self.assertEqual(self.last_bot(log)["result"], "queued")

    def test_c3_empty_bot_queue_falls_back_to_live(self):
        # BOT_QUEUE が空（配置の前）なら今までどおり FAX と同じ列
        port, log = self.start_bot(BOT_QUEUE="  ")
        self.send_bot(port)
        self.assertEqual(self.cloud.tasks[0]["path"], "/v2/" + LIVE_Q + "/tasks")
        self.assertEqual(self.cloud.tasks[0]["task"]["name"], LIVE_Q + "/tasks/BOT-123-20261102160000")

    def test_c4_test_mode_also_uses_bot_queue(self):
        # 試し書き（test）も問い合わせの列に入る（本番と同じ道を通す）
        port, log = self.start_bot(BOT_MODE="test", BOT_QUEUE=self.BOT_Q)
        self.send_bot(port)
        self.assertEqual(self.cloud.tasks[0]["task"]["name"], self.BOT_Q + "/tasks/BOT-TEST-123-20261102160000")


# LiveFlow（と MirrorFlow）のテストを二重に流さない
for _name in [n for n in dir(LiveFlow) if n.startswith("test_")]:
    setattr(BotFlow, _name, None)
del LiveFlow

if __name__ == "__main__":
    unittest.main(verbosity=1)
