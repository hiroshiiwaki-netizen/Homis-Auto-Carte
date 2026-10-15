# -*- coding: utf-8 -*-
"""ナビ（レントゲンナビ GAS）への知らせ

==============================================================================
バージョン: 3.1.0
最終更新: 2026/10/15
改定履歴（新しい順・全体は docs/SPEC_v3_cloud.md 0章「モジュール別の版」）:
  v3.1.0 10/15 新規。書き終えたらナビの doPost に知らせる（垂水 Python の gas_api.py と同じ形）
               ・集団の確かめ役（checkGroupComplete）を中継（GCP 移行計画 v0.4 フェーズ1）
==============================================================================

- 送る形は垂水 Python（src/gas_api.py）と同じ: {"action": "updateHomisLink", "orderId", "homisUrl"}
- 再送は「応答が無い（通信の失敗・時間切れ）」か「HTTP 5xx」のときだけ。最大 3 回（間 5秒・15秒）
  ナビが 200 で success=false（注文が見つからない等）を返したときは再送しない
- 3 回ともだめ、またはナビが失敗を返したら DX の Chat に「撮影完了 Chat が出ていない注文」を知らせる（人が判断）
- 患者名・カルテの URL・Webhook はログに出さない（orderId と結果だけ）
- GAS の Web アプリは POST に 302 を返し、移動先を GET で読むと結果の JSON が返る。urllib は 302 で GET に切り替えるのでそのまま使える
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger("homis_writer")

TIMEOUT_SEC = 30
WAITS = (5, 15)  # 1回目と2回目の失敗のあとに待つ秒数（合計 3 回）


def navi_url() -> str:
    return os.environ.get("NAVI_WEBAPP_URL", "").strip()


def enabled() -> bool:
    return bool(navi_url())


def _post_once(payload: dict) -> tuple[str, dict]:
    """1回送る。戻り値 (種類, 中身)。種類: ok / ng（返事は来た）/ retry（応答なし・5xx）"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        navi_url(), data=body,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if 500 <= e.code < 600:
            return "retry", {"message": f"HTTP {e.code}"}
        return "ng", {"message": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "retry", {"message": type(e).__name__}
    try:
        out = json.loads(text)
    except ValueError:
        # GAS がエラー画面（HTML）を返したとき。中身が分からないので再送しない（二重 Chat を避ける）
        return "ng", {"message": "not_json"}
    if not isinstance(out, dict):
        return "ng", {"message": "not_json"}
    return ("ok" if out.get("success") else "ng"), out


def post_action(payload: dict, sleep=time.sleep) -> dict:
    """再送つきで送る。戻り値 {"delivered": bool, "success": bool, "attempts": n, "message": str}"""
    if not enabled():
        return {"delivered": False, "success": False, "attempts": 0, "message": "navi_url_not_set"}
    attempts = 0
    kind, out = "retry", {}
    for i in range(len(WAITS) + 1):
        attempts += 1
        kind, out = _post_once(payload)
        if kind != "retry":
            break
        if i < len(WAITS):
            sleep(WAITS[i])
    return {
        "delivered": kind != "retry",
        "success": kind == "ok",
        "attempts": attempts,
        "message": str(out.get("message") or ""),
    }


def _dx_hook() -> str:
    return (os.environ.get("DX_ALERT_WEBHOOK", "") or os.environ.get("DX_EMPTY_KARTE_WEBHOOK", "")).strip()


def notify_dx(text: str, order_id: str = "") -> None:
    hook = _dx_hook()
    if not hook:
        logger.warning("DX webhook 未設定 orderId=%s", order_id)
        return
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        hook, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("DX Chat 送信 status=%s orderId=%s", resp.status, order_id)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.error("DX Chat 失敗 orderId=%s err=%s", order_id, type(e).__name__)


def notify_karte(order_id: str, karte_url: str, sleep=time.sleep) -> dict:
    """書き終えたことをナビに知らせる。失敗しても空の URL で知らせる（ナビが患者ページで撮影完了 Chat を出す）"""
    res = post_action({"action": "updateHomisLink", "orderId": order_id, "homisUrl": karte_url or ""}, sleep=sleep)
    logger.info(
        "NAVI updateHomisLink orderId=%s delivered=%s success=%s attempts=%s message=%s",
        order_id, res["delivered"], res["success"], res["attempts"], res["message"][:80],
    )
    if enabled() and not res["success"]:
        why = (f"{res['attempts']}回送って応答なし" if not res["delivered"]
               else f"ナビが失敗を返した: {res['message'][:80]}")
        notify_dx(
            "レントゲンナビへの「カルテを書いた」の知らせがうまくいきませんでした。撮影完了 Chat が出ていない可能性があります。"
            f"\norderId={order_id}\n（{why}。ナビの画面とシートを確認してください）",
            order_id,
        )
    return res


def check_group(group_id: str, sleep=time.sleep) -> dict:
    """集団の確かめ役。ナビの checkGroupComplete を呼ぶ（判定と DX Chat はナビ側）"""
    res = post_action({"action": "checkGroupComplete", "groupId": group_id}, sleep=sleep)
    logger.info(
        "NAVI checkGroupComplete groupId=%s delivered=%s success=%s attempts=%s message=%s",
        group_id, res["delivered"], res["success"], res["attempts"], res["message"][:80],
    )
    if enabled() and not res["delivered"]:
        notify_dx(
            "集団検診のまとめ通知の確かめで、レントゲンナビに届きませんでした。"
            f"\ngroupId={group_id}\n（まとめ通知が出ているか確認してください）",
        )
    return res
