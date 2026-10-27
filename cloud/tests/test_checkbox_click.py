# -*- coding: utf-8 -*-
"""browser_actions.py v1.3.0 と fax_so.yaml 1.1 のテスト（算定不要のチェック・電話再診の確かめ）

本物の Chrome（headless）で、HOMIS に似せた小さな画面を開いて確かめる。HOMIS には触らない。
単体: id で探して押す click ＋ verify_checked（_click_checkbox_safely）
結合: 型紙 fax_so.yaml を本物の部品（BrowserActions・型紙の読み込み）で、新規 → 電話再診 → 医科カルテ → 算定不要 → S・O → 完了 まで通す

使い方: py -3.12 -X utf8 cloud/tests/test_checkbox_click.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src")
sys.path.insert(0, SRC)

from selenium import webdriver  # noqa: E402
from selenium.webdriver.chrome.options import Options  # noqa: E402

from browser_actions import BrowserActions  # noqa: E402

# 単体用: 算定不要の箱（HOMIS の部品と同じ形 name/id NoNeedToOrca・onclick=setNoNeedToOrca）
UNIT_PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0">
<label style="position:absolute;left:20px;top:60px">算定不要
  <input type="checkbox" name="NoNeedToOrca" id="NoNeedToOrca" value="1" onclick="javascript:setNoNeedToOrca();"></label>
<div id="cover" style="position:fixed;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,.1);z-index:9"></div>
<script>
  window.__orca = 0;
  function setNoNeedToOrca() {
    window.__orca++;
    if (q.get('revert') === '1') { document.getElementById('NoNeedToOrca').checked = false; }  // 押しても印が戻る作り
  }
  var q = new URLSearchParams(location.search);
  if (q.get('dup') === '1') {   // 隠れた同じ id の箱を先頭に置く（黒ヤギ 10/27 指摘3）
    var h = document.createElement('input'); h.type = 'checkbox'; h.id = 'NoNeedToOrca'; h.style.display = 'none'; h.setAttribute('data-hidden', '1');
    document.body.insertBefore(h, document.body.firstChild);
  }
  if (q.get('pre') === '1') document.getElementById('NoNeedToOrca').checked = true;   // 最初から印が付いている
  var t = q.get('cover');
  if (t === 'none') document.getElementById('cover').remove();
  else if (t !== 'forever') setTimeout(function () { document.getElementById('cover').remove(); }, Number(t));
</script>
"""

