# -*- coding: utf-8 -*-
"""cloud/patient_lock.py 1.0.0 の単体テスト（偽の Cloud Storage を相手に）

使い方: py -3.12 -X utf8 cloud/tests/test_patient_lock.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import patient_lock as pl  # noqa: E402
from fake_gcs import FakeGCS  # noqa: E402

NAME = "locks/2277808"


class PatientLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gcs = FakeGCS()
        cls.gcs.install_env()
        cls.keep = (pl.LOCK_POLL_SEC, pl.LOCK_TTL_SEC, pl.LOCK_WAIT_SEC)
        pl.LOCK_POLL_SEC = 0.2   # テストでは 5秒も寝ない

    @classmethod
    def tearDownClass(cls):
        pl.LOCK_POLL_SEC, pl.LOCK_TTL_SEC, pl.LOCK_WAIT_SEC = cls.keep
        cls.gcs.shutdown()

    def setUp(self):
        self.gcs.reset()
        pl.LOCK_TTL_SEC = self.keep[1]
        pl._token_cache.update(value="", until=0.0)

    def test_l0_constants(self):
        # 仕様 v0.2: 期限 300秒（書き込み上限 280＋20）・札待ち 320秒（期限より長い）・5秒おき
        self.assertEqual((self.keep[1], self.keep[2], self.keep[0]), (300.0, 320.0, 5.0))
        self.assertGreater(self.keep[2], self.keep[1])

    def test_l1_acquire_and_release(self):
        out = pl.acquire("2277808", "ORDER-1")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["generation"], str(self.gcs.gen(NAME)))
        self.assertLess(out["waited_sec"], 1.0)
        self.assertEqual(self.gcs.objects[NAME]["metadata"]["orderId"], "ORDER-1")
        self.assertEqual(pl.release("2277808", out["generation"], "ORDER-1"), "deleted")
        self.assertIsNone(self.gcs.gen(NAME))
        self.assertEqual(pl.release("2277808", out["generation"], "ORDER-1"), "gone")   # 2回外しても害なし

    def test_l2_busy_waits_then_gives_up(self):
        held = self.gcs.put(NAME, age_sec=10)   # 別の台の札（期限内）
        t0 = time.time()
        out = pl.acquire("2277808", "ORDER-2", wait_sec=1.0)
        self.assertEqual((out["status"], out["reason"]), ("busy", "busy"))
        self.assertGreaterEqual(time.time() - t0, 1.0)
        self.assertEqual(self.gcs.gen(NAME), held)                    # 人の札は消していない
        self.assertGreaterEqual(self.gcs.count("POST"), 3)            # 取り直している
        self.assertEqual(self.gcs.count("DELETE"), 0)

    def test_l3_expired_lock_is_taken_over(self):
        old = self.gcs.put(NAME, age_sec=pl.LOCK_TTL_SEC + 1)        # 落ちた台の札（期限切れ）
        t0 = time.time()
        out = pl.acquire("2277808", "ORDER-3", wait_sec=5.0)
        self.assertEqual(out["status"], "ok")
        self.assertLess(time.time() - t0, 1.0)                        # 寝ずにすぐ取り直す
        self.assertNotEqual(int(out["generation"]), old)
        self.assertEqual(self.gcs.count("DELETE"), 1)

    def test_l4_fresh_lock_replaced_between_read_and_delete_is_not_stolen(self):
        # 黒ヤギ仕様2回目 指摘1: 期限切れを読んだあと、消す前に別の台が札を作り直した → 412 で消えず、人の札を奪わない
        self.gcs.put(NAME, age_sec=pl.LOCK_TTL_SEC + 1)
        state = {"fresh": None}

        def replace(name):
            if state["fresh"] is None:
                del self.gcs.objects[name]
                state["fresh"] = self.gcs.put(name, age_sec=0)       # 別の台の新しい札
        self.gcs.on_delete = replace
        out = pl.acquire("2277808", "ORDER-4", wait_sec=1.0)
        self.assertEqual(out["status"], "busy")
        self.assertEqual(self.gcs.gen(NAME), state["fresh"])          # 新しい札は無事

    def test_l5_single_get_reads_generation_and_time_together(self):
        # 世代番号と作成時刻は1回の GET で読む（2回に分けると世代のすり替わりの穴が開く）
        self.gcs.put(NAME, age_sec=10)
        pl.acquire("2277808", "ORDER-5", wait_sec=0.5)
        posts, gets = self.gcs.count("POST"), self.gcs.count("GET", "/storage/")
        self.assertGreaterEqual(posts, 2)
        self.assertLessEqual(gets, posts)                             # 取り直し1回につき GET は多くて1回

    def test_l6_release_with_other_generation_does_not_delete(self):
        mine = pl.acquire("2277808", "ORDER-6")["generation"]
        self.assertEqual(pl.release("2277808", str(int(mine) + 7), "ORDER-6"), "changed")
        self.assertEqual(str(self.gcs.gen(NAME)), mine)

    def test_l7_fatal_403_is_error_at_once(self):
        self.gcs.fail_next = (403, 10)
        t0 = time.time()
        out = pl.acquire("2277808", "ORDER-7", wait_sec=5.0)
        self.assertEqual((out["status"], out["reason"]), ("error", "storage:403"))
        self.assertLess(time.time() - t0, 1.0)
        self.assertIsNone(self.gcs.gen(NAME))

    def test_l8_transient_500_twice_then_ok(self):
        self.gcs.fail_next = (500, 2)
        out = pl.acquire("2277808", "ORDER-8", wait_sec=5.0)
        self.assertEqual(out["status"], "ok")

    def test_l9_500_three_times_is_error(self):
        self.gcs.fail_next = (500, 3)
        out = pl.acquire("2277808", "ORDER-9", wait_sec=5.0)
        self.assertEqual((out["status"], out["reason"]), ("error", "storage:500"))

    def test_l10_no_bucket_is_error(self):
        keep = os.environ.get("LOCK_BUCKET")
        os.environ["LOCK_BUCKET"] = " "
        try:
            out = pl.acquire("2277808", "ORDER-10", wait_sec=1.0)
        finally:
            os.environ["LOCK_BUCKET"] = keep
        self.assertEqual((out["status"], out["reason"]), ("error", "no_bucket"))
        self.assertEqual(self.gcs.count("POST"), 0)

    def test_l11_released_while_waiting_is_taken_at_once(self):
        # 待っている間に別の台が外した（GET が 404）→ 寝ずにすぐ取る
        self.gcs.put(NAME, age_sec=10)

        def vanish(name):
            self.gcs.objects.pop(name, None)
        self.gcs.on_get = vanish
        t0 = time.time()
        out = pl.acquire("2277808", "ORDER-11", wait_sec=5.0)
        self.assertEqual(out["status"], "ok")
        self.assertLess(time.time() - t0, 1.0)

    def test_l12_two_threads_same_patient_are_serialized(self):
        got, order = [], []
        lock = threading.Lock()

        def worker(n):
            out = pl.acquire("2277808", f"ORDER-12-{n}", wait_sec=5.0)
            with lock:
                order.append(("in", n, time.time()))
            time.sleep(0.6)
            with lock:
                order.append(("out", n, time.time()))
                got.append(out)
            pl.release("2277808", out["generation"], f"ORDER-12-{n}")
        ts = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual([o["status"] for o in got], ["ok", "ok"])
        self.assertNotEqual(got[0]["generation"], got[1]["generation"])
        ins = sorted(t for k, _, t in order if k == "in")
        outs = sorted(t for k, _, t in order if k == "out")
        self.assertGreaterEqual(ins[1], outs[0] - 0.05)                # 2人目が入ったのは1人目が出たあと
        self.assertIsNone(self.gcs.gen(NAME))

    def test_l13_parse_time_and_expired(self):
        self.assertAlmostEqual(pl.parse_time("2026-11-05T04:59:32.123Z"), 1793854772.123, places=3)
        self.assertAlmostEqual(pl.parse_time("2026-11-05T13:59:32+09:00"), 1793854772.0, places=3)
        self.assertAlmostEqual(pl.parse_time("2026-11-05T04:59:32Z"), 1793854772.0, places=3)
        self.assertIsNone(pl.parse_time("きのう"))
        self.assertIsNone(pl.parse_time(""))
        self.assertTrue(pl.expired({"timeCreated": "?"}))                                     # 読めない札は期限切れ扱い
        self.assertFalse(pl.expired({"timeCreated": "2026-11-05T04:59:32Z"}, now=1793854772.0 + 299))
        self.assertTrue(pl.expired({"timeCreated": "2026-11-05T04:59:32Z"}, now=1793854772.0 + 301))

    def test_l14_other_patient_is_independent(self):
        self.gcs.put(NAME, age_sec=10)
        out = pl.acquire("1234567", "ORDER-14", wait_sec=1.0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(pl.lock_name("1234567"), "locks/1234567")

    # --- v1.0.1 黒ヤギ実装1回目 ---
    def test_l15_token_ttl_follows_expires_in(self):
        # 残り寿命 121秒 → 余裕 120秒を引いて 1秒だけ使い回す → 1.1秒後は取り直す
        self.gcs.token_expires_in = 121
        pl.acquire("2277808", "ORDER-15a")
        self.assertEqual(self.gcs.count("GET", "/token"), 1)
        pl.release("2277808", str(self.gcs.gen(NAME)), "ORDER-15a")
        self.assertEqual(self.gcs.count("GET", "/token"), 1)       # 1秒以内は使い回す
        time.sleep(1.1)
        pl.acquire("2277808", "ORDER-15b")
        self.assertEqual(self.gcs.count("GET", "/token"), 2)       # 期限が来たら取り直す

    def test_l16_401_once_refetches_token_and_succeeds(self):
        self.gcs.fail_next = (401, 1)
        out = pl.acquire("2277808", "ORDER-16", wait_sec=5.0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(self.gcs.count("GET", "/token"), 2)       # 捨てて取り直した
        self.assertEqual(self.gcs.objects[NAME]["metadata"]["orderId"], "ORDER-16")

    def test_l17_401_twice_is_error(self):
        self.gcs.fail_next = (401, 5)
        out = pl.acquire("2277808", "ORDER-17", wait_sec=5.0)
        self.assertEqual((out["status"], out["reason"]), ("error", "storage:401"))

    def test_l18_release_retries_once_on_401(self):
        mine = pl.acquire("2277808", "ORDER-18")["generation"]
        self.gcs.fail_next = (401, 1)
        self.assertEqual(pl.release("2277808", mine, "ORDER-18"), "deleted")
        self.assertIsNone(self.gcs.gen(NAME))

    def test_l19_fast_retry_cannot_skip_deadline(self):
        # 作る→必ず 412・読む→404（置き場がおかしい）でも、寝ずに回り続けず上限で busy になる
        self.gcs.always_conflict = True
        t0 = time.time()
        out = pl.acquire("2277808", "ORDER-19", wait_sec=1.0)
        self.assertEqual(out["status"], "busy")
        self.assertLess(time.time() - t0, 3.0)
        self.assertLess(self.gcs.count("POST"), 30)                 # 高速の空回りになっていない


if __name__ == "__main__":
    unittest.main(verbosity=2)
