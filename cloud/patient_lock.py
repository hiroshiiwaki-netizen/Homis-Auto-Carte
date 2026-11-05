# -*- coding: utf-8 -*-
"""患者さんごとの札（同じ患者さんのカルテを2台のライターで同時に書かない）

==============================================================================
バージョン: 1.0.1
最終更新: 2026/11/05
改定履歴（新しい順・全体は docs/SPEC_v3_cloud.md 0章「モジュール別の版」）:
  v1.0.1 11/05 黒ヤギ実装1回目【直してから】: ①トークンは metadata の expires_in−2分だけ使い回す（箱の metadata は残り寿命の短い
               トークンを返すことがある）。401 ならトークンを捨てて1回取り直す（2回目の 401 で error）。
               ②繰り返しの先頭で上限（320秒）を見る。寝ずに取り直す（404・期限切れを消した）のは続けて3回まで、それ以上は5秒寝る
  v1.0.0 11/05 初版。仕様 docs/FAXカルテ_検討/SPEC_問い合わせの列を分ける_v0.md v0.4（黒ヤギ仕様2回・DX担当「案2」）。
               問い合わせの列を FAX と分けると、別の台が同じ患者さんを同時に書きうる（HOMIS は同じアカウントの編集中を新規で返す）。
               Cloud Storage の「同じ名前が無いときだけ作る」（ifGenerationMatch=0）で、患者番号ごとの札を1台だけが持つ
==============================================================================

札の決まり:
  - 置き場: 環境変数 LOCK_BUCKET（鍵専用のバケット）。札の名前は locks/<患者番号>。本文は空、注文番号と台の印は custom metadata（読み物用）
  - 期限: Cloud Storage が付けた作成時刻（timeCreated）＋ LOCK_TTL_SEC（300秒）。札を取ったあとの書き込みは最長 280秒（server.REQUEST_BUDGET_SEC）＋余裕
  - 取り方: 作れたら自分の札（世代番号 generation を控える）。412（もう有る）なら、メタデータを GET 1回で読み（世代と作成時刻を一緒に）、
            期限切れならその世代を指定して消してすぐ取り直す。期限内なら 5秒待って取り直す。最大 LOCK_WAIT_SEC（320秒・期限より長い）
  - 404（もう無い）・412（別の世代になった）は、別の台が先に動いた正常な競合。置き場の失敗（401/403・5xx が続く・つながらない）だけ error
  - 外し方: 控えた世代番号を指定して消す（他の台が期限切れとして消したあとの新しい札を消さない）
  - 置き場が使えない（LOCK_BUCKET が空・権限なし・つながらない）ときは error を返し、呼ぶ側（server.py）は書かずに知らせる（案A）

安全: 患者さんの名前・本文は扱わない。ログに出すのは患者番号の札の名前・世代番号・注文番号だけ
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
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("homis_writer.lock")

LOCK_TTL_SEC = 300.0      # 札の期限（作成から）。書き込み上限 280秒＋余裕 20秒（黒ヤギ仕様1回目 指摘1）
LOCK_WAIT_SEC = 320.0     # 札待ちの上限。期限より長くして、落ちた台の札を待っている間に必ず拾える（仕様 v0.2）
LOCK_POLL_SEC = 5.0       # 取り直しの間隔
HTTP_TIMEOUT = 10.0
ERROR_LIMIT = 3           # 置き場の失敗（5xx・つながらない）がこの回数続いたら error
TOKEN_TTL_SEC = 50 * 60   # トークンの使い回しの上限。実際は metadata の expires_in−TOKEN_MARGIN_SEC（v1.0.1）
TOKEN_MARGIN_SEC = 120    # 残り寿命の余裕。箱の metadata サーバーは残り寿命の短い同じトークンを返すことがある（黒ヤギ実装1回目 指摘1）
FAST_RETRY_MAX = 3        # 寝ずに取り直す回数の上限（404・期限切れを消したあと）。超えたら 5秒寝る（指摘2）
INSTANCE = (os.environ.get("K_REVISION", "local") + "/" + uuid.uuid4().hex[:8])   # 台の印（読み物用）

_token_lock = threading.Lock()
_token_cache: dict = {"value": "", "until": 0.0}
_TIME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(?:Z|([+-])(\d{2}):(\d{2}))?$")


class LockError(Exception):
    """置き場そのものの失敗（権限・接続・5xx が続く）"""


def bucket() -> str:
    return os.environ.get("LOCK_BUCKET", "").strip()


def _base() -> str:
    """テストでは偽の Cloud Storage（GCS_BASE）に向ける"""
    return os.environ.get("GCS_BASE", "https://storage.googleapis.com").rstrip("/")


def lock_name(homis_id: str) -> str:
    return "locks/" + str(homis_id)


def _token() -> str:
    """箱の中の metadata サーバーから、ライターのアカウントのトークンを取る（標準部品だけ・50分使い回す）"""
    with _token_lock:
        now = time.time()
        if _token_cache["value"] and now < _token_cache["until"]:
            return _token_cache["value"]
        url = os.environ.get("METADATA_TOKEN_URL",
                             "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token")
        req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            j = json.loads(r.read().decode("utf-8"))
        tok = j["access_token"]
        try:
            ttl = min(float(TOKEN_TTL_SEC), max(0.0, float(j.get("expires_in") or 0) - TOKEN_MARGIN_SEC))
        except (TypeError, ValueError):
            ttl = 0.0
        _token_cache.update(value=tok, until=now + ttl)
        return tok


def forget_token() -> None:
    """401 が返ったときに捨てる（次の呼び出しで metadata から取り直す）"""
    with _token_lock:
        _token_cache.update(value="", until=0.0)


def _request(method: str, url: str, data: bytes | None = None, content_type: str = "") -> tuple[int, dict]:
    """1回の HTTP。返り値 (status, JSON)。HTTPError はそのまま投げる（呼ぶ側が番号で分ける）"""
    headers = {"Authorization": "Bearer " + _token()}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            raw = r.read()
            return r.status, (json.loads(raw.decode("utf-8")) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            forget_token()   # 失効したトークン。次は取り直す（v1.0.1）
        raise


def parse_time(value: str) -> float | None:
    """timeCreated（RFC 3339・例 2026-11-05T04:59:32.123Z）を UNIX 秒に。読めなければ None"""
    m = _TIME_RE.match(str(value or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s, frac, sign, oh, om = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=timezone.utc)
    t = dt.timestamp() + (int(frac.ljust(6, "0")[:6]) / 1e6 if frac else 0.0)
    if sign:
        off = int(oh) * 3600 + int(om) * 60
        t -= off if sign == "+" else -off
    return t


def _create(homis_id: str, order_id: str) -> str:
    """札を作る（同じ名前が無いときだけ）。返り値は世代番号。もう有れば ""（412／409）。置き場の失敗は HTTPError／URLError のまま"""
    boundary = "lockboundary" + uuid.uuid4().hex
    meta = {"name": lock_name(homis_id), "metadata": {"orderId": str(order_id), "instance": INSTANCE}}
    body = ("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + json.dumps(meta)
            + "\r\n--" + boundary + "\r\nContent-Type: text/plain\r\n\r\n\r\n--" + boundary + "--\r\n").encode("utf-8")
    url = (f"{_base()}/upload/storage/v1/b/{urllib.parse.quote(bucket(), safe='')}/o"
           f"?uploadType=multipart&ifGenerationMatch=0")
    try:
        _, j = _request("POST", url, body, "multipart/related; boundary=" + boundary)
    except urllib.error.HTTPError as e:
        if e.code in (412, 409):
            return ""
        raise
    return str(j.get("generation") or "")


def _info(homis_id: str) -> dict | None:
    """札のメタデータ（generation・timeCreated を1回で）。無ければ None（404）"""
    url = f"{_base()}/storage/v1/b/{urllib.parse.quote(bucket(), safe='')}/o/{urllib.parse.quote(lock_name(homis_id), safe='')}"
    try:
        _, j = _request("GET", url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return j


def _delete(homis_id: str, generation: str) -> str:
    """世代を指定して消す。deleted／gone（404 もう無い）／changed（412 別の世代）。置き場の失敗は例外のまま"""
    url = (f"{_base()}/storage/v1/b/{urllib.parse.quote(bucket(), safe='')}/o/"
           f"{urllib.parse.quote(lock_name(homis_id), safe='')}?ifGenerationMatch={urllib.parse.quote(str(generation), safe='')}")
    try:
        _request("DELETE", url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "gone"
        if e.code == 412:
            return "changed"
        raise
    return "deleted"


def expired(info: dict, now: float | None = None) -> bool:
    """作成時刻＋期限を過ぎているか。作成時刻が読めない札は期限切れ扱い（残り続けないように）"""
    created = parse_time(str(info.get("timeCreated") or ""))
    if created is None:
        return True
    return (now if now is not None else time.time()) - created > LOCK_TTL_SEC


def _is_fatal(e: Exception, relogin: int = 0) -> bool:
    """すぐ error にする失敗（権限・設定）。5xx・接続は数回まで待って取り直す。
    401 は1回目はトークンの取り直し（_request が捨てている）、2回目で error（v1.0.1）"""
    if not isinstance(e, urllib.error.HTTPError):
        return False
    if e.code == 401:
        return relogin >= 2
    return e.code in (400, 403)


def acquire(homis_id: str, order_id: str, wait_sec: float | None = None) -> dict:
    """札を取る。返り値 {"status": ok／busy／error, "generation": 世代番号, "waited_sec": 待った秒, "reason": 短い言葉}"""
    t0 = time.time()
    wait = LOCK_WAIT_SEC if wait_sec is None else float(wait_sec)
    deadline = t0 + wait
    out = {"status": "error", "generation": "", "waited_sec": 0.0, "reason": ""}
    if not bucket():
        out["reason"] = "no_bucket"
        logger.error("札の置き場（LOCK_BUCKET）が設定されていない orderId=%s", order_id)
        return out
    errors = relogin = fast = attempts = 0
    while True:
        if attempts and time.time() >= deadline:
            # v1.0.1: 寝ずに取り直す道（continue）でも上限を踏み越えない（黒ヤギ実装1回目 指摘2）
            out.update(status="busy", reason="busy", waited_sec=round(time.time() - t0, 1))
            logger.warning("札が取れないまま上限 %.0f秒 %s orderId=%s", wait, lock_name(homis_id), order_id)
            return out
        attempts += 1
        try:
            gen = _create(homis_id, order_id)
            if gen:
                out.update(status="ok", generation=gen, waited_sec=round(time.time() - t0, 1))
                logger.info("札を取った %s 世代=%s 待ち=%.1f秒 orderId=%s", lock_name(homis_id), gen, out["waited_sec"], order_id)
                return out
            info = _info(homis_id)
            if info is None:
                fast += 1
                if fast < FAST_RETRY_MAX:
                    continue   # 別の台が外した直後。すぐ取り直す（寝ない・続けて3回まで）
            elif expired(info):
                res = _delete(homis_id, str(info.get("generation") or ""))
                logger.warning("期限切れの札を消した %s 世代=%s 結果=%s orderId=%s", lock_name(homis_id), info.get("generation"), res, order_id)
                fast += 1
                if fast < FAST_RETRY_MAX:
                    continue   # 消せても（deleted）・別の台が先に消していても（gone／changed）すぐ取り直す（続けて3回まで）
            else:
                fast = 0
            errors = 0   # 置き場は生きている
        except Exception as e:  # noqa: BLE001
            errors += 1
            if isinstance(e, urllib.error.HTTPError) and e.code == 401:
                relogin += 1
            if _is_fatal(e, relogin) or errors >= ERROR_LIMIT:
                code = getattr(e, "code", "") or type(e).__name__
                out.update(reason=f"storage:{code}", waited_sec=round(time.time() - t0, 1))
                logger.error("札の置き場の失敗 %s 理由=%s 回数=%s orderId=%s", lock_name(homis_id), out["reason"], errors, order_id)
                return out
            logger.warning("札の置き場の一時的な失敗 %s %s 回数=%s orderId=%s", lock_name(homis_id), type(e).__name__, errors, order_id)
        remaining = deadline - time.time()
        if remaining <= 0:
            out.update(status="busy", reason="busy", waited_sec=round(time.time() - t0, 1))
            logger.warning("札が取れないまま上限 %.0f秒 %s orderId=%s", wait, lock_name(homis_id), order_id)
            return out
        time.sleep(min(LOCK_POLL_SEC, remaining))


def release(homis_id: str, generation: str, order_id: str = "") -> str:
    """札を外す。deleted／gone／changed／failed。失敗しても例外を外に出さない（書いた結果は変えない）。
    401（トークン失効）なら取り直して1回だけやり直す（v1.0.1）"""
    try:
        try:
            res = _delete(homis_id, generation)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            res = _delete(homis_id, generation)
    except Exception as e:  # noqa: BLE001
        logger.error("札を外せなかった %s 世代=%s %s orderId=%s", lock_name(homis_id), generation, type(e).__name__, order_id)
        return "failed"
    (logger.info if res == "deleted" else logger.warning)("札を外した %s 世代=%s 結果=%s orderId=%s", lock_name(homis_id), generation, res, order_id)
    return res
