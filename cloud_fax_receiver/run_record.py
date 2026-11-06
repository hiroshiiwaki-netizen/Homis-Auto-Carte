# -*- coding: utf-8 -*-
"""実行リストの記録（1 注文＝1 つの JSON）を Cloud Storage に置く部品。受け口とライターで同じ中身を使う。

版: 1.1.0
最終更新: 2026-11-06
改定履歴:
  v1.1.0 11/06 道の名前に karte_edit（KE-）・karte_edit_test（KE-TEST-）を足した（共通 JSON の入口 ①）
  v1.0.0 11/06 新規（仕様 docs/SPEC_実行リスト_v0.md v0.4 の第1段）。
               置き場は環境変数 RECORD_BUCKET。空なら何もしない（配置しても、置き場を決めるまで今まで通り）。
               パス records/<日本時間の日付>/<注文番号>.json。再書き込み（-R1・-R2）も元の注文の日のフォルダ。
               カルテの書き込み・受け口の返事を止めないこと（仕様 5章）:
                 1 回の通信は 5 秒まで・例外は外に出さない・失敗したら 60 秒は通信しない（遅い置き場で毎回 5 秒待たない）。
               中身に患者さんの名前・本文が入るので、ログには注文番号と短い言葉だけを出す。

使い方:
  create(day, order_id, rec)        無いときだけ作る（ifGenerationMatch=0）。返り値 created / exists / failed / off
  update(day, order_id, change)     読んで change(rec) を当てて書く（世代つき）。無ければ change({}) で作る。
                                    返り値 updated / created / failed / off
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("run_record")

VERSION = "1.1.0"
JST = timezone(timedelta(hours=9))
TIMEOUT_SEC = 5.0        # 1 回の通信の上限（仕様 5章）
PAUSE_SEC = 60.0         # 失敗したあと通信しない時間
TOKEN_MARGIN_SEC = 120   # トークンの残り寿命の余裕（patient_lock と同じ）
SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
ORDER_RE = re.compile(r"^[0-9A-Za-z\-]{1,80}$")   # 注文番号の形（パスに使うので決まった文字だけ）
DAY_RE = re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]$")

_lock = threading.Lock()
_token_cache = {"value": "", "until": 0.0}
_paused_until = {"t": 0.0}


def bucket() -> str:
    return os.environ.get("RECORD_BUCKET", "").strip()


def enabled() -> bool:
    return bool(bucket())


def _base() -> str:
    """テストでは偽の Cloud Storage（GCS_BASE）に向ける"""
    return os.environ.get("GCS_BASE", "https://storage.googleapis.com").rstrip("/")


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def today() -> str:
    """日本時間の今日（YYYY-MM-DD）"""
    return datetime.now(JST).strftime("%Y-%m-%d")


def safe_day(day) -> str:
    """日付の形でなければ今日にする（パスに変な文字を入れない）"""
    d = str(day or "").strip()
    return d if DAY_RE.match(d) else today()


def object_name(day: str, order_id: str) -> str:
    return f"records/{safe_day(day)}/{order_id}.json"


def _paused() -> bool:
    return time.time() < _paused_until["t"]


def _pause(why: str, order_id: str) -> None:
    _paused_until["t"] = time.time() + PAUSE_SEC
    logger.warning("記録の置き場が使えないため %d 秒は書かない orderId=%s 理由=%s", int(PAUSE_SEC), order_id, why)


def _token() -> str:
    with _lock:
        if _token_cache["value"] and time.time() < _token_cache["until"]:
            return _token_cache["value"]
    url = os.environ.get("METADATA_TOKEN_URL",
                         "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token")
    url += ("&" if "?" in url else "?") + "scopes=" + urllib.parse.quote(SCOPE)
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
        body = json.loads(r.read().decode("utf-8"))
    tok = str(body.get("access_token") or "")
    life = float(body.get("expires_in") or 0)
    with _lock:
        _token_cache["value"] = tok
        _token_cache["until"] = time.time() + max(0.0, life - TOKEN_MARGIN_SEC)
    return tok


def _get(name: str):
    """(中身の dict, 世代) を返す。無ければ (None, 0)。通信の失敗は例外"""
    url = f"{_base()}/storage/v1/b/{urllib.parse.quote(bucket(), safe='')}/o/{urllib.parse.quote(name, safe='')}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + _token()})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            gen = int(r.headers.get("x-goog-generation") or 0)
            data = json.loads(r.read().decode("utf-8") or "{}")
            return (data if isinstance(data, dict) else {}), gen
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, 0
        raise


def _put(name: str, rec: dict, if_gen: int) -> str:
    """世代つきで書く。ok / conflict（412＝先を越された）。ほかの失敗は例外"""
    q = urllib.parse.urlencode({"uploadType": "media", "name": name, "ifGenerationMatch": str(if_gen)})
    url = f"{_base()}/upload/storage/v1/b/{urllib.parse.quote(bucket(), safe='')}/o?{q}"
    body = json.dumps(rec, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + _token(), "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC):
            return "ok"
    except urllib.error.HTTPError as e:
        if e.code == 412:
            return "conflict"
        raise


def _ready(order_id: str) -> str:
    """書いてよいか。'' なら書く。それ以外は返り値の言葉"""
    if not enabled():
        return "off"
    if not ORDER_RE.match(order_id or ""):
        logger.warning("記録しない（注文番号の形が違う）")
        return "failed"
    if _paused():
        return "failed"
    return ""


def create(day: str, order_id: str, rec: dict) -> str:
    """無いときだけ作る。有ればそのまま（exists）"""
    word = _ready(order_id)
    if word:
        return word
    try:
        res = _put(object_name(day, order_id), rec, 0)
        return "created" if res == "ok" else "exists"
    except Exception as e:  # noqa: BLE001  記録の失敗で本線を止めない
        _pause(type(e).__name__, order_id)
        return "failed"


def update(day: str, order_id: str, change) -> str:
    """読んで change(rec) を当てて書く。先を越されたら 1 回だけ読み直してやり直す"""
    word = _ready(order_id)
    if word:
        return word
    name = object_name(day, order_id)
    try:
        for _ in range(2):
            rec, gen = _get(name)
            new = dict(rec or {})
            change(new)
            if _put(name, new, gen) == "ok":
                return "created" if rec is None else "updated"
        logger.warning("記録を書けなかった（2 回とも先を越された） orderId=%s", order_id)
        return "failed"
    except Exception as e:  # noqa: BLE001
        _pause(type(e).__name__, order_id)
        return "failed"


def add_timeline(rec: dict, what: str) -> None:
    rec.setdefault("timeline", []).append({"at": now_iso(), "what": what})


def route_of(order_id: str) -> str:
    """注文番号の頭から道を決める（画面のタブと同じ）"""
    o = str(order_id or "")
    if o.startswith("FAX-MIRROR-"):
        return "fax_mirror"
    if o.startswith("FAX-"):
        return "fax"
    if o.startswith("BOT-TEST-"):
        return "bot_test"
    if o.startswith("BOT-G-"):
        return "bot_g"
    if o.startswith("BOT-"):
        return "bot"
    if o.startswith("KE-TEST-"):
        return "karte_edit_test"   # v1.1.0: 共通 JSON の入口 ①先生のカルテ（試験）
    if o.startswith("KE-"):
        return "karte_edit"        # v1.1.0: 共通 JSON の入口 ①先生が選んだカルテに書く
    if o.startswith("KJ-"):
        return "karte_json"
    return "other"
