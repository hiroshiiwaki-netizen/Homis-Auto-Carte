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

    def test_v12_no_karte_id_is_unverified(self):
        r = verify_karte.verify("2277808", "", "s", "o")
        self.assertEqual((r["verdict"], r["reason"]), ("unverified", "no_input"))

    def test_v13_result_has_no_text(self):
        # 戻り値に S・O の中身を入れない（記録に出ないように）
        self.h.karte_script = [karte(s="秘密の送り元", o="秘密の本文")]
        r = self.run_v(s="秘密の送り元", o="秘密の本文")
        self.assertNotIn("秘密", json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main(verbosity=1)
