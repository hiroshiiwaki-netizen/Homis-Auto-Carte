# -*- coding: utf-8 -*-
"""結合テスト: 受け口 0.6.0 → 列 → ライター 3.11.0 の記録 → 実行リストの箱 0.1.0（本番と同じ順番）

本物の部品: 受け口の server.py（別プロセス）・run_record.py・ライターの _write_karte_inner と記録の足し方・
            箱の Go（C:\\Ohisama\\AppKartelog\\src でビルドした kartelog.exe・別プロセス）
偽物: Cloud Storage（fake_records）・Cloud Tasks と metadata（test_mirror.FakeCloud）・Chat・HOMIS を書く部分（_write_locked）
すべてダミーの値。kartelog.exe が無ければ箱の段は飛ばす（先に C: で go build -o kartelog.exe）。
使い方: py -3.12 -X utf8 cloud/tests/test_kartelog_e2e.py
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RECV_TESTS = os.path.join(HERE, "..", "..", "cloud_fax_receiver", "tests")
sys.path.insert(0, HERE)
import test_run_record  # noqa: E402,F401  shared_log の偽物を先に入れる
sys.path.insert(0, RECV_TESTS)
from fake_records import FakeRecords  # noqa: E402
import test_records as tr  # noqa: E402

EXE = r"C:\Ohisama\AppKartelog\src\kartelog.exe"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class E2E(tr.Records):
    """受け口のテスト（test_records.Records）の起動・送信を借りる。Records のテスト（test_q*）は流さない（下の defaultTest）"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 「server」は受け口のテストが受け口の server.py として先に読み込むので、ライターは別の名前で読む
        import importlib.util   # noqa: PLC0415
        spec = importlib.util.spec_from_file_location("writer_server", os.path.join(HERE, "..", "server.py"))
        writer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(writer)
        cls.writer, cls.rr = writer, writer.run_record

    def test_e1_receiver_writer_app(self):
        port, _ = self.start()
        # 1) Tukusi と同じ形で 3 件（FAX 書ける・FAX 食い違い・疑義照会）
        self.assertEqual(self.fax(port, ticket="261106100000-1")[0], 200)
        self.assertEqual(self.fax(port, ticket="261106100000-2", patient="7654321")[0], 200)
        self.assertEqual(self.bot(port, inquiry="G", sent_at="2026-11-06 10:01:00")[0], 200)
        self.assertEqual(len(self.cloud.tasks), 2)   # 食い違いは列に入らない

        # 2) 列の仕事をライターへ（記録の置き場は同じ偽物・HOMIS を書く部分だけ偽物）
        w, rr = self.writer, self.rr
        env = dict(os.environ)
        os.environ.update(RECORD_BUCKET="test-records", GCS_BASE=self.rec.url, METADATA_TOKEN_URL=self.rec.url + "/token")
        rr._token_cache.update(value="", until=0.0)
        rr._paused_until["t"] = 0.0
        saved = (w.sheet_enabled, w._write_locked, w._release_lock, w.patient_lock.acquire)
        w.sheet_enabled = lambda: False
        w._release_lock = lambda o: None
        w.patient_lock.acquire = lambda h, o: {"status": "ok", "generation": "1", "waited_sec": 0}

        def fake_write(data, order_id, homis_id, *a):
            if order_id.startswith("FAX-"):
                return {"success": True, "error_type": "", "karte_id": "77", "karte_url": "https://homis.jp/k?karte_id=77",
                        "total_sec": 48.0, "left_in_homis": "saved"}
            return {"success": False, "error_type": "blocked:in_progress_karte", "karte_id": "", "karte_url": "",
                    "total_sec": 130.0, "left_in_homis": "none"}
        w._write_locked = fake_write
        try:
            for t in self.cloud.tasks:
                payload = json.loads(base64.b64decode(t["task"]["httpRequest"]["body"]).decode("utf-8"))
                self.assertIn("recordDay", payload)
                w._write_karte_inner(payload, payload["orderId"], payload["homisId"])
        finally:
            w.sheet_enabled, w._write_locked, w._release_lock, w.patient_lock.acquire = saved
            os.environ.clear()
            os.environ.update(env)

        recs = self.records()
        self.assertEqual(recs["FAX-261106100000-1"]["status"], "ok")
        self.assertEqual(recs["FAX-261106100000-1"]["payload"]["oContent"], tr.SECRET_O)   # 受け口の中身が残る
        self.assertEqual(recs["FAX-261106100000-2"]["status"], "rejected")
        self.assertEqual((recs["BOT-G-20261106100100"]["status"], recs["BOT-G-20261106100100"]["left_in_homis"]), ("fail", "none"))

        # 3) 本物の箱で読む
        if not os.path.exists(EXE):
            self.skipTest("kartelog.exe が無い（C: で go build してから）")
        day = next(iter(self.rec.objects)).split("/")[1]
        ap = free_port()
        aenv = dict(os.environ, PORT=str(ap), DEV_EMAIL="staff@nhw.jp", RECORD_BUCKET="test-records",
                    GCS_BASE=self.rec.url, METADATA_TOKEN_URL=self.rec.url + "/token", QUEUES="")
        aenv.pop("K_SERVICE", None)
        aenv.pop("IAP_AUDIENCE", None)
        logf = open(os.path.join(tempfile.gettempdir(), f"kartelog_{ap}.log"), "w", encoding="utf-8")
        p = subprocess.Popen([EXE], env=aenv, stdout=logf, stderr=subprocess.STDOUT)
        self.addCleanup(lambda: (p.terminate(), p.wait(10), logf.close()))
        body = None
        for _ in range(50):
            try:
                c = http.client.HTTPConnection("127.0.0.1", ap, timeout=5)
                c.request("GET", f"/kartelog/api/list?from={day}&days=1")
                r = c.getresponse()
                body = json.loads(r.read())
                break
            except OSError:
                time.sleep(0.2)
        self.assertIsNotNone(body)
        rows = {r["order_id"]: r for r in body["rows"]}
        self.assertEqual((rows["FAX-261106100000-1"]["view"], rows["FAX-261106100000-1"]["action"]), ("ok", "open"))
        self.assertEqual((rows["FAX-261106100000-2"]["view"], rows["FAX-261106100000-2"]["action"]), ("fail", "check"))
        self.assertEqual((rows["BOT-G-20261106100100"]["view"], rows["BOT-G-20261106100100"]["action"]), ("fail", "rewrite"))
        self.assertEqual(rows["BOT-G-20261106100100"]["doc_type"], "疑義照会")
        self.assertNotIn(tr.SECRET_O, json.dumps(body, ensure_ascii=False))   # 一覧に本文は出さない
        c = http.client.HTTPConnection("127.0.0.1", ap, timeout=5)
        c.request("GET", f"/kartelog/api/record?day={day}&id=FAX-261106100000-1")
        one = json.loads(c.getresponse().read())
        self.assertEqual(one["payload"]["oContent"], tr.SECRET_O)   # 詳しい窓では見える


if __name__ == "__main__":
    unittest.main(verbosity=2, defaultTest="E2E.test_e1_receiver_writer_app")
