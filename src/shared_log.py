# -*- coding: utf-8 -*-
"""共有フォルダへの人間向けログ（OhiScanGo方式）

Watchdog が読む heartbeat は C:\\HomisKarteWriter に残す。
人が読むログは HomisKarteWriter\\logs へ、1行ごとに開いて閉じて書く。
患者名・S/AP本文・パスワードは出さない。
"""

import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from paths import LOG_DIR, STATE_DIR

logger = logging.getLogger(__name__)

# Watchdog.bat 用の ASCII パス（ジャンクション先 = LOG_DIR）
LOCAL_SHARE_LINK = Path(r"C:\HomisKarteWriter\shared_logs")


def append_today(prefix: str, text: str, add_timestamp: bool = True) -> None:
    """日付付きファイルに1行追記してすぐ閉じる（Drive同期のため）"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now().strftime("%Y%m%d")
        path = LOG_DIR / f"{prefix}_{day}.log"
        line = text if not add_timestamp else (
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {text}"
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
            f.flush()
    except Exception:
        pass


def append_named(filename: str, text: str) -> None:
    """固定名ファイル（startup_error.log など）へ追記"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / filename, "a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
            f.flush()
    except Exception:
        pass


def write_shared_heartbeat(payload: str) -> None:
    """心拍のコピー。Watchdog の判定には使わない（閲覧用）"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "heartbeat.txt", "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
    except Exception:
        pass


def ensure_local_share_link() -> None:
    """C:\\HomisKarteWriter\\shared_logs → 共有 logs（bat が日本語パスを書かないため）"""
    try:
        if LOCAL_SHARE_LINK.exists() or not STATE_DIR.exists():
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(LOCAL_SHARE_LINK), str(LOG_DIR)],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass


def extract_karte_id(url: str) -> str:
    if not url or "karte_id=" not in url:
        return ""
    try:
        return (parse_qs(urlparse(url).query).get("karte_id") or [""])[0]
    except Exception:
        return ""


def infer_error_type(result: dict) -> str:
    if result.get("error_type"):
        return str(result["error_type"])
    err = str(result.get("error") or "").lower()
    if "invalid session" in err or "chrome" in err or "webdriver" in err:
        return "chrome"
    if "timeout" in err or "timed out" in err:
        return "timeout"
    if "login" in err:
        return "login"
    url = result.get("karte_url") or ""
    if result.get("success") and "karte_id=" not in url:
        return "no_karte_id"
    if not result.get("success"):
        return "unknown"
    return ""


def log_step(name: str, ok: bool, seconds: float) -> None:
    status = "ok" if ok else "fail"
    line = f"STEP {name} {status} {seconds:.1f}s"
    append_today("writer", line)
    logger.info(line)


def log_result(
    order_id: str,
    success: bool,
    karte_id: str,
    error_type: str,
    total_sec: float,
) -> None:
    payload = {
        "orderId": order_id or "",
        "success": bool(success),
        "has_karte_id": bool(karte_id),
        "error_type": error_type or "",
        "total_sec": round(float(total_sec), 1),
        "karte_id": karte_id or "",
    }
    line = "RESULT " + json.dumps(payload, ensure_ascii=False)
    append_today("writer", line)
    logger.info(line)


class DailyAppendHandler(logging.Handler):
    """起動日ではなく、書いた日の watcher_YYYYMMDD.log に出す"""

    def __init__(self, prefix: str = "watcher"):
        super().__init__()
        self.prefix = prefix

    def emit(self, record: logging.LogRecord) -> None:
        try:
            append_today(self.prefix, self.format(record), add_timestamp=False)
        except Exception:
            self.handleError(record)


class timed_step:
    """with ブロックで STEP 1行を出す"""

    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self._t0 = 0.0

    def __enter__(self) -> "timed_step":
        self._t0 = time.time()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        ok = self.ok and exc_type is None
        log_step(self.name, ok, time.time() - self._t0)
        return None
