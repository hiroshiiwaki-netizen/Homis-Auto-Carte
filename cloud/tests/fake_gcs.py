# -*- coding: utf-8 -*-
"""偽の Cloud Storage（札の置き場）と偽の metadata サーバー。テスト専用

patient_lock.py が使う 3 つの口だけをまねる:
  POST   /upload/storage/v1/b/<bucket>/o?uploadType=multipart&ifGenerationMatch=0   札を作る（有れば 412）
  GET    /storage/v1/b/<bucket>/o/<name>                                            メタデータ（generation・timeCreated・metadata）
  DELETE /storage/v1/b/<bucket>/o/<name>?ifGenerationMatch=<gen>                    世代指定で消す（無ければ 404・違えば 412）
  GET    /token                                                                     偽の metadata（access_token）
世代番号は本物と同じく作るたびに増える。timeCreated は clock() の値（テストで戻せる）。
fail_next=(status, 回数) で次の N 回を失敗にできる。on_delete／on_get のフック（競合の再現用）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int((t % 1) * 1000):03d}Z"


class FakeGCS:
    def __init__(self):
        self.lock = threading.RLock()   # フック（on_delete 等）の中から put() を呼べるように再入できる鍵
        self.objects: dict[str, dict] = {}
        self.next_gen = 1000
        self.clock = time.time
        self.calls: list[tuple[str, str]] = []
        self.fail_next: tuple[int, int] | None = None   # (status, 残り回数)
        self.on_delete = None   # def hook(name) → 消す直前に呼ぶ
        self.on_get = None      # def hook(name) → 読む直前に呼ぶ
        self.token_expires_in = 3600   # 偽の metadata が返す残り寿命（秒）
        self.always_conflict = False   # True なら札を作る POST を必ず 412 にする（高速の繰り返しの試験用）
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None):
                data = json.dumps(obj).encode("utf-8") if obj is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if data:
                    self.wfile.write(data)

            def _fail(self) -> bool:
                if outer.fail_next and outer.fail_next[1] > 0:
                    st = outer.fail_next[0]
                    outer.fail_next = (st, outer.fail_next[1] - 1)
                    self._send(st, {"error": "fake"})
                    return True
                return False

            def _name(self, path):
                m = re.match(r"^/storage/v1/b/[^/]+/o/(.+)$", path)
                return urllib.parse.unquote(m.group(1)) if m else None

            def do_GET(self):
                path, _, q = self.path.partition("?")
                with outer.lock:
                    outer.calls.append(("GET", path))
                if path == "/token":
                    return self._send(200, {"access_token": "fake-token-%d" % outer.count("GET", "/token"), "expires_in": outer.token_expires_in})
                if self._fail():
                    return
                name = self._name(path)
                with outer.lock:
                    if outer.on_get:
                        outer.on_get(name)
                    o = outer.objects.get(name) if name else None
                    if o is None:
                        return self._send(404, {"error": "not found"})
                    return self._send(200, {"name": name, "generation": str(o["generation"]),
                                            "timeCreated": _iso(o["created"]), "metadata": o["metadata"]})

            def do_POST(self):
                path, _, q = self.path.partition("?")
                qs = urllib.parse.parse_qs(q)
                n = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(n).decode("utf-8")
                with outer.lock:
                    outer.calls.append(("POST", path))
                if self._fail():
                    return
                m = re.search(r"\r\n\r\n(\{.*?\})\r\n--", raw, re.S)
                meta = json.loads(m.group(1)) if m else {}
                name = meta.get("name", "")
                with outer.lock:
                    if outer.always_conflict or (qs.get("ifGenerationMatch", ["0"])[0] == "0" and name in outer.objects):
                        return self._send(412, {"error": "precondition failed"})
                    outer.next_gen += 1
                    outer.objects[name] = {"generation": outer.next_gen, "created": outer.clock(), "metadata": meta.get("metadata", {})}
                    o = outer.objects[name]
                    return self._send(200, {"name": name, "generation": str(o["generation"]), "timeCreated": _iso(o["created"])})

            def do_DELETE(self):
                path, _, q = self.path.partition("?")
                qs = urllib.parse.parse_qs(q)
                with outer.lock:
                    outer.calls.append(("DELETE", path))
                if self._fail():
                    return
                name = self._name(path)
                want = qs.get("ifGenerationMatch", [""])[0]
                with outer.lock:
                    if outer.on_delete:
                        outer.on_delete(name)
                    o = outer.objects.get(name) if name else None
                    if o is None:
                        return self._send(404, {"error": "not found"})
                    if want and str(o["generation"]) != want:
                        return self._send(412, {"error": "precondition failed"})
                    del outer.objects[name]
                    return self._send(204)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    # --- テストから使う ---
    def install_env(self, bucket: str = "test-locks") -> None:
        os.environ["GCS_BASE"] = self.base
        os.environ["METADATA_TOKEN_URL"] = self.base + "/token"
        os.environ["LOCK_BUCKET"] = bucket

    def reset(self) -> None:
        with self.lock:
            self.objects.clear()
            self.calls.clear()
            self.fail_next = None
            self.on_delete = None
            self.on_get = None
            self.clock = time.time
            self.token_expires_in = 3600
            self.always_conflict = False

    def put(self, name: str, age_sec: float = 0.0, metadata: dict | None = None) -> int:
        """札を置く（age_sec 秒前に作ったことにする）。返り値は世代番号"""
        with self.lock:
            self.next_gen += 1
            self.objects[name] = {"generation": self.next_gen, "created": time.time() - age_sec, "metadata": metadata or {}}
            return self.next_gen

    def gen(self, name: str):
        with self.lock:
            o = self.objects.get(name)
            return o["generation"] if o else None

    def count(self, method: str, path_part: str = "") -> int:
        with self.lock:
            return sum(1 for m, p in self.calls if m == method and path_part in p)

    def shutdown(self) -> None:
        self.httpd.shutdown()
