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
import time
import types
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD = os.path.dirname(HERE)
sys.path.insert(0, CLOUD)
sys.path.insert(0, HERE)  # v3.2.0: 結合テストで test_verify_karte の偽の HOMIS を使う

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
from fake_gcs import FakeGCS  # noqa: E402  v3.9.0: 患者さんごとの札の置き場（偽物）

ORIG_WRITE_KARTE = server.write_karte  # v3.1.2 のテストで本物の write_karte を使う（setUp で偽物に差し替える前に控える）
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
    @classmethod
    def setUpClass(cls):
        cls.gcs = FakeGCS()   # v3.9.0: 札の置き場。write_karte は札が取れないと書かないので、全テストで偽物を立てる
        cls.gcs.install_env()

    @classmethod
    def tearDownClass(cls):
        cls.gcs.shutdown()

    def setUp(self):
        self.gcs.reset()
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
        # v3.2.0: 読み直しは既定で偽物（本物の HOMIS を読みに行かない）。calls に呼ばれた型紙を覚える
        self.verify_result = {"verdict": "ok", "status": "3", "reads": 1, "s_len": 1, "o_len": 1, "reason": ""}
        self.verify_calls = []
        server.verify_karte = types.SimpleNamespace(
            verify=lambda *a, **k: (self.verify_calls.append(a + tuple(sorted(k.items()))), dict(self.verify_result))[1])

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

    def test_s11_unexpected_error_in_notify_still_returns_result(self):
        # 知らせで思わぬ例外が出ても、書いた結果（200）は必ず返る（黒ヤギ 10/15 指摘1）
        orig = navi_callback.notify_karte
        navi_callback.notify_karte = lambda *a, **k: (_ for _ in ()).throw(TypeError("boom"))
        try:
            self.next_result = {"success": True, "karte_url": "https://h/?karte_id=9", "error_type": ""}
            code, out = post(self.base + "/write", self.body(oid="GCP-T-EXC"))
        finally:
            navi_callback.notify_karte = orig
        self.assertEqual(code, 200)
        self.assertEqual(out["navi"]["message"], "TypeError")
        self.assertTrue(out["success"])

    def test_s12_allow_all_with_star(self):
        # v3.1.1: ALLOWED_HOMIS_IDS="*" なら許可リストの外の患者も書く（本番の切り替え用）
        os.environ["ALLOWED_HOMIS_IDS"] = "*"
        self.next_result = {"success": True, "karte_url": "https://h/?karte_id=5", "error_type": ""}
        code, out = post(self.base + "/write", self.body(oid="GCP-T-ALL", homisId="1234567"))
        self.assertEqual(code, 200)
        self.assertEqual(self.navi.calls, [{"action": "updateHomisLink", "orderId": "GCP-T-ALL", "homisUrl": "https://h/?karte_id=5"}])

    def test_s13_not_allowed_still_notifies(self):
        # v3.1.1: 許可の外で断るときも黙らない（ナビに空の URL・DX に1通）。書かない
        called = []
        server.write_karte = lambda data: called.append(data) or {}
        code, out = post(self.base + "/write", self.body(oid="GCP-T-NG403", homisId="1234567"))
        self.assertEqual(code, 403)
        self.assertEqual(called, [])
        self.assertEqual(self.navi.calls, [{"action": "updateHomisLink", "orderId": "GCP-T-NG403", "homisUrl": ""}])
        self.assertEqual(len(self.dx.calls), 1)
        self.assertIn("ALLOWED_HOMIS_IDS", self.dx.calls[0]["text"])

    def test_s14_unset_means_test_patient_only(self):
        # 未設定はテスト舞子だけ（今までどおり）
        os.environ.pop("ALLOWED_HOMIS_IDS", None)
        self.assertEqual(server._allowed_ids(), {"2277808"})

    def test_s15_failed_step_with_karte_id_alerts_dx(self):
        # v3.1.2: カルテ番号が取れても、途中の手順の失敗（10/16 の「外来を選択」）は DX に知らせる（直リンク付き）
        url = "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&karte_id=99"
        server._run_once = lambda data: {"success": True, "karte_url": url, "error_type": "step:外来を選択", "failed_steps": ["外来を選択"]}
        out = ORIG_WRITE_KARTE(self.body(oid="GCP-T-STEP"))
        self.assertEqual(out["failed_steps"], ["外来を選択"])
        self.assertEqual(len(self.dx.calls), 1)
        self.assertIn("外来を選択", self.dx.calls[0]["text"])
        self.assertIn("karte_id=99", self.dx.calls[0]["text"])
        self.assertIn("GCP-T-STEP", self.dx.calls[0]["text"])

    def test_s15b_fax_failed_step_hint(self):
        # v3.1.3: FAX の型紙の失敗は「算定不要の印」を確かめる文（「外来」と出さない・黒ヤギ 10/27 指摘2）
        url = "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&karte_id=97"
        server._run_once = lambda data: {"success": True, "karte_url": url, "failed_steps": ["算定不要を押す"]}
        ORIG_WRITE_KARTE(self.body(oid="GCP-T-FAX", template="fax_so", sContent="s", oContent="o"))
        self.assertEqual(len(self.dx.calls), 1)
        text = self.dx.calls[0]["text"]
        self.assertIn("算定不要を押す", text)
        self.assertIn("算定不要の印", text)
        self.assertNotIn("外来", text)

    def test_s15c_xray_hint_unchanged(self):
        # レントゲンの文は今までどおり「外来」
        url = "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&karte_id=96"
        server._run_once = lambda data: {"success": True, "karte_url": url, "failed_steps": ["外来を選択"]}
        ORIG_WRITE_KARTE(self.body(oid="GCP-T-XR"))
        self.assertIn("カルテの種別（外来）", self.dx.calls[0]["text"])

    def test_s16_no_failed_step_no_alert(self):
        url = "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&karte_id=98"
        server._run_once = lambda data: {"success": True, "karte_url": url, "error_type": ""}
        out = ORIG_WRITE_KARTE(self.body(oid="GCP-T-OK"))
        self.assertEqual(out["failed_steps"], [])
        self.assertEqual(self.dx.calls, [])

    # --- v3.2.0 書いたあとの読み直し ---
    def fax(self, oid):
        return self.body(oid=oid, template="fax_so", sContent="送り元", oContent="本文")

    def test_s17_fax_not_completed_is_failure(self):
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=95"}
        self.verify_result.update(verdict="not_completed", status="1")
        out = ORIG_WRITE_KARTE(self.fax("GCP-T-V1"))
        self.assertEqual((out["success"], out["error_type"], out["verify"]), (False, "verify:not_completed", "not_completed"))
        self.assertEqual(self.verify_calls[0][:2], ("2277808", "95"))
        self.assertEqual(len(self.dx.calls), 1)
        self.assertIn("完了", self.dx.calls[0]["text"])
        self.assertIn("karte_id=95", self.dx.calls[0]["text"])

    def test_s18_fax_unverified_stays_success_but_tells_dx(self):
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=94"}
        self.verify_result.update(verdict="unverified", status="", reason="URLError")
        out = ORIG_WRITE_KARTE(self.fax("GCP-T-V2"))
        self.assertEqual((out["success"], out["verify"]), (True, "unverified"))
        self.assertEqual(len(self.dx.calls), 1)
        self.assertIn("読み直し", self.dx.calls[0]["text"])

    def test_s19_fax_ok_is_quiet(self):
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=93"}
        out = ORIG_WRITE_KARTE(self.fax("GCP-T-V3"))
        self.assertEqual((out["success"], out["verify"]), (True, "ok"))
        self.assertEqual(self.dx.calls, [])

    def test_s20_xray_is_not_verified(self):
        # レントゲンの型紙は今までどおり（読み直さない）
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=92"}
        out = ORIG_WRITE_KARTE(self.body(oid="GCP-T-V4"))
        self.assertEqual((out["success"], out["verify"]), (True, ""))
        self.assertEqual(self.verify_calls, [])

    def test_s21_fax_failed_write_is_not_verified(self):
        # カルテ番号が取れなかったときは読み直さない（今までどおりの失敗の扱い）
        server._run_once = lambda data: {"success": False, "karte_url": "", "error_type": "timeout"}
        ORIG_WRITE_KARTE(self.fax("GCP-T-V5"))
        self.assertEqual(self.verify_calls, [])

    # --- v3.3.0 本番の FAX が書けなかったときの現場への知らせ ---
    def field_setup(self):
        self.field = FakeNavi()
        os.environ["FAX_FIELD_WEBHOOK"] = self.field.url
        self.addCleanup(lambda: (self.field.close(), os.environ.pop("FAX_FIELD_WEBHOOK", None)))

    def live(self, oid):
        return self.body(oid=oid, template="fax_so", sContent="送り元", oContent="本文")

    def test_f1_live_fax_failure_tells_field(self):
        self.field_setup()
        server._run_once = lambda data: {"success": False, "karte_url": "", "error_type": "timeout"}
        ORIG_WRITE_KARTE(self.live("FAX-261029090000-1"))
        self.assertEqual(len(self.field.calls), 1)
        text = self.field.calls[0]["text"]
        self.assertIn("注文番号 FAX-261029090000-1", text)
        self.assertIn("patient_id=2277808", text)
        self.assertNotIn("本文", text.split("\n")[0] + text.split("\n")[-1])  # S/O の中身は入れない

    def test_f2_live_fax_verify_fail_tells_field(self):
        self.field_setup()
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=90"}
        self.verify_result.update(verdict="not_completed", status="1")
        out = ORIG_WRITE_KARTE(self.live("FAX-261029090000-2"))
        self.assertFalse(out["success"])
        self.assertEqual(len(self.field.calls), 1)
        self.assertIn("保存が完了していません", self.field.calls[0]["text"])
        self.assertIn("karte_id=90", self.field.calls[0]["text"])

    def test_f3_mirror_failure_does_not_tell_field(self):
        self.field_setup()
        server._run_once = lambda data: {"success": False, "karte_url": "", "error_type": "timeout"}
        ORIG_WRITE_KARTE(self.live("FAX-MIRROR-261029090000-3"))
        self.assertEqual(self.field.calls, [])

    def test_f4_live_fax_success_is_quiet(self):
        self.field_setup()
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=89"}
        ORIG_WRITE_KARTE(self.live("FAX-261029090000-4"))
        self.assertEqual(self.field.calls, [])

    def test_f5_field_unset_does_not_break(self):
        os.environ.pop("FAX_FIELD_WEBHOOK", None)
        server._run_once = lambda data: {"success": False, "karte_url": "", "error_type": "timeout"}
        out = ORIG_WRITE_KARTE(self.live("FAX-261029090000-5"))
        self.assertFalse(out["success"])

    # --- v3.4.0 新規が開けなかった（入力途中のカルテ）・カルテ番号なしは失敗 ---
    def test_b1_blocked_is_failure_and_tells_field_and_dx(self):
        self.field_setup()
        def run(data):
            server._TLS.karte_opened = True
            server._TLS.blocked = "in_progress_karte"
            return {"success": True, "karte_url": "", "error_type": "step:電話再診を選択", "failed_steps": ["電話再診を選択"]}
        server._run_once = run
        out = ORIG_WRITE_KARTE(self.live("FAX-261102113620-9"))
        self.assertEqual((out["success"], out["error_type"]), (False, "blocked:in_progress_karte"))
        self.assertEqual(len(self.field.calls), 1)
        self.assertIn("入力途中のカルテ", self.field.calls[0]["text"])
        self.assertEqual(len(self.dx.calls), 1)                       # 「空のカルテの疑い」ではなく止めた理由だけ
        self.assertIn("何も書かずに止めました", self.dx.calls[0]["text"])
        self.assertEqual(self.verify_calls, [])                      # 読み直しもしない

    def test_b2_fax_without_karte_id_is_failure(self):
        # 11/2 11:36: 成功扱いでカルテ番号なし → 現場に知らせが出なかった
        self.field_setup()
        server._run_once = lambda data: {"success": True, "karte_url": "", "error_type": ""}
        out = ORIG_WRITE_KARTE(self.live("FAX-261102113620-8"))
        self.assertEqual((out["success"], out["error_type"]), (False, "no_karte_id"))
        self.assertEqual(len(self.field.calls), 1)
        self.assertIn("カルテ番号が取れませんでした", self.field.calls[0]["text"])

    def test_b3_xray_without_karte_id_unchanged(self):
        # レントゲンは今までどおり（成功のまま・ナビが患者ページで出す）
        server._run_once = lambda data: {"success": True, "karte_url": "", "error_type": ""}
        out = ORIG_WRITE_KARTE(self.body(oid="GCP-T-B3"))
        self.assertTrue(out["success"])

    def test_b4_click_hook_detects_alert_and_skips_steps(self):
        accepted = []
        class FakeAlert:
            text = "入力途中のカルテが存在します"
            def accept(self): accepted.append(1)
        class FakeDriver:
            class switch_to:
                alert = FakeAlert()
            def execute_script(self, *a): pass
        fake = types.SimpleNamespace(driver=FakeDriver())
        server._reset_opened()
        self.assertFalse(server._click_cloud(fake, "#karteNew"))
        self.assertEqual((server._blocked(), accepted), ("in_progress_karte", [1]))
        self.assertFalse(server._opened())                           # 指摘5: 新規は開いていない
        called = []
        orig = server._orig_execute
        server._orig_execute = lambda *a: called.append(a) or True
        try:
            self.assertFalse(server._execute_cloud(fake, {"name": "S欄に入力"}, {}))   # S・O も完了も押さない
            self.assertEqual(called, [])
            server._reset_opened()
            self.assertTrue(server._execute_cloud(fake, {"name": "S欄に入力"}, {}))    # 止めていなければ今までどおり
            self.assertEqual(len(called), 1)
        finally:
            server._orig_execute = orig
            server._reset_opened()

    def test_b5_click_hook_no_alert_keeps_going(self):
        class NoAlert:
            @property
            def alert(self): raise RuntimeError("no alert")
        fake = types.SimpleNamespace(driver=types.SimpleNamespace(switch_to=NoAlert(), execute_script=lambda *a: None))
        server.BLOCK_ALERT_WAIT_SEC, keep = 0.3, server.BLOCK_ALERT_WAIT_SEC
        try:
            server._reset_opened()
            server._click_cloud(fake, "#karteNew")
            self.assertEqual(server._blocked(), "")
            self.assertTrue(server._opened())
        finally:
            server.BLOCK_ALERT_WAIT_SEC = keep

    def test_b6_other_alert_also_blocks(self):
        # 黒ヤギ 11/2 指摘4: 知らない文の知らせでも、新規が開いていないので止める
        class OtherAlert:
            text = "セッションが切れました"
            def accept(self): pass
        fake = types.SimpleNamespace(driver=types.SimpleNamespace(switch_to=types.SimpleNamespace(alert=OtherAlert())))
        server._reset_opened()
        self.assertFalse(server._click_cloud(fake, "#karteNew"))
        self.assertEqual(server._blocked(), "unexpected_alert")
        self.assertFalse(server._opened())
        server._reset_opened()

    def test_b7_new_form_seen_returns_early(self):
        # 指摘3: 完了ボタンが見えたら 2 秒待たずに進む
        class NoAlert:
            @property
            def alert(self): raise RuntimeError("no alert")
        seen = []
        def find(by, sel):
            seen.append(sel)
            return [types.SimpleNamespace(is_displayed=lambda: True)]
        fake = types.SimpleNamespace(driver=types.SimpleNamespace(switch_to=NoAlert(), find_elements=find, execute_script=lambda *a: None))
        server.BLOCK_ALERT_WAIT_SEC, keep = 5.0, server.BLOCK_ALERT_WAIT_SEC
        try:
            server._reset_opened()
            t0 = time.time()
            server._click_cloud(fake, "#karteNew")
            self.assertLess(time.time() - t0, 1.0)
            self.assertEqual(seen[0], server.NEW_FORM_SELECTOR)
            self.assertEqual(server._blocked(), "")
            self.assertTrue(server._opened())
        finally:
            server.BLOCK_ALERT_WAIT_SEC = keep
            server._reset_opened()

    def test_b8_blocked_dx_text_per_template(self):
        # 指摘1・2: FAX は Tukusi への送り直し（新しい札）、レントゲンは送り元から送り直すか手で（fax_requeue は書かない）
        def run(data):
            server._TLS.blocked = "in_progress_karte"
            return {"success": True, "karte_url": "", "error_type": ""}
        server._run_once = run
        self.field_setup()
        ORIG_WRITE_KARTE(self.live("FAX-261102113620-7"))
        self.assertIn("tukusi_resend", self.dx.calls[-1]["text"])
        self.assertIn("fax_requeue.py は使えません", self.dx.calls[-1]["text"])
        ORIG_WRITE_KARTE(self.body(oid="GCP-T-B8"))
        self.assertNotIn("fax_requeue", self.dx.calls[-1]["text"])
        self.assertIn("送り直す", self.dx.calls[-1]["text"])

    # --- v3.5.0 FAX は S（発信元）が空でも受ける・O が空なら断る ---
    def test_s30_fax_empty_s_is_accepted(self):
        self.next_result = {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=1"}
        st, _ = post(self.base + "/write", {"orderId": "FAX-T-S30", "homisId": "2277808", "template": "fax_so", "sContent": "", "oContent": "本文"})
        self.assertEqual(st, 200)
        st, body = post(self.base + "/write", {"orderId": "FAX-T-S30b", "homisId": "2277808", "template": "fax_so", "sContent": "送り元", "oContent": ""})
        self.assertEqual((st, body.get("error")), (400, "missing_so"))

    def test_s31_fax_empty_s_becomes_half_space(self):
        # S が空だと HOMIS が完了で保存しない → 半角スペース1つにして書く（読み直しにも同じ値を渡す）
        seen = []
        def run(data):
            seen.append(data.get("sContent"))
            return {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=5", "error_type": ""}
        server._run_once = run
        for s in ("", None, "  "):
            ORIG_WRITE_KARTE(self.body(oid="FAX-MIRROR-S31", template="fax_so", sContent=s, oContent="本文"))
        self.assertEqual(seen, [" ", " ", " "])
        self.assertEqual(self.verify_calls[-1][2], " ")
        seen.clear()
        ORIG_WRITE_KARTE(self.body(oid="FAX-MIRROR-S31b", template="fax_so", sContent="送り元", oContent="本文"))
        self.assertEqual(seen, ["送り元"])                                    # 中身があれば変えない

    # --- v3.5.0 問い合わせ（bot_s_interrupt） ---
    def bot_field_setup(self):
        self.bot_field = FakeNavi()
        os.environ["BOT_FIELD_WEBHOOK"] = self.bot_field.url
        self.addCleanup(lambda: (self.bot_field.close(), os.environ.pop("BOT_FIELD_WEBHOOK", None)))

    def bot(self, oid):
        return self.body(oid=oid, template="bot_s_interrupt", sContent="問い合わせ着信")

    def test_k1_bot_verified_as_interrupt(self):
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=77", "error_type": ""}
        self.verify_result = dict(self.verify_result, status="2")
        out = ORIG_WRITE_KARTE(self.bot("BOT-123-20261102160000"))
        self.assertTrue(out["success"])
        self.assertEqual(self.verify_calls[0], ("2277808", "77", "問い合わせ着信", "", ("expect", "interrupt")))

    def test_k2_bot_not_mine_fails_and_tells_bot_space(self):
        self.field_setup(); self.bot_field_setup()
        server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=78", "error_type": ""}
        self.verify_result = dict(self.verify_result, verdict="not_mine", status="2")
        out = ORIG_WRITE_KARTE(self.bot("BOT-123-20261102160001"))
        self.assertEqual((out["success"], out["error_type"]), (False, "verify:not_mine"))
        self.assertEqual(self.field.calls, [])                               # FAX のスペースには出さない
        self.assertEqual(len(self.bot_field.calls), 1)
        t = self.bot_field.calls[0]["text"]
        self.assertIn("問い合わせ（OhisamaBot）のカルテを書けませんでした", t)
        self.assertNotIn("FAX", t)

    def test_k3_bot_without_karte_id_is_failure(self):
        self.bot_field_setup()
        server._run_once = lambda data: {"success": True, "karte_url": "", "error_type": ""}
        out = ORIG_WRITE_KARTE(self.bot("BOT-123-20261102160002"))
        self.assertEqual((out["success"], out["error_type"]), (False, "no_karte_id"))
        self.assertEqual(len(self.bot_field.calls), 1)

    def test_k4_bot_test_order_is_quiet(self):
        self.bot_field_setup()
        server._run_once = lambda data: {"success": False, "karte_url": "", "error_type": "timeout"}
        ORIG_WRITE_KARTE(self.bot("BOT-TEST-123-20261102160003"))
        self.assertEqual(self.bot_field.calls, [])

    # --- v3.6.0 stop_on_fail の手順が失敗したら保存しない・1回だけやり直す ---
    def test_k6_stop_on_fail_skips_rest(self):
        fake = types.SimpleNamespace()
        orig = server._orig_execute
        called = []
        server._orig_execute = lambda s, a, d: called.append(a["name"]) or a.get("ok", False)
        try:
            server._reset_opened()
            self.assertFalse(server._execute_cloud(fake, {"name": "O欄", "ok": False}, {}))   # 印なしの失敗は止めない
            self.assertEqual(server._stopped(), "")
            self.assertFalse(server._execute_cloud(fake, {"name": "S欄に入力", "stop_on_fail": True}, {}))
            self.assertEqual(server._stopped(), "S欄に入力")
            self.assertFalse(server._execute_cloud(fake, {"name": "中断ボタンで保存", "ok": True}, {}))   # 保存は押さない
            self.assertEqual(called, ["O欄", "S欄に入力"])
            server._reset_opened()
            self.assertEqual(server._stopped(), "")                                           # 次の回には持ち越さない
            self.assertTrue(server._execute_cloud(fake, {"name": "S欄に入力", "stop_on_fail": True, "ok": True}, {}))
            self.assertEqual(server._stopped(), "")
        finally:
            server._orig_execute = orig
            server._reset_opened()

    def test_k7_stopped_once_then_ok(self):
        runs = []
        def run(data):
            runs.append(1)
            server._TLS.karte_opened = True
            if len(runs) == 1:
                server._TLS.stopped = "S欄に入力"
                return {"success": True, "karte_url": "", "error_type": "step:S欄に入力"}
            return {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=70", "error_type": ""}
        server._run_once = run
        self.verify_result = dict(self.verify_result, status="2")
        out = ORIG_WRITE_KARTE(self.bot("BOT-123-20261104140000"))
        self.assertEqual((out["success"], out["retried"], out["karte_id"], len(runs)), (True, "S欄に入力", "70", 2))
        self.assertEqual(self.dx.calls, [])

    def test_k8_stopped_twice_is_failure(self):
        self.bot_field_setup()
        runs = []
        def run(data):
            runs.append(1)
            server._TLS.karte_opened = True
            server._TLS.stopped = "S欄をもう一度確かめる"
            return {"success": True, "karte_url": "", "error_type": "step:S欄をもう一度確かめる"}
        server._run_once = run
        out = ORIG_WRITE_KARTE(self.bot("BOT-123-20261104140001"))
        self.assertEqual((out["success"], out["error_type"], len(runs)), (False, "stopped:unverified_input", 2))
        self.assertEqual(self.verify_calls, [])
        self.assertEqual(len(self.dx.calls), 1)
        self.assertIn("保存せずに止めました", self.dx.calls[0]["text"])
        self.assertIn("問い合わせの画面の内容から", self.dx.calls[0]["text"])
        self.assertEqual(len(self.bot_field.calls), 1)
        self.assertIn("S を入れたことを確かめられず", self.bot_field.calls[0]["text"])

    def test_k9_stopped_then_blocked_mentions_leftover(self):
        runs = []
        def run(data):
            runs.append(1)
            if len(runs) == 1:
                server._TLS.karte_opened = True
                server._TLS.stopped = "S欄に入力"
            else:
                server._TLS.blocked = "in_progress_karte"
            return {"success": True, "karte_url": "", "error_type": ""}
        server._run_once = run
        out = ORIG_WRITE_KARTE(self.bot("BOT-123-20261104140002"))
        self.assertEqual(out["error_type"], "blocked:in_progress_karte")
        self.assertIn("書きかけ（編集中）が1枚残っています", self.dx.calls[-1]["text"])

    def test_k10_fax_failure_does_not_retry(self):
        # 印の無い型紙（FAX）は今までどおり1回だけ
        runs = []
        def run(data):
            runs.append(1)
            server._TLS.karte_opened = True
            return {"success": True, "karte_url": "", "error_type": "step:S欄に入力"}
        server._run_once = run
        out = ORIG_WRITE_KARTE(self.body(oid="FAX-MIRROR-K10", template="fax_so", sContent="s", oContent="o"))
        self.assertEqual((len(runs), out["retried"]), (1, ""))

    # --- v3.7.0 前の書きかけの守り（判定） ---
    def test_g1_judge_reused(self):
        from datetime import datetime as D
        server._LEFT_KIDS.clear()
        server._start_order()
        pressed = D(2026, 11, 4, 16, 0, 20)
        f = lambda kid, date, hm: {"karte_id": kid, "act_date": date, "start_time": hm}
        J = server._judge_reused
        self.assertEqual(J(f("1", "2026-11-04", "16:00"), pressed), "ok")       # 今作った
        self.assertEqual(J(f("1", "2026-11-04", "15:59"), pressed), "ok")       # 秒の切り捨て・時計のずれ（1分20秒）
        self.assertEqual(J(f("1", "2026-11-04", "15:58"), pressed), "reused")   # 2分20秒前
        self.assertEqual(J(f("1", "2026-11-04", "15:44"), pressed), "reused")
        self.assertEqual(J(f("1", "2026-11-03", "16:00"), pressed), "reused")   # 前の日
        # 0時またぎ（日付だけで比べない）
        self.assertEqual(J(f("1", "2026-11-05", "00:00"), D(2026, 11, 5, 0, 0, 10)), "ok")
        self.assertEqual(J(f("1", "2026-11-04", "23:59"), D(2026, 11, 5, 0, 0, 10)), "ok")
        self.assertEqual(J(f("1", "2026-11-04", "23:57"), D(2026, 11, 5, 0, 0, 10)), "reused")
        # 読めない
        self.assertEqual(J(f(None, "2026-11-04", "16:00"), pressed), "unreadable")
        self.assertEqual(J(f("1", None, None), pressed), "unreadable")
        self.assertEqual(J(f("1", "2026-11-04", "16:00"), None), "unreadable")
        # 覚えた番号は時刻に関係なく止める・同じ注文の1回目の番号は止めない
        server.remember_left("77")
        self.assertEqual(J(f("77", "2026-11-04", "16:00"), pressed), "reused")
        server._TLS.order_first_kid = "77"
        self.assertEqual(J(f("77", "2026-11-04", "15:00"), pressed), "ok")
        server._start_order(); server._LEFT_KIDS.clear()

    def test_g2_left_kids_capped(self):
        server._LEFT_KIDS.clear()
        for i in range(server.LEFT_KIDS_MAX + 5):
            server.remember_left(str(i))
        self.assertEqual(len(server._LEFT_KIDS), server.LEFT_KIDS_MAX)
        self.assertFalse(server._is_left("0"))
        self.assertTrue(server._is_left(str(server.LEFT_KIDS_MAX + 4)))
        server.remember_left("")
        self.assertFalse(server._is_left(""))
        server._LEFT_KIDS.clear()

    def test_g3_guard_runs_once_before_first_input(self):
        # 新規のあと最初の js_input の前に1回だけ。click では見ない。古ければ以後の手順を飛ばす
        from datetime import datetime as D
        reads = []
        class Drv:
            def execute_script(self, js, *a):
                reads.append(1)
                return {"karte_id": "9", "act_date": "2026-11-04", "start_time": "15:00"}
        fake = types.SimpleNamespace(driver=Drv())
        orig = server._orig_execute
        called = []
        server._orig_execute = lambda s, a, d: called.append(a["name"]) or True
        try:
            server._start_order(); server._reset_opened()
            server._TLS.karte_opened = True
            server._TLS.new_pressed_at = D(2026, 11, 4, 16, 0, 0)
            self.assertTrue(server._execute_cloud(fake, {"name": "医科カルテ", "action": "click"}, {}))
            self.assertEqual(reads, [])
            self.assertFalse(server._execute_cloud(fake, {"name": "S欄に入力", "action": "js_input"}, {}))
            self.assertEqual((server._blocked(), len(reads)), ("reused_editing", 1))
            self.assertFalse(server._execute_cloud(fake, {"name": "中断ボタンで保存", "action": "click"}, {}))
            self.assertEqual(called, ["医科カルテ"])
            # 新しいカルテなら通す・2回目の入力では読まない
            reads.clear(); called.clear(); server._reset_opened()
            server._TLS.karte_opened = True
            server._TLS.new_pressed_at = D(2026, 11, 4, 15, 0, 30)
            self.assertTrue(server._execute_cloud(fake, {"name": "S", "action": "js_input"}, {}))
            self.assertTrue(server._execute_cloud(fake, {"name": "O", "action": "js_input"}, {}))
            self.assertEqual((len(reads), called, server._TLS.order_first_kid), (1, ["S", "O"], "9"))
            # 新規を開いていなければ読まない
            reads.clear(); server._reset_opened()
            self.assertTrue(server._execute_cloud(fake, {"name": "S", "action": "js_input"}, {}))
            self.assertEqual(reads, [])
        finally:
            server._orig_execute = orig
            server._reset_opened(); server._start_order()

    def test_g4_retry_failing_before_new_still_remembers_first(self):
        # 黒ヤギ実装1回目 指摘1: 1回目に開いて止めた番号は、2回目が新規の前で失敗しても覚える
        server._LEFT_KIDS.clear()
        runs = []
        def run(data):
            runs.append(1)
            if len(runs) == 1:
                server._TLS.karte_opened = True
                server._note_kid("55")
                server._TLS.stopped = "S欄に入力"
                return {"success": True, "karte_url": "", "error_type": ""}
            return {"success": False, "karte_url": "", "error_type": "timeout"}   # 新規の前で失敗
        server._run_once = run
        out = ORIG_WRITE_KARTE(self.bot("BOT-TEST-123-20261104170000"))
        self.assertFalse(out["success"])
        self.assertTrue(server._is_left("55"))
        # 書けたカルテは覚えない（やり直しで同じ番号に書けた）
        server._LEFT_KIDS.clear(); runs.clear()
        def run2(data):
            runs.append(1)
            server._TLS.karte_opened = True
            server._note_kid("56")
            if len(runs) == 1:
                server._TLS.stopped = "S欄に入力"
                return {"success": True, "karte_url": "", "error_type": ""}
            return {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=56", "error_type": ""}
        server._run_once = run2
        self.verify_result = dict(self.verify_result, status="2")
        self.assertTrue(ORIG_WRITE_KARTE(self.bot("BOT-TEST-123-20261104170001"))["success"])
        self.assertFalse(server._is_left("56"))
        server._LEFT_KIDS.clear()

    def test_g5_unreadable_time_still_keeps_first_kid(self):
        # 黒ヤギ実装1回目 指摘2: 番号が読めて時刻が読めないとき、その番号を1回目の番号として控える
        class Drv:
            def execute_script(self, js, *a):
                return {"karte_id": "88", "act_date": "", "start_time": ""}
        server._start_order(); server._reset_opened()
        keep = server.EDIT_FIELDS_WAIT_SEC
        server.EDIT_FIELDS_WAIT_SEC = 0.2
        try:
            self.assertEqual(server._guard_editing(Drv()), "")
        finally:
            server.EDIT_FIELDS_WAIT_SEC = keep
        self.assertEqual((server._TLS.order_first_kid, server._TLS.guard_unreadable, server._TLS.order_kids), ("88", True, ["88"]))
        server._start_order(); server._reset_opened()

    def test_g6_guard_also_before_input_but_not_select(self):
        # 黒ヤギ実装1回目 指摘3: 「input」の手順の前でも見る（レントゲンの開始時間）。select（指示医）では見ない
        from datetime import datetime as D
        reads = []
        class Drv:
            def execute_script(self, js, *a):
                reads.append(1)
                return {"karte_id": "9", "act_date": "2026-11-04", "start_time": "16:00"}
        fake = types.SimpleNamespace(driver=Drv())
        orig = server._orig_execute
        server._orig_execute = lambda s, a, d: True
        try:
            server._start_order(); server._reset_opened()
            server._TLS.karte_opened = True
            server._TLS.new_pressed_at = D(2026, 11, 4, 16, 0, 30)
            server._execute_cloud(fake, {"name": "指示医を選択", "action": "select"}, {})
            self.assertEqual(reads, [])
            server._execute_cloud(fake, {"name": "開始時間を入力", "action": "input"}, {})
            self.assertEqual(len(reads), 1)
        finally:
            server._orig_execute = orig
            server._start_order(); server._reset_opened()

    def test_k5_bot_blocked_dx_text(self):
        self.bot_field_setup()
        def run(data):
            server._TLS.blocked = "in_progress_karte"
            return {"success": True, "karte_url": "", "error_type": ""}
        server._run_once = run
        ORIG_WRITE_KARTE(self.bot("BOT-123-20261102160004"))
        t = self.dx.calls[-1]["text"]
        self.assertIn("問い合わせの画面の内容から", t)
        self.assertNotIn("tukusi_resend", t)
        self.assertEqual(len(self.bot_field.calls), 1)

    def test_i1_http_write_with_real_verify_against_fake_homis(self):
        # 結合: 受け口の HTTP（/write）→ 本物の write_karte → 本物の verify_karte → 偽の HOMIS（編集中のまま）→ 500・DX 1件
        import verify_karte as real_verify
        from test_verify_karte import FakeHomis, karte
        homis = FakeHomis()
        try:
            real_verify.BASE = homis.url
            real_verify.WAIT_SEC = 0
            os.environ["HOMIS_USER"], os.environ["HOMIS_PASSWORD"] = "u", "p"
            homis.karte_script = [karte(status="1", s="", o="")]
            server.verify_karte = real_verify
            server.write_karte = ORIG_WRITE_KARTE
            server._run_once = lambda data: {"success": True, "karte_url": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=91"}
            code, out = post(self.base + "/write", self.fax("GCP-T-I1"))
            self.assertEqual((code, out["verify"], out["error_type"]), (500, "not_completed", "verify:not_completed"))
            self.assertEqual(homis.reads, 2)
            self.assertFalse(homis.edit_opened)
            self.assertEqual(len(self.dx.calls), 1)
            # 同じ道で、完了・一致なら 200 で DX は黙る
            homis.karte_script = [karte(s="送り元", o="本文")]
            homis.reads = 0
            code, out = post(self.base + "/write", self.fax("GCP-T-I2"))
            self.assertEqual((code, out["verify"]), (200, "ok"))
            self.assertEqual(len(self.dx.calls), 1)
        finally:
            homis.close()
            os.environ.pop("HOMIS_USER", None); os.environ.pop("HOMIS_PASSWORD", None)

    def test_s10_write_still_needs_key(self):
        code, _ = post(self.base + "/write", self.body(), key="wrong-k")
        self.assertEqual(code, 401)
        self.assertEqual(self.navi.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
