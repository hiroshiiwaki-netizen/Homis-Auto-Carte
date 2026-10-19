# -*- coding: utf-8 -*-
"""browser_actions.py v1.2.0 のテスト（文字で探して押す: 待つ・JavaScript で押す・選べたかの確かめ）

本物の Chrome（headless）で、わざと上に覆いをかぶせた小さな画面を開いて確かめる。HOMIS には触らない。
10/16 の本番: 「外来を選択」が element click intercepted（<div> がかぶさる）になり、種別が定期のまま保存された。

使い方: py -3.12 -X utf8 cloud/tests/test_label_click.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src")
sys.path.insert(0, SRC)

from selenium import webdriver  # noqa: E402
from selenium.webdriver.chrome.options import Options  # noqa: E402

from browser_actions import BrowserActions  # noqa: E402

PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0">
<form>
  <label><input type="radio" name="kind" value="teiki" checked> 定期</label>
  <label id="L" style="position:absolute;left:20px;top:60px"><input type="radio" name="kind" value="gairai"> 外来</label>
  <label id="NORADIO" style="position:absolute;left:20px;top:120px">ラジオ無し</label>
</form>
<div id="cover" style="position:fixed;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,.1);z-index:9"></div>
<script>
  // 外来に切り替わったときの画面の処理（HOMIS の onchange の代わり）。JavaScript で押しても動くかを確かめる（黒ヤギ 10/19 指摘3）
  window.__changed = 0;
  document.querySelector('input[value=gairai]').addEventListener('change', function () { window.__changed++; });
  document.getElementById('L').addEventListener('click', function () { window.__labelClicked = (window.__labelClicked || 0) + 1; });
  var t = new URLSearchParams(location.search).get('cover');
  if (t === 'none') document.getElementById('cover').remove();
  else if (t !== 'forever') setTimeout(function () { document.getElementById('cover').remove(); }, Number(t));
</script>
"""


class LabelClick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        o = Options()
        o.add_argument("--headless=new")
        o.add_argument("--window-size=800,600")
        cls.driver = webdriver.Chrome(options=o)
        fd, cls.path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(PAGE)
        cls.url = "file:///" + cls.path.replace("\\", "/")
        cls.actions = BrowserActions(cls.driver)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        os.remove(cls.path)

    def open(self, cover):
        self.driver.get(f"{self.url}?cover={cover}")

    def checked(self, value):
        return self.driver.execute_script(f"return document.querySelector('input[value={value}]').checked")

    def step(self, text="外来", verify=True):
        return self.actions.execute_action(
            {"name": "外来を選択", "action": "click", "selector": "label", "text_contains": text, "verify_checked": verify}, {})

    def test_1_cover_disappears_then_clicked(self):
        # 覆いが 1.5 秒で消える → 待って押せる（直す前は即押して intercepted で失敗した）
        self.open(1500)
        self.assertTrue(self.step())
        self.assertTrue(self.checked("gairai"))
        self.assertFalse(self.checked("teiki"))

    def test_2_cover_forever_js_selects(self):
        # 覆いが消えない → 10 秒待ったあと JavaScript で押す。外来が選ばれ、定期は外れる
        self.open("forever")
        self.assertTrue(self.step())
        self.assertTrue(self.checked("gairai"))
        self.assertFalse(self.checked("teiki"))
        # JavaScript で押しても change が1回起き、label のクリックの処理も動く（画面の切り替えの処理が走る）
        self.assertEqual(self.driver.execute_script("return window.__changed"), 1)
        self.assertGreaterEqual(self.driver.execute_script("return window.__labelClicked || 0"), 1)

    def test_3_no_cover_plain_click(self):
        self.open("none")
        self.assertTrue(self.step())
        self.assertTrue(self.checked("gairai"))

    def test_4_verify_fails_when_not_selectable(self):
        # 押しても選べない（中にラジオが無い）→ 手順の失敗（False）にする
        self.open("none")
        self.assertFalse(self.step(text="ラジオ無し", verify=True))

    def test_5_not_found_is_failure(self):
        self.open("none")
        self.assertFalse(self.step(text="入院", verify=True))

    def test_6_blocker_has_no_text(self):
        # かぶさった物の記録はタグ・id・class だけ（文字を返さない）
        self.open("forever")
        elem = self.actions._find_label("label", "外来")
        b = self.actions._blocker(elem)
        self.assertTrue(b.startswith("DIV#cover"), b)
        self.assertNotIn("外来", b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
