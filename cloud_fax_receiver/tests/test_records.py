# -*- coding: utf-8 -*-
"""受け口 v0.6.0 の実行リストの記録（received・rejected）のテスト

本物の server.py を別プロセスで動かし、偽の metadata・偽の Cloud Tasks（test_mirror.FakeCloud）・偽の Chat（test_live.FakeChat）・
偽の Cloud Storage（cloud/tests/fake_records.py）に向ける。Tukusi と同じ形で送り、置き場に残った JSON を確かめる。すべてダミーの値。
使い方: py -3.12 -X utf8 cloud_fax_receiver/tests/test_records.py
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "cloud", "tests"))
from fake_records import FakeRecords  # noqa: E402
from test_live import LIVE_Q, URL_OK, FakeChat  # noqa: E402
from test_mirror import KEY, SECRET_O, SECRET_S, SERVER, WKEY, FakeCloud, free_port  # noqa: E402

BOT_KEY = "bot-key-dummy-RRQ"
BOT_Q = "projects/p/locations/asia-northeast1/queues/homis-bot-writer"


class Records(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cloud = FakeCloud()
        cls.chat = FakeChat()
        cls.rec = FakeRecords()
        cls.tmp = tempfile.mkdtemp(prefix="records_")

    @classmethod
    def tearDownClass(cls):
        cls.cloud.close()
        cls.chat.close()
        cls.rec.close()

    def start(self, **over):
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        self.chat.texts.clear()
        self.rec.reset()
        port = free_port()
        log = os.path.join(self.tmp, f"recv_{port}.jsonl")
        env = dict(os.environ, PORT=str(port), FAX_RECEIVER_KEY=KEY, PYTHONIOENCODING="utf-8",
                   FAX_MODE="live", LIVE_QUEUE=LIVE_Q, WRITER_URL="https://writer.example.run.app",
                   TASKS_INVOKER_SA="homis-tasks-invoker@p.iam.gserviceaccount.com", WRITER_KEY=WKEY,
                   METADATA_TOKEN_URL=f"http://127.0.0.1:{self.cloud.port}/token",
                   CLOUD_TASKS_BASE=f"http://127.0.0.1:{self.cloud.port}/v2/",
                   FAX_FIELD_WEBHOOK=self.chat.url + "/field", DX_ALERT_WEBHOOK=self.chat.url + "/dx",
                   BOT_MODE="live", BOT_RECEIVER_KEY=BOT_KEY, BOT_QUEUE=BOT_Q, BOT_FIELD_WEBHOOK=self.chat.url + "/bot",
                   RECORD_BUCKET="test-records", GCS_BASE=self.rec.url)
        env.update(over)
        f = open(log, "w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-u", SERVER], env=env, stdout=f, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                c.request("GET", "/health")
                if c.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        self.addCleanup(lambda: (p.terminate(), p.wait(10), f.close()))
        return port, log

    def post(self, port, path, d, key):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=40)
        t0 = time.time()
        c.request("POST", path, body=json.dumps(d, ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        r = c.getresponse()
        out = (r.status, time.time() - t0)
        r.read()
        c.close()
        return out

    def fax(self, port, ticket="261106090000-1", homis=URL_OK, patient="1234567", o=SECRET_O):
        d = {"source": "WF1573", "lock": {"ticket": ticket, "granted": True}, "homis_id": homis, "homis_patient": patient,
             "s": SECRET_S, "o": o, "doc_type": "検査結果", "route": "垂水FAX"}
        return self.post(port, "/fax/receive", d, KEY)

    def bot(self, port, inquiry="123", sent_at="2026-11-06 09:00:00", s="問い合わせダミーPPQ"):
        d = {"id": inquiry, "sent_at": sent_at, "homis_url": URL_OK, "homis_id": "1234567", "s": s}
        return self.post(port, "/bot/receive", d, BOT_KEY)

    def records(self):
        return {n.rsplit("/", 1)[1][:-5]: r for n, (g, r) in self.rec.objects.items()}

    def day_of_only_record(self):
        names = list(self.rec.objects)
        self.assertEqual(len(names), 1, names)
        return names[0].split("/")[1]

    def task_payload(self, i=0):
        return json.loads(base64.b64decode(self.cloud.tasks[i]["task"]["httpRequest"]["body"]).decode("utf-8"))

    def log_text(self, log):
        with open(log, encoding="utf-8") as f:
            return f.read()

    # ---- FAX ----
    def test_q1_fax_received(self):
        port, log = self.start()
        self.assertEqual(self.fax(port)[0], 200)
        rec = self.records()["FAX-261106090000-1"]
        self.assertEqual((rec["status"], rec["route"], rec["doc_type"], rec["source"], rec["fax_route"]),
                         ("received", "fax", "検査結果", "WF1573", "垂水FAX"))
        self.assertEqual((rec["payload"]["sContent"], rec["payload"]["oContent"]), (SECRET_S, SECRET_O))
        self.assertEqual(rec["patient"], {"homis_id": "1234567"})
        self.assertNotIn("recordDay", rec["payload"])
        p = self.task_payload()
        self.assertEqual(p["recordDay"], self.day_of_only_record())   # ライターが同じ日のフォルダに足せる
        self.assertNotIn(SECRET_O, self.log_text(log))   # 本文はログに出ない

    def test_q2_fax_rejected_bad_patient(self):
        port, _ = self.start()
        self.assertEqual(self.fax(port, patient="7654321")[0], 200)   # 食い違い
        self.assertEqual(self.cloud.tasks, [])
        rec = self.records()["FAX-261106090000-1"]
        self.assertEqual((rec["status"], rec["error_type"], rec["left_in_homis"]), ("rejected", "skip:id_mismatch", "none"))
        self.assertEqual(rec["payload"]["oContent"], SECRET_O)   # 落としたものも中身を見られる

    def test_q3_fax_no_ticket(self):
        port, _ = self.start()
        d = {"source": "WF1573", "homis_id": URL_OK, "homis_patient": "1234567", "s": "s", "o": "o", "doc_type": "処方箋"}
        self.assertEqual(self.post(port, "/fax/receive", d, KEY)[0], 200)
        (name, rec), = self.records().items()
        self.assertTrue(name.startswith("FAX-NOID-"), name)
        self.assertEqual((rec["status"], rec["error_type"], rec["doc_type"]), ("rejected", "skip:no_ticket", "処方箋"))

    def test_q4_tasks_down_rejected(self):
        port, _ = self.start()
        self.cloud.mode = "down"
        status, sec = self.fax(port)
        self.assertEqual(status, 200)
        self.assertLess(sec, 28)   # 受け口の上限 30 秒の中
        rec = self.records()["FAX-261106090000-1"]
        self.assertEqual(rec["status"], "rejected")
        self.assertTrue(rec["error_type"].startswith("error:"), rec["error_type"])

    def test_q5_storage_hang_does_not_block(self):
        port, _ = self.start()
        self.rec.mode, self.rec.hang_sec = "hang", 8.0
        status, sec = self.fax(port)
        self.assertEqual(status, 200)
        self.assertLess(sec, 6.0)          # 記録は 3 秒であきらめる
        self.assertEqual(len(self.cloud.tasks), 1)   # 列には入る

    def test_q6_second_arrival_keeps_writer_result(self):
        port, _ = self.start()
        self.assertEqual(self.fax(port)[0], 200)
        name = next(iter(self.rec.objects))
        rec = self.rec.get(name)
        rec.update(status="ok", karte_id="55")
        self.rec.put(name, rec)                      # ライターが書き終えた
        self.cloud.mode = "dup"
        self.assertEqual(self.fax(port)[0], 200)     # 同じ札がもう一度（409）
        self.assertEqual(self.rec.get(name)["status"], "ok")
        self.assertEqual(self.fax(port, patient="7654321")[0], 200)   # 同じ札で今度は落とした
        got = self.rec.get(name)
        self.assertEqual((got["status"], got["karte_id"]), ("ok", "55"))   # 結果は消さず、一言だけ足す
        self.assertIn("同じ注文がもう一度届き", got["timeline"][-1]["what"])

    def test_q7_off_without_bucket(self):
        port, _ = self.start(RECORD_BUCKET="")
        self.assertEqual(self.fax(port)[0], 200)
        self.assertEqual(self.rec.calls, [])
        self.assertNotIn("recordDay", self.task_payload())   # 置き場が無ければ仕事の形は今まで通り

    # ---- 問い合わせ・疑義照会 ----
    def test_q8_bot_and_gi(self):
        port, _ = self.start()
        self.assertEqual(self.bot(port)[0], 200)
        self.assertEqual(self.bot(port, inquiry="G", sent_at="2026-11-06 09:05:00")[0], 200)
        recs = self.records()
        a, g = recs["BOT-123-20261106090000"], recs["BOT-G-20261106090500"]
        self.assertEqual((a["status"], a["doc_type"], a["route"]), ("received", "問い合わせ", "bot"))
        self.assertEqual((g["status"], g["doc_type"], g["route"]), ("received", "疑義照会", "bot_g"))
        self.assertEqual(a["payload"]["template"], "bot_s_interrupt")
        self.assertEqual(self.task_payload(1)["recordDay"], self.task_payload(0)["recordDay"])

    def test_q9_bot_rejected_without_number(self):
        port, _ = self.start()
        self.assertEqual(self.bot(port, inquiry="G", sent_at="")[0], 200)   # 時刻が無い疑義照会
        (name, rec), = self.records().items()
        self.assertTrue(name.startswith("BOT-G-NOID-"), name)
        self.assertEqual((rec["status"], rec["error_type"], rec["doc_type"]), ("rejected", "skip:bad_sent_at", "疑義照会"))

    def test_q10_bot_test_mode_marked(self):
        port, _ = self.start(BOT_MODE="test")
        self.assertEqual(self.bot(port)[0], 200)
        (name, rec), = self.records().items()
        self.assertEqual((name, rec["route"]), ("BOT-TEST-123-20261106090000", "bot_test"))   # 画面ではふだん隠す


if __name__ == "__main__":
    unittest.main(verbosity=2)
