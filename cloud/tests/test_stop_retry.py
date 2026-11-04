# -*- coding: utf-8 -*-
"""cloud/server.py v3.6.0 と bot_s_interrupt.yaml 1.2 の結合テスト（S を確かめられなければ保存しない・1回やり直す）

DX担当「問い合わせで S 欄が空はあかん」（11/4 0017）。
本物の server.write_karte → 本物の TemplateEngine → 本物の BrowserActions（本物の Chrome・headless）で、
本物の型紙 bot_s_interrupt.yaml の手順を通す。HOMIS の代わりに手元の偽サーバーを立てる:
  - 新規: 書きかけ（編集中）が残っていれば同じカルテ番号を返す（ライター自身の編集中は同じアカウントの新規で戻る・11/2 5b）
  - 医科カルテ: 回ごとに「欄が出ない」か「○ミリ秒後に出る」
  - 中断: 保存した中身（種別・S）を覚える
HOMIS・共有ドライブ・本物の Chat には触らない（shared_log は偽物・読み直しは偽サーバーの保存を見る偽物）。

使い方: py -3.12 -X utf8 cloud/tests/test_stop_retry.py
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD = os.path.dirname(HERE)
SRC = os.path.join(os.path.dirname(CLOUD), "src")
sys.path.insert(0, CLOUD)
sys.path.insert(0, SRC)

# 共有ドライブのログに書かない（timed_step・log_result だけの偽物）
sl = types.ModuleType("shared_log")


@contextlib.contextmanager
def _timed_step(name):
    yield types.SimpleNamespace(ok=False)


sl.timed_step = _timed_step
sl.extract_karte_id = lambda url: (url.split("karte_id=", 1)[1].split("&", 1)[0] if "karte_id=" in (url or "") else "")
sl.infer_error_type = lambda r: r.get("error_type") or ""
sl.log_result = lambda *a, **k: None
sys.modules["shared_log"] = sl

from selenium import webdriver  # noqa: E402
from selenium.webdriver.chrome.options import Options  # noqa: E402

import server  # noqa: E402
import template_engine  # noqa: E402
from browser_actions import BrowserActions  # noqa: E402

PAGE = """<!doctype html><meta charset="utf-8"><body>
<div style="display:none"><textarea id="subjective" data-old="1"></textarea></div>
<a id="karteNew" href="#" onclick="newKarte();return false;">新規</a>
<div id="kind" style="display:none">
  <label><input type="radio" name="kind" value="teiki" checked> 定期</label>
  <label><input type="radio" name="kind" value="denwa"> 電話再診</label>
  <a href="#" onclick="openLater();return false;">医科カルテ</a>
