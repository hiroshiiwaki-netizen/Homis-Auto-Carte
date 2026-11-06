# -*- coding: utf-8 -*-
"""共通 JSON の入口 ①先生が選んだカルテに書く ときの、書く前の確かめと「人が書いたか」の見分け（読むだけ）

版: 1.0.1
最終更新: 2026-11-06
改定履歴:
  v1.0.1 11/06 黒ヤギ実装1回目: 読めなかった理由（例外の種類と短い文）をログに残す／human_changed に生のカルテ（upd_user が辞書）を渡しても名前で比べる
  v1.0.0 11/06 新規（仕様 docs/FAXカルテ_検討/SPEC_共通JSON入口_v0.md v1.0 5章 2)・2b)・3b)・14章）。
               ajax_karte_show（読むだけ・verify_karte と同じログイン）でそのカルテを読み、
               患者さんが同じか・完了（3・5・6・7）でないか・取消（0）でないか・診察日が今日か昨日か（KARTE_EDIT_MAX_DAYS・既定 1）を確かめる。
               最終更新日時（upd_datetime）と更新者（upd_user.full_name）を控えにして返す。
               人が書いた＝更新日時が控えと違い、かつ更新者がライター以外（編集画面を開くだけで日時が変わっても、更新者はライター自身なので取り違えない）
               本物の形（11/6 テスト舞子・読むだけで確認）: act_date '2026-11-05'・upd_datetime '2026-11-05 20:02:37'・upd_user.full_name 'おひさまロボット GCP'
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

import verify_karte

VERSION = "1.0.1"
JST = timezone(timedelta(hours=9))
logger = logging.getLogger("karte_guard")
DONE_STATUS = verify_karte.DONE_STATUS   # 3・5・6・7
CANCEL_STATUS = {"0"}


def max_days() -> int:
    try:
        return max(0, int(os.environ.get("KARTE_EDIT_MAX_DAYS", "1")))
    except ValueError:
        return 1


def parse_day(text) -> date | None:
    """'2026-11-05'・'2026/11/05'・'2026-11-05 10:00:00' をそろえて日付に（黒ヤギ v1.0 14章）"""
    m = re.match(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(text or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _who(v) -> str:
    """更新者の名前（辞書 {full_name: …} でも文字でも）"""
    if isinstance(v, dict):
        v = v.get("full_name")
    return verify_karte._clean_name(v if isinstance(v, str) else "")


def snapshot(karte: dict) -> dict:
    """控えにする最終更新日時と更新者"""
    name = _who(karte.get("upd_user"))
    return {"upd_datetime": str(karte.get("upd_datetime") or ""), "upd_user": verify_karte._clean_name(name)}


def judge(karte: dict | None, homis_id: str, today: date | None = None) -> str:
    """書いてよいか。'' なら書く。理由の言葉: karte_not_found・karte_cancelled・karte_completed・karte_too_old・karte_other_patient"""
    if not karte:
        return "karte_not_found"
    if str(karte.get("patient_id") or "") != str(homis_id):
        return "karte_other_patient"
    st = str(karte.get("status") or "")
    if st in CANCEL_STATUS:
        return "karte_cancelled"
    if st in DONE_STATUS:
        return "karte_completed"
    d = parse_day(karte.get("act_date"))
    today = today or datetime.now(JST).date()
    if d is None or d > today or (today - d).days > max_days():
        return "karte_too_old"
    return ""


def human_changed(baseline: dict | None, now: dict | None) -> bool:
    """人が書いた見込みか。控えが無い・今が読めない → True（分からないときは書かない）"""
    if not baseline or not now:
        return True
    if now.get("upd_datetime") == baseline.get("upd_datetime"):
        return False
    return _who(now.get("upd_user")) != verify_karte._expected_updater()


def read(homis_id: str, karte_id: str) -> dict | None:
    """そのカルテを読む（読むだけ）。読めなければ None"""
    user = os.environ.get("HOMIS_USER", "")
    password = os.environ.get("HOMIS_PASSWORD", "")
    if not (user and password and homis_id and karte_id):
        return None
    try:
        op = verify_karte._opener()
        verify_karte._login(op, user, password)
        return verify_karte._read(op, homis_id, karte_id)
    except Exception as e:  # noqa: BLE001  読めなければ「分からない」（呼ぶ側は書かない）
        # 理由は種類と短い文だけ（verify_karte と同じ・カルテの中身は入らない）（黒ヤギ実装1回目 指摘1）
        logger.warning("カルテを読めなかった karte_id=%s 理由=%s: %s", karte_id, type(e).__name__, str(e)[:80])
        return None


def before_write(homis_id: str, karte_id: str, today: date | None = None) -> tuple[str, dict | None]:
    """書く前の確かめ。返り値 (止める理由 or '', 控え)。読めなければ karte_unreadable"""
    karte = read(homis_id, karte_id)
    if karte is None:
        return "karte_unreadable", None
    reason = judge(karte, homis_id, today)
    return reason, (snapshot(karte) if not reason else None)
