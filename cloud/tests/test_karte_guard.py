# -*- coding: utf-8 -*-
"""karte_guard.py 1.0.0（共通 JSON の入口 ① 書く前の確かめ・人が書いたかの見分け）のテスト。すべてダミーの値。
偽の HOMIS（test_verify_karte.FakeHomis）に向けて、本物の verify_karte のログインと読み方で読む。
使い方: py -3.12 -X utf8 cloud/tests/test_karte_guard.py
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import karte_guard as kg  # noqa: E402
import verify_karte  # noqa: E402
from test_verify_karte import FakeHomis  # noqa: E402

TODAY = date(2026, 11, 6)


def k(status="2", act="2026-11-06", pid="1234567", upd="2026-11-06 10:00:00", who="おひさまロボット GCP"):
    return {"status": status, "act_date": act, "patient_id": pid, "upd_datetime": upd, "upd_user": {"full_name": who},
            "subjective": "", "objective": ""}


class Judge(unittest.TestCase):
    def test_g1_ok_today_and_yesterday(self):
        self.assertEqual(kg.judge(k(), "1234567", TODAY), "")
        self.assertEqual(kg.judge(k(act="2026-11-05"), "1234567", TODAY), "")      # 23:59 に送って 0:01 に書く
        self.assertEqual(kg.judge(k(act="2026/11/05"), "1234567", TODAY), "")      # 表記ゆれ
        self.assertEqual(kg.judge(k(status="1"), "1234567", TODAY), "")            # 診察中
        self.assertEqual(kg.judge(k(status="70"), "1234567", TODAY), "")           # ORCA登録不要(編集中)は未完了

    def test_g2_stops(self):
        cases = [(k(act="2026-11-04"), "karte_too_old"), (k(act="2026-11-07"), "karte_too_old"), (k(act=""), "karte_too_old"),
                 (k(status="0"), "karte_cancelled"), (k(pid="7654321"), "karte_other_patient"), (None, "karte_not_found")]
        for st in ("3", "5", "6", "7"):
            cases.append((k(status=st), "karte_completed"))
        for karte, want in cases:
            self.assertEqual(kg.judge(karte, "1234567", TODAY), want, karte)

    def test_g3_max_days_setting(self):
        old = os.environ.get("KARTE_EDIT_MAX_DAYS")
        try:
            os.environ["KARTE_EDIT_MAX_DAYS"] = "3"
            self.assertEqual(kg.judge(k(act="2026-11-03"), "1234567", TODAY), "")
            os.environ["KARTE_EDIT_MAX_DAYS"] = "0"
            self.assertEqual(kg.judge(k(act="2026-11-05"), "1234567", TODAY), "karte_too_old")
        finally:
            os.environ.pop("KARTE_EDIT_MAX_DAYS", None) if old is None else os.environ.__setitem__("KARTE_EDIT_MAX_DAYS", old)

    def test_g4_human_changed(self):
        base = kg.snapshot(k())
        self.assertFalse(kg.human_changed(base, kg.snapshot(k())))                                        # 何も変わらない
        self.assertFalse(kg.human_changed(base, kg.snapshot(k(upd="2026-11-06 10:05:00"))))               # ライター自身（編集を開いた）
        self.assertFalse(kg.human_changed(base, kg.snapshot(k(upd="2026-11-06 10:05:00", who="おひさまロボット　GCP"))))  # 空白のゆれ
        self.assertTrue(kg.human_changed(base, kg.snapshot(k(upd="2026-11-06 10:05:00", who="医師 一郎"))))    # 人が書いた
        self.assertTrue(kg.human_changed(None, kg.snapshot(k())))                                          # 控えが無い
        self.assertTrue(kg.human_changed(base, None))                                                      # 今が読めない


class Read(unittest.TestCase):
    def setUp(self):
        self.h = FakeHomis()
        self.base = verify_karte.BASE
        verify_karte.BASE = self.h.url
        os.environ["HOMIS_USER"], os.environ["HOMIS_PASSWORD"] = "u", "p"

    def tearDown(self):
        verify_karte.BASE = self.base
        self.h.close()

    def test_r1_before_write_gives_baseline(self):
        self.h.karte_script = [k()]
        reason, base = kg.before_write("1234567", "100", TODAY)
        self.assertEqual((reason, base), ("", {"upd_datetime": "2026-11-06 10:00:00", "upd_user": "おひさまロボット GCP"}))

    def test_r2_completed_is_stopped_without_baseline(self):
        self.h.karte_script = [k(status="7")]
        self.assertEqual(kg.before_write("1234567", "100", TODAY), ("karte_completed", None))

    def test_r3_unreadable(self):
        os.environ["HOMIS_PASSWORD"] = "wrong"
        self.h.karte_script = [k()]
        self.assertEqual(kg.before_write("1234567", "100", TODAY), ("karte_unreadable", None))   # 読めなければ書かない

    def test_r4_never_opens_edit(self):
        self.h.karte_script = [k()]
        kg.before_write("1234567", "100", TODAY)
        self.assertFalse(self.h.edit_opened)   # 確かめは読むだけ（編集画面を開くと編集中になるため）


if __name__ == "__main__":
    unittest.main(verbosity=2)
