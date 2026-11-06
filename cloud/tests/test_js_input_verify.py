# -*- coding: utf-8 -*-
"""browser_actions.py v1.4.0 と bot_s_interrupt.yaml 1.1 のテスト（S 欄の入れ方を確かめる）

11/4 問い合わせ 0017: 画面の表示が遅く、S が見えていない欄に入り、新しいカルテの S が空のまま中断で保存された。
本物の Chrome（headless）で、HOMIS に似せた小さな画面を開いて確かめる。HOMIS には触らない。
単体: js_input ＋ verify_value（見える欄が出るまで待つ・読み返す・消えたら入れ直す・入らなければ失敗）
結合: 型紙 bot_s_interrupt.yaml を本物の部品で、新規 → 電話再診 → 医科カルテ → S → 中断 まで通す（画面が遅いとき）

使い方: py -3.12 -X utf8 cloud/tests/test_js_input_verify.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src")
sys.path.insert(0, SRC)

from selenium import webdriver  # noqa: E402
from selenium.webdriver.chrome.options import Options  # noqa: E402

from browser_actions import BrowserActions  # noqa: E402

# 単体用: 隠れた S 欄（前のカルテの名残）が最初からあり、見える S 欄は ?show=ミリ秒 後に新しく差し込まれる。
# ?wipe=ミリ秒 なら、見える欄が出たあと一度だけ中身を消す（描き直し）。show=never なら見える欄は出ない
UNIT_PAGE = """<!doctype html><meta charset="utf-8"><body>
<div style="display:none"><textarea id="subjective" data-old="1"></textarea></div>
<div id="slot"></div>
<script>
  var q = new URLSearchParams(location.search);
  function show() { document.getElementById('slot').innerHTML = '<textarea id="subjective"></textarea>'; }
  var t = q.get('show');
  if (t === '0') show(); else if (t !== 'never') setTimeout(show, Number(t));
  var w = q.get('wipe');   // 最初に入れられてから w ミリ秒後に一度だけ消す
  if (w) document.addEventListener('input', function f(ev) {
    if (!ev.target.closest('#slot')) return;
    document.removeEventListener('input', f);
    setTimeout(function () { ev.target.value = ''; }, Number(w));
  });
</script>
"""

# 結合用: 医科カルテを押すと ?delay=ミリ秒 後に入力欄が新しく差し込まれる。中断で確認2回のあと karte_id 付き URL へ
FLOW_PAGE = """<!doctype html><meta charset="utf-8"><body>
<div style="display:none"><textarea id="subjective" data-old="1"></textarea></div>
<a id="karteNew" href="#" onclick="document.getElementById('kind').style.display='block';return false;">新規</a>
<div id="kind" style="display:none">
  <label><input type="radio" name="kind" value="teiki" checked> 定期</label>
  <label><input type="radio" name="kind" value="denwa"> 電話再診</label>
  <a href="#" onclick="setTimeout(openForm, Number(new URLSearchParams(location.search).get('delay')||500));return false;">医科カルテ</a>
