# -*- coding: utf-8 -*-
"""書込失敗の自動やり直し（auto_retry.py 1.0.0・ライター 3.12.0）のテスト。すべてダミーの値。

本物の server.py の流れ（_write_karte_inner → _locked_out → 知らせ → 記録 → 予約）を通し、
HOMIS・列・Chat・カルテ一覧だけ偽物にする。記録は偽の置き場（fake_records）に本物の run_record で書く。
使い方: py -3.12 -X utf8 cloud/tests/test_auto_retry.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_run_record as trr  # noqa: E402  shared_log の偽物と置き場の準備を借りる
import auto_retry as ar  # noqa: E402

DAY = trr.DAY


class Parts(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        os.environ["RETRY_MODE"] = "on"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)

    def test_p1_attempt_and_next(self):
        self.assertEqual(ar.split_attempt("FAX-261106-7"), ("FAX-261106-7", 0))
        self.assertEqual(ar.split_attempt("FAX-261106-7-A2"), ("FAX-261106-7", 2))
        self.assertEqual(ar.next_order_id("FAX-261106-7"), "FAX-261106-7-A1")
        self.assertEqual(ar.next_order_id("FAX-261106-7-A1"), "FAX-261106-7-A2")   # 元の番号に付け直す
        self.assertEqual(ar.next_order_id("FAX-261106-7-A3"), "")                  # 3 回目のあとは無い
        self.assertEqual(ar.split_attempt("FAX-1-A4"), ("FAX-1-A4", 0))           # 決まった形でなければ 0 回

    def test_p2_never_more_than_three_from_any_start(self):
        for start in ("FAX-1", "FAX-1-A1", "FAX-1-A1-A1", "BOT-G-20261106131542-A2", "FAX-1-A9"):
            o, n = start, 0
            while True:
                nxt = ar.next_order_id(o)
                if not nxt:
                    break
                o, n = nxt, n + 1
                self.assertLessEqual(n, 3, start)   # どこから始めても 3 回で止まる

    def test_p3_eligible_matrix(self):
        ok = ("fax_so", "FAX-1", "locked:busy", "none")
        self.assertTrue(ar.eligible(*ok))
        for err in ar.RETRYABLE_ERRORS:
            self.assertTrue(ar.eligible("bot_s_interrupt", "BOT-G-20261106131542", err, "none"), err)
        for err in ("verify:o_mismatch", "no_karte_id", "stopped:unverified_input", "blocked:reused_editing",
                    "skipped:new_karte_found", "sheet", "opened_then_fail"):
            self.assertFalse(ar.eligible("fax_so", "FAX-1", err, "none"), err)
        for left in ("editing", "saved", "unknown", ""):
            self.assertFalse(ar.eligible("fax_so", "FAX-1", "locked:busy", left), left)
        self.assertFalse(ar.eligible("xray_karte", "FAX-1", "locked:busy", "none"))     # レントゲンはやらない
        self.assertFalse(ar.eligible("fax_so", "FAX-MIRROR-1", "locked:busy", "none"))  # 試し書きはやらない
        self.assertTrue(ar.eligible("bot_s_interrupt", "BOT-TEST-1-20261106090000", "locked:busy", "none"))
        self.assertFalse(ar.eligible("fax_so", "FAX-1-A3", "locked:busy", "none"))      # 3 回目のあと
        os.environ["RETRY_MODE"] = "off"
        self.assertFalse(ar.eligible(*ok))                                               # 切っていれば何もしない

    def test_p4_build_task(self):
        os.environ.update(WRITER_URL="https://writer.example.run.app/", TASKS_INVOKER_SA="inv@p.iam.gserviceaccount.com",
                          HOMIS_WRITER_KEY="wk-dummy")
        now = datetime(2026, 11, 6, 1, 0, 0, tzinfo=timezone.utc)
        t = ar.build_task("projects/p/locations/l/queues/homis-fax-writer", {"orderId": "FAX-1-A1", "sContent": "s"}, 300, now)["task"]
        self.assertEqual(t["name"], "projects/p/locations/l/queues/homis-fax-writer/tasks/FAX-1-A1")
        self.assertEqual(t["scheduleTime"], "2026-11-06T01:05:00Z")
        self.assertEqual(t["dispatchDeadline"], "900s")
        self.assertEqual(t["httpRequest"]["url"], "https://writer.example.run.app/write")
        self.assertEqual(t["httpRequest"]["headers"]["X-Writer-Key"], "wk-dummy")
        self.assertEqual(json.loads(base64.b64decode(t["httpRequest"]["body"]))["orderId"], "FAX-1-A1")

    def test_p5_human_wrote_compares_numbers(self):
        saved = ar.latest_karte_id
        try:
            ar.latest_karte_id = lambda h: 100000
            self.assertEqual(ar.human_wrote("1234567", "99999"), (True, 100000))   # 文字で比べると逆になる境目
            ar.latest_karte_id = lambda h: 99999
            self.assertEqual(ar.human_wrote("1234567", 99999), (False, 99999))
            ar.latest_karte_id = lambda h: None
            self.assertEqual(ar.human_wrote("1234567", 5), (True, None))           # 読めなければ止める
            self.assertEqual(ar.human_wrote("1234567", None), (True, None))        # 控えが無ければ止める
        finally:
            ar.latest_karte_id = saved


class Flow(trr.Base):
    """本物のライターの流れ（_write_karte_inner）。札が取れない（locked:busy）で失敗を作る"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import server   # noqa: PLC0415
        cls.s = server

    def setUp(self):
        super().setUp()
        s = self.s
        os.environ.update(RETRY_MODE="on", FAX_FIELD_WEBHOOK="https://chat.example/field", BOT_FIELD_WEBHOOK="https://chat.example/bot")
        self.field, self.dx, self.queued = [], [], []
        self.list_id = 500
        self.enqueue_word = "queued"
        self.saved = {
            "sheet_enabled": s.sheet_enabled, "_notify_field": s._notify_field, "_write_locked": s._write_locked,
            "acquire": s.patient_lock.acquire, "notify_dx": s.navi_callback.notify_dx,
            "enqueue": ar.enqueue, "latest": ar.latest_karte_id,
        }
        s.sheet_enabled = lambda: False
        s._notify_field = lambda order_id, url, err, template="fax_so", prefix="", note="": self.field.append((order_id, err, prefix, note))
        s.navi_callback.notify_dx = lambda text, order_id="": self.dx.append((order_id, text))
        s.patient_lock.acquire = lambda h, o: {"status": "busy", "generation": "", "waited_sec": 320, "reason": "x"}
        ar.enqueue = lambda template, payload, delay: (self.queued.append((template, payload, delay)), self.enqueue_word)[1]
        ar.latest_karte_id = lambda h: self.list_id

    def tearDown(self):
        s, v = self.s, self.saved
        s.sheet_enabled, s._notify_field, s._write_locked = v["sheet_enabled"], v["_notify_field"], v["_write_locked"]
        s.patient_lock.acquire, s.navi_callback.notify_dx = v["acquire"], v["notify_dx"]
        ar.enqueue, ar.latest_karte_id = v["enqueue"], v["latest"]
        super().tearDown()

    def data(self, order="FAX-261106-7", **extra):
        d = {"orderId": order, "homisId": "1234567", "template": "fax_so", "sContent": "s", "oContent": "o", "recordDay": DAY}
        d.update(extra)
        return d

    def run_order(self, order="FAX-261106-7", **extra):
        return self.s._write_karte_inner(self.data(order, **extra), order, "1234567")

    def test_f1_first_failure_tells_field_and_schedules_a1(self):
        self.fake.put(self.name("FAX-261106-7"), {"order_id": "FAX-261106-7", "status": "received", "doc_type": "検査結果",
                                                  "patient": {"homis_id": "1234567"}})
        res = self.run_order()
        self.assertEqual(res["error_type"], "locked:busy")
        (oid, err, prefix, note), = self.field
        self.assertTrue(prefix.startswith("【手で書かずにお待ちください】"))
        self.assertIn("自動でやり直します", note)
        (template, payload, delay), = self.queued
        self.assertEqual((payload["orderId"], delay, payload["baseline_karte_id"], payload["recordDay"]), ("FAX-261106-7-A1", 300, 500, DAY))
        parent = self.fake.get(self.name("FAX-261106-7"))
        child = self.fake.get(self.name("FAX-261106-7-A1"))
        self.assertEqual((parent["status"], parent["retried_as"]), ("handed_over", "FAX-261106-7-A1"))
        self.assertEqual((child["status"], child["retry_of"], child["attempt"], child["doc_type"]), ("scheduled", "FAX-261106-7", 1, "検査結果"))
        self.assertEqual(child["payload"]["oContent"], "o")
        self.assertNotIn("baseline_karte_id", child["payload"])

    def test_f2_middle_failure_dx_only_and_a2_in_15min(self):
        self.run_order("FAX-261106-7-A1", baseline_karte_id=500)
        self.assertEqual(self.field, [])                              # 途中の失敗は現場に出さない
        self.assertTrue(any("1 回目も書けませんでした" in t for _, t in self.dx))
        (_, payload, delay), = self.queued
        self.assertEqual((payload["orderId"], delay, payload["baseline_karte_id"]), ("FAX-261106-7-A2", 900, 500))

    def test_f3_third_failure_asks_hand_and_stops(self):
        self.run_order("FAX-261106-7-A3", baseline_karte_id=500)
        self.assertEqual(self.queued, [])                             # 3 回目のあとは入れない
        (_, _, prefix, _), = self.field
        self.assertIn("自動で 3 回やり直しましたが書けませんでした。手で書いてください", prefix)
        self.assertTrue(self.fake.get(self.name("FAX-261106-7-A3"))["manual"])

    def test_f4_human_wrote_skips_without_writing(self):
        self.list_id = 501
        called = []
        self.s._write_locked = lambda *a: called.append(1)
        res = self.run_order("FAX-261106-7-A1", baseline_karte_id=500)
        self.assertEqual((res["error_type"], res["left_in_homis"]), ("skipped:new_karte_found", "none"))
        self.assertEqual((called, self.field, self.queued), ([], [], []))   # 書かない・現場に出さない・入れない
        self.assertTrue(any("新しいカルテ 501" in t for _, t in self.dx))
        rec = self.fake.get(self.name("FAX-261106-7-A1"))
        self.assertEqual(rec["error_type"], "skipped:new_karte_found")
        self.assertNotIn("manual", rec)                                       # 「手動でお願いします」と出さない

    def test_f5_list_unreadable_asks_hand(self):
        self.list_id = None
        res = self.run_order("FAX-261106-7-A1", baseline_karte_id=500)
        self.assertEqual(res["error_type"], "skipped:karte_list_unreadable")
        (_, _, prefix, _), = self.field
        self.assertIn("手で書いてください", prefix)
        self.assertTrue(self.fake.get(self.name("FAX-261106-7-A1"))["manual"])

    def test_f6_enqueue_failure_asks_hand(self):
        self.enqueue_word = "error:http403"
        self.run_order()
        self.assertEqual(len(self.field), 2)                                  # 1 回目の案内＋入れられなかった
        self.assertIn("自動でやり直せませんでした", self.field[1][2])
        self.assertTrue(self.fake.get(self.name("FAX-261106-7"))["manual"])

    def test_f7_no_baseline_does_not_retry(self):
        self.list_id = None
        self.run_order()
        self.assertEqual(self.queued, [])
        self.assertIn("自動でやり直せませんでした", self.field[-1][2])

    def test_f8_mode_off_is_unchanged(self):
        os.environ["RETRY_MODE"] = "off"
        self.run_order()
        (_, _, prefix, note), = self.field
        self.assertEqual((prefix, note, self.queued), ("", "", []))           # 今までどおりの知らせだけ

    def test_f9_not_retryable_is_normal(self):
        self.s.patient_lock.acquire = lambda h, o: {"status": "ok", "generation": "1", "waited_sec": 0}
        self.s._write_locked = lambda *a: {"success": False, "error_type": "verify:o_mismatch", "left_in_homis": "saved",
                                           "karte_id": "9", "verify": "o_mismatch"}
        saved_release = self.s._release_lock
        self.s._release_lock = lambda o: None
        try:
            self.run_order()
        finally:
            self.s._release_lock = saved_release
        self.assertEqual(self.queued, [])
        rec = self.fake.get(self.name("FAX-261106-7"))
        self.assertEqual(rec["verify"], "o_mismatch")                        # 書込後確認を記録
        self.assertIn("書込後確認 ×", [t["what"] for t in rec["timeline"]])

    def test_f10_retry_success_is_silent_to_field(self):
        self.s.patient_lock.acquire = lambda h, o: {"status": "ok", "generation": "1", "waited_sec": 0}
        self.s._write_locked = lambda *a: {"success": True, "error_type": "", "left_in_homis": "saved", "karte_id": "9",
                                           "karte_url": "https://homis.jp/k?karte_id=9", "verify": "unverified"}
        saved_release = self.s._release_lock
        self.s._release_lock = lambda o: None
        try:
            self.run_order("FAX-261106-7-A2", baseline_karte_id=500)
        finally:
            self.s._release_lock = saved_release
        self.assertEqual((self.field, self.queued), ([], []))                # 成功は現場に出さない
        rec = self.fake.get(self.name("FAX-261106-7-A2"))
        self.assertIn("書込後確認 未確認（カルテは保存済み）", [t["what"] for t in rec["timeline"]])
        self.assertNotIn("manual", rec)



class ProcessedFlow(Flow):
    """v3.12.0: 書いた直後に人が処理した（ok_processed）は書込成功・現場にも DX にも失敗を出さない"""

    def test_g1_ok_processed_is_success(self):
        self.s.patient_lock.acquire = lambda h, o: {"status": "ok", "generation": "1", "waited_sec": 0}
        self.s._write_locked = lambda *a: {"success": True, "error_type": "", "left_in_homis": "saved", "karte_id": "9",
                                           "karte_url": "https://homis.jp/k?karte_id=9", "verify": "ok_processed"}
        saved_release = self.s._release_lock
        self.s._release_lock = lambda o: None
        try:
            res = self.run_order("BOT-20261106-0026-20261106134815", template="bot_s_interrupt")
        finally:
            self.s._release_lock = saved_release
        self.assertTrue(res["success"])
        self.assertEqual((self.field, self.queued), ([], []))
        rec = self.fake.get(self.name("BOT-20261106-0026-20261106134815"))
        self.assertEqual(rec["status"], "ok")
        self.assertIn("書込後確認 ○（そのあと人が処理）", [t["what"] for t in rec["timeline"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
