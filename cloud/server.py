# -*- coding: utf-8 -*-
"""Cloud Run 受け口（フェーズ2a＋失敗ガード）

==============================================================================
バージョン: 3.9.0
最終更新: 2026/11/05
改定履歴（新しい順・全体は docs/SPEC_v3_cloud.md 0章「モジュール別の版」）:
  v3.9.0 11/05 患者さんごとの札（patient_lock.py 1.0.0・Cloud Storage の LOCK_BUCKET）。問い合わせの列を FAX と分けると別の台が同じ患者さんを
               同時に書きうる（HOMIS は同じアカウントの編集中を新規で返す）ので、結果シートの受付のあと・新規の前に札を取り、
               書き終わり（読み直し・知らせ・結果シートまで）で外す。3型紙とも。札待ちは最長 320 秒、取れなければ locked:busy、
               置き場が使えなければ locked:error（案A・書かずに現場と DX に知らせ、結果シートも fail で閉じる）。
               書きかけ（編集中）を残して終わったときは札を外さず期限（300秒）で消えるに任せる（次の台が新規を押すころには
               v3.7.0 の守りが時刻で止められる・黒ヤギ仕様2回目 指摘3）。v3.8.0・v3.6.0 のやり直しの時間の見張りは札を取ってから数える
               （共有ログの経過時間は受け取りから・指摘4）。仕様 docs/FAXカルテ_検討/SPEC_問い合わせの列を分ける_v0.md v0.4
  v3.8.0 11/05 新規で「入力途中のカルテが存在します」と止められたら（blocked:in_progress_karte）、90秒あけて1回だけ最初からやり直す。
               FAX（fax_so）と問い合わせ（bot_s_interrupt）だけ。レントゲンと、ほかの文の知らせ（unexpected_alert）は今までどおり。
               待つ前の経過＋90秒＋120秒（やり直し1回分の見込み）が 280 秒を超えるならやり直さない（Cloud Run の上限 300 秒）。
               2回とも止められたら今までどおり失敗・現場と DX に知らせる（DX の文に「やり直しても同じ」）。
               11/5 10:19 同じ患者さんへの FAX 3枚目（-103）で起きた・DX担当「案2」
  v3.7.0 11/04 前の書きかけ（ライター自身が残した編集中）が新規で戻ったら、書く前に止める（全型紙共通・DX担当「案①」）。
               新規のあと最初の js_input の直前に、編集画面の #karte_id・#act_date・#start_time を読み、
               日付＋開始時刻が新規を押した時刻より2分以上前、または書けずに残した番号として覚えたものなら blocked:reused_editing。
               同じ注文の中のやり直し（v3.6.0）で1回目と同じ番号なら止めない。欄が読めなければ止めずに書き、DX に知らせる。
               仕様 docs/FAXカルテ_検討/SPEC_ライター_編集中の守り_v0.md v0.5（黒ヤギ仕様2回）
  v3.6.0 11/04 型紙の手順に stop_on_fail があり、その手順が失敗したら、以後の手順と保存（中断・完了）を一切しない。
               ライターの中で1回だけ最初からやり直す（ライター自身が残した編集中は、同じアカウントの新規で同じカルテが戻る・
               11/2 テスト舞子 5b）。2回とも止まったら失敗（error_type stopped:unverified_input）・DX と現場（本番）に知らせる。
               問い合わせの型紙 bot_s_interrupt 1.2 の S の2手順に使う（DX担当「問い合わせで S 欄が空はあかん」・11/4 0017）。
               FAX・レントゲンの型紙には付けないので動きは変わらない
  v3.5.0 11/02 問い合わせ（bot_s_interrupt・注文番号 BOT-…）を本番で受けられるようにする（受け口 0.4.0 の /bot/receive から）。
               書いたあと読み直す（verify_karte 1.1.0 の expect="interrupt"＝中断・更新者がライター自身・S 一致・O 空）。
               カルテ番号が取れなければ失敗（FAX と同じ）。書けなかったら現場の知らせを型紙ごとに分ける
               （FAX＝FAX_FIELD_WEBHOOK「FAX の原本から」／問い合わせ＝BOT_FIELD_WEBHOOK「問い合わせの画面の内容から」・
               試し書き BOT-TEST-… は知らせない）。止めたとき（blocked）の DX の文も問い合わせ用を足す。
               FAX（fax_so）は S（発信元）が空でも受ける（O が空のときだけ 400・11/2 札 -13・DX担当「空でいい」）。
               ただし S が空だと HOMIS が完了で保存しない（テスト舞子で編集中のまま残った）ので、空なら半角スペース1つを入れて書く
               （半角・全角とも完了まで保存できることをテスト舞子で確認。DX担当「半角スペースを入れて」）。
               それ以外の FAX・レントゲンの動きは変えない。
               仕様 docs/FAXカルテ_検討/SPEC_問い合わせ_ライター移行_v0.md v0.3（黒ヤギ仕様1回目 指摘2・4）
  v3.4.0 11/02 「新規」を押した直後に HOMIS が「入力途中のカルテが存在します」と出したら、そこで止める（以後の手順を一切しない）。
               失敗（error_type blocked:in_progress_karte）にして DX と現場（本番の FAX）に理由つきで知らせる。
               FAX（fax_so）でカルテ番号が取れなかったら必ず失敗にする（11/2 11:36 本番の1件が成功扱いになり現場に知らせが出なかった）。
               黒ヤギ 11/2 1回目: 新規のあとの知らせはどんな文でも止める（unexpected_alert）・完了ボタンが出たら待たずに進む・
               止めたら karte_opened を戻す・DX の文は型紙ごと（FAX は Tukusi への送り直し＝新しい札、レントゲンは送り元から送り直すか手で）。
               fax_requeue は live では使えない（同じ注文番号は二重よけで弾かれ、本文は試し書きにしか無い）ので案内しない
  v3.3.0 10/29 段3: 本番の FAX（注文番号 FAX-…・試し書きの FAX-MIRROR-… は除く）が書けなかったとき（読み直しで合わない場合も）、
               現場用のスペース（FAX_FIELD_WEBHOOK）にも直リンク付きで知らせる。DX への知らせは今まで通り。
               仕様 docs/FAXカルテ_検討/SPEC_段3_本番切替.md 4章
  v3.2.0 10/29 FAX（fax_so）は書いたあと HOMIS を読み直し（verify_karte.py）、完了か・S/O が送ったとおりかを確かめる。
               合わなければ失敗（error_type verify:…）にして DX に直リンク付きで知らせる。読めなければ成功のまま DX に一言。
               レントゲン・ボットの型紙は変えない
  v3.1.3 10/27 途中の手順の失敗を DX に知らせる文を型紙ごとに（FAX は「種別（電話再診）・算定不要の印」、レントゲンは今までどおり「外来」）。
               FAX の型紙 fax_so 1.1（算定不要）・押し方の部品 src/browser_actions.py v1.3.0 と一緒に配る
  v3.1.2 10/19 カルテ番号が取れても途中の手順が失敗していたら DX に知らせる（直リンク付き）。押し方の改善は src/browser_actions.py v1.2.0
  v3.1.1 10/15 ALLOWED_HOMIS_IDS="*" で全員を許可（本番の切り替え用）。許可の外で断ったときもナビ（空の URL）と DX に知らせる
  v3.1.0 10/15 書き終えたらナビの doPost に知らせる（NAVI_WEBAPP_URL があるときだけ・xray_karte だけ）
               ・POST /check-group（集団の確かめ役をナビへ中継）を追加（GCP 移行計画 v0.4 フェーズ1）
  v3.0.x 09/08 受け口2a・失敗ガード・結果シート（2b）・fax_so・bot_s_interrupt
==============================================================================

GET  /health       生存確認（合言葉不要）
POST /write        HOMIS 書き込み。同期。書き終えたらナビに知らせる（NAVI_WEBAPP_URL があるとき）
POST /check-group  集団の確かめ役。ナビの checkGroupComplete を呼ぶだけ（Cloud Tasks の予約から呼ばれる）

安全:
  - 合言葉 X-Writer-Key が空なら 503、不一致は 401
  - 既定はテスト舞子（2277808）だけ書く
  - 患者名・S/AP・パスワード・合言葉・Webhookはログに出さない
  - 新規（#karteNew）より前だけ 1 回リトライ。押したあとは禁止
  - 空カルテ疑いは DX エラーChat（固定文＋患者URL）
  - 202+裏処理はしない（Cloud Run は応答後に CPU を止める）
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

import navi_callback
import patient_lock
import verify_karte
from browser_actions import BrowserActions
from result_sheet import claim, enabled as sheet_enabled
from result_sheet import finish, result_from_row
from shared_log import extract_karte_id, infer_error_type, log_result
from template_engine import TemplateEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("homis_writer")

CHROME_BIN = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
CHROMEDRIVER = os.environ.get("CHROMEDRIVER", "/usr/bin/chromedriver")
BEFORE_NEW = {"chrome", "login", "timeout"}
ALLOWED_TEMPLATES = {"xray_karte", "fax_so", "bot_s_interrupt"}
WRITE_LOCK = threading.Lock()
_TLS = threading.local()

_orig_click = BrowserActions._action_click
_orig_execute = getattr(BrowserActions, "execute_action", None)
# v3.4.0: 「新規」を押したあとに HOMIS が出す知らせのうち、新規の画面が開いていないことを表すもの
BLOCK_ALERT_WORDS = ("入力途中のカルテが存在します",)
BLOCK_ALERT_WAIT_SEC = 2.0
# 新規の画面が開くと編集タブ（最初は空の div・11/2 テスト舞子のページで確認）に「完了」ボタンが入る。
# 見つからなくても 2 秒待つだけ。誤って早く進んでも、FAX はカルテ番号なしで失敗になる（v3.4.0 の守り）
NEW_FORM_SELECTOR = "#pdetail_karteedit #karteCompletion"
# v3.8.0: 「入力途中のカルテが存在します」で止められたら、少しあけて1回だけやり直す（11/5 同じ患者さんへの FAX 3枚目で起きた・DX担当「案2」）。
# レントゲンは変えない（撮影完了の知らせの流れがあるため）。知らせの文が違うとき（unexpected_alert）もやり直さない
BLOCKED_RETRY_TEMPLATES = {"fax_so", "bot_s_interrupt"}
BLOCKED_RETRY_WAIT_SEC = 90.0
# Cloud Run の待ちの上限は 300 秒（11/5 確認）。やり直しの1回分（ログイン〜保存〜読み直し）を 120 秒と見て、
# 待つ前の経過＋待ち＋120 秒が 280 秒を超えるならやり直さない（今までどおり知らせる）
BLOCKED_RETRY_RUN_SEC = 120.0
REQUEST_BUDGET_SEC = 280.0

# v3.7.0: 前の書きかけの守り（仕様 SPEC_ライター_編集中の守り_v0.md v0.5）
JST = timezone(timedelta(hours=9))
REUSED_AFTER = timedelta(minutes=2)       # 開始時刻が新規を押した時刻よりこれ以上前なら前の書きかけ（黒ヤギ仕様2回目 指摘1）
EDIT_FIELDS_WAIT_SEC = 10.0               # 編集画面の欄が出るのを待つ上限（画面が遅いとき・0017 の型）
# 守りを見るのは、新規のあと最初の「欄に入れる」手順の直前。select は入れない（レントゲンの「指示医を選択」は医科カルテより前）
GUARD_BEFORE_ACTIONS = ("js_input", "input")
# 限界: _LEFT_KIDS はプロセスの中だけ。ライターは最大3台（maxScale=3・11/4 確認）なので、別の台が残した番号は分からない
# （そのときは時刻の判定だけで守る）
LEFT_KIDS_MAX = 200
_LEFT_KIDS: "OrderedDict[str, float]" = OrderedDict()   # 書けずに残したカルテの番号（プロセスの中だけ・再起動で消える）
# 値は覚えた時刻だが、期限は無い（200件を超えて古い順に捨てられるか、再起動まで残る）。黒ヤギ実装2回目 指摘1
_LEFT_LOCK = threading.Lock()
_EDIT_FIELDS_JS = """
var r = {};
['karte_id', 'act_date', 'start_time'].forEach(function (n) {
  var e = document.querySelector('#pdetail_karteedit #' + n);
  r[n] = e ? String(e.value || '') : null;
});
return r;
"""

# v3.1.3: 途中の手順が失敗したとき、DX に「どこを確かめるか」を型紙ごとに伝える
STEP_FAIL_HINT = {
    "xray_karte": "カルテの種別（外来）や中身",
    "fax_so": "カルテの種別（電話再診）・算定不要の印・S と O の中身",
    "bot_s_interrupt": "カルテの種別（電話再診）や S の中身",
}

# v3.2.0: 書いたあと読み直す型紙と、合わなかったときの DX への文
VERIFY_TEMPLATES = {"fax_so", "bot_s_interrupt"}   # v3.5.0: 問い合わせも読み直す（中断が合格）
VERIFY_EXPECT = {"bot_s_interrupt": "interrupt"}    # 無ければ "done"（完了が合格）
VERIFY_TEXT = {
    "not_completed": "カルテが「完了」になっていません",
    "not_interrupted": "カルテが「中断」になっていません",
    "not_mine": "読み直したカルテの最後の更新者がライターではありません（別のカルテを読んでいる見込み）",
    "s_mismatch": "S が送った文と違います",
    "o_mismatch": "O が送った文と違います",
    "unverified": "書いたあとの読み直しができませんでした（書けていないとは限りません）",
}

# v3.3.0: 本番の FAX が書けなかったときの、現場用スペースへの文（理由の言葉）
FIELD_REASON = {
    "blocked:in_progress_karte": "その患者さんに入力途中のカルテ（訪問の予定など）があり、新規が開けませんでした",
    "blocked:unexpected_alert": "新規を押したあと HOMIS から知らせが出て、新規が開けませんでした",
    "no_karte_id": "カルテ番号が取れませんでした（保存できていない見込み）",
    "verify:not_completed": "保存が完了していません",
    "verify:not_interrupted": "中断で保存できていません",
    "verify:not_mine": "書いたカルテを確かめられませんでした（別のカルテの見込み）",
    "verify:s_mismatch": "S が送った文と違います",
    "verify:o_mismatch": "O が送った文と違います",
    "stopped:unverified_input": "S を入れたことを確かめられず、保存しませんでした",
    "blocked:reused_editing": "前に書けずに残った書きかけのカルテが新規で戻ってきたため、書かずに止めました",
    "locked:busy": "同じ患者さんのカルテを別の仕事が書いていて、順番を待ちましたが時間内に回ってきませんでした",
    "locked:error": "同時に書くのを防ぐ札の置き場が使えず、安全のため書きませんでした",
}


DX_EMPTY = {
    "xray_karte": (
        "レントゲンナビでカルテを空で作成した可能性があるので、"
        "確認して空なら削除してください。"
    ),
    "fax_so": (
        "つくしでカルテを空で作成した可能性があるので、"
        "確認して空なら削除してください。"
    ),
    "bot_s_interrupt": (
        "おひさまボットでカルテを空で作成した可能性があるので、"
        "確認して空なら削除してください。"
    ),
}


def _reset_opened():
    _TLS.karte_opened = False
    _TLS.blocked = ""
    _TLS.stopped = ""
    _TLS.new_pressed_at = None   # v3.7.0: 新規を押した時刻（日本時間・tz なし）
    _TLS.edit_checked = False    # v3.7.0: この回で書きかけの守りを見たか
    _TLS.current_kid = ""        # v3.7.0: この回で開いたカルテの番号（編集画面から）


def _start_order():
    """v3.7.0: 注文ごと（やり直しをまたいで残す）の印"""
    _TLS.order_first_kid = ""    # 1回目に開いたカルテの番号（同じ注文の中のやり直しの例外）
    _TLS.order_kids = []         # この注文で開いたカルテの番号すべて（やり直しの前の回も・黒ヤギ実装1回目 指摘1）
    _TLS.guard_unreadable = False


def _note_kid(kid: str) -> None:
    """この注文で開いたカルテの番号を控える（_reset_opened では消さない）"""
    kids = getattr(_TLS, "order_kids", None)
    if kid and isinstance(kids, list) and kid not in kids:
        kids.append(kid)


def _now_jst() -> datetime:
    return datetime.now(JST).replace(tzinfo=None)


def remember_left(kid: str) -> None:
    """書けずに残したカルテの番号を覚える（古い順に捨てる）"""
    if not kid:
        return
    with _LEFT_LOCK:
        _LEFT_KIDS[kid] = time.time()
        _LEFT_KIDS.move_to_end(kid)
        while len(_LEFT_KIDS) > LEFT_KIDS_MAX:
            _LEFT_KIDS.popitem(last=False)


def _is_left(kid: str) -> bool:
    with _LEFT_LOCK:
        return kid in _LEFT_KIDS


def _read_edit_fields(driver) -> dict:
    """編集画面の3つの欄を読む。出るまで EDIT_FIELDS_WAIT_SEC 待つ。読めなければ欄は None"""
    end = time.time() + EDIT_FIELDS_WAIT_SEC
    got = {}
    while True:
        try:
            got = driver.execute_script(_EDIT_FIELDS_JS) or {}
        except Exception:  # noqa: BLE001
            got = {}
        if got.get("karte_id") and got.get("act_date") and got.get("start_time"):
            return got
        if time.time() >= end:
            return got
        time.sleep(0.5)


def _judge_reused(fields: dict, pressed_at) -> str:
    """返り値: "reused"（前の書きかけ）／"ok"／"unreadable"（欄が読めない）"""
    kid = str(fields.get("karte_id") or "")
    if kid and kid == str(getattr(_TLS, "order_first_kid", "") or ""):
        return "ok"   # 同じ注文の中のやり直しで、1回目に自分が開いたカルテ（v3.6.0）
    if kid and _is_left(kid):
        return "reused"
    try:
        started = datetime.strptime(f"{fields.get('act_date')} {str(fields.get('start_time'))[:5]}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "unreadable"
    if not kid or pressed_at is None:
        return "unreadable"
    # 日付＋時刻で比べる（日付だけで比べると0時またぎで誤る・黒ヤギ仕様2回目 指摘2）
    return "reused" if pressed_at - started >= REUSED_AFTER else "ok"


def _guard_editing(driver) -> str:
    """v3.7.0: 新規のあと最初の入力の直前に1回だけ。前の書きかけなら blocked にして理由を返す"""
    _TLS.edit_checked = True
    fields = _read_edit_fields(driver)
    verdict = _judge_reused(fields, getattr(_TLS, "new_pressed_at", None))
    kid = str(fields.get("karte_id") or "")
    _TLS.current_kid = kid
    _note_kid(kid)
    logger.info("書きかけの守り: %s karte_id=%s 開始=%s %s", verdict, kid or "-",
                fields.get("act_date") or "-", fields.get("start_time") or "-")
    if verdict == "reused":
        _TLS.blocked = "reused_editing"
        return "reused_editing"
    if kid and not getattr(_TLS, "order_first_kid", ""):
        # 欄の一部が読めなくても番号が読めたら控える（やり直しを誤って止めない・黒ヤギ実装1回目 指摘2）
        _TLS.order_first_kid = kid
    if verdict == "unreadable":
        _TLS.guard_unreadable = True
    return ""


def _blocked() -> str:
    return str(getattr(_TLS, "blocked", "") or "")


def _stopped() -> str:
    """v3.6.0: stop_on_fail の手順が失敗して止めたときの手順の名前（空なら止めていない）"""
    return str(getattr(_TLS, "stopped", "") or "")


def _check_block_alert(driver) -> str:
    """新規を押した直後の知らせを見る。返り値: 止める理由（in_progress_karte／unexpected_alert）か空。
    知らせはどんな文でも閉じて止める（新規の画面が開いていないのに先へ進まない・黒ヤギ 11/2 指摘4）。
    新規の画面（完了ボタン）が出たら待たずに戻る（指摘3）"""
    end = time.time() + BLOCK_ALERT_WAIT_SEC
    while time.time() < end:
        try:
            alert = driver.switch_to.alert
            text = str(alert.text or "")
        except Exception:  # noqa: BLE001  知らせが無い
            try:
                if any(e.is_displayed() for e in driver.find_elements("css selector", NEW_FORM_SELECTOR)):
                    return ""
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.2)
            continue
        try:
            alert.accept()
        except Exception:  # noqa: BLE001
            pass
        return "in_progress_karte" if any(w in text for w in BLOCK_ALERT_WORDS) else "unexpected_alert"
    return ""


def _execute_cloud(self, action, data):
    """v3.4.0: 新規が開けなかった（blocked）あとは、どの手順も実行しない（S・O の入力や完了を押さない）
    v3.6.0: stop_on_fail の手順が失敗したら、そのあとも同じく何もしない（保存しない・on_complete も飛ぶ）"""
    if _blocked() or _stopped():
        logger.info("止めているため手順を飛ばす: %s", action.get("name", "") if isinstance(action, dict) else "")
        return False
    if (isinstance(action, dict) and action.get("action") in GUARD_BEFORE_ACTIONS and _opened()
            and not getattr(_TLS, "edit_checked", False)):
        # v3.7.0: 最初の入力の前に、前の書きかけが戻っていないかを見る（3型紙とも医科カルテのあと）。
        # レントゲンは「診察日」「開始時間」を撮影日時に書き換えるので、その前に見ること（黒ヤギ実装1回目 指摘3）
        if _guard_editing(self.driver):
            logger.warning("前の書きかけが戻ったため書かずに止める: %s", action.get("name", ""))
            return False
    ok = _orig_execute(self, action, data)
    if not ok and isinstance(action, dict) and action.get("stop_on_fail"):
        _TLS.stopped = str(action.get("name") or "stop_on_fail")
        logger.warning("確かめられない手順があるため保存せずに止める: %s", _TLS.stopped)
    return ok


def _opened() -> bool:
    return bool(getattr(_TLS, "karte_opened", False))


def _init_driver_cloud(self):
    if self.driver:
        return
    options = Options()
    options.binary_location = CHROME_BIN
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=ja-JP")
    self.driver = webdriver.Chrome(service=Service(CHROMEDRIVER), options=options)
    self.actions = BrowserActions(self.driver)
    logger.info("Chrome起動 (cloud headless)")


def _click_cloud(self, selector, selector_type="css", text_contains=""):
    if selector in ("#karteCompletion", "#karteInterruption"):
        self.driver.execute_script("window.confirm=()=>true; window.alert=()=>{};")
        logger.info("保存前にアラート自動OKを設定")
    out = _orig_click(self, selector, selector_type, text_contains)
    if selector == "#karteNew":
        _TLS.new_pressed_at = _now_jst()   # v3.7.0: 書きかけの守りで比べる相手
        _TLS.karte_opened = True
        logger.info("karte_opened=1")
        # v3.4.0: 新規の画面が開かなかった知らせ（入力途中のカルテ）なら、ここで止める
        reason = _check_block_alert(self.driver)
        if reason:
            _TLS.blocked = reason
            _TLS.karte_opened = False   # 新規は開いていない（黒ヤギ 11/2 指摘5）
            logger.warning("新規が開けないため止める（HOMIS の知らせ: %s）", reason)
            return False
    return out


def _allowed_ids():
    """書いてよい患者。None なら全員（v3.1.1: ALLOWED_HOMIS_IDS="*"・本番の切り替え用）。未設定はテスト舞子だけ"""
    raw = os.environ.get("ALLOWED_HOMIS_IDS", "2277808").strip()
    if raw == "*":
        return None
    return {x.strip() for x in raw.split(",") if x.strip()}


def _key_ok(got: str) -> bool:
    expect = os.environ.get("HOMIS_WRITER_KEY", "")
    if not expect or len(got) != len(expect):
        return False
    return hmac.compare_digest(got, expect)


def _patient_url(homis_id: str, karte_url: str) -> str:
    if karte_url and "karte_id=" in karte_url:
        return karte_url
    return f"https://homis.jp/homic/?pid=patient_detail&patient_id={homis_id}"


def _should_notify_dx(opened: bool, kid: str, err: str) -> bool:
    """新規後で未完了。完了済みの no_karte_id（#8）は対象外。"""
    if not opened or kid:
        return False
    return err != "no_karte_id"