</div>
<div id="form"></div>
<script>
function openForm() {
  document.getElementById('form').innerHTML =
    '<textarea id="subjective"></textarea><textarea id="objective"></textarea>' +
    '<textarea id="ap"></textarea><textarea id="ap_today"></textarea><textarea id="report"></textarea>' +
    '<a id="karteInterruption" href="#">中断</a>';
  document.getElementById('karteInterruption').onclick = function () {
    if (confirm('保存しますか') && confirm('中断しますか')) {
      window.__saved = {kind: document.querySelector('input[name=kind]:checked').value,
                        s: document.querySelector('#form #subjective').value};
      location.hash = 'karte_id=12345';
    }
    return false;
  };
}
</script>
"""


def _chrome():
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--window-size=800,600")
    return webdriver.Chrome(options=o)


def _write(html: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    return path


TEXT = "【試験】問い合わせの S\r\n二行目 \"記号\" & <タグ>"
WANT = TEXT.replace("\r\n", "\n")


class JsInputVerify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = _chrome()
        cls.path = _write(UNIT_PAGE)
        cls.url = "file:///" + cls.path.replace("\\", "/")
        cls.actions = BrowserActions(cls.driver)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        os.remove(cls.path)

    def open(self, **q):
        self.driver.get(self.url + "?" + "&".join(f"{k}={v}" for k, v in q.items()))

    def step(self, verify=True):
        a = {"name": "S欄に入力", "action": "js_input", "selector": "textarea#subjective", "value": "{sContent}"}
        if verify:
            a["verify_value"] = True
        return self.actions.execute_action(a, {"sContent": TEXT})

    def visible(self):
        return self.driver.execute_script("var e=document.querySelector('#slot #subjective');return e?e.value:null")

    def old(self):
        return self.driver.execute_script("return document.querySelector('[data-old]').value")

    def test_1_visible_now(self):
        self.open(show=0)
        self.assertTrue(self.step())
        self.assertEqual(self.visible(), WANT)
        self.assertEqual(self.old(), "")

    def test_2_waits_for_late_field(self):
        # 見える欄が 2.5 秒後に出る → 待って、見える欄に入れる（隠れた名残には入れない）
        self.open(show=2500)
        self.assertTrue(self.step())
        self.assertEqual(self.visible(), WANT)
        self.assertEqual(self.old(), "")

    def test_3_refills_after_wipe(self):
        # 入れた直後に描き直しで消える → 読み返しで気づいて入れ直す
        self.open(show=0, wipe=200)
        self.assertTrue(self.step())
        time.sleep(0.5)   # 消える時刻を過ぎてから見る
        self.assertEqual(self.visible(), WANT)

    def test_4_never_visible_is_failure(self):
        # 見える欄が出ない → 手順の失敗（False）。隠れた名残にも入れない
        self.open(show="never")
        self.assertFalse(self.step())
        self.assertEqual(self.old(), "")

    def test_6_lone_cr_is_matched(self):
        # \r 単体の改行もブラウザは \n にする → そろえて読み返しが一致する（黒ヤギ 11/4 指摘1）
        self.open(show=0)
        a = {"name": "S欄に入力", "action": "js_input", "selector": "textarea#subjective",
             "value": "{sContent}", "verify_value": True}
        t0 = time.time()
        self.assertTrue(self.actions.execute_action(a, {"sContent": "一行目\r二行目\r\n三行目"}))
        self.assertEqual(self.visible(), "一行目\n二行目\n三行目")
        self.assertLess(time.time() - t0, 3)   # 10 秒待って失敗、にならない

    def test_5_without_verify_is_unchanged(self):
        # verify_value が無い js_input は今までどおり（見える欄が無ければ隠れた名残に入れて「完了」）
        self.open(show=2500)
        self.assertTrue(self.step(verify=False))
        self.assertEqual(self.old(), WANT)


class BotFlow(unittest.TestCase):
    """結合: 本物の型紙 bot_s_interrupt.yaml の手順を、本物の BrowserActions で順番どおりに通す"""

    @classmethod
    def setUpClass(cls):
        cls.driver = _chrome()
        cls.path = _write(FLOW_PAGE)
        cls.url = "file:///" + cls.path.replace("\\", "/")
        with open(os.path.join(SRC, "templates", "bot_s_interrupt.yaml"), encoding="utf-8") as f:
            cls.tpl = yaml.safe_load(f)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        os.remove(cls.path)

    def run_flow(self, delay):
        self.driver.get(f"{self.url}?delay={delay}")
        actions = BrowserActions(self.driver)
        data = {"sContent": TEXT, "homisId": "0000000"}
        return [s["name"] for s in self.tpl["steps"] if not actions.execute_action(s, data)]

    def test_template_version_and_steps(self):
        names = [s["name"] for s in self.tpl["steps"]]
        steps = {s["name"]: s for s in self.tpl["steps"]}
        self.assertEqual(self.tpl["version"], "1.3")   # 1.2: S の2手順に stop_on_fail（test_stop_retry.py で確かめる）・1.3: 算定不要を外す（test_checkbox_click.py）
        self.assertTrue(steps["電話再診を選択"].get("verify_checked"))
        self.assertTrue(steps["S欄に入力"].get("verify_value"))
        # 保存の直前に S をもう一度確かめる
        self.assertTrue(steps["S欄をもう一度確かめる"].get("verify_value"))
        self.assertEqual(names.index("S欄をもう一度確かめる") + 1, names.index("中断ボタンで保存"))

    def test_full_flow_normal(self):
        self.assertEqual(self.run_flow(500), [])
        saved = self.driver.execute_script("return window.__saved")
        self.assertEqual(saved["kind"], "denwa")
        self.assertEqual(saved["s"], WANT)
        self.assertIn("karte_id=12345", self.driver.current_url)

    def test_full_flow_slow_screen(self):
        # 0017 と同じ: 医科カルテを押してから欄が出るまで 4.5 秒（型紙の待ち 3 秒より長い）
        self.assertEqual(self.run_flow(4500), [])
        saved = self.driver.execute_script("return window.__saved")
        self.assertEqual(saved["s"], WANT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
