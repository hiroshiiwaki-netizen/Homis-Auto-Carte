# -*- coding: utf-8 -*-
"""Cloud Run Job: テスト舞子へレントゲン相当のカルテを1件書く。"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from browser_actions import BrowserActions
from template_engine import TemplateEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("write_once")

JST = timezone(timedelta(hours=9))
TEST_HOMIS_ID = "2277808"
CHROME_BIN = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
CHROMEDRIVER = os.environ.get("CHROMEDRIVER", "/usr/bin/chromedriver")


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


_orig_click = BrowserActions._action_click


def _click_cloud(self, selector, selector_type="css", text_contains=""):
    if selector == "#karteCompletion":
        self.driver.execute_script("window.confirm=()=>true; window.alert=()=>{};")
        logger.info("完了前にアラート自動OKを設定")
    return _orig_click(self, selector, selector_type, text_contains)


def build_payload():
    now = datetime.now(JST)
    start = now.strftime("%H:%M")
    end = (now + timedelta(minutes=10)).strftime("%H:%M")
    date_iso = now.strftime("%Y-%m-%d")
    date_us = now.strftime("%Y_%m_%d")
    order_id = f"GCP-TEST-{now.strftime('%Y%m%d-%H%M%S')}"
    purpose = "GCP Cloud Run接続確認"
    return order_id, {
        "orderId": order_id,
        "homisId": TEST_HOMIS_ID,
        "patientName": "テスト舞子",
        "shootingDate": date_iso,
        "shootingTime": start,
        "shootingTimeEnd": end,
        "requestDate": date_us,
        "doctorName": "山口 高秀",
        "orcaNumber": "000003 ",
        "sContent": f"胸部正面レントゲン\n{purpose}",
        "apContent": (
            "指示医：山口 高秀\n"
            f"000003 テスト舞子様XP {date_us} XP依頼日: {date_us}\n"
            f"目的：{purpose}\n"
            "部位：胸部正面PA（立位）\n"
            "撮影枚数：2枚\n"
            "\n"
            "合計：2枚"
        ),
    }


def main():
    user = os.environ.get("HOMIS_USER", "")
    password = os.environ.get("HOMIS_PASSWORD", "")
    if not user or not password:
        logger.error("HOMIS_USER / HOMIS_PASSWORD が空です")
        print("RESULT " + json.dumps({"success": False, "error": "missing_secret"}))
        return 2

    TemplateEngine._init_driver = _init_driver_cloud
    BrowserActions._action_click = _click_cloud
    order_id, data = build_payload()
    logger.info("書き込み開始 orderId=%s homisId=%s", order_id, TEST_HOMIS_ID)

    engine = TemplateEngine(
        {"homis_user": user, "homis_password": password, "test_mode": False},
        headless=True,
    )
    t0 = time.time()
    result = engine.execute("xray_karte", data)
    karte_url = result.get("karte_url") or ""
    from shared_log import extract_karte_id, infer_error_type, log_result
    kid = extract_karte_id(karte_url)
    log_result(
        order_id,
        bool(result.get("success")),
        kid,
        infer_error_type(result),
        time.time() - t0,
    )
    out = {
        "orderId": order_id,
        "success": bool(result.get("success")),
        "has_karte_id": bool(kid),
        "error_type": infer_error_type(result),
        "karte_id": kid,
        "karte_url": karte_url,
    }
    print("RESULT " + json.dumps(out, ensure_ascii=False))
    return 0 if out["success"] and out["has_karte_id"] else 1


if __name__ == "__main__":
    sys.exit(main())