def _template_name(data: dict) -> str:
    return str(data.get("template") or "xray_karte")


def _notify_dx_empty(order_id: str, page_url: str, template: str) -> None:
    hook = os.environ.get("DX_EMPTY_KARTE_WEBHOOK", "")
    if not hook:
        logger.warning("DX webhook 未設定 orderId=%s", order_id)
        return
    head = DX_EMPTY.get(template) or DX_EMPTY["xray_karte"]
    text = f"{head}\n{page_url}\norderId={order_id}"
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        hook,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("DXエラーChat送信 status=%s orderId=%s", resp.status, order_id)
    except (urllib.error.URLError, TimeoutError) as e:
        logger.error("DXエラーChat失敗 orderId=%s err=%s", order_id, type(e).__name__)


def _is_live_fax(data: dict) -> bool:
    """本番の FAX の注文か（試し書き FAX-MIRROR-… は現場に知らせない）"""
    oid = str(data.get("orderId") or "")
    return _template_name(data) == "fax_so" and oid.startswith("FAX-") and not oid.startswith("FAX-MIRROR-")


def _is_live_bot(data: dict) -> bool:
    """v3.5.0: 本番の問い合わせの注文か（試し書き BOT-TEST-… は現場に知らせない）"""
    oid = str(data.get("orderId") or "")
    return _template_name(data) == "bot_s_interrupt" and oid.startswith("BOT-") and not oid.startswith("BOT-TEST-")


