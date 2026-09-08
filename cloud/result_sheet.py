# -*- coding: utf-8 -*-
"""試験用結果シート（案B）。患者名は書かない。

列: A受付時刻 B orderId C status D homisUrl E エラー種別 F 処理済 G groupId
status: accepted = 受付（まだ書いていない） / ok / ok_no_id / fail
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("homis_writer")

JST = timezone(timedelta(hours=9))
SCOPES = "https://www.googleapis.com/auth/spreadsheets"


def _sheet_id() -> str:
    return os.environ.get("RESULT_SPREADSHEET_ID", "").strip()


def enabled() -> bool:
    return bool(_sheet_id())


def _token() -> str:
    url = (
        "http://metadata.google.internal/computeMetadata/v1/"
        "instance/service-accounts/default/token?scopes="
        + urllib.parse.quote(SCOPES)
    )
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8")).get("access_token") or ""


def _req(method: str, url: str, payload: dict | None = None) -> dict:
    token = _token()
    data = None
    headers = {"Authorization": "Bearer " + token}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        logger.error("Sheets API失敗 status=%s", e.code)
        raise


def _tab() -> str:
    sid = urllib.parse.quote(_sheet_id())
    meta = _req(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}?fields=sheets.properties.title",
    )
    sheets = meta.get("sheets") or []
    if not sheets:
        raise RuntimeError("シートが空")
    return str(sheets[0]["properties"]["title"])


def _values_url(tab: str, rng: str, extra: str = "") -> str:
    sid = urllib.parse.quote(_sheet_id())
    enc = urllib.parse.quote(f"{tab}!{rng}")
    return f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{enc}{extra}"


def _ensure_header(tab: str) -> None:
    out = _req("GET", _values_url(tab, "A1:B1"))
    rows = out.get("values") or []
    if rows and rows[0] and str(rows[0][0]) == "受付時刻":
        return
    body = {
        "values": [["受付時刻", "orderId", "status", "homisUrl", "エラー種別", "処理済", "groupId"]]
    }
    _req("PUT", _values_url(tab, "A1:G1", "?valueInputOption=RAW"), body)


def find_order(order_id: str) -> dict | None:
    """同じ orderId の行。なければ None。"""
    if not enabled() or not order_id:
        return None
    tab = _tab()
    _ensure_header(tab)
    out = _req("GET", _values_url(tab, "A2:G"))
    for i, row in enumerate(out.get("values") or [], start=2):
        cells = list(row) + [""] * 7
        if str(cells[1]) == order_id:
            return {
                "row": i,
                "status": str(cells[2] or ""),
                "homisUrl": str(cells[3] or ""),
                "error_type": str(cells[4] or ""),
                "groupId": str(cells[6] or ""),
            }
    return None


def claim(order_id: str, group_id: str = "") -> dict:
    """受付行を先に置く。既存ならその行。新規なら status=accepted。"""
    existing = find_order(order_id)
    if existing:
        return existing
    tab = _tab()
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    body = {"values": [[now, order_id, "accepted", "", "", "0", group_id or ""]]}
    sid = urllib.parse.quote(_sheet_id())
    enc = urllib.parse.quote(f"{tab}!A:G")
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{enc}:append"
        "?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
    )
    out = _req("POST", url, body)
    rng = str((out.get("updates") or {}).get("updatedRange") or "")
    m = re.search(r"!A(\d+)", rng)
    row = int(m.group(1)) if m else 0
    return {
        "row": row,
        "status": "accepted",
        "homisUrl": "",
        "error_type": "",
        "groupId": group_id or "",
        "created": True,
    }


def finish(row: int, status: str, homis_url: str, error_type: str) -> None:
    if not enabled() or row < 2:
        return
    tab = _tab()
    body = {"values": [[status, homis_url or "", error_type or ""]]}
    _req("PUT", _values_url(tab, f"C{row}:E{row}", "?valueInputOption=RAW"), body)


def result_from_row(found: dict, order_id: str) -> dict:
    url = found.get("homisUrl") or ""
    kid = ""
    if "karte_id=" in url:
        kid = url.split("karte_id=", 1)[1].split("&", 1)[0]
    st = found.get("status") or ""
    return {
        "orderId": order_id,
        "success": st in ("ok", "ok_no_id"),
        "has_karte_id": bool(kid),
        "error_type": "duplicate" if st != "accepted" else "already_accepted",
        "karte_opened": False,
        "total_sec": 0,
        "karte_id": kid,
        "karte_url": url,
        "duplicated": True,
        "sheet_status": st,
    }
