# -*- coding: utf-8 -*-
"""受け口 v0.3.0 の本番（FAX_MODE=live・段3）のテスト

test_mirror.py と同じく、偽の metadata・偽の Cloud Tasks を立て、本物の server.py を別プロセスで動かして Tukusi と同じ形で送る。
偽の Chat（現場用・DX）も立て、仕事にできなかったときの知らせを確かめる。すべてダミーの値。
使い方: py -3.12 -X utf8 cloud_fax_receiver/tests/test_live.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import server  # noqa: E402
from test_mirror import QUEUE, SECRET_O, SECRET_S, WKEY, FakeCloud, MirrorFlow  # noqa: E402

LIVE_Q = "projects/p/locations/asia-northeast1/queues/homis-fax-writer"
URL_OK = "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&p=5"


class FakeChat:
    """偽の Chat Webhook。届いた本文を texts に覚える。hang=True なら返事をしない"""

    def __init__(self):
        self.texts = []
        self.hang = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                outer.texts.append((self.path, json.loads(self.rfile.read(n))["text"]))
                if outer.hang:
                    time.sleep(6)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ExtractHomisId(unittest.TestCase):
    def test_e1_cases(self):
        f = server.extract_homis_id
        self.assertEqual(f(URL_OK), "1234567")
        self.assertEqual(f("https://homis.jp/homic/?patient_id=7654321"), "7654321")       # 最後の項目
        self.assertEqual(f(" 2277808 "), "2277808")                                       # 数字だけ
        self.assertEqual(f("https://homis.jp/homic/?pid=patient_detail&p=5"), "")          # patient_id が無い
        self.assertEqual(f("https://homis.jp/homic/?xpatient_id=1234567"), "")             # 別の名前の項目
        self.assertEqual(f("https://homis.jp/homic/?patient_id=12345678901"), "")          # 11桁
        self.assertEqual(f("https://homis.jp/homic/?patient_id=12a45"), "")                # 数字でない
        self.assertEqual(f(None), "")
        self.assertEqual(f("1"), "1")                                                     # 1桁も通す（幅を持たせる）

    def test_e2_mode(self):
        env = dict(os.environ)
        try:
            for fm, fx, want in [("live", "", "live"), ("mirror", "", "mirror"), ("off", "on", "off"), ("", "on", "mirror"),
                                 ("", "", "off"), ("LIVE ", "", "live"), ("bogus", "on", "off")]:
                os.environ["FAX_MODE"], os.environ["FAX_MIRROR"] = fm, fx
                self.assertEqual(server.fax_mode(), want, (fm, fx))
        finally:
            os.environ.clear()
            os.environ.update(env)


class LiveFlow(MirrorFlow):
    """MirrorFlow の起動・送信・記録の読み方を借り、live の設定で動かす（MirrorFlow のテストはここでは流さない）"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.chat = FakeChat()

    @classmethod
    def tearDownClass(cls):
        cls.chat.close()
        super().tearDownClass()

    def start_live(self, **over):
        env = dict(FAX_MODE="live", LIVE_QUEUE=LIVE_Q, FAX_FIELD_WEBHOOK=self.chat.url + "/field",
                   DX_ALERT_WEBHOOK=self.chat.url + "/dx")
        env.update(over)
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        self.chat.texts.clear()
        self.chat.hang = False
        return self.start(**env)

    def send_live(self, port, ticket="261029090000-1", s=SECRET_S, o=SECRET_O, homis=URL_OK, patient="1234567"):
        import http.client
        d = {"source": "WF1573", "lock": {"ticket": ticket, "granted": True}, "homis_id": homis,
             "s": s, "o": o, "doc_type": "検査結果", "route": "垂水FAX"}
        if patient is not None:
            d["homis_patient"] = patient
        body = json.dumps(d).encode("utf-8")
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        t0 = time.time()
        c.request("POST", "/fax/receive", body=body, headers={"Content-Type": "application/json", "Authorization": "Bearer mirror-test-key"})
        r = c.getresponse()
        out = (r.status, json.loads(r.read()), time.time() - t0)
        c.close()
        return out

    def last(self, log):
        return [r for r in self.records(log) if r.get("event") == "fax_shadow"][-1]

    def assert_no_secret_in_log(self, log):
        with open(log, encoding="utf-8") as f:
            raw = f.read()
        for w in ("ZZQ", "XXQ", WKEY, "1234567"):
            self.assertNotIn(w, raw)

    # --- 本番の仕事 ---
    def test_l1_live_task_to_real_patient(self):
        port, log = self.start_live()
        st, body, _ = self.send_live(port)
        self.assertEqual((st, body["ok"]), (200, True))
        self.assertEqual(len(self.cloud.tasks), 1)                    # 本番だけ（試し書きは入れない）
        t = self.cloud.tasks[0]
        self.assertEqual(t["path"], "/v2/" + LIVE_Q + "/tasks")
        task = t["task"]
        self.assertEqual(task["name"], LIVE_Q + "/tasks/FAX-261029090000-1")
        hr = task["httpRequest"]
        self.assertEqual(hr["headers"]["X-Writer-Key"], WKEY)
        self.assertEqual(hr["oidcToken"]["audience"], "https://writer.example.run.app")
        p = json.loads(base64.b64decode(hr["body"]).decode("utf-8"))
        self.assertEqual((p["orderId"], p["homisId"], p["template"]), ("FAX-261029090000-1", "1234567", "fax_so"))
        self.assertEqual((p["sContent"], p["oContent"]), (SECRET_S, SECRET_O))   # 試し書きの印を付けない
        rec = self.last(log)
        self.assertEqual((rec["mode"], rec["live"], rec["mirror"]), ("live", "queued", "off"))
        self.assertEqual(self.chat.texts, [])
        self.assert_no_secret_in_log(log)

    def test_l2_duplicate_is_quiet(self):
        port, log = self.start_live()
        self.cloud.mode = "dup"
        self.send_live(port, ticket="261029090000-2")
        self.assertEqual(self.last(log)["live"], "duplicate")
        self.assertEqual(self.chat.texts, [])

    # --- 仕事にできなかった → 現場と DX に知らせる ---
    def check_skip(self, log, word, ticket):
        rec = self.last(log)
        self.assertEqual(rec["live"], word)
        self.assertEqual(self.cloud.tasks, [])
        self.assertEqual(sorted(p for p, _ in self.chat.texts), ["/dx", "/field"])
        for _, text in self.chat.texts:
            self.assertIn(ticket or "（なし）", text)
            for w in ("ZZQ", "XXQ", "1234567"):
                self.assertNotIn(w, text)                             # 本文・患者番号を知らせに入れない

    def test_l3_bad_homis_id(self):
        port, log = self.start_live()
        self.send_live(port, ticket="261029090000-3", homis="https://homis.jp/homic/?pid=patient_detail&p=5")
        self.check_skip(log, "skip:bad_homis_id", "261029090000-3")
        self.assertIn("患者番号が読めません", self.chat.texts[0][1])

    def test_l4_empty_s(self):
        port, log = self.start_live()
        self.send_live(port, ticket="261029090000-4", s=" ")
        self.check_skip(log, "skip:empty", "261029090000-4")

    def test_l5_no_ticket(self):
        port, log = self.start_live()
        self.send_live(port, ticket="")
        self.check_skip(log, "skip:no_ticket", "")

    def test_l6_no_config(self):
        port, log = self.start_live(LIVE_QUEUE="")
        self.send_live(port, ticket="261029090000-6")
        self.check_skip(log, "skip:no_config", "261029090000-6")

    def test_l7_tasks_down_notifies_and_still_200(self):
        port, log = self.start_live()
        self.cloud.mode = "down"
        st, _, sec = self.send_live(port, ticket="261029090000-7")
        self.assertEqual(st, 200)
        self.assertLess(sec, 6.5)
        self.assertTrue(self.last(log)["live"].startswith("error:"))
        self.assertEqual(len(self.chat.texts), 2)
        self.cloud.mode = "ok"

    def test_l8_chat_hang_does_not_block_tukusi(self):
        # 知らせが応えなくても、待ちは1つ3秒まで・Tukusi には 200（黒ヤギ 10/29 段3仕様 指摘4）
        port, log = self.start_live()
        self.chat.hang = True
        st, body, sec = self.send_live(port, ticket="261029090000-8", homis="abc")
        self.assertEqual((st, body["ok"]), (200, True))
        self.assertLess(sec, 8.0)
        self.assertEqual(self.last(log)["live"], "skip:bad_homis_id")
        self.chat.hang = False

    def test_l9_mirror_mode_unchanged(self):
        # FAX_MODE=mirror は今までの試し書きと同じ（本番の列には入れない・知らせない）
        port, log = self.start_live(FAX_MODE="mirror")
        self.send_live(port, ticket="261029090000-9")
        rec = self.last(log)
        self.assertEqual((rec["mode"], rec["mirror"]), ("mirror", "queued"))
        self.assertNotIn("live", rec)
        self.assertEqual(self.cloud.tasks[0]["path"], "/v2/" + QUEUE + "/tasks")
        self.assertEqual(self.chat.texts, [])

    # --- v0.3.1 患者さんの食い違い ---
    def test_p1_mismatch_is_not_written(self):
        port, log = self.start_live()
        self.send_live(port, ticket="261029090000-11", patient="7654321")
        self.check_skip(log, "skip:id_mismatch", "261029090000-11")
        self.assertIn("食い違って", self.chat.texts[0][1])
        with open(log, encoding="utf-8") as f:                                  # 黒ヤギ 10/29 指摘4: 閉じる
            self.assertNotIn("7654321", f.read())                               # どちらの番号も記録に出さない
        self.assertEqual(self.last(log)["patient_check"], "mismatch")

    def test_p2_missing_patient_is_not_written(self):
        port, log = self.start_live()
        self.send_live(port, ticket="261029090000-12", patient=None)
        self.check_skip(log, "skip:id_missing", "261029090000-12")

    def test_p3_same_in_url_or_number_form(self):
        # OhiScanGo の番号が数字でも URL でも、同じ人なら書く
        port, log = self.start_live()
        self.send_live(port, ticket="261029090000-13", patient=URL_OK)
        self.assertEqual((self.last(log)["live"], self.last(log)["patient_check"]), ("queued", "same"))

    def test_p4_mirror_records_check_but_still_writes_test(self):
        # 練習モードでも比べた結果を残す（11/2 までに実績をためる）。試し書きは今までどおり
        port, log = self.start_live(FAX_MODE="mirror")
        self.send_live(port, ticket="261029090000-14", patient="7654321")
        rec = self.last(log)
        self.assertEqual((rec["patient_check"], rec["mirror"]), ("mismatch", "queued"))
        self.assertEqual(self.chat.texts, [])

    def test_p5_unit(self):
        f = server.patient_check
        self.assertEqual(f(URL_OK, "1234567"), "same")
        self.assertEqual(f(URL_OK, " 1234567 "), "same")
        self.assertEqual(f(URL_OK, "1234568"), "mismatch")
        self.assertEqual(f("abc", "1234567"), "unreadable")   # 書く先が読めない（v0.3.1 で mismatch と分けた）
        self.assertEqual(f(URL_OK, ""), "missing")
        self.assertEqual(f(URL_OK, None), "missing")
        self.assertEqual(f(URL_OK, "None"), "missing")   # Tukusi は空の変数を "None" で送ることがある
        # 黒ヤギ 10/29 指摘1〜3・5
        self.assertEqual(f(URL_OK, "１２３４５６７"), "same")                                   # 全角は半角にそろえる
        self.assertEqual(f(URL_OK.replace("1234567", "１２３４５６７"), "1234567"), "same")
        self.assertEqual(server.extract_homis_id("１２３４５６７"), "1234567")                  # 半角で返す
        for zero in ("0", 0, "0000000", "0123456"):
            self.assertEqual(f(URL_OK, zero), "missing", zero)                                # 先頭 0 は番号にしない
        self.assertEqual(server.extract_homis_id("https://homis.jp/homic/?patient_id=0"), "")
        self.assertEqual(server.extract_homis_id("エラー: x&patient_id=1234567"), "")          # 文章の中は拾わない
        self.assertEqual(server.extract_homis_id("http://evil.example/?patient_id=1234567"), "")
        self.assertEqual(f("https://homis.jp/invalid", "1234567"), "unreadable")             # 書く先が読めない
        # 黒ヤギ 10/29 再レビュー 指摘2・3
        self.assertEqual(server.extract_homis_id(URL_OK.replace("&p=5", "#karte")), "1234567")
        self.assertEqual(server.extract_homis_id("HTTPS://HOMIS.JP/homic/?pid=patient_detail&patient_id=1234567&p=5"), "1234567")

    def test_p7_only_same_is_written(self):
        # 黒ヤギ 10/29 再レビュー 指摘1: patient_check が想定外の値を返しても書かない
        orig = server.patient_check
        try:
            server.patient_check = lambda a, b: "something_new"
            self.assertEqual(server.enqueue_live("261029090000-16", URL_OK, "s", "o", "1234567"), "skip:id_mismatch")
        finally:
            server.patient_check = orig

    def test_p6_unreadable_target_logs_unreadable(self):
        # 書く先が読めないときは、知らせは「患者番号が読めません」・記録は unreadable（食い違いと分ける）
        port, log = self.start_live()
        self.send_live(port, ticket="261029090000-15", homis="https://homis.jp/invalid", patient="1234567")
        self.check_skip(log, "skip:bad_homis_id", "261029090000-15")
        self.assertEqual(self.last(log)["patient_check"], "unreadable")
        self.assertIn("患者番号が読めません", self.chat.texts[0][1])

    def test_l10_off_mode_sends_nothing(self):
        port, log = self.start_live(FAX_MODE="off")
        self.send_live(port, ticket="261029090000-10", s=" ")
        self.assertEqual(self.cloud.tasks, [])
        self.assertEqual(self.chat.texts, [])


# MirrorFlow のテストを二重に流さない
for _name in [n for n in dir(MirrorFlow) if n.startswith("test_")]:
    setattr(LiveFlow, _name, None)
del MirrorFlow

if __name__ == "__main__":
    unittest.main(verbosity=1)
