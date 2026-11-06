# -*- coding: utf-8 -*-
"""書込失敗の自動やり直し（仕様 docs/SPEC_実行リスト_v0.md v1.2 14章・黒ヤギ 仕様3回【進めてよい】）

版: 1.1.0
最終更新: 2026-11-06
改定履歴:
  v1.1.0 11/06 共通 JSON の入口 ①先生が選んだカルテに書く（型紙 karte_edit・注文番号 KE-）もやり直す（仕様 SPEC_共通JSON入口_v0.md 7章）。
               列は RETRY_QUEUE_KARTE。書く前にカルテを読めなかった（karte_unreadable）もやり直してよい失敗に足す（HOMIS には何も残っていない）。
               人が書いたかは、①ではカルテ番号が増えないので、カルテの最終更新日時・更新者の控え（baseline_upd・ライター側）で見る
  v1.0.0 11/06 新規。やり直してよい失敗の判定・注文番号の回数（-A1〜-A3）・同じ列への予約つきの投入・人が書いた見込みの守り（カルテ一覧の番号）。
               RETRY_MODE が on でなければ何もしない（配置しても今まで通り）。

決まり:
  - やり直すのは HOMIS に何も残っていない失敗（left_in_homis=none）で、RETRYABLE_ERRORS のどれかのときだけ
  - 回数は注文番号の末尾を ^(.*)-A([1-3])$ でだけ読む。読めなければ 0 回。3 回目のあとはどんな場合も入れない（MAX_ATTEMPTS）
  - 2 回目以降も元の番号に付け直す（-A1-A2 にしない）
  - 列の名前＝注文番号なので、同じやり直しを 2 回入れても 409（duplicate）で 1 回になる
  - カルテ番号は数（int）で比べる。一覧が読めなければ「分からない」（呼ぶ側は書かない）
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import verify_karte

logger = logging.getLogger("auto_retry")

VERSION = "1.1.0"
MAX_ATTEMPTS = 3
DELAYS_SEC = {1: 5 * 60, 2: 15 * 60, 3: 30 * 60}   # -A1 は 5 分後・-A2 は 15 分後・-A3 は 30 分後
RETRYABLE_ERRORS = {"locked:busy", "locked:error", "blocked:in_progress_karte", "blocked:unexpected_alert",
                    "login", "chrome", "timeout", "karte_unreadable"}
RETRY_TEMPLATES = {"fax_so", "bot_s_interrupt", "karte_edit"}
ATTEMPT_RE = re.compile(r"^(.*)-A([1-3])$")
POST_TIMEOUT = 5.0
DISPATCH_DEADLINE = "900s"   # 受け口と同じ


def enabled() -> bool:
    return os.environ.get("RETRY_MODE", "").strip().lower() == "on"


def split_attempt(order_id: str) -> tuple[str, int]:
    """(元の番号, 何回目のやり直しか)。末尾が -A1〜-A3 でなければ 0 回"""
    m = ATTEMPT_RE.match(str(order_id or ""))
    if not m:
        return str(order_id or ""), 0
    return m.group(1), int(m.group(2))


def next_order_id(order_id: str) -> str:
    """次のやり直しの番号。もう 3 回目なら空（入れない）"""
    base, n = split_attempt(order_id)
    if n >= MAX_ATTEMPTS:
        return ""
    return f"{base}-A{n + 1}"


def is_live_or_test(order_id: str) -> bool:
    o = split_attempt(order_id)[0]
    if o.startswith("FAX-MIRROR-"):
        return False
    return o.startswith("FAX-") or o.startswith("BOT-") or o.startswith("KE-")   # BOT-G-・BOT-TEST-・KE-TEST- を含む


def eligible(template: str, order_id: str, err: str, left: str) -> bool:
    """やり直してよい失敗か（仕様 14.1）。RETRY_MODE が on でなければ False"""
    if not enabled():
        return False
    if template not in RETRY_TEMPLATES or not is_live_or_test(order_id):
        return False
    if left != "none" or err not in RETRYABLE_ERRORS:
        return False
    return next_order_id(order_id) != ""


def queue_for(template: str) -> str:
    name = {"fax_so": "RETRY_QUEUE_FAX", "karte_edit": "RETRY_QUEUE_KARTE"}.get(template, "RETRY_QUEUE_BOT")
    return os.environ.get(name, "").strip().strip("/")


def _access_token() -> str:
    url = os.environ.get("METADATA_TOKEN_URL",
                         "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token")
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=POST_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def build_task(queue: str, payload: dict, delay_sec: int, now: datetime | None = None) -> dict:
    """列に入れる仕事（受け口の _build_task と同じ形＋予約の時刻）"""
    writer = os.environ.get("WRITER_URL", "").rstrip("/")
    at = (now or datetime.now(timezone.utc)) + timedelta(seconds=delay_sec)
    return {"task": {
        "name": queue + "/tasks/" + payload["orderId"],
        "scheduleTime": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dispatchDeadline": DISPATCH_DEADLINE,
        "httpRequest": {
            "url": writer + "/write",
            "httpMethod": "POST",
            "headers": {"Content-Type": "application/json", "X-Writer-Key": os.environ.get("HOMIS_WRITER_KEY", "").strip()},
            "body": base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii"),
            "oidcToken": {"serviceAccountEmail": os.environ.get("TASKS_INVOKER_SA", ""), "audience": writer},
        },
    }}


def _post_once(queue: str, task: dict) -> str:
    try:
        base = os.environ.get("CLOUD_TASKS_BASE", "https://cloudtasks.googleapis.com/v2/")
        req = urllib.request.Request(base.rstrip("/") + "/" + queue + "/tasks", data=json.dumps(task).encode("utf-8"),
                                     method="POST", headers={"Authorization": "Bearer " + _access_token(),
                                                             "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=POST_TIMEOUT):
            return "queued"
    except urllib.error.HTTPError as e:
        return "duplicate" if e.code == 409 else f"error:http{e.code}"
    except Exception as e:  # noqa: BLE001
        return "error:" + type(e).__name__


def enqueue(template: str, payload: dict, delay_sec: int) -> str:
    """やり直しを列に入れる。queued／duplicate（もう入っている）／error:…。例外は外に出さない。
    通信の失敗（返事が無い）のときだけ 1 回やり直す（受け口 0.5.1 と同じ・名前が同じなので二重にならない）"""
    queue = queue_for(template)
    if not all([queue, os.environ.get("WRITER_URL", "").strip(), os.environ.get("TASKS_INVOKER_SA", "").strip(),
                os.environ.get("HOMIS_WRITER_KEY", "").strip()]):
        return "error:no_config"
    task = build_task(queue, payload, delay_sec)
    word = _post_once(queue, task)
    if word.startswith("error:") and not word.startswith("error:http"):
        word = _post_once(queue, task)
    return word


def latest_karte_id(homis_id: str) -> int | None:
    """その患者さんのカルテ一覧（読むだけ）の一番大きいカルテ番号。カルテが無ければ 0。読めなければ None（分からない）"""
    user = os.environ.get("HOMIS_USER", "")
    password = os.environ.get("HOMIS_PASSWORD", "")
    if not user or not password or not re.match(r"^[1-9][0-9]{0,9}$", str(homis_id or "")):
        return None
    try:
        op = verify_karte._opener()
        verify_karte._login(op, user, password)
        q = urllib.parse.urlencode({"patient_id": homis_id})
        with op.open(verify_karte.BASE + "functions/getKarteList.php?" + q, timeout=verify_karte.TIMEOUT_SEC) as r:
            items = json.loads(r.read().decode("utf-8", errors="replace"))
        if not isinstance(items, list):
            return None
        ids = [int(str(k.get("karte_id"))) for k in items if isinstance(k, dict) and str(k.get("karte_id") or "").isdigit()]
        return max(ids) if ids else 0
    except Exception as e:  # noqa: BLE001  分からないときは「分からない」（呼ぶ側は書かない）
        logger.warning("カルテ一覧を読めなかった homis=%s 理由=%s", "***", type(e).__name__)
        return None


def human_wrote(homis_id: str, baseline) -> tuple[bool, int | None]:
    """人が書いた見込みか（仕様 14.2b）。返り値 (書かずに止めるか, 今の一番大きい番号)。
    控えが無い・一覧が読めない → 止める（分からないときは書かない）。控えより大きい番号がある → 止める。数で比べる"""
    try:
        base = int(str(baseline))
    except (TypeError, ValueError):
        return True, None
    now = latest_karte_id(homis_id)
    if now is None:
        return True, None
    return now > base, now
