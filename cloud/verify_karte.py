# -*- coding: utf-8 -*-
"""書いたカルテを読み直して確かめる（読むだけ）

==============================================================================
バージョン: 1.0.1
最終更新: 2026/10/29
改定履歴（全体は docs/SPEC_v3_cloud.md 0章「モジュール別の版」）:
  v1.0.1 10/29 黒ヤギ1回目: 読めなかった理由に例外の文も残す（80字まで）・ログイン後もまだ auth.php なら login_failed。
               記号（< & >）は HOMIS がそのまま返す（試し書き122欄で実体参照0件）ので、比べ方は変えない
  v1.0.0 10/29 新規。法人内で「空だ」「書けていない」と言われる前に、ライター自身が気づくため
               （10/23〜10/28 に Tukusi のカルテが7件、保存されないまま成功扱いになっていた）
==============================================================================

書き終えたあと、ブラウザとは別のログインで HOMIS の表示用データ（?qid=ajax_karte_show・読むだけ）を読み、
  1 状態が完了か（DONE_STATUS: 3 診察完了・5 ORCA送信済・6 ORCA登録済・7 ORCA登録不要。
    算定不要で書くと 7 になる。0 取消・1 診察中・2 診療中断・70 ORCA登録不要(編集中) などは未完了。10/29 本物で対応を確認）
  2 S・O が送ったとおりか（改行の種類・行末の空白・前後の空白の違いは見ない）
を確かめる。完了でなければ WAIT_SEC 待って1回だけ読み直す。
編集画面（pdetail_karteedit.php）は開かない。開くだけでカルテが「編集中」になるため（10/29 テスト患者で確認）。
結果の verdict:
  ok             完了で S・O も一致
  not_completed  完了になっていない（編集中・中断・取消）
  s_mismatch     S が違う
  o_mismatch     O が違う
  unverified     読めなかった（ログイン・通信・形が違う）。書けなかったとは限らない
記録・戻り値に S・O の中身は入れない（文字数だけ）。
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.parse
import urllib.request

BASE = os.environ.get("HOMIS_BASE_URL", "https://homis.jp/homic/")
TIMEOUT_SEC = 20
WAIT_SEC = 2.0
DONE_STATUS = {"3", "5", "6", "7"}
STATUS_LABEL = {"0": "取消", "1": "診察中", "2": "診療中断", "3": "診察完了", "5": "ORCA送信済",
                "6": "ORCA登録済", "7": "ORCA登録不要", "70": "ORCA登録不要(編集中)"}


def _norm(text) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in t.split("\n")).strip()


def _opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _login(op, user: str, password: str) -> None:
    body = urllib.parse.urlencode({"id": user, "pw": password, "jaddr": ""}).encode("utf-8")
    req = urllib.request.Request(BASE + "auth.php", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with op.open(req, timeout=TIMEOUT_SEC) as r:
        r.read()
        # 成功すると 302 でトップ（?pid=top）へ移る（10/29 本物で確認）。auth.php のままなら入れていない
        if "auth.php" in r.geturl():
            raise ValueError("login_failed")


def _read(op, homis_id: str, karte_id: str) -> dict:
    q = urllib.parse.urlencode({"qid": "ajax_karte_show", "patient_id": homis_id, "karte_id": karte_id})
    with op.open(BASE + "?" + q, timeout=TIMEOUT_SEC) as r:
        raw = r.read().decode("utf-8", errors="replace")
    karte = json.loads(raw).get("this_karte")  # ログイン画面（HTML）なら json で落ちる＝unverified
    if not isinstance(karte, dict):
        raise ValueError("this_karte なし")
    return karte


def verify(homis_id: str, karte_id: str, s_expect: str, o_expect: str) -> dict:
    """書いたカルテを読み直す。例外は外に出さない（unverified で返す）"""
    out = {"verdict": "unverified", "status": "", "status_label": "", "reads": 0, "s_len": 0, "o_len": 0, "reason": ""}
    user = os.environ.get("HOMIS_USER", "")
    password = os.environ.get("HOMIS_PASSWORD", "")
    if not (user and password and homis_id and karte_id):
        out["reason"] = "no_input"
        return out
    try:
        op = _opener()
        _login(op, user, password)
        karte = _read(op, homis_id, karte_id)
        out["reads"] = 1
        if str(karte.get("status")) not in DONE_STATUS:
            time.sleep(WAIT_SEC)
            karte = _read(op, homis_id, karte_id)
            out["reads"] = 2
    except Exception as e:  # noqa: BLE001 — 確かめの失敗で書いた結果を壊さない
        # 理由は種類と短い文だけ（この部品が投げる文・JSON・通信の文で、カルテの中身は入らない）
        out["reason"] = f"{type(e).__name__}: {str(e)[:80]}"
        return out
    s_got, o_got = _norm(karte.get("subjective")), _norm(karte.get("objective"))
    out.update(status=str(karte.get("status")), s_len=len(s_got), o_len=len(o_got))
    out["status_label"] = STATUS_LABEL.get(out["status"], "状態" + out["status"])
    if out["status"] not in DONE_STATUS:
        out["verdict"] = "not_completed"
    elif s_got != _norm(s_expect):
        out["verdict"] = "s_mismatch"
    elif o_got != _norm(o_expect):
        out["verdict"] = "o_mismatch"
    else:
        out["verdict"] = "ok"
    return out
