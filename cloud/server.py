# -*- coding: utf-8 -*-
"""Cloud Run 受け口（フェーズ2a＋失敗ガード）

GET  /health  生存確認（合言葉不要）
POST /write   HOMIS 書き込み。同期。ナビ切替はまだしない。

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
    raw = os.environ.get("ALLOWED_HOMIS_IDS", "2277808")
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
    total = time.time() - t0
    log_result(order_id, bool(result.get("success")), kid, err, total)
    if _should_notify_dx(opened, kid, err):
        _notify_dx_empty(order_id, _patient_url(homis_id, url), _template_name(data))
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
    }


class Handler(BaseHTTPRequestHandler):
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

    def do_POST(self):
        if self.path.split("?")[0] != "/write":
            self._send(404, {"ok": False, "error": "not_found"})
            return
        if not os.environ.get("HOMIS_WRITER_KEY"):
            logger.error("HOMIS_WRITER_KEY が空")
            self._send(503, {"ok": False, "error": "key_not_set"})
            return
        if not _key_ok(self.headers.get("X-Writer-Key", "")):
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._send(400, {"ok": False, "error": "bad_body"})
            return
        if length <= 0 or length > 200000:
            self._send(400, {"ok": False, "error": "bad_body"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"ok": False, "error": "bad_json"})
            return
        if not isinstance(data, dict):
            self._send(400, {"ok": False, "error": "bad_json"})
            return
        order_id = str(data.get("orderId") or "")
        homis_id = str(data.get("homisId") or "")
        if not order_id or not homis_id:
            self._send(400, {"ok": False, "error": "missing_ids"})
            return
        if homis_id not in _allowed_ids():
            logger.warning("拒否 homisId は許可リスト外 orderId=%s", order_id)
            self._send(403, {"ok": False, "error": "homis_id_not_allowed"})
            return
        template = _template_name(data)
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
        self._send(code, out)


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("listen :%s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