# v3.5.0: 現場への知らせの送り先と文（型紙ごと・黒ヤギ 11/2 仕様1回目 指摘4: FAX の文が問い合わせに出ないように）
FIELD_TARGET = {
    "fax_so": ("FAX_FIELD_WEBHOOK", "FAX のカルテを書けませんでした（{why}）。HOMIS でカルテを確かめ、無ければ FAX の原本から書いてください。"),
    "bot_s_interrupt": ("BOT_FIELD_WEBHOOK", "問い合わせ（OhisamaBot）のカルテを書けませんでした（{why}）。"
                        "HOMIS でカルテを確かめ、無ければ問い合わせの画面の内容から書いてください。"),
}


def _notify_field(order_id: str, page_url: str, err: str, template: str = "fax_so") -> None:
    """本番の FAX・問い合わせが書けなかったことを現場用スペースに知らせる。例外は外に出さない（書いた結果は必ず返す）"""
    env_name, head = FIELD_TARGET.get(template, FIELD_TARGET["fax_so"])
    hook = os.environ.get(env_name, "").strip()
    if not hook:
        logger.warning("%s 未設定 orderId=%s", env_name, order_id)
        return
    why = FIELD_REASON.get(err, f"書き込みに失敗しました（{err or '理由不明'}）")
    text = head.format(why=why) + f"\n{page_url}\n注文番号 {order_id}"
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(hook, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("現場への知らせ status=%s orderId=%s", resp.status, order_id)
    except Exception as e:  # noqa: BLE001
        logger.error("現場への知らせ失敗 orderId=%s err=%s", order_id, type(e).__name__)


def _run_once(data: dict) -> dict:
    user = os.environ.get("HOMIS_USER", "")
    password = os.environ.get("HOMIS_PASSWORD", "")
    if not user or not password:
        return {"success": False, "karte_url": None, "error_type": "login"}
    TemplateEngine._init_driver = _init_driver_cloud
    BrowserActions._action_click = _click_cloud
    if _orig_execute is not None:
        BrowserActions.execute_action = _execute_cloud
    engine = TemplateEngine(
        {"homis_user": user, "homis_password": password, "test_mode": False},
        headless=True,
    )
    return engine.execute(_template_name(data), data)


def _sheet_status(success: bool, kid: str) -> str:
    if success and kid:
        return "ok"
    if success:
        return "ok_no_id"
    return "fail"


def write_karte(data: dict) -> dict:
    if _template_name(data) == "fax_so" and not str(data.get("sContent") or "").strip():
        # v3.5.0: S（発信元）が空だと HOMIS は完了で保存しない（11/2 テスト舞子で「編集中」のまま残った）。
        # 半角スペース1つなら完了まで保存できる（同日テスト舞子で確認）。DX担当「S が空のときは半角スペースを入れて」
        data = dict(data, sContent=" ")
    order_id = str(data.get("orderId") or "")
    homis_id = str(data.get("homisId") or "")
    t0 = time.time()
    sheet_row = 0
    if sheet_enabled():
        try:
            claimed = claim(order_id, str(data.get("groupId") or ""))
        except Exception:
            logger.exception("結果シート受付失敗 orderId=%s", order_id)
            return {
                "orderId": order_id,
                "success": False,
                "has_karte_id": False,
                "error_type": "sheet",
                "karte_opened": False,
                "total_sec": 0,
                "karte_id": "",
                "karte_url": "",
            }
        if not claimed.get("created") and claimed.get("status") != "accepted":
            logger.info("同じorderIdのため書かない orderId=%s status=%s", order_id, claimed.get("status"))
            return result_from_row(claimed, order_id)
        if not claimed.get("created") and claimed.get("status") == "accepted":
            logger.info("受付済み未完了のため書かない orderId=%s", order_id)
            return result_from_row(claimed, order_id)
        sheet_row = int(claimed.get("row") or 0)
    # v3.9.0: 患者さんごとの札（別の台が同じ患者さんを同時に書かない）。取れなければ書かずに知らせる（案A）
    lock = patient_lock.acquire(homis_id, order_id)
    if lock["status"] != "ok":
        return _locked_out(data, order_id, homis_id, t0, sheet_row, lock)
    _TLS.lock = (homis_id, lock["generation"])
    _TLS.keep_lock = False
    try:
        return _write_locked(data, order_id, homis_id, t0, time.time(), sheet_row, lock)
    finally:
        _release_lock(order_id)


def _locked_out(data: dict, order_id: str, homis_id: str, t0: float, sheet_row: int, lock: dict) -> dict:
    """v3.9.0: 札が取れなかった（busy＝時間内に順番が来ない／error＝置き場が使えない）。何も書かずに、
    共有ログ・現場（本番）・DX・結果シート（fail）をほかの失敗と同じ流れで出す（黒ヤギ仕様1回目 指摘3）"""
    err = "locked:busy" if lock["status"] == "busy" else "locked:error"
    total = time.time() - t0
    log_result(order_id, False, "", err, total)
    if _is_live_fax(data) or _is_live_bot(data):
        _notify_field(order_id, _patient_url(homis_id, ""), err, _template_name(data))
    navi_callback.notify_dx(
        f"HOMIS ライター（GCP）: {FIELD_REASON[err]}。何も書かずに止めました"
        f"（札 {patient_lock.lock_name(homis_id)}・待ち {lock.get('waited_sec', 0)}秒・{lock.get('reason', '')}）。"
        + ("札の置き場（LOCK_BUCKET）の設定・権限を白ヤギが確かめます。" if err == "locked:error"
           else "前の仕事が長引いているか、札が残っています（期限 5 分で消えます）。白ヤギが確かめます。")
        + f"\n{_patient_url(homis_id, '')}\norderId={order_id}",
        order_id,
    )
    if sheet_row:
        try:
            finish(sheet_row, "fail", "", err)
        except Exception:
            logger.exception("結果シート更新失敗 orderId=%s", order_id)
    return {
        "orderId": order_id,
        "success": False,
        "has_karte_id": False,
        "error_type": err,
        "karte_opened": False,
        "total_sec": round(total, 1),
        "karte_id": "",
        "karte_url": "",
        "failed_steps": [],
        "verify": "",
        "retried": "",
        "retried_blocked": "",
        "lock_waited_sec": lock.get("waited_sec", 0),
    }


def _release_lock(order_id: str) -> None:
    """v3.9.0: 札を外す。書きかけ（編集中）を残して終わったときは外さず、期限（300秒）で消えるに任せる
    （次の台が新規を押すころには書きかけが2分以上前になり、v3.7.0 の守りが時刻で止められる・黒ヤギ仕様2回目 指摘3）"""
    homis_id, generation = getattr(_TLS, "lock", ("", ""))
    _TLS.lock = ("", "")
    if not generation:
        return
    if getattr(_TLS, "keep_lock", False):
        logger.warning("書きかけを残したため札を外さない（期限で消える） %s 世代=%s orderId=%s",
                       patient_lock.lock_name(homis_id), generation, order_id)
        return
    patient_lock.release(homis_id, generation, order_id)


def _write_locked(data: dict, order_id: str, homis_id: str, t0: float, t_write: float, sheet_row: int, lock: dict) -> dict:
    """v3.9.0: 札を持っている間の書き込み（新規〜読み直し〜知らせ〜結果シート）。中身は 3.8.0 の write_karte の後半と同じ。
    t0＝受け取った時刻（共有ログの経過時間）・t_write＝札を取った時刻（やり直しの時間の見張り・黒ヤギ仕様2回目 指摘4）"""
    _start_order()
    _reset_opened()
    result = _run_once(data)
    opened = _opened()
    err = infer_error_type(result)
    if (not result.get("success")) and (not opened) and err in BEFORE_NEW:
        logger.info("新規前のみ1回リトライ orderId=%s error_type=%s", order_id, err)
        _reset_opened()
        result = _run_once(data)
        opened = _opened()
        err = infer_error_type(result)
    blocked_retry = ""
    if _blocked() == "in_progress_karte" and _template_name(data) in BLOCKED_RETRY_TEMPLATES:
        # v3.8.0: 新規は開いていない（何も書いていない）。少しあけて1回だけ最初からやり直す
        spent = time.time() - t_write   # v3.9.0: 札を取ってから数える（札待ちの時間は入れない）
        if spent + BLOCKED_RETRY_WAIT_SEC + BLOCKED_RETRY_RUN_SEC <= REQUEST_BUDGET_SEC:
            blocked_retry = "in_progress_karte"
            logger.warning("入力途中のカルテで止められたため %s 秒あけて1回だけやり直す orderId=%s",
                           int(BLOCKED_RETRY_WAIT_SEC), order_id)
            time.sleep(BLOCKED_RETRY_WAIT_SEC)
            _reset_opened()
            result = _run_once(data)
            opened = _opened()
            err = infer_error_type(result)
        else:
            logger.warning("入力途中のカルテで止められたが、時間が足りないのでやり直さない orderId=%s 経過=%.0f秒", order_id, spent)
    left_editing = ""
    if _stopped() and time.time() - t_write + BLOCKED_RETRY_RUN_SEC > REQUEST_BUDGET_SEC:
        # v3.8.0: 入力途中のやり直しのあとなどで時間が足りない。上限で切られると知らせが出ないので、やり直さず失敗で知らせる
        logger.warning("保存せずに止めたが、時間が足りないのでやり直さない orderId=%s 経過=%.0f秒", order_id, time.time() - t_write)
    elif _stopped():
        # v3.6.0: 保存せずに止めた（書きかけは編集中で残る）。同じアカウントの新規で同じカルテが戻るので、1回だけやり直す
        left_editing = _stopped()
        logger.warning("保存せずに止めたため1回だけやり直す orderId=%s 手順=%s", order_id, left_editing)
        _reset_opened()
        result = _run_once(data)
        opened = _opened()
        err = infer_error_type(result)
    if opened and (not result.get("success") or err.startswith("step:")):
        if err != "no_karte_id":
            err = err or "opened_then_fail"
    url = result.get("karte_url") or ""
    kid = extract_karte_id(url)
    blocked = _blocked()
    stopped = _stopped()
    # v3.9.0: この注文が書きかけ（編集中）を残して終わるときは札を外さない（_release_lock）。
    # stopped＝2回とも S を確かめられず保存しなかった／left_editing かつ blocked＝1回目の書きかけが残ったまま2回目が新規で止まった／
    # opened かつ kid なし＝新規は開いたのにカルテ番号が取れずに終わった（保存できていない見込み・黒ヤギ実装1回目 指摘3）。
    # reused_editing（前の注文の書きかけが戻った）もここに入るが、外さなくても害は無い（次の台は v3.7.0 の守りで止まる）
    _TLS.keep_lock = bool(stopped) or bool(left_editing and blocked) or bool(opened and not kid)
    if blocked:
        # v3.4.0: 新規が開けず止めた。何も保存していない（以後の手順は飛ばした）
        result["success"] = False
        err = "blocked:" + blocked
        kid, url = "", ""
    elif stopped:
        # v3.6.0: やり直しでも確かめられなかった。保存していない（書きかけは編集中で残る）
        result["success"] = False
        err = "stopped:unverified_input"
        kid, url = "", ""
    elif _template_name(data) in ("fax_so", "bot_s_interrupt") and not kid and result.get("success"):
        # v3.4.0: カルテ番号が取れないのに成功扱いにしない（11/2 11:36 現場に知らせが出なかった）。v3.5.0: 問い合わせも同じ
        result["success"] = False
        err = err or "no_karte_id"
    checked = None
    if _template_name(data) in VERIFY_TEMPLATES and result.get("success") and kid:
        # v3.2.0: カルテ番号が取れても、保存されたとは限らない（10/23〜28 Tukusi で7件が空のまま成功扱い）。読み直して確かめる
        checked = verify_karte.verify(homis_id, kid, str(data.get("sContent") or ""), str(data.get("oContent") or ""),
                                      expect=VERIFY_EXPECT.get(_template_name(data), "done"))
        logger.info("読み直し orderId=%s verdict=%s status=%s reads=%s s_len=%s o_len=%s reason=%s", order_id,
                    checked["verdict"], checked["status"], checked["reads"], checked["s_len"], checked["o_len"], checked["reason"])
        if checked["verdict"] != "ok":
            navi_callback.notify_dx(
                "HOMIS ライター（GCP）: " + VERIFY_TEXT.get(checked["verdict"], checked["verdict"])
                + f"（状態 {checked.get('status_label') or checked['status'] or '－'}）。HOMIS でカルテを確かめてください。"
                + f"\n{_patient_url(homis_id, url)}\norderId={order_id}",
                order_id,
            )
        if checked["verdict"] in ("not_completed", "not_interrupted", "not_mine", "s_mismatch", "o_mismatch"):
            result["success"] = False
            err = "verify:" + checked["verdict"]
    total = time.time() - t0
    log_result(order_id, bool(result.get("success")), kid, err, total)
    if (_is_live_fax(data) or _is_live_bot(data)) and not result.get("success"):
        _notify_field(order_id, _patient_url(homis_id, url), err, _template_name(data))
    if blocked:
        why = FIELD_REASON.get("blocked:" + blocked, blocked)
        if _template_name(data) == "fax_so":
            # 黒ヤギ 11/2 指摘1: 同じ注文番号は二重よけ（結果の表・列の名前）で弾かれる。live では本文をどこにも残さない
            # （受け口の決まり）ので fax_requeue（試し書きから読む）も使えない。Tukusi への送り直しなら新しい札＝新しい注文番号になる
            how = ("現場には「FAX の原本から書いてください」と知らせました。白ヤギが戻すときは、入力途中のカルテが片付いてから "
                   "OhiScanGo\\tools\\tukusi_resend で Tukusi に送り直します（新しい札になるので二重よけに当たらない）。"
                   "tools\\fax_requeue.py は使えません（同じ注文番号・live では試し書きが無い）。")
        elif _template_name(data) == "bot_s_interrupt":
            # v3.5.0: 問い合わせは本文がどこにも残らない（受け口の決まり）。直しの再送なら新しい注文番号になる
            how = ("現場（問い合わせ用の Chat）には「問い合わせの画面の内容から書いてください」と知らせました。"
                   "入力途中のカルテが片付いたあと、問い合わせを直して送り直せば、新しい注文番号で書けます。")
        else:
            how = "入力途中のカルテが片付いてから、送り元（レントゲンナビ等）から送り直すか、手でカルテを書いてください。"   # 指摘2
        if blocked == "reused_editing":
            how += (f"\n戻ってきたのはカルテ {getattr(_TLS, 'current_kid', '') or '（番号不明）'}"
                    "（前にライターが書けずに残した書きかけ）。白ヤギがその日のうちに取り消します。")
        if blocked_retry and blocked == "in_progress_karte":
            how += f"\n※{int(BLOCKED_RETRY_WAIT_SEC)}秒あけて1回やり直しましたが、同じ知らせで止められました。"
        elif blocked_retry:
            # 黒ヤギ v3.8.0 指摘2: やり直しの2回目が別の理由で止まったときも、待ってやり直した経緯を残す
            how += f"\n※1回目は「入力途中のカルテ」で止められ、{int(BLOCKED_RETRY_WAIT_SEC)}秒あけてやり直した2回目で、上の理由で止まりました。"
        if left_editing:
            how += f"\n※1回目に「{left_editing}」を確かめられず保存せずに止めたため、ライターの書きかけ（編集中）が1枚残っています。"
        navi_callback.notify_dx(
            f"HOMIS ライター（GCP）: {why}。何も書かずに止めました。\n{how}"
            f"\n{_patient_url(homis_id, '')}\norderId={order_id}",
            order_id,
        )
    elif stopped:
        navi_callback.notify_dx(
            f"HOMIS ライター（GCP）: 「{stopped}」を確かめられず、保存せずに止めました"
            # 黒ヤギ v3.8.0 指摘1: 時間が足りずにやり直さなかったときは「やり直しても同じ」と書かない
            + ("（やり直しても同じ）。" if left_editing else "（時間が足りないため、やり直していません）。")
            + (f"1回目は「入力途中のカルテ」で止められ、{int(BLOCKED_RETRY_WAIT_SEC)}秒あけてやり直していました。" if blocked_retry else "")
            + "ライターの書きかけ（編集中）が1枚残っています。次にライターがこの患者さんの新規を開くと、そのカルテが戻って使われます。"
            "残したくなければ白ヤギが取り消します。"
            + ("現場（問い合わせ用の Chat）には「問い合わせの画面の内容から書いてください」と知らせました。" if _is_live_bot(data) else "")
            + f"\n{_patient_url(homis_id, '')}\norderId={order_id}",
            order_id,
        )
    elif _should_notify_dx(opened, kid, err):
        _notify_dx_empty(order_id, _patient_url(homis_id, url), _template_name(data))
    for k in list(getattr(_TLS, "order_kids", []) or []):
        # v3.7.0: 書けずに終わったカルテの番号を覚える（次の新規で戻ったら時刻に関係なく止める）。
        # やり直しの前の回に開いた番号も含める（黒ヤギ実装1回目 指摘1）。書けたカルテ（kid）は覚えない
        if not result.get("success") or k != kid:
            remember_left(k)
    if getattr(_TLS, "guard_unreadable", False):
        # v3.7.0: 守りの欄が読めなかった。書くのは止めないが、黙って守りが外れないよう知らせる（黒ヤギ仕様2回目 指摘3）
        navi_callback.notify_dx(
            "HOMIS ライター（GCP）: 前の書きかけの守りで、編集画面の欄（カルテ番号・診察日・開始時刻）が読めず、守りを飛ばしました。"
            "HOMIS の画面が変わった見込みがあります（白ヤギが確かめます）。"
            f"\n{_patient_url(homis_id, url)}\norderId={order_id}",
            order_id,
        )
    failed_steps = [str(s) for s in (result.get("failed_steps") or [])]
    if result.get("success") and kid and failed_steps:
        # v3.1.2: カルテ番号が取れても、途中の手順の失敗は黙らない（10/16 に「外来を選択」が失敗し、種別が定期のまま保存された）
        # v3.1.3: 確かめる所を型紙ごとに（黒ヤギ 10/27 指摘2: FAX の失敗でも「外来」と出ていた）
        check_hint = STEP_FAIL_HINT.get(_template_name(data), "カルテの中身")
        navi_callback.notify_dx(
            "HOMIS ライター（GCP）: カルテは保存しましたが、途中の手順が失敗しました: " + "・".join(failed_steps)
            + f"\n{check_hint}を確認し、違っていれば HOMIS で直してください。"
            + f"\n{_patient_url(homis_id, url)}\norderId={order_id}",
            order_id,
        )
    if sheet_row:
        try:
            finish(sheet_row, _sheet_status(bool(result.get("success")), kid), url, err)
        except Exception:
            logger.exception("結果シート更新失敗 orderId=%s", order_id)
    return {
        "orderId": order_id,
        "success": bool(result.get("success")),
        "has_karte_id": bool(kid),
        "error_type": err,
        "karte_opened": opened,
        "total_sec": round(total, 1),
        "karte_id": kid,
        "karte_url": url,
        "failed_steps": failed_steps,
        "verify": checked["verdict"] if checked else "",
        "retried": left_editing,   # v3.6.0: 1回目に止めた手順の名前（やり直さなかったら空）
        "retried_blocked": blocked_retry,   # v3.8.0: 入力途中のカルテで止められて、あけてやり直したら "in_progress_karte"
        "lock_waited_sec": lock.get("waited_sec", 0),   # v3.9.0: 札を待った秒
    }


class Handler(BaseHTTPRequestHandler):
    # v3.1.0: 受け取りの読み書きの待ちに上限（送る側が途中で止まっても待ち続けない。黒ヤギ 10/15 指摘3）
    # HOMIS に書いている時間はここに含まれない（ソケットを読み書きしている間だけの上限）
    timeout = 60

    def log_message(self, fmt, *args):
        logger.info(fmt, *args)

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send(200, {"ok": True, "service": "homis-karte-writer"})
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def _drain(self):
        """断るときも本文を読み切る（読まずに閉じると、送る側が「接続を切られた」になり応答コードが読めない）"""
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            return
        if 0 < length <= 200000:
            self.rfile.read(length)

    def _auth_and_body(self):
        """合言葉と本文の確かめ。だめなら応答を返して None"""
        if not os.environ.get("HOMIS_WRITER_KEY"):
            logger.error("HOMIS_WRITER_KEY が空")
            self._drain()
            self._send(503, {"ok": False, "error": "key_not_set"})
            return None
        if not _key_ok(self.headers.get("X-Writer-Key", "")):
            self._drain()
            self._send(401, {"ok": False, "error": "unauthorized"})
            return None
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._send(400, {"ok": False, "error": "bad_body"})
            return None
        if length <= 0 or length > 200000:
            self._send(400, {"ok": False, "error": "bad_body"})
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"ok": False, "error": "bad_json"})
            return None
        if not isinstance(data, dict):
            self._send(400, {"ok": False, "error": "bad_json"})
            return None
        return data

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/write", "/check-group"):
            self._send(404, {"ok": False, "error": "not_found"})
            return
        data = self._auth_and_body()
        if data is None:
            return
        if path == "/check-group":
            # v3.1.0: 集団の確かめ役（Cloud Tasks の予約から）。判定と DX Chat はナビ側
            group_id = str(data.get("groupId") or "")
            if not group_id:
                self._send(400, {"ok": False, "error": "missing_group_id"})
                return
            res = navi_callback.check_group(group_id)
            self._send(200, {"ok": True, "navi": res})
            return
        order_id = str(data.get("orderId") or "")
        homis_id = str(data.get("homisId") or "")
        if not order_id or not homis_id:
            self._send(400, {"ok": False, "error": "missing_ids"})
            return
        template = _template_name(data)
        allowed = _allowed_ids()
        if allowed is not None and homis_id not in allowed:
            logger.warning("拒否 homisId は許可リスト外 orderId=%s", order_id)
            out = {"ok": False, "error": "homis_id_not_allowed"}
            # v3.1.1: 黙って止めない。ナビに空の URL で知らせ（撮影完了 Chat は患者ページで出る）、DX にも知らせる
            if template == "xray_karte" and navi_callback.enabled():
                try:
                    out["navi"] = navi_callback.notify_karte(order_id, "")
                    navi_callback.notify_dx(
                        "HOMIS ライター（GCP）: 書いてよい患者の設定（ALLOWED_HOMIS_IDS）の外なので、カルテを書きませんでした。"
                        f"\norderId={order_id}\n（撮影完了 Chat は患者ページで出ています。設定を確かめ、カルテは手で作ってください）",
                        order_id,
                    )
                except Exception as e:
                    logger.error("許可外の知らせで予期しない例外 orderId=%s err=%s", order_id, type(e).__name__)
            self._send(403, out)
            return
        if template not in ALLOWED_TEMPLATES:
            self._send(400, {"ok": False, "error": "unknown_template"})
            return
        if template == "fax_so" and not str(data.get("oContent") or ""):
            # v3.5.0: S（発信元）は空でもよい。O（本文）が無いときだけ断る（11/2 札 -13・DX担当「空でいい」）
            self._send(400, {"ok": False, "error": "missing_so"})
            return
        if template == "bot_s_interrupt" and not str(data.get("sContent") or ""):
            self._send(400, {"ok": False, "error": "missing_s"})
            return
        logger.info("書き込み開始 orderId=%s homisId=%s template=%s", order_id, homis_id, template)
        with WRITE_LOCK:
            out = write_karte(data)
        err = out.get("error_type") or ""
        if err in ("duplicate", "already_accepted"):
            code = 409
        elif err == "sheet":
            code = 503
        elif out.get("success"):
            code = 200
        else:
            code = 500
        # v3.1.0: 書き終えたらナビに知らせる（垂水 Python と同じ）。成功・失敗とも知らせる（撮影完了 Chat は止めない）
        # 直リンク（karte_id 入り）だけ渡し、取れなければ空＝ナビが患者ページで出す（仕様 7.2 #8）
        # 同じ注文の2回目（409）と結果シートの失敗（503）は知らせない（1回目が知らせる／書いていない）
        if template == "xray_karte" and code in (200, 500) and navi_callback.enabled():
            url = out.get("karte_url") or ""
            try:
                out["navi"] = navi_callback.notify_karte(order_id, url if "karte_id=" in url else "")
            except Exception as e:  # 知らせで思わぬ失敗があっても、書いた結果は必ず返す（黒ヤギ 10/15 指摘1）
                logger.error("ナビへの知らせで予期しない例外 orderId=%s err=%s", order_id, type(e).__name__)
                out["navi"] = {"delivered": False, "success": False, "attempts": 0, "message": type(e).__name__}
        self._send(code, out)


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("listen :%s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
