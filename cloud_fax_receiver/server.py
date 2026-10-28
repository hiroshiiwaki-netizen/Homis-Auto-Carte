# -*- coding: utf-8 -*-
"""FAX カルテの受け口（横付けで受け取るだけ・段1）

==============================================================================
バージョン: 0.2.0
最終更新: 2026/10/28
改定履歴（新しい順・全体は docs/SPEC_v3_cloud.md 0章「モジュール別の版」）:
  v0.2.0 10/28 段1b 並走の試し書き: FAX_MIRROR=on のとき、受け取った件の S・O を、テスト舞子あての仕事として列 homis-fax-mirror に入れる
               （書き終わりは待たない・入れられなくても Tukusi には今まで通り 200）。記録に mirror（queued／off／skip／duplicate／error）だけ足す。
               仕様 docs/FAXカルテ_検討/SPEC_段1b_並走試し書き.md。黒ヤギ1回目の指摘2: 列の名前の前後の空白と「/」を取る
  v0.1.2 10/26 黒ヤギ再レビューの指摘2: 制御文字の種類（ctrl_codes・最大5種類）も記録する（改ページ \f などの見分け用）
  v0.1.1 10/26 黒ヤギ実装レビューの指摘: 読み込みに10秒の上限（少しずつ送る相手で止まらない）・
               読めなかったら静かに切る・起動直後の印を鍵の中で付ける（同時2件で2つ付かない）
  v0.1.0 10/26 初版。Tukusi WF1573 の横付けから届いた中身の「様子」だけを記録する。カルテは書かない
==============================================================================

仕様: docs/FAXカルテ_検討/SPEC_受け口_横付け_v0.md（v0.2）

GET  /health        生存確認（合言葉不要）
POST /fax/receive   横付けの受け口。合言葉（Bearer）→ 大きさ → JSON の順に確かめ、様子を1行記録して 200

安全:
  - 本文（s・o）と HOMIS ID は保存しない・ログに出さない・返事にも入れない（数えたらすぐ捨てる）
  - 合言葉は環境変数 FAX_RECEIVER_KEY（Secret Manager から渡す）。空なら 503
  - 合言葉は前後の空白を除き hmac.compare_digest で比べる
  - 合言葉が合うまで本文の中身は見ない（断るときは 256KB 以内なら読み捨ててから返事をする。切断で番号が伝わらないため）
  - 大きすぎる本文（256KB 超）・長さが無い本文は読まずに 413／411
  - 断った件は時刻と番号だけの短い1行
  - 外へ送るのは、FAX_MIRROR=on のときの「列 homis-fax-mirror に仕事を入れる」だけ（書く先はテスト舞子に固定・v0.2.0）。
    off なら外へ何も送らない
"""
from __future__ import annotations

import base64
import hmac
import json
import urllib.error
import urllib.request
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.0"
MAX_BODY = 256 * 1024          # 受け取る本文の上限（バイト）
READ_TIMEOUT = 10.0            # 1回の読み込みを待つ上限（秒）。少しずつ送る相手で箱がふさがらないように
LABEL_MAX = 40                 # source・doc_type・route を記録する最大の長さ
TICKET_RE = re.compile(r"^[0-9A-Za-z\-]{1,40}$")   # 札番号の形（例: 261021120224-54）
AMP_ENTITY_RE = re.compile(r"&[A-Za-z]+;?")         # HOMIS の編集画面で化ける「&英字」
QQ_RE = re.compile(r"[?？]{2,}")                     # 「??」の続き（手前の化けの目安）
# よくある文字化けの字（UTF-8 を Shift_JIS で読んだときに出やすい）。手前の化けの目安で、合否には使わない
MOJIBAKE_CHARS = set("縺繧譁蜈繝螟蝣邵髢")
PROCESS_START = time.time()

