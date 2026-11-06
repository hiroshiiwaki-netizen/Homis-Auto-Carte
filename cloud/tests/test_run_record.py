# -*- coding: utf-8 -*-
"""実行リストの記録（run_record.py 1.0.0）と、ライター 3.11.0 の記録の足し方・left_in_homis のテスト

偽の Cloud Storage（fake_records.py）に向けて、本物の run_record.py を動かす。すべてダミーの値。
使い方: py -3.12 -X utf8 cloud/tests/test_run_record.py
"""
from __future__ import annotations

import contextlib
import os
import sys
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD = os.path.dirname(HERE)
SRC = os.path.join(os.path.dirname(CLOUD), "src")
sys.path.insert(0, HERE)
sys.path.insert(0, CLOUD)
sys.path.insert(0, SRC)

# 共有ドライブのログに書かない（test_stop_retry.py と同じ偽物）
sl = types.ModuleType("shared_log")


@contextlib.contextmanager
def _timed_step(name):
    yield types.SimpleNamespace(ok=False)


sl.timed_step = _timed_step
sl.extract_karte_id = lambda url: (url.split("karte_id=", 1)[1].split("&", 1)[0] if "karte_id=" in (url or "") else "")
sl.infer_error_type = lambda r: r.get("error_type") or ""
sl.log_result = lambda *a, **k: None
sys.modules.setdefault("shared_log", sl)

import run_record as rr  # noqa: E402
from fake_records import FakeRecords  # noqa: E402

DAY = "2026-11-06"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeRecords()

    @classmethod
    def tearDownClass(cls):
        cls.fake.close()

    def setUp(self):
        self.fake.reset()
        self.env = dict(os.environ)
        os.environ.update(RECORD_BUCKET="test-records", GCS_BASE=self.fake.url,
                          METADATA_TOKEN_URL=self.fake.url + "/token")
        rr._token_cache.update(value="", until=0.0)
        rr._paused_until["t"] = 0.0
        self.timeout = rr.TIMEOUT_SEC

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        rr.TIMEOUT_SEC = self.timeout
        rr._paused_until["t"] = 0.0

    def name(self, order):
        return f"records/{DAY}/{order}.json"


class RunRecord(Base):
    def test_r1_off_without_bucket(self):
        os.environ["RECORD_BUCKET"] = ""
        self.assertEqual(rr.create(DAY, "FAX-1", {"a": 1}), "off")
        self.assertEqual(rr.update(DAY, "FAX-1", lambda r: None), "off")
        self.assertEqual(self.fake.calls, [])

    def test_r2_create_once(self):
        self.assertEqual(rr.create(DAY, "FAX-261106-1", {"status": "received"}), "created")
        self.assertEqual(rr.create(DAY, "FAX-261106-1", {"status": "other"}), "exists")
        self.assertEqual(self.fake.get(self.name("FAX-261106-1"))["status"], "received")   # 2回目は上書きしない

    def test_r3_update_merges_and_creates(self):
        self.assertEqual(rr.update(DAY, "FAX-2", lambda r: r.update(status="accepted")), "created")
        rr.update(DAY, "FAX-2", lambda r: r.update(status="ok", karte_id="9"))
        self.assertEqual(self.fake.get(self.name("FAX-2")), {"status": "ok", "karte_id": "9"})

    def test_r4_conflict_retries_once(self):
        self.fake.put(self.name("FAX-3"), {"status": "received", "payload": {"sContent": "s"}})
        bumped = []

        def hook(name):
            if not bumped:
                bumped.append(1)
                self.fake.bump(name)   # 読んだあと、書く前にほかの書き手が書いた
        self.fake.before_put = hook
        self.assertEqual(rr.update(DAY, "FAX-3", lambda r: r.update(status="accepted")), "updated")
        got = self.fake.get(self.name("FAX-3"))
        self.assertEqual(got["status"], "accepted")
        self.assertEqual(got["payload"], {"sContent": "s"})   # 前の中身は残る

    def test_r5_hang_gives_up_and_pauses(self):
        rr.TIMEOUT_SEC = 0.5
        self.fake.mode, self.fake.hang_sec = "hang", 3.0
        t0 = time.time()
        self.assertEqual(rr.create(DAY, "FAX-4", {}), "failed")
        self.assertLess(time.time() - t0, 2.5)
        n = len(self.fake.calls)
        t1 = time.time()
        self.assertEqual(rr.update(DAY, "FAX-4", lambda r: None), "failed")   # 60 秒は通信しない
        self.assertLess(time.time() - t1, 0.2)
        self.assertEqual(len(self.fake.calls), n)

    def test_r6_down_and_deny_never_raise(self):
        for mode in ("down", "deny"):
            rr._paused_until["t"] = 0.0
            self.fake.mode = mode
            self.assertEqual(rr.create(DAY, "FAX-5", {}), "failed", mode)
            rr._paused_until["t"] = 0.0
            self.assertEqual(rr.update(DAY, "FAX-5", lambda r: None), "failed", mode)

    def test_r7_bad_order_and_day(self):
        self.assertEqual(rr.create(DAY, "../x", {}), "failed")
        self.assertEqual(rr.create(DAY, "", {}), "failed")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(rr.object_name("../../etc", "FAX-1"), f"records/{rr.today()}/FAX-1.json")

    def test_r8_route_of(self):
        f = rr.route_of
        self.assertEqual([f("FAX-1"), f("FAX-MIRROR-1"), f("BOT-1-2"), f("BOT-G-1"), f("BOT-TEST-G-1"), f("KJ-1"), f("XR-1")],
                         ["fax", "fax_mirror", "bot", "bot_g", "bot_test", "karte_json", "other"])


