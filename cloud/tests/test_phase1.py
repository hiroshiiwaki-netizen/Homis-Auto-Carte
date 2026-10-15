# -*- coding: utf-8 -*-
"""GCP 移行計画 フェーズ1 のテスト（navi_callback.py・server.py v3.1.0）

本物の server.py（HTTP の受け口）と navi_callback.py を動かし、手元に
  - 偽のナビ（GAS と同じく POST に 302 → 移動先を GET で読むと JSON）
  - 偽の DX Chat（届いた本文を覚える）
を立てて、外から見た結果（ナビに何が届いたか・DX に何が届いたか・応答コード）を確かめる。
HOMIS には書かない（write_karte は偽物に差し替える）。共有ドライブにも触らない（shared_log 等は偽物）。

使い方: py -3.12 -X utf8 cloud/tests/test_phase1.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import types
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD = os.path.dirname(HERE)
sys.path.insert(0, CLOUD)

# --- server.py が読み込む重い部品を偽物にする（Chrome・共有ドライブに触らない） ---
for name in ["selenium", "selenium.webdriver", "selenium.webdriver.chrome", "selenium.webdriver.chrome.options",
             "selenium.webdriver.chrome.service"]:
    sys.modules[name] = types.ModuleType(name)
sys.modules["selenium"].webdriver = sys.modules["selenium.webdriver"]
sys.modules["selenium.webdriver.chrome.options"].Options = object
sys.modules["selenium.webdriver.chrome.service"].Service = object
ba = types.ModuleType("browser_actions")
ba.BrowserActions = type("BrowserActions", (), {"_action_click": lambda *a, **k: None})
sys.modules["browser_actions"] = ba
te = types.ModuleType("template_engine")
te.TemplateEngine = type("TemplateEngine", (), {})
sys.modules["template_engine"] = te
sl = types.ModuleType("shared_log")
sl.extract_karte_id = lambda url: (url.split("karte_id=", 1)[1].split("&", 1)[0] if "karte_id=" in (url or "") else "")
sl.infer_error_type = lambda r: r.get("error_type") or ""
sl.log_result = lambda *a, **k: None
sys.modules["shared_log"] = sl

import navi_callback  # noqa: E402
import server  # noqa: E402

navi_callback.WAITS = (0, 0)  # テストでは待たない
navi_callback.TIMEOUT_SEC = 2


class FakeNavi:
    """偽のナビ。script に従って返す。届いた本文を calls に覚える"""

    def __init__(self):
        self.calls = []
        self.script = []  # 1回ごとの返し方: "ok" / "ng" / "500" / "hang" / "html"
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                outer.calls.append(body)
                how = outer.script.pop(0) if outer.script else "ok"
                if how == "500":
                    self.send_response(500); self.end_headers(); return
                if how == "hang":
                    import time; time.sleep(3); return  # 応答しない（クライアントは時間切れ）
                # GAS と同じ: 302 で移動先へ。移動先を GET で読むと結果
                self.send_response(302)
                self.send_header("Location", f"/echo?how={how}")
                self.end_headers()

            def do_GET(self):
                how = self.path.split("how=", 1)[1] if "how=" in self.path else "ok"
                if how == "html":
                    data = b"<html>error</html>"
                else:
                    data = json.dumps({"success": how == "ok", "message": "fake " + how}).encode("utf-8")
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/exec"

    def close(self):
        self.httpd.shutdown()


class FakeDx(FakeNavi):
    """偽の DX Chat。本文を覚えて 200"""

    def __init__(self):
        super().__init__()


def start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def post(url, payload, key="k-test"):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "X-Writer-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


class Phase1(unittest.TestCase):
    def setUp(self):
        self.navi = FakeNavi()
        self.dx = FakeNavi()  # DX Chat も同じ偽物で本文を覚える（302 で GET → 200）
        os.environ["NAVI_WEBAPP_URL"] = self.navi.url
        os.environ["DX_ALERT_WEBHOOK"] = self.dx.url
        os.environ["HOMIS_WRITER_KEY"] = "k-test"
        os.environ["ALLOWED_HOMIS_IDS"] = "2277808"
        os.environ.pop("RESULT_SPREADSHEET_ID", None)
        self.httpd, self.base = start_server()
        self.next_result = {}
        server.write_karte = lambda data: dict(self.next_result, orderId=data.get("orderId"))

    def tearDown(self):
        self.httpd.shutdown(); self.navi.close(); self.dx.close()

    def body(self, oid="GCP-T-1", **kw):
        d = {"orderId": oid, "homisId": "2277808", "patientName": "テスト"}
        d.update(kw)
        return d

    # --- navi_callback 単体 ---
    def test_u1_ok_once(self):
        r = navi_callback.post_action({"action": "updateHomisLink", "orderId": "X"})
        self.assertEqual((r["delivered"], r["success"], r["attempts"]), (True, True, 1))

    def test_u2_retry_on_500_then_ok(self):
        self.navi.script = ["500", "500", "ok"]
        r = navi_callback.post_action({"action": "x"})
        self.assertEqual((r["delivered"], r["success"], r["attempts"]), (True, True, 3))

    def test_u3_no_retry_when_navi_says_ng(self):
        self.navi.script = ["ng"]
        r = navi_callback.post_action({"action": "x"})
        self.assertEqual((r["delivered"], r["success"], r["attempts"]), (True, False, 1))

    def test_u4_hang_three_times_then_give_up(self):
        self.navi.script = ["hang", "hang", "hang"]
        r = navi_callback.post_action({"action": "x"})
        self.assertEqual((r["delivered"], r["success"], r["attempts"]), (False, False, 3))

    def test_u5_html_is_not_retried(self):
        self.navi.script = ["html"]
        r = navi_callback.post_action({"action": "x"})
        self.assertEqual((r["delivered"], r["success"], r["attempts"], r["message"]), (True, False, 1, "not_json"))

    def test_u6_disabled_without_url(self):
        os.environ["NAVI_WEBAPP_URL"] = ""
        r = navi_callback.notify_karte("X", "")
        self.assertEqual(r["attempts"], 0)
        self.assertEqual(self.navi.calls, [])
        self.assertEqual(self.dx.calls, [])

    # --- server 結合（本物の受け口 → 偽のナビ） ---
    def test_s1_success_sends_direct_link(self):
        self.next_result = {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=111", "error_type": ""}
        code, out = post(self.base + "/write", self.body())
        self.assertEqual(code, 200)
        self.assertEqual(self.navi.calls, [{"action": "updateHomisLink", "orderId": "GCP-T-1",
                                            "homisUrl": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=111"}])
        self.assertEqual(self.dx.calls, [])
        self.assertTrue(out["navi"]["success"])

    def test_s2_failure_sends_empty_url(self):
        self.next_result = {"success": False, "karte_url": "", "error_type": "login"}
        code, _ = post(self.base + "/write", self.body())
        self.assertEqual(code, 500)
        self.assertEqual(self.navi.calls, [{"action": "updateHomisLink", "orderId": "GCP-T-1", "homisUrl": ""}])

    def test_s3_no_karte_id_sends_empty_url(self):
        # 完了したが直リンクが取れない（仕様 7.2 #8）→ 空で知らせる（ナビが患者ページで出す）
        self.next_result = {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808", "error_type": ""}
        post(self.base + "/write", self.body())
        self.assertEqual(self.navi.calls[0]["homisUrl"], "")

    def test_s4_duplicate_does_not_notify(self):
        self.next_result = {"success": True, "karte_url": "", "error_type": "duplicate"}
        code, _ = post(self.base + "/write", self.body())
        self.assertEqual(code, 409)
        self.assertEqual(self.navi.calls, [])

    def test_s5_other_templates_do_not_notify(self):
        self.next_result = {"success": True, "karte_url": "", "error_type": ""}
        code, _ = post(self.base + "/write", self.body(template="bot_s_interrupt", sContent="s"))
        self.assertEqual(code, 200)
        self.assertEqual(self.navi.calls, [])

    def test_s6_navi_down_alerts_dx(self):
        self.navi.script = ["hang", "hang", "hang"]
        self.next_result = {"success": True, "karte_url": "https://h/?karte_id=9", "error_type": ""}
        code, out = post(self.base + "/write", self.body(oid="GCP-T-DOWN"))
        self.assertEqual(code, 200)
        self.assertEqual(len(self.navi.calls), 3)
        self.assertEqual(len(self.dx.calls), 1)
        self.assertIn("GCP-T-DOWN", self.dx.calls[0]["text"])
        self.assertNotIn("karte_id", self.dx.calls[0]["text"])  # URL は DX に出さない

    def test_s7_navi_says_ng_alerts_dx_once(self):
        self.navi.script = ["ng"]
        self.next_result = {"success": True, "karte_url": "https://h/?karte_id=9", "error_type": ""}
        post(self.base + "/write", self.body(oid="GCP-T-NG"))
        self.assertEqual(len(self.navi.calls), 1)
        self.assertEqual(len(self.dx.calls), 1)

    def test_s8_check_group_forwards(self):
        code, out = post(self.base + "/check-group", {"groupId": "GRP_T"})
        self.assertEqual(code, 200)
        self.assertEqual(self.navi.calls, [{"action": "checkGroupComplete", "groupId": "GRP_T"}])

    def test_s9_check_group_needs_key_and_group(self):
        code, _ = post(self.base + "/check-group", {"groupId": "GRP_T"}, key="wrong-k")
        self.assertEqual(code, 401)
        code, _ = post(self.base + "/check-group", {})
        self.assertEqual(code, 400)
        self.assertEqual(self.navi.calls, [])

    def test_s10_write_still_needs_key(self):
        code, _ = post(self.base + "/write", self.body(), key="wrong-k")
        self.assertEqual(code, 401)
        self.assertEqual(self.navi.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