# ---------- v0.2.0: 本番と並走して、同じ中身をテスト舞子に書く（試し書き・段1b） ----------
# FAX_MIRROR="on" のときだけ動く。列 homis-fax-mirror に、カルテライターあての仕事を1つ入れるだけ（書き終わりは待たない）
MIRROR_MARK = "【GCP試し書き・本物は別の患者さん】"
MIRROR_TIMEOUT = 5.0   # 列に入れる・トークンを取る ときの待ち時間の上限（秒）。超えたら入れずに先へ（Tukusi を待たせない）
# 試し書きの宛先として許す患者（テスト舞子・テスト西宮・テスト芦屋）。設定を間違えても本物の患者さんには書かない
MIRROR_TEST_PATIENTS = {"2277808", "2080376", "2196689"}


def mirror_on() -> bool:
    return os.environ.get("FAX_MIRROR", "").strip().lower() == "on"


def mirror_queue() -> str:
    """列の名前（projects/…/locations/…/queues/…）。前後の空白と「/」を取る（黒ヤギ 10/28 指摘2: //projects で 404 になる）"""
    return os.environ.get("MIRROR_QUEUE", "").strip().strip("/")


def build_mirror_task(ticket: str, s: str, o: str) -> dict:
    """列に入れる仕事（Cloud Tasks の task）を作る。書く先は必ずテスト舞子（設定 MIRROR_HOMIS_ID・既定 2277808）"""
    writer = os.environ.get("WRITER_URL", "").rstrip("/")
    order_id = "FAX-MIRROR-" + ticket
    payload = {
        "orderId": order_id,
        "homisId": os.environ.get("MIRROR_HOMIS_ID", "2277808").strip(),
        "patientName": "テスト",
        "template": "fax_so",
        "sContent": MIRROR_MARK + s,
        "oContent": o,
    }
    return {"task": {
        "name": mirror_queue() + "/tasks/" + order_id,
        "httpRequest": {
            "url": writer + "/write",
            "httpMethod": "POST",
            "headers": {"Content-Type": "application/json", "X-Writer-Key": os.environ.get("WRITER_KEY", "").strip()},
            "body": base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii"),
            "oidcToken": {"serviceAccountEmail": os.environ.get("TASKS_INVOKER_SA", ""), "audience": writer},
        },
    }}


