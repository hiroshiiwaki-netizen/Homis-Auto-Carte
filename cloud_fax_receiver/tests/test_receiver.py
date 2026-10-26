# -*- coding: utf-8 -*-
"""受け口 server.py の単体テスト（v0.1.0）

実行: py -3.12 -X utf8 -m unittest discover -s cloud_fax_receiver/tests -v
すべてダミーの値。本物の患者情報は使わない。
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402

KEY = "unit-test-key-0001"
SECRET_S = "テスト送り元ZZQ"          # ログに出てはいけない目印
SECRET_O = "テスト本文XXQ\n二行目"
SECRET_ID = "9876543"


class FunctionTests(unittest.TestCase):
    def test_key_ok(self):
        self.assertTrue(server.key_ok("Bearer " + KEY, KEY))
        self.assertTrue(server.key_ok("  Bearer   " + KEY + "  ", KEY))      # 前後の空白
        self.assertTrue(server.key_ok("Bearer " + KEY, KEY + " "))           # 設定側の空白
        self.assertTrue(server.key_ok("bearer " + KEY, KEY))
        self.assertFalse(server.key_ok("Bearer wrong", KEY))
        self.assertFalse(server.key_ok("", KEY))
        self.assertFalse(server.key_ok(KEY, KEY))                            # Bearer なし
        self.assertFalse(server.key_ok("Bearer ", ""))                       # 設定が空

    def test_text_stats(self):
        st = server.text_stats("あいう\nえお &curren; ??\u0001�縺")
        self.assertEqual(st["newlines"], 1)
        self.assertEqual(st["fffd"], 1)
        self.assertEqual(st["ctrl"], 1)
        self.assertEqual(st["qq"], 1)
        self.assertEqual(st["mojibake"], 1)
        self.assertTrue(st["amp_entity"])
        self.assertFalse(st["empty"])
        self.assertNotIn("text", st)
        self.assertEqual(st["ctrl_codes"], ["0x01"])
        ff = server.text_stats("一枚目\f二枚目\f三枚目\u0000")
        self.assertEqual(ff["ctrl"], 3)
        self.assertEqual(ff["ctrl_codes"], ["0x00", "0x0c"])               # 改ページ（0x0c）と NUL を見分けられる
        many = server.text_stats("".join(chr(c) for c in range(1, 9)))
        self.assertEqual(len(many["ctrl_codes"]), 5)                         # 最大5種類
        tab = server.text_stats("a\tb\r\nc")
        self.assertEqual(tab["ctrl"], 0)                                     # タブ・改行は制御文字に数えない
        self.assertEqual(tab["ctrl_codes"], [])
        self.assertTrue(server.text_stats("  ")["empty"])
        self.assertFalse(server.text_stats(None)["present"])
        self.assertFalse(server.text_stats("A & B")["amp_entity"])          # & 単体は数えない

    def test_homis_stats(self):
        self.assertEqual(server.homis_stats(SECRET_ID), {"empty": False, "digits_only": True, "len": 7})
        self.assertEqual(server.homis_stats(9876543)["digits_only"], True)  # 数字で届いても
        self.assertTrue(server.homis_stats("")["empty"])
        self.assertFalse(server.homis_stats("12a")["digits_only"])

    def test_pick_ticket(self):
        self.assertEqual(server.pick_ticket({"ticket": "261021120224-54"}), ("261021120224-54", "ticket"))
        lock = {"ticket": "261021120224-55", "granted": True}
        self.assertEqual(server.pick_ticket({"lock": lock}), ("261021120224-55", "lock"))
        self.assertEqual(server.pick_ticket({"lock": json.dumps(lock)}), ("261021120224-55", "lock"))
        # 差し込みが効かず {{ }} のまま届いたとき → lock を見る・無ければ invalid
        self.assertEqual(server.pick_ticket({"ticket": "{{札をください.result.ticket}}"}), ("", "invalid"))
        self.assertEqual(server.pick_ticket({"ticket": "{{x}}", "lock": lock}), ("261021120224-55", "lock"))
        self.assertEqual(server.pick_ticket({}), ("", "missing"))

    def test_label_cut(self):
        self.assertEqual(len(server._label("あ" * 100)), server.LABEL_MAX)

    def test_read_timeout_is_set(self):
        """v0.1.1: 受け口の本体に読み込みの上限が付いている（下の試験は 0.5 秒に置き換えて動かすので、ここで本体の値を見る）"""
        self.assertIsNotNone(server.Handler.timeout)
        self.assertEqual(server.Handler.timeout, server.READ_TIMEOUT)
        self.assertLessEqual(server.READ_TIMEOUT, 10)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FAX_RECEIVER_KEY"] = KEY
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.th = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.buf = io.StringIO()
        self._old = sys.stdout
        sys.stdout = self.buf

    def tearDown(self):
        sys.stdout = self._old

    def post(self, body: bytes | None, headers: dict | None = None, path="/fax/receive"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method="POST")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def good_body(self) -> bytes:
        return json.dumps({
            "source": "WF1573", "ticket": "261021120224-54", "homis_id": SECRET_ID,
            "s": SECRET_S, "o": SECRET_O, "doc_type": "診療情報提供書", "route": "西宮FAX",
        }).encode("utf-8")   # ensure_ascii=True（Tukusi と同じく \uXXXX）

    def logs(self) -> list[dict]:
        return [json.loads(x) for x in self.buf.getvalue().splitlines() if x.strip()]

    def assert_no_secret_in_logs(self):
        text = self.buf.getvalue()
        for secret in (SECRET_S, "ZZQ", "XXQ", SECRET_ID, KEY):
            self.assertNotIn(secret, text, f"ログに出てはいけない値: {secret}")

    def test_ok(self):
        st, js = self.post(self.good_body(), {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        self.assertEqual(st, 200)
        self.assertEqual(js, {"ok": True, "mode": "shadow"})                 # 本文は返さない
        lg = self.logs()[-1]
        self.assertEqual(lg["event"], "fax_shadow")
        self.assertEqual(lg["ticket"], "261021120224-54")
        self.assertEqual(lg["doc_type"], "診療情報提供書")
        self.assertEqual(lg["homis_id"], {"empty": False, "digits_only": True, "len": 7})
        self.assertEqual(lg["o"]["newlines"], 1)
        self.assertEqual(lg["s"]["len"], len(SECRET_S))
        self.assertTrue(lg["json_ok"])
        self.assert_no_secret_in_logs()

    def test_key_with_spaces(self):
        st, _ = self.post(self.good_body(), {"Authorization": "Bearer  " + KEY + " "})
        self.assertEqual(st, 200)

    def test_no_key_401(self):
        st, js = self.post(self.good_body())
        self.assertEqual(st, 401)
        self.assertEqual(js, {"ok": False})
        lg = self.logs()[-1]
        self.assertEqual(lg["event"], "fax_shadow_reject")
        self.assertEqual(set(lg) - {"time", "severity"}, {"event", "status", "reason"})   # 短い1行だけ
        self.assert_no_secret_in_logs()

    def test_wrong_key_401(self):
        st, _ = self.post(self.good_body(), {"Authorization": "Bearer nope"})
        self.assertEqual(st, 401)
        self.assert_no_secret_in_logs()

    def test_bad_json_400(self):
        st, _ = self.post(b'{"s": "' + SECRET_S.encode("utf-8") + b'", broken', {"Authorization": "Bearer " + KEY})
        self.assertEqual(st, 400)
        self.assertFalse(self.logs()[-1]["json_ok"])
        self.assert_no_secret_in_logs()

    def test_not_object_400(self):
        st, _ = self.post(b'["a"]', {"Authorization": "Bearer " + KEY})
        self.assertEqual(st, 400)

    def test_too_large_413_without_reading(self):
        # 本文は送らず「大きい」と名乗るだけ。読みに行くと待ちになるので、すぐ 413 が返れば「読んでいない」
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/fax/receive", method="POST")
        req.add_header("Authorization", "Bearer " + KEY)
        req.add_header("Content-Length", str(server.MAX_BODY + 1))
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("413 になるはず")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 413)

    def test_no_length_411(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", "/fax/receive")
        c.putheader("Authorization", "Bearer " + KEY)
        c.endheaders()
        self.assertEqual(c.getresponse().status, 411)
        c.close()

    def test_key_checked_before_size(self):
        # 合言葉なしで大きいと名乗っても 401（本文を読む前に断る）
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/fax/receive", method="POST")
        req.add_header("Content-Length", str(server.MAX_BODY + 1))
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_no_key_configured_503(self):
        old = os.environ["FAX_RECEIVER_KEY"]
        os.environ["FAX_RECEIVER_KEY"] = "  "
        try:
            st, _ = self.post(self.good_body(), {"Authorization": "Bearer  "})
            self.assertEqual(st, 503)
        finally:
            os.environ["FAX_RECEIVER_KEY"] = old

    def test_other_path_404_and_health(self):
        st, _ = self.post(self.good_body(), {"Authorization": "Bearer " + KEY}, path="/write")
        self.assertEqual(st, 404)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=5) as r:
            self.assertEqual(json.loads(r.read())["version"], server.VERSION)


class SlowAndBrokenClientTests(unittest.TestCase):
    """v0.1.1: 少しずつ送る相手・途中で切れる相手で止まらない（黒ヤギ実装レビュー 指摘3・足りないテスト2）"""

    @classmethod
    def setUpClass(cls):
        os.environ["FAX_RECEIVER_KEY"] = KEY
        cls._old_timeout = server.Handler.timeout
        server.Handler.timeout = 0.5
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.Handler.timeout = cls._old_timeout

    def setUp(self):
        self.buf = io.StringIO()
        self._old = sys.stdout
        sys.stdout = self.buf

    def tearDown(self):
        sys.stdout = self._old

    def raw_send(self, head: bytes, body_part: bytes, wait: float):
        import socket
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(head + body_part)
        t0 = __import__("time").time()
        s.settimeout(wait)
        try:
            got = s.recv(100)
        except OSError:
            got = b"(timeout)"
        s.close()
        return got, __import__("time").time() - t0

    def test_slow_body_is_cut(self):
        # 1000バイトと名乗って10バイトだけ送り、黙る → 0.5秒で受け口が切る（返事は無い）
        head = (b"POST /fax/receive HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + KEY.encode()
                + b"\r\nContent-Length: 1000\r\n\r\n")
        got, sec = self.raw_send(head, b"0123456789", wait=3)
        self.assertEqual(got, b"")            # 返事なしで切られた
        self.assertLess(sec, 2.5)
        __import__("time").sleep(0.2)
        self.assertIn('"read_incomplete"', self.buf.getvalue())

    def test_slow_body_on_reject_is_cut(self):
        # 合言葉なし（断る側の読み捨て）でも同じく止まらない
        head = b"POST /fax/receive HTTP/1.1\r\nHost: x\r\nContent-Length: 1000\r\n\r\n"
        got, sec = self.raw_send(head, b"0123456789", wait=3)
        self.assertEqual(got, b"")
        self.assertLess(sec, 2.5)

    def test_client_disconnects_mid_body(self):
        # 途中で切れても例外で止まらず、次の件は普通に受ける
        import socket
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(b"POST /fax/receive HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + KEY.encode()
                  + b"\r\nContent-Length: 1000\r\n\r\n0123")
        s.close()
        __import__("time").sleep(0.3)
        body = json.dumps({"ticket": "T-1", "s": "a", "o": "b", "homis_id": "1"}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/fax/receive", data=body, method="POST")
        req.add_header("Authorization", "Bearer " + KEY)
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)


class FirstRequestTests(unittest.TestCase):
    def test_only_one_first_even_if_concurrent(self):
        """v0.1.1: 起動直後に同時に来ても first_request は1件だけ（黒ヤギ実装レビュー 指摘5）"""
        server._first_request_done = False
        results = []
        barrier = threading.Barrier(20)

        def go():
            barrier.wait()
            results.append(server.mark_first_request())
        ths = [threading.Thread(target=go) for _ in range(20)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(results.count(True), 1)


class VersionTests(unittest.TestCase):
    def test_header_matches_version(self):
        """先頭のバージョンと VERSION がそろっている（版の決まり）"""
        with open(server.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("バージョン: " + server.VERSION, src)
        self.assertIn("v" + server.VERSION + " ", src)

    def test_spec_table_matches_version(self):
        """docs/SPEC_v3_cloud.md 0章の表に受け口と道具の版が載っている"""
        spec = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "SPEC_v3_cloud.md")
        with open(spec, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("cloud_fax_receiver/server.py | " + server.VERSION, text)
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
        import fax_shadow_reconcile as rec
        self.assertIn("tools/fax_shadow_reconcile.py | " + rec.VERSION, text)
        with open(rec.__file__, encoding="utf-8") as f:
            self.assertIn("バージョン: " + rec.VERSION, f.read())


if __name__ == "__main__":
    unittest.main()
