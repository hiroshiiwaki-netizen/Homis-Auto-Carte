# -*- coding: utf-8 -*-
"""cloud/server.py v3.6.0〜v3.8.0 と bot_s_interrupt.yaml 1.2 の結合テスト（S を確かめられなければ保存しない・1回やり直す）

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
import datetime
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
var ACT = '', ST = '';
function newKarte() { var r = call('/new'); if (r.alert) { alert(r.alert); return; } KID = r.karte_id; ACT = r.act_date; ST = r.start_time;
  document.getElementById('kind').style.display = 'block'; }
function openLater() {
  var m = call('/mode').mode;
  document.getElementById('form').innerHTML = '<div id="pdetail_karteedit"><input type="hidden" id="karte_id" value="' + KID +
    '"><input type="date" id="act_date" value="' + ACT + '"><input type="text" id="start_time" value="' + ST +
    '"><div id="inner"></div></div>';
  if (m === 'noguard') document.getElementById('pdetail_karteedit').innerHTML = '<div id="inner"></div>';
  if (m === 'noguard') m = '500';
  if (m === 'hidden') openForm(true); else if (m.indexOf('never') !== 0) setTimeout(openForm, Number(m));
}
// hidden: 中断ボタンは出るのに S 欄だけ見えない（0017 と同じく、そのまま押すと S が空で保存される）
function openForm(hideS) {
  document.getElementById('inner').innerHTML =
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
                    if path == "/new" and outer.alerts:
                        outer.news.append(("alert", False))   # v3.8.0: 新規が開かず知らせだけ出る（何も作らない）
                        self._json({"alert": outer.alerts.pop(0)})
                    elif path == "/new":
                        if outer.editing is None:
                            outer.next_id += 1
                            outer.editing = outer.next_id
                            outer.created[outer.editing] = outer.clock()
                            outer.news.append((outer.editing, False))
                        else:
                            outer.news.append((outer.editing, True))   # 書きかけが戻る（作った時刻のまま）
                        c = outer.created[outer.editing]
                        self._json({"karte_id": outer.editing, "act_date": c.strftime("%Y-%m-%d"),
                                    "start_time": c.strftime("%H:%M")})
                    elif path == "/mode":
                        m = outer.modes.pop(0) if outer.modes else "500"
                        if m == "never_old" and outer.editing is not None:
                            outer.created[outer.editing] -= datetime.timedelta(minutes=5)
                        self._json({"mode": m})
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
        self.editing, self.next_id, self.created = None, 1000, {}
        self.clock = datetime.datetime.now   # 手元の PC は日本時間
        self.modes, self.news, self.saves, self.dx, self.field = [], [], [], [], []
        self.alerts = []


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
        getattr(server, "_LEFT_KIDS", {}).clear()   # v3.7.0: 覚えた番号はテストごとに空から（直す前の版でも流せるように）
        self._keep_wait = getattr(server, "BLOCKED_RETRY_WAIT_SEC", None)
        if self._keep_wait is not None:
            server.BLOCKED_RETRY_WAIT_SEC = 0.5   # v3.8.0: テストでは 90 秒も待たない

    def tearDown(self):
        if self._keep_wait is not None:
            server.BLOCKED_RETRY_WAIT_SEC = self._keep_wait

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

    # --- v3.7.0 前の書きかけの守り ---
    def test_g1_old_leftover_is_not_written(self):
        # 5分前に残った書きかけが新規で戻る → S を入れる前に止める・保存しない・DX と現場に知らせる
        self.homis.editing, self.homis.next_id = 1001, 1001
        self.homis.created[1001] = datetime.datetime.now() - datetime.timedelta(minutes=5)
        out = self.write("BOT-1-20261104160001")
        self.assertEqual((out["success"], out["error_type"]), (False, "blocked:reused_editing"))
        self.assertEqual(self.homis.news, [(1001, True)])
        self.assertEqual(self.homis.saves, [])
        self.assertEqual(len(self.homis.dx), 1)
        self.assertIn("カルテ 1001", self.homis.dx[0])
        self.assertEqual(len(self.homis.field), 1)
        self.assertIn("書きかけ", self.homis.field[0])

    def test_g2_retry_of_same_order_is_allowed(self):
        # 同じ注文の中のやり直し: 1回目の書きかけ（5分前に作ったことにする）が戻っても止めない
        self.homis.modes = ["never_old", "500"]
        out = self.write("BOT-1-20261104160002")
        self.assertEqual((out["success"], out["retried"]), (True, "S欄に入力"))
        self.assertEqual([(x["karte_id"], x["s"]) for x in self.homis.saves], [(1001, WANT)])

    def test_g3_left_kid_is_blocked_even_if_recent(self):
        # 1件目が2回とも止まり書きかけを残す → すぐ来た2件目（2分以内）は、覚えた番号で止める
        self.homis.modes = ["never", "never"]
        self.assertFalse(self.write("BOT-1-20261104160003")["success"])
        self.homis.dx.clear(); self.homis.field.clear()
        out = self.write("BOT-1-20261104160004")
        self.assertEqual(out["error_type"], "blocked:reused_editing")
        self.assertEqual(self.homis.saves, [])

    def test_g4_midnight_new_karte_is_fine(self):
        # 0時またぎ: 新規を押したのが 0:00:10、カルテは 11/5 0:00 → 新しいカルテとして書く
        self.homis.clock = lambda: datetime.datetime(2026, 11, 5, 0, 0, 0)
        keep = server._now_jst
        server._now_jst = lambda: datetime.datetime(2026, 11, 5, 0, 0, 10)
        try:
            out = self.write("BOT-1-20261104160005")
        finally:
            server._now_jst = keep
        self.assertTrue(out["success"])
        self.assertEqual(len(self.homis.saves), 1)

    def test_g5_unreadable_fields_still_write_and_tell_dx(self):
        # 編集画面の欄が無い（画面が変わった）→ 止めずに書く・DX に「守りの欄が読めず」
        self.homis.modes = ["noguard"]
        keep = server.EDIT_FIELDS_WAIT_SEC
        server.EDIT_FIELDS_WAIT_SEC = 1.0
        try:
            out = self.write("BOT-1-20261104160006")
        finally:
            server.EDIT_FIELDS_WAIT_SEC = keep
        self.assertTrue(out["success"])
        self.assertEqual(len(self.homis.saves), 1)
        self.assertEqual(len(self.homis.dx), 1)
        self.assertIn("守りを飛ばしました", self.homis.dx[0])

    def test_i4_test_order_is_quiet_for_field(self):
        # 試し書き（BOT-TEST-…）は現場に知らせない。保存しないのは同じ
        self.homis.modes = ["never", "never"]
        out = self.write("BOT-TEST-1-20261104140003")
        self.assertFalse(out["success"])
        self.assertEqual(self.homis.saves, [])
        self.assertEqual(self.homis.field, [])
        self.assertEqual(len(self.homis.dx), 1)

    # --- v3.8.0 入力途中のカルテで止められたら、あけて1回だけやり直す ---
    IN_PROGRESS = "入力途中のカルテが存在します"

    def test_b1_blocked_once_then_written(self):
        # 1回目: 新規で「入力途中」→ 何もしない。あけて2回目: 普通に書ける → 成功・現場にも DX にも知らせない
        self.homis.alerts = [self.IN_PROGRESS]
        out = self.write("BOT-1-20261105110001")
        self.assertEqual((out["success"], out["error_type"], out["retried_blocked"]), (True, "", "in_progress_karte"))
        self.assertEqual(self.homis.news, [("alert", False), (1001, False)])
        self.assertEqual([(x["karte_id"], x["s"]) for x in self.homis.saves], [(1001, WANT)])
        self.assertEqual((self.homis.dx, self.homis.field), ([], []))

    def test_b2_blocked_twice_fails_and_tells(self):
        # 2回とも「入力途中」→ 何も書かない・失敗・現場と DX に1回ずつ（DX に「やり直しても同じ」）
        self.homis.alerts = [self.IN_PROGRESS, self.IN_PROGRESS]
        out = self.write("BOT-1-20261105110002")
        self.assertEqual((out["success"], out["error_type"]), (False, "blocked:in_progress_karte"))
        self.assertEqual(self.homis.news, [("alert", False), ("alert", False)])
        self.assertEqual(self.homis.saves, [])
        self.assertEqual(len(self.homis.field), 1)
        self.assertIn("入力途中のカルテ", self.homis.field[0])
        self.assertEqual(len(self.homis.dx), 1)
        self.assertIn("やり直しましたが", self.homis.dx[0])

    def test_b3_other_alert_is_not_retried(self):
        # 別の文の知らせ（unexpected_alert）はやり直さない（今までどおり1回で止める）
        self.homis.alerts = ["ほかの知らせ", self.IN_PROGRESS]
        out = self.write("BOT-1-20261105110003")
        self.assertEqual((out["success"], out["error_type"], out["retried_blocked"]), (False, "blocked:unexpected_alert", ""))
        self.assertEqual(self.homis.news, [("alert", False)])

    def test_b4_no_time_left_no_retry(self):
        # 時間が足りない（上限で切られると知らせが出ない）ときはやり直さず、今までどおり知らせる
        keep = server.REQUEST_BUDGET_SEC
        server.REQUEST_BUDGET_SEC = 10.0
        self.homis.alerts = [self.IN_PROGRESS]
        try:
            out = self.write("BOT-1-20261105110004")
        finally:
            server.REQUEST_BUDGET_SEC = keep
        self.assertEqual((out["success"], out["error_type"], out["retried_blocked"]), (False, "blocked:in_progress_karte", ""))
        self.assertEqual(self.homis.news, [("alert", False)])
        self.assertEqual(len(self.homis.field), 1)

    def test_b5_scope_and_wait(self):
        # やり直すのは FAX と問い合わせだけ（レントゲンは変えない）。本番の待ちは 90 秒・上限の見込みは 300 秒の内側
        self.assertEqual(server.BLOCKED_RETRY_TEMPLATES, {"fax_so", "bot_s_interrupt"})
        self.assertEqual(self._keep_wait, 90.0)
        self.assertLess(server.REQUEST_BUDGET_SEC, 300.0)

    def test_b6_stop_retry_skipped_when_no_time(self):
        # 入力途中のやり直しのあと S を確かめられなかったが、時間が足りない → S のやり直しはせず失敗で知らせる（保存しない）
        keep = server.BLOCKED_RETRY_RUN_SEC
        server.BLOCKED_RETRY_RUN_SEC = 0.0   # 入力途中のやり直しは通す
        self.homis.alerts = [self.IN_PROGRESS]
        self.homis.modes = ["never", "500"]
        keep_budget = server.REQUEST_BUDGET_SEC
        try:
            server.REQUEST_BUDGET_SEC = 1.0e9
            orig_run = server._run_once
            calls = []

            def run_and_shrink(data):
                calls.append(1)
                r = orig_run(data)
                if len(calls) == 2:
                    server.BLOCKED_RETRY_RUN_SEC = 1.0e9   # 2回目のあとは時間が無いことにする
                return r
            server._run_once = run_and_shrink
            out = self.write("BOT-1-20261105110006")
        finally:
            server._run_once = orig_run
            server.BLOCKED_RETRY_RUN_SEC = keep
            server.REQUEST_BUDGET_SEC = keep_budget
        self.assertEqual(len(calls), 2)
        self.assertEqual((out["success"], out["error_type"], out["retried"]), (False, "stopped:unverified_input", ""))
        self.assertEqual(self.homis.saves, [])
        self.assertEqual(len(self.homis.field), 1)
        # 黒ヤギ v3.8.0 指摘1: やり直していないのに「やり直しても同じ」と書かない・入力途中で待った経緯は書く
        self.assertEqual(len(self.homis.dx), 1)
        self.assertNotIn("やり直しても同じ", self.homis.dx[0])
        self.assertIn("やり直していません", self.homis.dx[0])
        self.assertIn("入力途中のカルテ", self.homis.dx[0])

    def test_b7_second_try_blocked_by_other_reason_keeps_history(self):
        # 黒ヤギ v3.8.0 指摘2: 1回目は入力途中・2回目は別の知らせで止まる → DX に待ってやり直した経緯が残る
        self.homis.alerts = [self.IN_PROGRESS, "ほかの知らせ"]
        out = self.write("BOT-1-20261105110007")
        self.assertEqual((out["success"], out["error_type"], out["retried_blocked"]), (False, "blocked:unexpected_alert", "in_progress_karte"))
        self.assertEqual(self.homis.saves, [])
        self.assertEqual(len(self.homis.dx), 1)
        self.assertIn("あけてやり直した2回目", self.homis.dx[0])
        self.assertEqual(len(self.homis.field), 1)

    def test_b8_stop_twice_after_wait_says_same(self):
        # S のやり直しまで通したときは今までどおり「やり直しても同じ」（時間の見張りが誤って効かない）
        self.homis.modes = ["never", "never"]
        out = self.write("BOT-1-20261105110008")
        self.assertEqual(out["retried"], "S欄に入力")
        self.assertIn("やり直しても同じ", self.homis.dx[0])
        self.assertNotIn("入力途中のカルテ", self.homis.dx[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