# 結合用: HOMIS の新規カルテに似せた画面（新規で欄が出る・医科カルテで算定不要の箱が出る・完了で確認2回のあと karte_id 付き URL へ）
FLOW_PAGE = """<!doctype html><meta charset="utf-8"><body>
<a id="karteNew" href="#" onclick="document.getElementById('kind').style.display='block';return false;">新規</a>
<div id="kind" style="display:none">
  <label><input type="radio" name="kind" value="teiki" checked> 定期</label>
  <label><input type="radio" name="kind" value="denwa"> 電話再診</label>
  <a href="#" onclick="setTimeout(function(){document.getElementById('form').style.display='block';},500);return false;">医科カルテ</a>
</div>
<div id="form" style="display:none">
  医師 看護師 診療科
  <label>算定不要 <input type="checkbox" name="NoNeedToOrca" id="NoNeedToOrca" value="1" onclick="javascript:setNoNeedToOrca();"></label>
  <textarea id="subjective"></textarea><textarea id="objective"></textarea>
  <textarea id="ap"></textarea><textarea id="ap_today"></textarea><textarea id="report"></textarea>
  <a id="karteCompletion" href="#" onclick="if(confirm('保存しますか')&&confirm('完了しますか')){window.__saved={kind:document.querySelector('input[name=kind]:checked').value,orca:document.getElementById('NoNeedToOrca').checked,s:document.getElementById('subjective').value,o:document.getElementById('objective').value};location.hash='karte_id=12345';}return false;">完了</a>
</div>
<script>window.__orca = 0; function setNoNeedToOrca(){ window.__orca++; }</script>
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


class CheckboxClick(unittest.TestCase):
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

    def open(self, cover="none", **q):
        extra = "".join(f"&{k}={v}" for k, v in q.items())
        self.driver.get(f"{self.url}?cover={cover}{extra}")

    def checked(self):
        return self.driver.execute_script("return document.getElementById('NoNeedToOrca').checked")

    def orca(self):
        return self.driver.execute_script("return window.__orca")

    def step(self, verify=True, selector="#NoNeedToOrca"):
        a = {"name": "算定不要を押す", "action": "click", "selector": selector}
        if verify:
            a["verify_checked"] = True
        return self.actions.execute_action(a, {})

    def test_1_plain_click_checks_and_runs_onclick(self):
        self.open("none")
        self.assertTrue(self.step())
        self.assertTrue(self.checked())
        self.assertEqual(self.orca(), 1)          # setNoNeedToOrca が1回動いた（値を直接入れていない）

    def test_2_cover_disappears_then_clicked(self):
        self.open(1500)
        self.assertTrue(self.step())
        self.assertTrue(self.checked())
        self.assertEqual(self.orca(), 1)

    def test_3_cover_forever_js_click_runs_onclick(self):
        self.open("forever")
        self.assertTrue(self.step())
        self.assertTrue(self.checked())
        self.assertEqual(self.orca(), 1)          # JavaScript で押しても onclick は動く

    def test_4_already_checked_is_not_unchecked(self):
        # 最初から印が付いていれば押さない（押すと外れる）。印は付いたまま・onclick は動かない
        self.open("none", pre=1)
        self.assertTrue(self.step())
        self.assertTrue(self.checked())
        self.assertEqual(self.orca(), 0)

    def test_5_fails_when_mark_does_not_stick(self):
        # 押しても印が戻る作り → 手順の失敗（False）
        self.open("none", revert=1)
        self.assertFalse(self.step())

    def test_6_not_found_is_failure(self):
        self.open("none")
        self.assertFalse(self.step(selector="#NoSuchBox"))

    def test_8_hidden_duplicate_is_skipped(self):
        # 同じ id の隠れた箱が先にあっても、見えている箱に印を付ける
        self.open("none", dup=1)
        self.assertTrue(self.step())
        vis = self.driver.execute_script("return document.querySelector('label #NoNeedToOrca').checked")
        hid = self.driver.execute_script("return document.querySelector('[data-hidden]').checked")
        self.assertTrue(vis)
        self.assertFalse(hid)
        self.assertEqual(self.orca(), 1)

    def test_7_click_without_verify_is_unchanged(self):
        # verify_checked が無い click は今までどおり（押すだけ・確かめない）
        self.open("none", revert=1)
        self.assertTrue(self.step(verify=False))
        self.assertEqual(self.orca(), 1)


class FaxSoFlow(unittest.TestCase):
    """結合: 本物の型紙 fax_so.yaml の手順を、本物の BrowserActions で順番どおりに通す"""

    @classmethod
    def setUpClass(cls):
        cls.driver = _chrome()
        cls.path = _write(FLOW_PAGE)
        cls.url = "file:///" + cls.path.replace("\\", "/")
        with open(os.path.join(SRC, "templates", "fax_so.yaml"), encoding="utf-8") as f:
            cls.tpl = yaml.safe_load(f)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        os.remove(cls.path)

    def test_template_version_and_steps(self):
        names = [s["name"] for s in self.tpl["steps"]]
        self.assertEqual(self.tpl["version"], "1.1")
        self.assertLess(names.index("医科カルテボタンをクリック"), names.index("算定不要を押す"))
        self.assertLess(names.index("算定不要を押す"), names.index("S欄に入力"))
        orca = self.tpl["steps"][names.index("算定不要を押す")]
        self.assertEqual(orca["selector"], "#NoNeedToOrca")
        self.assertTrue(orca.get("verify_checked"))
        self.assertTrue(self.tpl["steps"][names.index("電話再診を選択")].get("verify_checked"))

    def test_full_flow(self):
        self.driver.get(self.url)
        actions = BrowserActions(self.driver)
        data = {"sContent": "テスト送り元", "oContent": "テスト本文 \"記号\" & 改行\n二行目", "homisId": "0000000"}
        failed = [s["name"] for s in self.tpl["steps"] if not actions.execute_action(s, data)]
        self.assertEqual(failed, [])
        saved = self.driver.execute_script("return window.__saved")
        self.assertEqual(saved["kind"], "denwa")          # 電話再診が選ばれて保存
        self.assertTrue(saved["orca"])                     # 算定不要に印が付いて保存
        self.assertEqual(saved["s"], data["sContent"])
        self.assertEqual(saved["o"], data["oContent"])
        self.assertEqual(self.driver.execute_script("return window.__orca"), 1)
        self.assertIn("karte_id=12345", self.driver.current_url)   # カルテ番号入りの URL


if __name__ == "__main__":
    unittest.main(verbosity=2)
