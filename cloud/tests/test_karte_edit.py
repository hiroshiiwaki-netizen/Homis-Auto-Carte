# -*- coding: utf-8 -*-
"""cloud/server.py v3.13.0 と karte_edit.yaml 1.0 の結合テスト（共通 JSON の入口 ①先生が選んだカルテに書く）。すべてダミーの値。

本物の server.write_karte → 本物の TemplateEngine → 本物の BrowserActions（本物の Chrome・headless）で、
本物の型紙 karte_edit.yaml の手順を通す。HOMIS の代わりに手元の偽サーバー:
  - カルテの画面: 今の中身（時刻・各欄・バイタル）が入った編集画面。編集を押すと欄が出る（出ない回も作れる）
  - 中断: 保存した中身を全部覚える
書く前の確かめ（karte_guard.read）は偽物に差し替え、テストごとにカルテの状態・更新者を決める。
HOMIS・共有ドライブ・本物の Chat には触らない。

使い方: py -3.12 -X utf8 cloud/tests/test_karte_edit.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_stop_retry as tsr  # noqa: E402  共有ログの偽物・手元の Chrome・札の偽物の置き場を借りる

server, template_engine, FakeGCS, pl = tsr.server, tsr.template_engine, tsr.FakeGCS, tsr.pl
import auto_retry  # noqa: E402
import karte_guard  # noqa: E402

TODAY = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

PAGE = """<!doctype html><meta charset="utf-8"><body>
<a id="karteEdit" href="#" onclick="openEdit();return false;">編集</a>
<div id="form"></div>
<a href="#" onclick="copyLinkOfKarte('none');return false;">リンク</a>
<script>
function copyLinkOfKarte(u) {}
function call(path, body) {
  var x = new XMLHttpRequest(); x.open('POST', path, false);
  x.send(JSON.stringify(body || {})); return JSON.parse(x.responseText);
}
var IDS = ['start_time','end_time','bt','bp_h','bp_l','pr','o2'], TX = ['subjective','objective','ap','ap_today','report'];
function openEdit() {
  var r = call('/edit');
  if (r.mode === 'never') return;
  var h = '';
  IDS.forEach(function (k) { h += '<input type="text" id="' + k + '" value="' + (r.now[k] || '') + '">'; });
  TX.forEach(function (k) { h += '<textarea id="' + k + '"' + (r.mode === 'hide_s' && k === 'subjective' ? ' style="display:none"' : '') + '>' +
                              (r.now[k] || '') + '</textarea>'; });
  h += '<a id="karteInterruption" href="#">中断</a>';
  document.getElementById('form').innerHTML = h;
  document.getElementById('karteInterruption').onclick = function () {
    if (confirm('保存しますか') && confirm('中断しますか')) {
      var b = {karte_id: r.karte_id};
      IDS.concat(TX).forEach(function (k) { b[k] = document.getElementById(k).value; });
      call('/save', b);
      location.hash = 'karte_id=' + r.karte_id;
    }
    return false;
  };
}
</script>
"""

NOW = {"start_time": "09:00", "end_time": "09:10", "bt": "36.1", "bp_h": "110", "bp_l": "70", "pr": "60", "o2": "97",
       "subjective": "先生が前に書いた S", "objective": "前の O", "ap": "前の AP", "ap_today": "前の本日AP", "report": "前の指導"}


class Homis(tsr.FakeHomis):
    """test_stop_retry の偽 HOMIS に、編集の画面（/edit）を足す"""

    def reset(self):
        super().reset()
        self.edit_modes, self.edits = [], 0

    def __init__(self):
        super().__init__()
        outer, base = self, self.httpd.RequestHandlerClass

        class H(base):
            def do_GET(self):
                data = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if self.path.split("?")[0] == "/edit":
                    n = int(self.headers.get("Content-Length", "0") or 0)
                    self.rfile.read(n)
                    with outer.lock:
                        outer.edits += 1
                        m = outer.edit_modes.pop(0) if outer.edit_modes else "ok"
                    return self._json({"mode": m, "karte_id": 18000001, "now": NOW})
                return base.do_POST(self)
        self.httpd.RequestHandlerClass = H


def karte(status="2", act=TODAY, upd="2026-11-06 10:00:00", who="医師 一郎", pid="2277808"):
    return {"status": status, "act_date": act, "patient_id": pid, "upd_datetime": upd, "upd_user": {"full_name": who}}


S_TEXT = "【試験】音声カルテの S\r\n二行目"


class KarteEdit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.homis = Homis()
        cls.gcs = FakeGCS()
        cls.gcs.install_env()
        with open(os.path.join(tsr.SRC, "templates", "karte_edit.yaml"), encoding="utf-8") as f:
            cls.tpl = yaml.safe_load(f)
        tpl = dict(cls.tpl, target_url=cls.homis.base + "/patient?patient_id={homisId}&karte_id={karteId}")
        cls.tmp = tempfile.mkdtemp()
        with open(os.path.join(cls.tmp, "karte_edit.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(tpl, f, allow_unicode=True)
        template_engine.TEMPLATES_DIR = __import__("pathlib").Path(cls.tmp)
        server._init_driver_cloud = tsr._local_driver
        server.verify_karte = types.SimpleNamespace(verify=cls.fake_verify)
        os.environ.update({"HOMIS_USER": "u", "HOMIS_PASSWORD": "p", "DX_ALERT_WEBHOOK": cls.homis.base + "/dx",
                           "BOT_FIELD_WEBHOOK": cls.homis.base + "/field", "FAX_FIELD_WEBHOOK": cls.homis.base + "/field"})
        os.environ.pop("RESULT_SPREADSHEET_ID", None)
        os.environ.pop("RETRY_MODE", None)
        cls.real_read = karte_guard.read

    @classmethod
    def tearDownClass(cls):
        karte_guard.read = cls.real_read
        cls.homis.httpd.shutdown()
        cls.gcs.shutdown()

    @classmethod
    def fake_verify(cls, homis_id, kid, s, o, expect="done"):
        got = [x for x in cls.homis.saves if str(x.get("karte_id")) == str(kid)]
        ok = bool(got) and got[-1]["subjective"] == s.replace("\r\n", "\n")
        cls.verify_calls.append(expect)
        return {"verdict": "ok" if ok else "s_mismatch", "status": "2", "status_label": "中断", "reads": 1,
                "s_len": 0, "o_len": 0, "reason": ""}

    def setUp(self):
        self.homis.reset()
        self.gcs.reset()
        type(self).verify_calls = []
        self.reads = [karte()]   # 書く前・保存の直前に読む中身（最後の1つを使い続ける）
        self.read_calls = 0

        def fake_read(hid, kid):
            self.read_calls += 1
            item = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
            return None if item is None else dict(item)
        karte_guard.read = fake_read
        self._keep_poll = pl.LOCK_POLL_SEC
        pl.LOCK_POLL_SEC = 0.5

    def tearDown(self):
        pl.LOCK_POLL_SEC = self._keep_poll
        os.environ.pop("RETRY_MODE", None)

    def write(self, oid="KE-18000001-20261106160000", **over):
        d = {"orderId": oid, "homisId": "2277808", "karteId": "18000001", "template": "karte_edit",
             "karteUrl": "https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18000001",
             "soap_s": S_TEXT, "soap_o": "新しい O", "soap_ap_summary": "", "soap_ap_temporary": "新しい AP",
             "instruction": "新しい指導", "vital_bt": "36.8", "vital_bp_h": "", "vital_bp_l": "", "vital_pr": "72",
             "vital_spo2": "", "start_time": "10:00", "end_time": "", "senderEmail": "doctor@example.jp"}
        d.update(over)
        return server.write_karte(d)

    def test_t0_template(self):
        steps = {s["name"]: s for s in self.tpl["steps"]}
        self.assertEqual(self.tpl["version"], "1.0")
        self.assertEqual(steps["編集ボタンをクリック"]["selector"], "#karteEdit")
        self.assertTrue(steps["中断ボタンで保存"].get("check_before_save"))
        self.assertEqual([n for n, s in steps.items() if s.get("stop_on_fail")],
                         ["編集ボタンをクリック", "S欄に入力", "O欄に入力", "S欄をもう一度確かめる"])
        self.assertNotIn("#karteNew", str(self.tpl))   # 新規は押さない
        self.assertEqual(self.tpl["steps"][0]["name"], server.EDIT_BUTTON_STEP)   # ライターが手順の名前で見分けるため
        self.assertIn("karte_edit", server.ALLOWED_TEMPLATES)

    def test_e1_overwrites_and_keeps_blank_times_and_vitals(self):
        out = self.write()
        self.assertEqual((out["success"], out["error_type"], out["left_in_homis"], out["karte_id"], out["verify"]),
                         (True, "", "saved", "18000001", "ok"))
        (saved,) = self.homis.saves
        self.assertEqual(saved["subjective"], S_TEXT.replace("\r\n", "\n"))   # 上書き
        self.assertEqual((saved["objective"], saved["ap"], saved["ap_today"], saved["report"]),
                         ("新しい O", "　", "新しい AP", "新しい指導"))   # 空の文の欄は全角スペース
        self.assertEqual((saved["start_time"], saved["end_time"]), ("10:00", "09:10"))   # 空の終了は触らない
        self.assertEqual((saved["bt"], saved["bp_h"], saved["bp_l"], saved["pr"], saved["o2"]),
                         ("36.8", "110", "70", "72", "97"))   # 空のバイタルは今の値のまま
        self.assertEqual(self.verify_calls, ["interrupt"])
        self.assertEqual(self.read_calls, 2)   # 書く前と保存の直前
        self.assertEqual(self.homis.dx, [])

    def test_e2_completed_or_old_is_never_opened(self):
        for item, want in ((karte(status="7"), "karte_completed"), (karte(act="2020-01-01"), "karte_too_old"),
                           (karte(pid="1111111"), "karte_other_patient"), (None, "karte_unreadable")):
            self.homis.reset()
            self.reads = [item]
            out = self.write()
            self.assertEqual((out["success"], out["error_type"], out["left_in_homis"]), (False, want, "none"), want)
            self.assertEqual((self.homis.edits, self.homis.saves), (0, []))   # 編集を開かない
            self.assertEqual(len(self.homis.dx), 1)
            self.assertIn("doctor@example.jp", self.homis.dx[0])
            self.assertEqual(self.homis.field, [])   # 現場には出さない（KARTE_FIELD_WEBHOOK はまだ無い）

    def test_e3_human_saved_while_writing_is_not_saved(self):
        self.reads = [karte(), karte(upd="2026-11-06 10:05:00", who="看護師 花子")]
        out = self.write()
        self.assertEqual((out["success"], out["error_type"], out["left_in_homis"]),
                         (False, "skipped:human_saved_during", "editing"))
        self.assertEqual((self.homis.edits, self.homis.saves), (1, []))
        self.assertIn("編集中のまま残っています", self.homis.dx[0])

    def test_e4_own_edit_open_is_not_a_human(self):
        # 編集を開いただけで更新日時が変わっても、更新者がライターなら人とみなさない（仕様 5章 3b の【確認】の両方の形）
        self.reads = [karte(), karte(upd="2026-11-06 10:05:00", who="おひさまロボット GCP")]
        self.assertTrue(self.write()["success"])

    def test_e5_presave_unreadable_is_not_saved(self):
        self.reads = [karte(), None]
        out = self.write()
        self.assertEqual((out["success"], out["error_type"], out["left_in_homis"]), (False, "blocked:presave_unreadable", "editing"))
        self.assertEqual(self.homis.saves, [])

    def test_e6_hidden_s_never_saves_and_is_not_rerun(self):
        self.homis.edit_modes = ["hide_s"]
        out = self.write()
        self.assertEqual((out["success"], out["error_type"], out["left_in_homis"]), (False, "stopped:unverified_input", "editing"))
        self.assertEqual((self.homis.edits, self.homis.saves), (1, []))   # 取り直さない（新規の守りは使わない）

    def test_e7_edit_never_opens_is_none(self):
        self.homis.edit_modes = ["never"]
        out = self.write()
        self.assertFalse(out["success"])
        self.assertEqual(self.homis.saves, [])
        self.assertIn(out["left_in_homis"], ("none", "editing"))   # 欄が出ないので S が入らず止まる

    def test_r1_retry_stops_if_human_changed_since_baseline(self):
        base = karte_guard.snapshot(karte())
        self.reads = [karte(upd="2026-11-06 11:00:00", who="医師 一郎")]
        out = self.write("KE-18000001-20261106160000-A1", baseline_upd=base)
        self.assertEqual((out["error_type"], out["left_in_homis"]), ("skipped:human_edited", "none"))
        self.assertEqual(self.homis.edits, 0)
        out = self.write("KE-18000001-20261106160000-A2", baseline_upd=None)   # 控えが無い＝分からない＝書かない
        self.assertEqual(out["error_type"], "skipped:human_edited")
        self.reads = [karte()]
        out = self.write("KE-18000001-20261106160000-A3", baseline_upd=base)   # 変わっていなければ書く
        self.assertTrue(out["success"])

    def test_r2_retry_rules_for_karte_edit(self):
        os.environ["RETRY_MODE"] = "on"
        el = auto_retry.eligible
        self.assertTrue(el("karte_edit", "KE-1-20261106160000", "karte_unreadable", "none"))
        self.assertTrue(el("karte_edit", "KE-TEST-1-20261106160000", "locked:busy", "none"))
        for err in ("karte_completed", "karte_too_old", "karte_not_found", "karte_cancelled", "karte_other_patient",
                    "skipped:human_edited", "skipped:human_saved_during", "stopped:unverified_input"):
            self.assertFalse(el("karte_edit", "KE-1-20261106160000", err, "none"), err)
        self.assertFalse(el("karte_edit", "KE-1-20261106160000", "karte_unreadable", "editing"))
        os.environ["RETRY_QUEUE_KARTE"] = "projects/p/locations/l/queues/homis-karte-json-writer"
        self.assertTrue(auto_retry.queue_for("karte_edit").endswith("homis-karte-json-writer"))

    def test_r3_unreadable_first_time_schedules_retry_with_baseline(self):
        os.environ["RETRY_MODE"] = "on"
        os.environ["RETRY_QUEUE_KARTE"] = "projects/p/locations/l/queues/homis-karte-json-writer"
        sent = []
        keep = auto_retry.enqueue
        auto_retry.enqueue = lambda tpl, payload, delay: sent.append((tpl, payload, delay)) or "queued"
        try:
            self.reads = [None, karte()]   # 書く前は読めない → 控えを取り直す（読めた）
            out = self.write()
        finally:
            auto_retry.enqueue = keep
        self.assertEqual(out["error_type"], "karte_unreadable")
        ((tpl, payload, delay),) = sent
        self.assertEqual((tpl, payload["orderId"], delay), ("karte_edit", "KE-18000001-20261106160000-A1", 300))
        self.assertEqual(payload["baseline_upd"], karte_guard.snapshot(karte()))
        self.assertNotIn("baseline_karte_id", payload)
        self.assertIn("5 分後にやり直します", self.homis.dx[0])

    def test_v1_processed_is_failure_for_karte_edit(self):
        """verify_karte 1.4.0 の ok_processed（S が空でない）は、①では S が同じでも違っても失敗（黒ヤギ 3.13.0 実装1回目 指摘1:
        ライターが編集を開いたまま保存に失敗すると状態は 1・70 になり、前の S が残るため）"""
        keep = server.verify_karte
        try:
            for reason, want in (("s_edited", (False, "verify:not_interrupted")), ("", (False, "verify:not_interrupted"))):
                server.verify_karte = types.SimpleNamespace(verify=lambda *a, r=reason, **k: {
                    "verdict": "ok_processed", "status": "1", "status_label": "診察中", "reads": 2,
                    "s_len": 3, "o_len": 0, "reason": r})
                self.homis.reset()
                out = self.write()
                self.assertEqual((out["success"], out["error_type"]), want, reason)
        finally:
            server.verify_karte = keep

    def test_e8_edit_click_crash_is_not_retried(self):
        """編集ボタンを押している途中で落ちても「開いたかもしれない」＝ editing（自動やり直しに回さない・黒ヤギ 指摘3）"""
        os.environ["RETRY_MODE"] = "on"
        keep = server._orig_click

        def crash(self_, selector, *a, **k):
            if selector == "#karteEdit":
                raise RuntimeError("chrome not reachable")
            return keep(self_, selector, *a, **k)
        server._orig_click = crash
        sent = []
        keep_enq = auto_retry.enqueue
        auto_retry.enqueue = lambda *a: sent.append(a) or "queued"
        try:
            out = self.write()
        finally:
            server._orig_click = keep
            auto_retry.enqueue = keep_enq
        self.assertEqual((out["success"], out["left_in_homis"]), (False, "editing"))
        self.assertEqual(out["error_type"], "step:編集ボタンをクリック")   # S の確かめの失敗と取り違えない（黒ヤギ 3回目 指摘2）
        self.assertNotIn("S を入れたこと", self.homis.dx[0])
        self.assertEqual((sent, self.homis.saves), ([], []))

    def test_e10_other_error_while_finding_button_is_retried(self):
        """編集ボタンを探す途中で時間切れ以外の例外（Chrome が落ちた等）でも、開いていなければ timeout でやり直す（黒ヤギ 3回目 指摘1）"""
        from selenium.common.exceptions import WebDriverException
        keep = server.BrowserActions._find_element

        def broken(self_, selector, *a, **k):
            if selector == "#karteEdit":
                raise WebDriverException("chrome not reachable")
            return keep(self_, selector, *a, **k)
        server.BrowserActions._find_element = broken
        os.environ["RETRY_MODE"] = "on"
        sent = []
        keep_enq = auto_retry.enqueue
        auto_retry.enqueue = lambda tpl, payload, delay: sent.append(payload["orderId"]) or "queued"
        try:
            out = self.write()
        finally:
            server.BrowserActions._find_element = keep
            auto_retry.enqueue = keep_enq
        self.assertEqual((out["success"], out["left_in_homis"], out["error_type"]), (False, "none", "timeout"))
        self.assertEqual(sent, ["KE-18000001-20261106160000-A1"])

    def test_e9_edit_button_not_found_is_not_opened(self):
        """編集ボタンが見つからない（読み込みの遅れ等）ときは押していない＝ none（黒ヤギ 3.13.0 実装2回目 指摘1）"""
        from selenium.common.exceptions import TimeoutException
        keep = server.BrowserActions._find_element

        def slow(self_, selector, *a, **k):
            if selector == "#karteEdit":
                raise TimeoutException("not found")
            return keep(self_, selector, *a, **k)
        server.BrowserActions._find_element = slow
        os.environ["RETRY_MODE"] = "on"
        sent = []
        keep_enq = auto_retry.enqueue
        auto_retry.enqueue = lambda tpl, payload, delay: sent.append(payload["orderId"]) or "queued"
        try:
            out = self.write()
        finally:
            server.BrowserActions._find_element = keep
            auto_retry.enqueue = keep_enq
        self.assertEqual((out["success"], out["left_in_homis"], out["error_type"]), (False, "none", "timeout"))
        self.assertEqual((self.homis.edits, self.homis.saves), (0, []))
        self.assertEqual(sent, ["KE-18000001-20261106160000-A1"])   # 時間切れとして自動やり直しに回る
        self.assertNotIn("編集中のまま残っています", self.homis.dx[0])

    def test_v2_not_interrupted_note_in_dx(self):
        """中断になっていない失敗の DX の知らせに「書いた直後に先生が開いた場合も」の一言（黒ヤギ 3.13.0 実装2回目 指摘2）"""
        keep = server.verify_karte
        server.verify_karte = types.SimpleNamespace(verify=lambda *a, **k: {
            "verdict": "ok_processed", "status": "1", "status_label": "診察中", "reads": 2,
            "s_len": 3, "o_len": 0, "reason": ""})
        try:
            out = self.write()
        finally:
            server.verify_karte = keep
        self.assertEqual(out["error_type"], "verify:not_interrupted")
        self.assertIn("書いた直後に先生がカルテを開いた場合も", self.homis.dx[0])
        self.homis.reset()
        self.reads = [karte(status="7")]
        self.write()
        self.assertNotIn("書いた直後に先生がカルテを開いた場合も", self.homis.dx[0])   # ほかの失敗には付けない

    def test_c1_fill_rules(self):
        f = server.edit_fill({"soap_s": "S", "soap_o": "x" * 70000, "soap_ap_summary": " ", "soap_ap_temporary": None,
                              "instruction": ""})
        self.assertEqual((f["soap_ap_summary"], f["soap_ap_temporary"], f["instruction"]), ("　",) * 3)
        self.assertLessEqual(server._homis_bytes(f["soap_o"]), server.O_MAX_BYTES)   # O は上限で区切る
        self.assertEqual((f["sContent"], f["oContent"]), (f["soap_s"], f["soap_o"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