def _access_token() -> str:
    """箱の中の metadata サーバーから、受け口のアカウントのトークンを取る（標準部品だけ）"""
    url = os.environ.get("METADATA_TOKEN_URL",
                         "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token")
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=MIRROR_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def enqueue_mirror(ticket: str, s, o) -> str:
    """試し書きの仕事を列に入れる。返り値は記録用の短い言葉（本文・合言葉は返さない）。どんな失敗でも例外を外に出さない"""
    if not mirror_on():
        return "off"
    if not ticket:
        return "skip:no_ticket"
    if not isinstance(s, str) or not isinstance(o, str) or not s.strip() or not o.strip():
        return "skip:empty"
    for need in ("WRITER_URL", "MIRROR_QUEUE", "TASKS_INVOKER_SA", "WRITER_KEY"):
        if not os.environ.get(need, "").strip():
            return "skip:no_config"
    if os.environ.get("MIRROR_HOMIS_ID", "2277808").strip() not in MIRROR_TEST_PATIENTS:
        return "skip:not_test_patient"
    try:
        task = build_mirror_task(ticket, s, o)
        base = os.environ.get("CLOUD_TASKS_BASE", "https://cloudtasks.googleapis.com/v2/")
        url = base.rstrip("/") + "/" + mirror_queue() + "/tasks"
        req = urllib.request.Request(url, data=json.dumps(task).encode("utf-8"), method="POST", headers={
            "Authorization": "Bearer " + _access_token(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=MIRROR_TIMEOUT):
            return "queued"
    except urllib.error.HTTPError as e:
        return "duplicate" if e.code == 409 else f"error:http{e.code}"
    except Exception as e:  # noqa: BLE001  通信の失敗・時間切れなど。本番（Tukusi への返事）は止めない
        return "error:" + type(e).__name__
_first_request_done = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_log_lock = threading.Lock()


def log_line(record: dict) -> None:
    """Cloud Logging に1行（JSON）。本文・HOMIS ID を入れないのは呼ぶ側の責任。
    同時に受けた件の行が混ざらないよう、鍵をかけて「行＋改行」を1回で書く（print は本体と改行を分けて書くため混ざる）"""
    record.setdefault("time", _now())
    record.setdefault("severity", "INFO")
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _log_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def key_ok(auth_header: str, expected: str) -> bool:
    """Authorization: Bearer <合言葉> を確かめる。前後の空白は無視（Tukusi の設定欄に空白が入った例あり）"""
    expected = (expected or "").strip()
    if not expected:
        return False
    value = (auth_header or "").strip()
    if not value.lower().startswith("bearer "):
        return False
    given = value[7:].strip()
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def _is_ctrl(ch: str) -> bool:
    """改行・タブ以外の制御文字（運びの化けの印）"""
    code = ord(ch)
    if ch in "\n\r\t":
        return False
    return code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F


def text_stats(value) -> dict:
    """s・o の様子だけを数える。中身は返さない"""
    if value is None:
        return {"present": False, "empty": True, "len": 0}
    if not isinstance(value, str):
        return {"present": True, "type": type(value).__name__, "empty": False, "len": 0}
    return {
        "present": True,
        "empty": value.strip() == "",
        "len": len(value),
        "newlines": value.count("\n"),
        "fffd": value.count("�"),
        "ctrl": sum(1 for c in value if _is_ctrl(c)),
        # v0.1.2: どの制御文字かを最大5種類（例 "0x0c"＝改ページ）。運びの化けか、手前の記号かを見分ける材料
        "ctrl_codes": sorted({f"0x{ord(c):02x}" for c in value if _is_ctrl(c)})[:5],
        "qq": len(QQ_RE.findall(value)),
        "mojibake": sum(1 for c in value if c in MOJIBAKE_CHARS),
        "amp_entity": bool(AMP_ENTITY_RE.search(value)),
    }


def homis_stats(value) -> dict:
    """HOMIS ID は空か・数字だけか・桁数だけ。番号そのものは返さない"""
    s = "" if value is None else str(value).strip()
    return {"empty": s == "", "digits_only": s.isdigit(), "len": len(s)}


def _label(value) -> str:
    """種類・経路の名前。長すぎるものは切る（患者の情報は入らない欄）"""
    if value is None:
        return ""
    s = str(value).strip().replace("\n", " ")
    return s[:LABEL_MAX]


def pick_ticket(body: dict) -> tuple[str, str]:
    """札番号を取り出す。ticket が無い・形が違うときは lock（札をください.result まるごと）から。
    返り値: (札番号 or "", どこから取ったか)"""
    t = body.get("ticket")
    if isinstance(t, str) and TICKET_RE.match(t.strip()):
        return t.strip(), "ticket"
    lock = body.get("lock")
    if isinstance(lock, str):
        try:
            lock = json.loads(lock)
        except ValueError:
            lock = None
    if isinstance(lock, dict):
        lt = lock.get("ticket")
        if isinstance(lt, str) and TICKET_RE.match(lt.strip()):
            return lt.strip(), "lock"
    if t is None and lock is None:
        return "", "missing"
    return "", "invalid"


def summarize(body: dict) -> dict:
    """届いた中身から、記録してよい様子だけを作る"""
    ticket, ticket_from = pick_ticket(body)
    return {
        "source": _label(body.get("source")),
        "ticket": ticket,
        "ticket_from": ticket_from,
        "doc_type": _label(body.get("doc_type")),
        "route": _label(body.get("route")),
        "homis_id": homis_stats(body.get("homis_id")),
        "s": text_stats(body.get("s")),
        "o": text_stats(body.get("o")),
    }


def mark_first_request() -> bool:
    """起動して最初の件なら True。同時に2件来ても True は1件だけ（鍵の中で判定と更新をする）"""
    global _first_request_done
    with _log_lock:
        first = not _first_request_done
        _first_request_done = True
    return first


class Handler(BaseHTTPRequestHandler):
    server_version = "fax-receiver/" + VERSION
    sys_version = ""
    timeout = READ_TIMEOUT   # 標準の仕組みで、つながった時に読み込みの上限を付ける

    def _read_body(self, length: int) -> bytes | None:
        """本文を読む。上限時間を過ぎた・途中で切れた・足りないときは None（呼ぶ側で静かに切る）"""
        try:
            data = self.rfile.read(length)
        except OSError:
            return None
        return data if len(data) == length else None

    def _drop(self, reason: str) -> None:
        """読めなかったとき。返事は送らずに切る（相手はもう居ないか、わざと遅い）"""
        log_line({"event": "fax_shadow_reject", "status": 0, "reason": reason, "severity": "WARNING"})
        self.close_connection = True

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if status != 200:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _drain(self) -> bool:
        """断る前に本文を読み捨てる（中身は見ない）。読まずに閉じると相手に切断が届き、返事の番号が伝わらない
        （今のライター v3.1.0 と同じ学び）。256KB を超える・長さが無いときは読まない"""
        raw_len = (self.headers.get("Content-Length") or "").strip()
        if raw_len.isdigit() and 0 < int(raw_len) <= MAX_BODY:
            return self._read_body(int(raw_len)) is not None
        return True

    def _reject(self, status: int, reason: str) -> None:
        log_line({"event": "fax_shadow_reject", "status": status, "reason": reason, "severity": "WARNING"})
        if not self._drain():
            self.close_connection = True
            return
        try:
            self._reply(status, {"ok": False})
        except OSError:
            self.close_connection = True

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/health":
            self._reply(200, {"ok": True, "version": VERSION})
        else:
            self._reply(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        t0 = time.time()
        if self.path.split("?")[0] != "/fax/receive":
            if self._drain():
                self._reply(404, {"ok": False})
            else:
                self.close_connection = True
            return
        expected = os.environ.get("FAX_RECEIVER_KEY", "")
        if not expected.strip():
            self._reject(503, "no_key_configured")
            return
        if not key_ok(self.headers.get("Authorization", ""), expected):
            self._reject(401, "bad_key")
            return
        raw_len = self.headers.get("Content-Length")
        if raw_len is None or not raw_len.strip().isdigit():
            self._reject(411, "no_length")
            return
        length = int(raw_len.strip())
        if length > MAX_BODY:
            self._reject(413, "too_large")
            return
        raw = self._read_body(length) if length else b""
        if raw is None:
            self._drop("read_incomplete")
            return
        record = {
            "event": "fax_shadow",
            "version": VERSION,
            "content_type": (self.headers.get("Content-Type", "") or "")[:60],
            "body_bytes": len(raw),
            "first_request": mark_first_request(),
            "since_start_sec": round(t0 - PROCESS_START, 1),
        }
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            record.update({"json_ok": False, "json_error": type(e).__name__, "severity": "WARNING"})
            log_line(record)
            self._reply(400, {"ok": False})
            return
        if not isinstance(body, dict):
            record.update({"json_ok": False, "json_error": "not_object", "severity": "WARNING"})
            log_line(record)
            self._reply(400, {"ok": False})
            return
        record["json_ok"] = True
        record.update(summarize(body))
        # v0.2.0: 試し書き（FAX_MIRROR=on のときだけ）。記録には結果の短い言葉だけ
        record["mirror"] = enqueue_mirror(record.get("ticket", ""), body.get("s"), body.get("o"))
        del body, raw   # 本文はここで捨てる
        record["elapsed_ms"] = int((time.time() - t0) * 1000)
        log_line(record)
        self._reply(200, {"ok": True, "mode": "shadow"})

    def log_message(self, *args):  # 標準のアクセスログ（パスなど）は出さない
        pass


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    log_line({"event": "fax_receiver_start", "version": VERSION, "key_configured": bool(os.environ.get("FAX_RECEIVER_KEY", "").strip())})
    ThreadingHTTPServer(("", port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
