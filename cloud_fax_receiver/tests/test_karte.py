# -*- coding: utf-8 -*-
"""受け口 v0.7.0 の共通 JSON の入口 ①先生が選んだカルテに書く（POST /karte/receive）のテスト。すべてダミーの値。
本物の server.py を別プロセスで動かし、偽の列（test_mirror.FakeCloud）・偽の置き場（fake_records）に向ける。
使い方: py -3.12 -X utf8 cloud_fax_receiver/tests/test_karte.py
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "cloud", "tests"))
import test_records as tr  # noqa: E402

KKEY = "karte-key-dummy-KKQ"
KQ = "projects/p/locations/asia-northeast1/queues/homis-karte-json-writer"
URL = "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&karte_id=18000001&p=5"
TEST_URL = "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18000002&p=5"
SECRET_S = "音声の所見ダミーKSQ"


class Karte(tr.Records):
    """受け口のテスト（test_records）の起動を借りる。Records のテスト（test_q*）はここでは流さない"""

    def startk(self, **over):
        env = dict(KARTE_MODE="live", KARTE_RECEIVER_KEY=KKEY, KARTE_QUEUE=KQ)
        env.update(over)
        return self.start(**env)

    def send(self, port, body=None, key=KKEY, **over):
        d = {"karte_url": URL, "sent_at": "2026-11-06 16:00:00", "save_mode": "interrupt", "soap_s": SECRET_S,
             "soap_o": "O の文", "soap_ap_summary": "", "soap_ap_temporary": "AP", "instruction": "指導",
             "vital_bt": "36.5", "vital_bp_h": "120", "vital_bp_l": "80", "vital_pr": "70", "vital_spo2": "98",
             "start_time": "10:00", "end_time": "10:10", "sender_email": "doctor@example.jp", "source": "音声カルテ_WF"}
        if body is not None:
            d = body
        d = {**d, **over}
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=40)
        c.request("POST", "/karte/receive", body=json.dumps(d, ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        r = c.getresponse()
        out = (r.status, json.loads(r.read() or b"{}"))
        c.close()
        return out

    def test_k1_off_records_nothing(self):
        port, _ = self.startk(KARTE_MODE="off")
        code, body = self.send(port)
        self.assertEqual((code, body["order_id"], body["mode"]), (200, "KE-18000001-20261106160000", "off"))
        self.assertEqual((self.cloud.tasks, self.rec.calls), ([], []))

    def test_k2_live_queues_karte_edit(self):
        port, log = self.startk()
        code, body = self.send(port)
        self.assertEqual((code, body["order_id"]), (200, "KE-18000001-20261106160000"))
        (t,) = self.cloud.tasks
        self.assertTrue(t["task"]["name"].endswith("homis-karte-json-writer/tasks/KE-18000001-20261106160000"))
        p = json.loads(base64.b64decode(t["task"]["httpRequest"]["body"]).decode("utf-8"))
        self.assertEqual((p["template"], p["homisId"], p["karteId"], p["sContent"], p["soap_ap_temporary"], p["vital_spo2"],
                          p["start_time"], p["senderEmail"]),
                         ("karte_edit", "1234567", "18000001", SECRET_S, "AP", "98", "10:00", "doctor@example.jp"))
        self.assertIn("recordDay", p)
        rec = self.records()["KE-18000001-20261106160000"]
        self.assertEqual((rec["status"], rec["route"], rec["doc_type"], rec["sender"]),
                         ("received", "karte_edit", "音声カルテ（先生のカルテ）", "doctor@example.jp"))
        text = self.log_text(log)
        self.assertNotIn(SECRET_S, text)         # 本文はログに出さない
        self.assertNotIn("18000001&", text)      # URL もログに出さない

    def test_k3_bad_requests_are_4xx_with_reason(self):
        port, _ = self.startk()
        cases = [
            ({"karte_url": "https://example.com/?patient_id=1&karte_id=2"}, "bad_karte_url"),
            ({"karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&p=5"}, "bad_karte_url"),
            ({"karte_url": ""}, "no_karte_url"),
            ({"sent_at": ""}, "bad_sent_at"),
            ({"save_mode": "complete"}, "bad_save_mode"),
            ({"soap_s": "  "}, "empty_s"),
            ({"start_time": "25:00"}, "bad_time"),
            ({"patient_id": "7654321"}, "patient_mismatch"),
        ]
        for over, want in cases:
            code, body = self.send(port, **over)
            self.assertEqual((code, body["error"]), (400, want), over)
            self.assertTrue(body["message"])
        self.assertEqual(self.cloud.tasks, [])
        code, body = self.send(port, patient_id="1234567", homis_url="https://homis.jp/homic/?pid=patient_detail&patient_id=1234567")
        self.assertEqual(code, 200)              # 両方来ても一致すれば受ける

    def test_k4_url_variations(self):
        port, _ = self.startk()
        for u in ("https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&karte_id=18000001#top",
                  " HTTPS://homis.jp/homic/?karte_id=１８０００００１&patient_id=1234567 "):
            code, body = self.send(port, karte_url=u, sent_at="2026-11-06 16:0%d:00" % (len(u) % 9))
            self.assertEqual(code, 200, u)
            self.assertTrue(body["order_id"].startswith("KE-18000001-"))

    def test_k5_test_mode_only_test_patient(self):
        port, _ = self.startk(KARTE_MODE="test")
        code, body = self.send(port)
        self.assertEqual((code, body["error"]), (400, "test_only"))
        self.assertIn("テスト運用中のため本番のカルテには書けません", body["message"])
        code, body = self.send(port, karte_url=TEST_URL)
        self.assertEqual((code, body["order_id"]), (200, "KE-TEST-18000002-20261106160000"))

    def test_k6_new_karte_not_yet(self):
        port, _ = self.startk()
        code, body = self.send(port, karte_url="", patient_id="1234567")
        self.assertEqual((code, body["error"]), (400, "not_supported_yet"))

    def test_k7_key_and_config(self):
        port, _ = self.startk()
        self.assertEqual(self.send(port, key="wrong")[0], 401)
        port2, _ = self.startk(KARTE_QUEUE="")
        code, body = self.send(port2)
        self.assertEqual((code, body["error"]), (503, "no_config"))

    def test_k7b_mode_unset_or_typo_is_503(self):
        for m in ("", "liv"):
            port, _ = self.startk(KARTE_MODE=m)
            code, body = self.send(port)
            self.assertEqual((code, body["error"]), (503, "no_config"), m)   # 黙って何もしない 200 にしない

    def test_k8_existing_routes_unchanged(self):
        port, _ = self.startk()
        self.assertEqual(self.fax(port)[0], 200)
        self.assertEqual(self.bot(port)[0], 200)
        names = sorted(t["task"]["name"].rsplit("/", 1)[1] for t in self.cloud.tasks)
        self.assertEqual(names, ["BOT-123-20261106090000", "FAX-261106090000-1"])

    def test_k9_queue_down_is_503_and_rejected(self):
        port, _ = self.startk()
        self.cloud.mode = "down"
        code, body = self.send(port)
        self.assertEqual((code, body["error"]), (503, "queue"))
        self.assertEqual(self.records()["KE-18000001-20261106160000"]["status"], "rejected")


if __name__ == "__main__":
    unittest.main(verbosity=2, defaultTest=[f"Karte.{n}" for n in dir(Karte) if n.startswith("test_k")])
