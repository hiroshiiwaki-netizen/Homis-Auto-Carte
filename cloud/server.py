# -*- coding: utf-8 -*-
"""Cloud Run 受け口（フェーズ2a＋失敗ガード）

==============================================================================
バージョン: 3.3.0
最終更新: 2026/10/29
改定履歴（新しい順・全体は docs/SPEC_v3_cloud.md 0章「モジュール別の版」）:
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

import navi_callback
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

# v3.1.3: 途中の手順が失敗したとき、DX に「どこを確かめるか」を型紙ごとに伝える
STEP_FAIL_HINT = {
    "xray_karte": "カルテの種別（外来）や中身",
    "fax_so": "カルテの種別（電話再診）・算定不要の印・S と O の中身",
    "bot_s_interrupt": "カルテの種別（電話再診）や S の中身",
}

# v3.2.0: 書いたあと読み直す型紙と、合わなかったときの DX への文
VERIFY_TEMPLATES = {"fax_so"}
VERIFY_TEXT = {
    "not_completed": "カルテが「完了」になっていません",
    "s_mismatch": "S が送った文と違います",
    "o_mismatch": "O が送った文と違います",
    "unverified": "書いたあとの読み直しができませんでした（書けていないとは限りません）",
}

# v3.3.0: 本番の FAX が書けなかったときの、現場用スペースへの文（理由の言葉）
FIELD_REASON = {
    "verify:not_completed": "保存が完了していません",
    "verify:s_mismatch": "S が送った文と違います",
    "verify:o_mismatch": "O が送った文と違います",
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
        _TLS.karte_opened = True
        logger.info("karte_opened=1")
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


def _notify_field(order_id: str, page_url: str, err: str) -> None:
    """本番の FAX が書けなかったことを現場用スペースに知らせる。例外は外に出さない（書いた結果は必ず返す）"""
    hook = os.environ.get("FAX_FIELD_WEBHOOK", "").strip()
    if not hook:
        logger.warning("FAX_FIELD_WEBHOOK 未設定 orderId=%s", order_id)
        return
    why = FIELD_REASON.get(err, f"書き込みに失敗しました（{err or '理由不明'}）")
    text = f"FAX のカルテを書けませんでした（{why}）。HOMIS でカルテを確かめ、無ければ FAX の原本から書いてください。\n{page_url}\n注文番号 {order_id}"
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
    if opened and (not result.get("success") or err.startswith("step:")):
        if err != "no_karte_id":
            err = err or "opened_then_fail"
    url = result.get("karte_url") or ""
    kid = extract_karte_id(url)
    checked = None
    if _template_name(data) in VERIFY_TEMPLATES and result.get("success") and kid:
        # v3.2.0: カルテ番号が取れても、保存されたとは限らない（10/23〜28 Tukusi で7件が空のまま成功扱い）。読み直して確かめる
        checked = verify_karte.verify(homis_id, kid, str(data.get("sContent") or ""), str(data.get("oContent") or ""))
        logger.info("読み直し orderId=%s verdict=%s status=%s reads=%s s_len=%s o_len=%s reason=%s", order_id,
                    checked["verdict"], checked["status"], checked["reads"], checked["s_len"], checked["o_len"], checked["reason"])
        if checked["verdict"] != "ok":
            navi_callback.notify_dx(
                "HOMIS ライター（GCP）: " + VERIFY_TEXT.get(checked["verdict"], checked["verdict"])
                + f"（状態 {checked.get('status_label') or checked['status'] or '－'}）。HOMIS でカルテを確かめてください。"
                + f"\n{_patient_url(homis_id, url)}\norderId={order_id}",
                order_id,
            )
        if checked["verdict"] in ("not_completed", "s_mismatch", "o_mismatch"):
            result["success"] = False
            err = "verify:" + checked["verdict"]
    total = time.time() - t0
    log_result(order_id, bool(result.get("success")), kid, err, total)
    if _is_live_fax(data) and not result.get("success"):
        _notify_field(order_id, _patient_url(homis_id, url), err)
    if _should_notify_dx(opened, kid, err):
        _notify_dx_empty(order_id, _patient_url(homis_id, url), _template_name(data))
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
        if template == "fax_so" and (
            not str(data.get("sContent") or "") or not str(data.get("oContent") or "")
        ):
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
