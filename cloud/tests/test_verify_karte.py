# -*- coding: utf-8 -*-
"""verify_karte.py（書いたカルテの読み直し）のテスト

手元に偽の HOMIS（auth.php でクッキーを渡し、?qid=ajax_karte_show で台本どおりの JSON を返す）を立て、
本物の verify_karte.verify を動かして verdict を確かめる。本物の HOMIS には触らない。
使い方: py -3.12 -X utf8 cloud/tests/test_verify_karte.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import verify_karte  # noqa: E402

verify_karte.WAIT_SEC = 0


class FakeHomis:
    """偽の HOMIS。karte_script の順に this_karte を返す（尽きたら最後のものを返し続ける）。
    "html" はログイン画面のまね、"down" は接続を切る"""

    def __init__(self):
        self.karte_script = []
        self.reads = 0
        self.logged_in = False
        self.edit_opened = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0") or 0)
                form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))
                if self.path.startswith("/auth.php") and form.get("id") == ["u"] and form.get("pw") == ["p"]:
                    outer.logged_in = True
                    self.send_response(302)
                    self.send_header("Set-Cookie", "HOMIS=ok; Path=/")
                    self.send_header("Location", "/top")
                    self.end_headers()
                    return
                self.send_response(200); self.end_headers(); self.wfile.write(b"<html>login</html>")

            def do_GET(self):
                if "pdetail_karteedit" in self.path:
                    outer.edit_opened = True
                if "qid=ajax_karte_show" not in self.path:
                    self.send_response(200); self.end_headers(); self.wfile.write(b"<html>top</html>"); return
                outer.reads += 1
                item = outer.karte_script[min(outer.reads - 1, len(outer.karte_script) - 1)]
                if item == "down":
                    self.connection.close(); return
                if item == "html" or "HOMIS=ok" not in (self.headers.get("Cookie") or ""):
                    data = b"<html>login</html>"
                else:
                    data = json.dumps({"this_karte": item}, ensure_ascii=False).encode("utf-8")
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def close(self):
        self.httpd.shutdown()


def karte(status="3", s="送り元", o="一行目\n二行目"):
    return {"status": status, "subjective": s, "objective": o}


class VerifyKarte(unittest.TestCase):
    def setUp(self):
        self.h = FakeHomis()
        verify_karte.BASE = self.h.url
        os.environ["HOMIS_USER"] = "u"
        os.environ["HOMIS_PASSWORD"] = "p"

    def tearDown(self):
        self.h.close()

    def run_v(self, s="送り元", o="一行目\n二行目"):
        return verify_karte.verify("2277808", "100", s, o)

    def test_v1_ok(self):
        self.h.karte_script = [karte()]
        r = self.run_v()
        self.assertEqual((r["verdict"], r["reads"], r["status"]), ("ok", 1, "3"))
        self.assertTrue(self.h.logged_in)
        self.assertFalse(self.h.edit_opened)  # 編集画面は開かない（開くとカルテがロックされる）

    def test_v2_completed_on_second_read(self):
        self.h.karte_script = [karte(status="1"), karte()]
        r = self.run_v()
        self.assertEqual((r["verdict"], r["reads"]), ("ok", 2))

    def test_v3_still_not_completed(self):
        self.h.karte_script = [karte(status="1", s="", o=""), karte(status="1", s="", o="")]
        r = self.run_v()
        self.assertEqual((r["verdict"], r["reads"], r["status"]), ("not_completed", 2, "1"))

    def test_v4_interrupted_is_not_completed(self):
        self.h.karte_script = [karte(status="2")]
        self.assertEqual(self.run_v()["verdict"], "not_completed")

    def test_v4b_orca_statuses_are_completed(self):
        # 10/29 本物で確認: 算定不要で書くと 7（ORCA登録不要）。5・6 も完了のあと
        for st in ("5", "6", "7"):
            self.h.karte_script = [karte(status=st)]
            self.h.reads = 0
            r = self.run_v()
            self.assertEqual((r["verdict"], r["reads"]), ("ok", 1), st)
        self.assertEqual(r["status_label"], "ORCA登録不要")

    def test_v4c_editing_after_done_is_not_completed(self):
        # 70＝ORCA登録不要(編集中)・0＝取消 は未完了
        for st in ("70", "0"):
            self.h.karte_script = [karte(status=st)]
            self.h.reads = 0
            self.assertEqual(self.run_v()["verdict"], "not_completed", st)

    def test_v5_s_mismatch(self):
        self.h.karte_script = [karte(s="別の送り元")]
        self.assertEqual(self.run_v()["verdict"], "s_mismatch")

    def test_v6_o_mismatch(self):
        self.h.karte_script = [karte(o="一行目")]
        self.assertEqual(self.run_v()["verdict"], "o_mismatch")

    def test_v7_newline_and_trailing_space_ignored(self):
        self.h.karte_script = [karte(s=" 送り元 ", o="一行目  \r\n二行目\r\n")]
        self.assertEqual(self.run_v()["verdict"], "ok")

    def test_v8_empty_karte_is_not_ok(self):
        # 空のまま完了扱い（10/29 abortEdit で見た形）も見逃さない
        self.h.karte_script = [karte(s="", o="")]
        self.assertEqual(self.run_v()["verdict"], "s_mismatch")

    def test_v9_login_page_is_unverified(self):
        self.h.karte_script = ["html"]
        r = self.run_v()
        self.assertEqual(r["verdict"], "unverified")
        self.assertTrue(r["reason"])

    def test_v10_connection_cut_is_unverified(self):
        self.h.karte_script = ["down"]
        self.assertEqual(self.run_v()["verdict"], "unverified")

    def test_v11_wrong_password_is_unverified(self):
        os.environ["HOMIS_PASSWORD"] = "x"
        self.h.karte_script = [karte()]
        r = self.run_v()
        self.assertEqual(r["verdict"], "unverified")
        self.assertIn("login_failed", r["reason"])  # 黒ヤギ指摘4: ログインの失敗と分かる
        self.assertEqual(self.h.reads, 0)  # ログインできなければ読みに行かない

    def test_v11b_reason_keeps_message(self):
        # 黒ヤギ指摘3: 「ValueError」だけでなく、何が起きたかの短い文を残す
        self.h.karte_script = ["html"]
        r = self.run_v()
        self.assertTrue(r["reason"].startswith("JSONDecodeError: "), r["reason"])

    def test_v7b_symbols_round_trip(self):
        # 黒ヤギ指摘1: HOMIS は < & > をそのまま返す（10/29 本物で 122欄・実体参照0件）。記号入りでも ok
        text = 'SpO2 < 90% & CRP > 10 "要確認"'
        self.h.karte_script = [karte(s=text, o=text)]
        self.assertEqual(self.run_v(s=text, o=text)["verdict"], "ok")

    def test_v7c_apostrophe_becomes_right_quote(self):
        # 11/5: HOMIS は保存のとき ' を ’ に置き換える（テスト舞子で確認）。送ったとおりなら ok
        sent = "Dr. O'Brien's report 'normal'"
        self.h.karte_script = [karte(s=sent.replace("'", "’"), o="x\n" + sent.replace("'", "’"))]
        self.assertEqual(self.run_v(s=sent, o="x\n" + sent)["verdict"], "ok")

    def test_v7d_other_quote_change_is_still_mismatch(self):
        # そろえるのは ' と ’ だけ。" が “ に変わったら見逃さない
        self.h.karte_script = [karte(o='a "b"'.replace('"', "“"))]
        self.assertEqual(self.run_v(o='a "b"')["verdict"], "o_mismatch")

    def test_v12_no_karte_id_is_unverified(self):
        r = verify_karte.verify("2277808", "", "s", "o")
        self.assertEqual((r["verdict"], r["reason"]), ("unverified", "no_input"))

    def test_v13_result_has_no_text(self):
        # 戻り値に S・O の中身を入れない（記録に出ないように）
        self.h.karte_script = [karte(s="秘密の送り元", o="秘密の本文")]
        r = self.run_v(s="秘密の送り元", o="秘密の本文")
        self.assertNotIn("秘密", json.dumps(r, ensure_ascii=False))

    # --- v1.1.0 問い合わせ（expect="interrupt"） ---
    def bot(self, status="2", s="問い合わせ着信", o=" ", who="おひさまロボット GCP"):
        k = karte(status=status, s=s, o=o)
        k["upd_user"] = {"full_name": who}
        return k

    def run_i(self, s="問い合わせ着信"):
        return verify_karte.verify("2277808", "100", s, "", expect="interrupt")

    def test_i1_interrupt_ok(self):
        self.h.karte_script = [self.bot()]
        self.assertEqual(self.run_i()["verdict"], "ok")

    def test_i2_completed_is_not_interrupt(self):
        self.h.karte_script = [self.bot(status="3"), self.bot(status="3")]
        r = self.run_i()
        self.assertEqual((r["verdict"], r["reads"]), ("not_interrupted", 2))

    def test_i3_someone_elses_karte(self):
        # 中断・S も同じでも、更新者がライターでなければ合格にしない（名前は結果に出さない）
        self.h.karte_script = [self.bot(who="職員 太郎")]
        r = self.run_i()
        self.assertEqual(r["verdict"], "not_mine")
        self.assertNotIn("太郎", json.dumps(r, ensure_ascii=False))

    def test_i3b_name_spaces_are_normalized(self):
        # 指摘1: 全角の空白・前後の空白・連続した空白はそろえて比べる
        for who in ("おひさまロボット　GCP", " おひさまロボット  GCP ", "おひさまロボット GCP"):
            self.h.karte_script = [self.bot(who=who)]
            self.assertEqual(self.run_i()["verdict"], "ok", who)

    def test_i6_processed_by_human_right_after(self):
        # v1.3.0: 中断で書いた直後に HIO さんが完了（ORCA登録不要 7）にした。更新者が人・S が同じなら書込成功
        for st in ("3", "5", "6", "7"):
            self.h.karte_script = [self.bot(status=st, who="職員 太郎", o="処理のメモ"), self.bot(status=st, who="職員 太郎", o="処理のメモ")]
            r = self.run_i()
            self.assertEqual(r["verdict"], "ok_processed", st)
            self.assertNotIn("太郎", json.dumps(r, ensure_ascii=False))

    def test_i7_processed_and_s_edited_is_ok(self):
        # v1.4.0: 人が完了にして S も直した → 人が S を直すことがある（岩城さん 11/6「大きい心で」）。成功・reason=s_edited
        self.h.karte_script = [self.bot(status="7", who="職員 太郎", s="別の文"), self.bot(status="7", who="職員 太郎", s="別の文")]
        r = self.run_i()
        self.assertEqual((r["verdict"], r["reason"]), ("ok_processed", "s_edited"))
        self.assertNotIn("別の文", json.dumps(r, ensure_ascii=False))

    def test_i10_opened_by_human_right_after(self):
        # v1.4.0: 中断で書いた直後に人が開いた（診察中 1・ORCA登録不要(編集中) 70）。開くだけでは更新者は変わらない見込みなので更新者は見ない
        for st in ("1", "70"):
            for who in ("おひさまロボット GCP", "職員 太郎"):
                self.h.karte_script = [self.bot(status=st, who=who), self.bot(status=st, who=who)]
                r = self.run_i()
                self.assertEqual((r["verdict"], r["reason"]), ("ok_processed", ""), (st, who))

    def test_i11_opened_and_s_edited_is_ok(self):
        self.h.karte_script = [self.bot(status="1", s="直した文", o="メモ"), self.bot(status="1", s="直した文", o="メモ")]
        r = self.run_i()
        self.assertEqual((r["verdict"], r["reason"]), ("ok_processed", "s_edited"))

    def test_i12_editing_with_empty_s_is_still_failure(self):
        # ロボットが中断で保存できず書きかけが残った（S が空）→ 今まで通り失敗。人が完了にしても S が空なら失敗
        for st, who in (("1", "おひさまロボット GCP"), ("70", "おひさまロボット GCP"), ("7", "職員 太郎"), ("1", "職員 太郎")):
            self.h.karte_script = [self.bot(status=st, who=who, s=""), self.bot(status=st, who=who, s="")]
            self.assertEqual(self.run_i()["verdict"], "not_interrupted", (st, who))
        self.h.karte_script = [self.bot(status="1", s=" \n "), self.bot(status="1", s=" \n ")]   # 空白だけも空
        self.assertEqual(self.run_i()["verdict"], "not_interrupted")

    def test_i13_other_statuses_unchanged(self):
        # 取消（0）は人が開いた扱いにしない
        self.h.karte_script = [self.bot(status="0"), self.bot(status="0")]
        self.assertEqual(self.run_i()["verdict"], "not_interrupted")

    def test_i14_fax_opened_is_still_not_completed(self):
        # FAX（expect=done）は変えない: 診察中なら今まで通り not_completed
        self.h.karte_script = [karte(status="1"), karte(status="1")]
        self.assertEqual(self.run_v()["verdict"], "not_completed")

    def test_i8_writer_completed_itself_is_still_failure(self):
        # ライター自身が完了にしてしまった（本当の失敗）は今まで通り
        self.h.karte_script = [self.bot(status="7"), self.bot(status="7")]
        self.assertEqual(self.run_i()["verdict"], "not_interrupted")

    def test_i9_fax_is_unchanged(self):
        # FAX（expect=done）は変えない: 人が更新していても完了・S/O 一致なら ok、O が違えば o_mismatch
        k = karte(status="7")
        k["upd_user"] = {"full_name": "職員 太郎"}
        self.h.karte_script = [k]
        self.assertEqual(self.run_v()["verdict"], "ok")

    def test_i4_o_must_be_blank(self):
        self.h.karte_script = [self.bot(o="訪問の記録")]
        self.assertEqual(self.run_i()["verdict"], "o_mismatch")

    def test_i5_s_mismatch(self):
        self.h.karte_script = [self.bot(s="別の問い合わせ")]
        self.assertEqual(self.run_i()["verdict"], "s_mismatch")

    def test_i6_no_upd_user(self):
        self.h.karte_script = [karte(status="2", s="問い合わせ着信", o=" ")]
        self.assertEqual(self.run_i()["verdict"], "not_mine")

    def test_i7_fax_unchanged_ignores_updater(self):
        # FAX（既定 done）は更新者を見ない（今までどおり）
        k = karte()
        k["upd_user"] = {"full_name": "だれか"}
        self.h.karte_script = [k]
        self.assertEqual(self.run_v()["verdict"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=1)