class Writer(Base):
    """ライター 3.11.0 の記録の足し方（server.py を読み込み、書き込みの中身は偽物に置き換える）"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import server   # noqa: PLC0415  selenium の読み込みが要る
        cls.server = server

    def setUp(self):
        super().setUp()
        s = self.server
        self.saved = {k: getattr(s, k) for k in ("sheet_enabled", "claim", "_write_locked", "_locked_out", "_release_lock")}
        self.saved_acquire = s.patient_lock.acquire
        s.sheet_enabled = lambda: False
        s._release_lock = lambda order_id: None
        s.patient_lock.acquire = lambda h, o: {"status": "ok", "generation": "1", "waited_sec": 0}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(self.server, k, v)
        self.server.patient_lock.acquire = self.saved_acquire
        super().tearDown()

    def data(self, order="FAX-261106-7"):
        return {"orderId": order, "homisId": "1234567", "template": "fax_so", "sContent": "s", "oContent": "o",
                "recordDay": DAY}

    def test_w1_success_on_top_of_receiver_record(self):
        s = self.server
        self.fake.put(self.name("FAX-261106-7"), {"order_id": "FAX-261106-7", "status": "received", "doc_type": "検査結果",
                                                  "payload": {"sContent": "元の文"}, "timeline": [{"at": "x", "what": "受け口が受けた"}]})
        seen = []

        def fake_write(data, order_id, homis_id, t0, t_write, sheet_row, lock):
            seen.append(self.fake.get(self.name(order_id))["status"])   # 書いている間は accepted
            return {"success": True, "error_type": "", "karte_id": "55", "karte_url": "https://homis.jp/k?karte_id=55",
                    "total_sec": 40.0, "left_in_homis": "saved"}
        s._write_locked = fake_write
        res = s._write_karte_inner(self.data(), "FAX-261106-7", "1234567")
        self.assertTrue(res["success"])
        self.assertEqual(seen, ["accepted"])
        got = self.fake.get(self.name("FAX-261106-7"))
        self.assertEqual((got["status"], got["karte_id"], got["left_in_homis"], got["doc_type"]), ("ok", "55", "saved", "検査結果"))
        self.assertEqual(got["payload"], {"sContent": "元の文"})   # 受け口の中身はライターが上書きしない
        self.assertEqual([t["what"] for t in got["timeline"]], ["受け口が受けた", "ライターが受け取った", "書けた"])

    def test_w2_locked_out_records_none(self):
        s = self.server
        s.patient_lock.acquire = lambda h, o: {"status": "busy", "generation": "", "waited_sec": 320, "reason": "x"}
        s._locked_out = lambda *a: {"success": False, "error_type": "locked:busy", "left_in_homis": "none", "total_sec": 1}
        s._write_karte_inner(self.data("BOT-123-20261106090000"), "BOT-123-20261106090000", "1234567")
        got = self.fake.get(self.name("BOT-123-20261106090000"))
        self.assertEqual((got["status"], got["error_type"], got["left_in_homis"]), ("fail", "locked:busy", "none"))
        self.assertEqual(got["payload"]["sContent"], "s")   # 受け口の記録が無いときはライターが中身を入れる
        self.assertNotIn("recordDay", got["payload"])

    def test_w3_storage_down_does_not_stop_writing(self):
        s = self.server
        rr.TIMEOUT_SEC = 0.5
        self.fake.mode, self.fake.hang_sec = "hang", 2.0
        s._write_locked = lambda *a: {"success": True, "error_type": "", "karte_id": "1", "left_in_homis": "saved"}
        t0 = time.time()
        res = s._write_karte_inner(self.data(), "FAX-261106-7", "1234567")
        self.assertTrue(res["success"])
        self.assertLess(time.time() - t0, 2.0)   # 受け取りで 1 回あきらめ、結果は通信しない

    def test_w4_exception_leaves_accepted(self):
        s = self.server

        def boom(*a):
            raise RuntimeError("chrome died")
        s._write_locked = boom
        with self.assertRaises(RuntimeError):
            s._write_karte_inner(self.data(), "FAX-261106-7", "1234567")
        self.assertEqual(self.fake.get(self.name("FAX-261106-7"))["status"], "accepted")   # 画面は「止まっているかも」

    def test_w5_left_in_homis_matrix(self):
        f = self.server.left_in_homis
        # (success, blocked, stopped, left_editing, opened, err) → 期待
        cases = [
            ((True, "", "", "", True, ""), "saved"),
            ((False, "", "", "", True, "no_karte_id"), "saved"),
            ((False, "", "", "", True, "verify:o_mismatch"), "saved"),
            ((False, "", "", "", True, "verify:not_completed"), "saved"),
            ((False, "", "s_input", "s_input", True, "stopped:unverified_input"), "editing"),
            ((False, "in_progress_karte", "", "s_input", False, "blocked:in_progress_karte"), "editing"),   # 1回目の書きかけのあと
            ((False, "reused_editing", "", "", True, "blocked:reused_editing"), "editing"),
            ((False, "in_progress_karte", "", "", False, "blocked:in_progress_karte"), "none"),
            ((False, "unexpected_alert", "", "", False, "blocked:unexpected_alert"), "none"),
            ((False, "", "", "", False, "login"), "none"),
            ((False, "", "", "", True, "opened_then_fail"), "unknown"),
            ((False, "", "", "", True, "step:click_save"), "unknown"),
        ]
        for args, want in cases:
            self.assertEqual(f(*args), want, args)
        # 黒ヤギ 実装1回目 指摘1: この注文の前の回でカルテを開いていたら、最後の回が開く前に止まっても none にしない
        self.assertEqual(f(False, "in_progress_karte", "", "", False, "blocked:in_progress_karte", True), "unknown")
        self.assertEqual(f(False, "unexpected_alert", "", "", False, "blocked:unexpected_alert", True), "unknown")
        self.assertEqual(f(False, "", "", "", False, "login", True), "unknown")
        self.assertEqual(f(False, "reused_editing", "", "", True, "blocked:reused_editing", True), "editing")   # 編集中はそのまま
        self.assertEqual(f(True, "", "", "", True, "", True), "saved")

    def test_w6_order_kids_reach_left_in_homis(self):
        """_write_locked の返り値まで order_kids が届くか（1回目で開いた番号が残ったまま2回目が新規で止められた形）"""
        s = self.server
        calls = []

        def run_once(data):
            calls.append(1)
            if len(calls) == 1:
                s._TLS.order_kids.append("901")   # 1回目: カルテを開いた（S を確かめられず保存しない）
                s._TLS.karte_opened, s._TLS.stopped = True, "s_input"
                return {"success": False, "error_type": "step:s_input"}
            s._TLS.karte_opened, s._TLS.stopped, s._TLS.blocked = False, "", "in_progress_karte"   # 2回目: 新規で止められた
            return {"success": False, "error_type": "blocked"}
        saved = (s._run_once, s.navi_callback.notify_dx, s._notify_field, s.remember_left, s.BLOCKED_RETRY_TEMPLATES)
        s._run_once, s.navi_callback.notify_dx = run_once, (lambda *a, **k: None)
        s._notify_field, s.remember_left, s.BLOCKED_RETRY_TEMPLATES = (lambda *a, **k: None), (lambda k: None), set()
        try:
            res = s._write_locked(self.data(), "FAX-261106-7", "1234567", time.time(), time.time(), 0, {"waited_sec": 0})
        finally:
            s._run_once, s.navi_callback.notify_dx, s._notify_field, s.remember_left, s.BLOCKED_RETRY_TEMPLATES = saved
        self.assertEqual(len(calls), 2)
        self.assertEqual(res["error_type"], "blocked:in_progress_karte")
        self.assertEqual(res["left_in_homis"], "editing")   # 1回目の書きかけ（left_editing）が残る


if __name__ == "__main__":
    unittest.main(verbosity=2)
