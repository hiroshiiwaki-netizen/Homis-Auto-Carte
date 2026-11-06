# -*- coding: utf-8 -*-
"""実行リストの記録（run_record.py）のテスト用の偽の Cloud Storage。中身を持ち、世代つきで読み書きする。

  GET  /storage/v1/b/<bucket>/o/<name>?alt=media                       中身（x-goog-generation に世代）。無ければ 404
  POST /upload/storage/v1/b/<bucket>/o?uploadType=media&name=…&ifGenerationMatch=N
                                                                       N=0 は無いときだけ・N>0 は世代が同じときだけ。違えば 412
  GET  /token                                                          偽の metadata（トークン）
mode: ok／down（500）／hang（返事を遅らせる）／deny（403）
受け口のテスト（cloud_fax_receiver/tests）からも使う。すべてダミーの値。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeRecords:
    def __init__(self):
        self.objects = {}    # name -> (generation, dict)
        self.calls = []      # (method, name)
        self.mode = "ok"
        self.hang_sec = 10.0
        self.before_put = None   # def hook(name) → 書く直前に呼ぶ（先を越される場面を作る）
        self._gen = 1000
        self._lock = threading.RLock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:   # 相手が時間切れで先に切った（テストの想定どおり）
                    pass

            def _trouble(self) -> bool:
                if outer.mode == "hang":
                    time.sleep(outer.hang_sec)
                    # 遅れたあとは書かない（呼んだ側はもう時間切れであきらめている。遅れて書くと、あとのテストの最中に
                    # 記録が入り込んで数がずれる＝11/6 test_q9 が 3 回に 1 回 2 件になった）
                    self._send(504, b"{}")
                    return True
                if outer.mode == "down":
                    self._send(500, b"{}")
                    return True
                if outer.mode == "deny":
                    self._send(403, b"{}")
                    return True
                return False

            def do_GET(self):
                path, _, q = self.path.partition("?")
                if path.startswith("/token"):
                    self._send(200, json.dumps({"access_token": "tok-rec", "expires_in": 3600}).encode())
                    return
                if re.match(r"^/storage/v1/b/[^/]+/o$", path):   # 一覧（実行リストの箱が使う）
                    prefix = urllib.parse.parse_qs(q).get("prefix", [""])[0]
                    with outer._lock:
                        items = [{"name": n} for n in sorted(outer.objects) if n.startswith(prefix)]
                    self._send(200, json.dumps({"items": items}).encode())
                    return
                m = re.match(r"^/storage/v1/b/[^/]+/o/(.+)$", path)
                if not m:
                    self._send(404)
                    return
                name = urllib.parse.unquote(m.group(1))
                with outer._lock:
                    outer.calls.append(("GET", name))
                if self._trouble():
                    return
                with outer._lock:
                    got = outer.objects.get(name)
                if got is None:
                    self._send(404, b"{}")
                    return
                self._send(200, json.dumps(got[1], ensure_ascii=False).encode("utf-8"), {"x-goog-generation": str(got[0])})

            def do_POST(self):
                path, _, q = self.path.partition("?")
                qs = urllib.parse.parse_qs(q)
                n = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(n)
                name = qs.get("name", [""])[0]
                with outer._lock:
                    outer.calls.append(("POST", name))
                if self._trouble():
                    return
                if outer.before_put:
                    outer.before_put(name)
                want = int(qs.get("ifGenerationMatch", ["-1"])[0])
                with outer._lock:
                    cur = outer.objects.get(name)
                    cur_gen = cur[0] if cur else 0
                    if want != -1 and want != cur_gen:
                        self._send(412, b"{}")
                        return
                    outer._gen += 1
                    outer.objects[name] = (outer._gen, json.loads(raw.decode("utf-8")))
                self._send(200, json.dumps({"name": name, "generation": str(outer._gen)}).encode())

        class Srv(ThreadingHTTPServer):
            request_queue_size = 64   # 箱が並べて読むので、受けの列を広げる

        self.httpd = Srv(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def get(self, name: str):
        with self._lock:
            got = self.objects.get(name)
        return got[1] if got else None

    def put(self, name: str, rec: dict) -> None:
        with self._lock:
            self._gen += 1
            self.objects[name] = (self._gen, rec)

    def bump(self, name: str) -> None:
        """世代だけ上げる（ほかの書き手が先に書いた場面）"""
        with self._lock:
            g, rec = self.objects[name]
            self._gen += 1
            self.objects[name] = (self._gen, rec)

    def reset(self) -> None:
        with self._lock:
            self.objects.clear()
            self.calls.clear()
        self.mode = "ok"
        self.before_put = None

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