</div>
<div id="form"></div>
<a href="#" onclick="copyLinkOfKarte('none');return false;">リンク</a>
<script>
var KID = null;
function copyLinkOfKarte(u) {}
function call(path, body) {
  var x = new XMLHttpRequest(); x.open('POST', path, false);
  x.send(JSON.stringify(body || {})); return JSON.parse(x.responseText);
}
function newKarte() { KID = call('/new').karte_id; document.getElementById('kind').style.display = 'block'; }
function openLater() {
  var m = call('/mode').mode;
  if (m === 'hidden') openForm(true); else if (m !== 'never') setTimeout(openForm, Number(m));
}
// hidden: 中断ボタンは出るのに S 欄だけ見えない（0017 と同じく、そのまま押すと S が空で保存される）
function openForm(hideS) {
  document.getElementById('form').innerHTML =
    '<textarea id="subjective"' + (hideS ? ' style="display:none"' : '') + '></textarea><textarea id="objective"></textarea>' +
    '<textarea id="ap"></textarea><textarea id="ap_today"></textarea><textarea id="report"></textarea>' +
    '<a id="karteInterruption" href="#">中断</a>';
  document.getElementById('karteInterruption').onclick = function () {
    if (confirm('保存しますか') && confirm('中断しますか')) {
      call('/save', {karte_id: KID, kind: document.querySelector('input[name=kind]:checked').value,
                     s: document.querySelector('#form #subjective').value});
      location.hash = 'karte_id=' + KID;
    }
    return false;
  };
}
</script>
"""


class FakeHomis:
    """偽の HOMIS・DX Chat・現場 Chat をひとつのサーバーで"""

    def __init__(self):
        self.reset()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj):
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                data = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                path = self.path.split("?")[0]
                with outer.lock:
                    if path == "/new":
                        if outer.editing is None:
                            outer.next_id += 1
                            outer.editing = outer.next_id
                            outer.news.append((outer.editing, False))
                        else:
                            outer.news.append((outer.editing, True))   # 書きかけが戻る
                        self._json({"karte_id": outer.editing})
                    elif path == "/mode":
                        self._json({"mode": outer.modes.pop(0) if outer.modes else "500"})
                    elif path == "/save":
                        outer.saves.append(body)
                        outer.editing = None
                        self._json({"ok": True})
                    elif path in ("/dx", "/field"):
                        (outer.dx if path == "/dx" else outer.field).append(body.get("text", ""))
                        self._json({"success": True})
                    else:
                        self._json({})

        self.lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def reset(self):
        self.editing, self.next_id = None, 1000
        self.modes, self.news, self.saves, self.dx, self.field = [], [], [], [], []


def _local_driver(self):
    """Cloud Run の Chrome の代わりに手元の headless Chrome"""
    if self.driver:
        return
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--window-size=1000,800")
    self.driver = webdriver.Chrome(options=o)
    self.actions = BrowserActions(self.driver)


TEXT = "【試験】問い合わせの S\r\n二行目"
WANT = TEXT.replace("\r\n", "\n")


class StopRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.homis = FakeHomis()
        with open(os.path.join(SRC, "templates", "bot_s_interrupt.yaml"), encoding="utf-8") as f:
            tpl = yaml.safe_load(f)
        cls.tpl = tpl
        # 型紙は本物のまま。開く先だけ偽の HOMIS にする
        tpl = dict(tpl, target_url=cls.homis.base + "/patient?patient_id={homisId}")
        cls.tmp = tempfile.mkdtemp()
        with open(os.path.join(cls.tmp, "bot_s_interrupt.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(tpl, f, allow_unicode=True)
        template_engine.TEMPLATES_DIR = __import__("pathlib").Path(cls.tmp)
        server._init_driver_cloud = _local_driver
        server.verify_karte = types.SimpleNamespace(verify=cls.fake_verify)
        os.environ.update({"HOMIS_USER": "u", "HOMIS_PASSWORD": "p",
                           "DX_ALERT_WEBHOOK": cls.homis.base + "/dx", "BOT_FIELD_WEBHOOK": cls.homis.base + "/field"})
        os.environ.pop("RESULT_SPREADSHEET_ID", None)

    @classmethod
    def tearDownClass(cls):
        cls.homis.httpd.shutdown()

    @classmethod
    def fake_verify(cls, homis_id, kid, s, o, expect="done"):
        """読み直しの偽物: 偽 HOMIS に保存された中身を見る"""
        got = [x for x in cls.homis.saves if str(x.get("karte_id")) == str(kid)]
        ok = bool(got) and got[-1]["s"] == s.replace("\r\n", "\n")
        return {"verdict": "ok" if ok else "s_mismatch", "status": "2", "status_label": "中断",
                "reads": 1, "s_len": len(got[-1]["s"]) if got else 0, "o_len": 0, "reason": ""}

    def setUp(self):
        self.homis.reset()

    def write(self, oid):
        return server.write_karte({"orderId": oid, "homisId": "2277808", "template": "bot_s_interrupt", "sContent": TEXT})

    def test_t0_template_flags(self):
        steps = {s["name"]: s for s in self.tpl["steps"]}
        self.assertEqual(self.tpl["version"], "1.2")
        self.assertTrue(steps["S欄に入力"].get("stop_on_fail"))
        self.assertTrue(steps["S欄をもう一度確かめる"].get("stop_on_fail"))
        # S 以外の手順には付けない（失敗しても今までどおり進む）
        self.assertEqual([n for n, s in steps.items() if s.get("stop_on_fail")], ["S欄に入力", "S欄をもう一度確かめる"])

    def test_i1_normal_once(self):
        self.homis.modes = ["500"]
        out = self.write("BOT-1-20261104140000")
        self.assertEqual((out["success"], out["retried"], out["error_type"]), (True, "", ""))
        self.assertEqual(len(self.homis.news), 1)
        self.assertEqual([(x["kind"], x["s"]) for x in self.homis.saves], [("denwa", WANT)])

    def test_i2_stop_then_retry_saves_same_karte(self):
        # 1回目: S の欄が出ない → 保存しない。2回目: 新規で同じカルテが戻り、S を入れて中断で保存
        self.homis.modes = ["never", "500"]
        out = self.write("BOT-1-20261104140001")
        self.assertTrue(out["success"])
        self.assertEqual(out["retried"], "S欄に入力")
        self.assertEqual(self.homis.news, [(1001, False), (1001, True)])
        self.assertEqual([(x["karte_id"], x["kind"], x["s"]) for x in self.homis.saves], [(1001, "denwa", WANT)])
        self.assertEqual(out["karte_id"], "1001")
        self.assertIsNone(self.homis.editing)                       # 書きかけは残っていない
        self.assertEqual(self.homis.field, [])

    def test_i3_twice_stopped_never_saves(self):
        # 2回とも S の欄が出ない → 一度も保存しない（空の S のカルテを作らない）・失敗・DX と現場に知らせる
        self.homis.modes = ["never", "never"]
        out = self.write("BOT-1-20261104140002")
        self.assertEqual((out["success"], out["error_type"], out["karte_id"]), (False, "stopped:unverified_input", ""))
        self.assertEqual(self.homis.saves, [])
        self.assertEqual(self.homis.editing, 1001)                  # 書きかけ1枚（2回目も同じカルテ）
        self.assertEqual(len(self.homis.dx), 1)
        self.assertIn("保存せずに止めました", self.homis.dx[0])
        self.assertIn("編集中", self.homis.dx[0])
        self.assertNotIn("空で作成した可能性", self.homis.dx[0])
        self.assertEqual(len(self.homis.field), 1)
        self.assertIn("S を入れたことを確かめられず", self.homis.field[0])

    def test_i5_hidden_s_with_save_button_never_saves_empty(self):
        # 0017 の形: 中断ボタンはあるのに S が入らない → 直す前は S 空のまま中断で保存していた。今は一度も保存しない
        self.homis.modes = ["hidden", "hidden"]
        out = self.write("BOT-1-20261104140004")
        self.assertFalse(out["success"])
        self.assertEqual(self.homis.saves, [])

    def test_i4_test_order_is_quiet_for_field(self):
        # 試し書き（BOT-TEST-…）は現場に知らせない。保存しないのは同じ
        self.homis.modes = ["never", "never"]
        out = self.write("BOT-TEST-1-20261104140003")
        self.assertFalse(out["success"])
        self.assertEqual(self.homis.saves, [])
        self.assertEqual(self.homis.field, [])
        self.assertEqual(len(self.homis.dx), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
