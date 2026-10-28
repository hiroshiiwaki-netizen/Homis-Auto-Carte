# -*- coding: utf-8 -*-
"""受け口 v0.2.0 の試し書き（段1b）のテスト

偽の metadata サーバー（トークン）と偽の Cloud Tasks（列）を手元に立て、本物の server.py を別プロセスで動かして
Tukusi と同じ形で送る。列に入った仕事の中身（宛先・テスト舞子・S の印・合言葉ヘッダー・IDトークンの設定）と、
受け口の記録（mirror の言葉だけ・本文なし）を確かめる。すべてダミーの値。
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "server.py")
sys.path.insert(0, os.path.join(HERE, ".."))
import server  # noqa: E402

KEY = "mirror-test-key"
WKEY = "writer-key-dummy-QQX"
SECRET_S = "送り元ダミーZZQ"
SECRET_O = "本文ダミーXXQ\n二行目"
QUEUE = "projects/p/locations/asia-northeast1/queues/homis-fax-mirror"


class FakeCloud:
    """偽の metadata と偽の Cloud Tasks。mode: ok / dup / down"""

    def __init__(self):
        self.tasks = []
        self.mode = "ok"
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/token") and self.headers.get("Metadata-Flavor") == "Google":
                    body = json.dumps({"access_token": "tok-123", "expires_in": 3600}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(403)
                    self.end_headers()

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(n))
                if outer.mode == "down":
                    time.sleep(7)   # 時間切れ（受け口は5秒で先へ進む）
                    self.send_response(503)
                    self.end_headers()
                    return
                outer.tasks.append({"path": self.path, "auth": self.headers.get("Authorization"), "task": data["task"]})
                code = 409 if outer.mode == "dup" else 200
                body = b"{}"
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class MirrorFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cloud = FakeCloud()
        cls.tmp = tempfile.mkdtemp(prefix="mirror_")

    @classmethod
    def tearDownClass(cls):
        cls.cloud.close()

    def start(self, **env_over):
        port = free_port()
        log = os.path.join(self.tmp, f"recv_{port}.jsonl")
        env = dict(os.environ, PORT=str(port), FAX_RECEIVER_KEY=KEY, PYTHONIOENCODING="utf-8",
                   FAX_MIRROR="on", WRITER_URL="https://writer.example.run.app", MIRROR_QUEUE=QUEUE,
                   TASKS_INVOKER_SA="homis-tasks-invoker@p.iam.gserviceaccount.com", WRITER_KEY=WKEY + "\n",
                   METADATA_TOKEN_URL=f"http://127.0.0.1:{self.cloud.port}/token",
                   CLOUD_TASKS_BASE=f"http://127.0.0.1:{self.cloud.port}/v2/")
        env.update(env_over)
        f = open(log, "w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-u", SERVER], env=env, stdout=f, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                c.request("GET", "/health")
                if c.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        self.addCleanup(lambda: (p.terminate(), p.wait(10), f.close()))
        return port, log

    def send(self, port, ticket="261028090000-1", s=SECRET_S, o=SECRET_O):
        body = json.dumps({"source": "WF1573", "lock": {"ticket": ticket, "granted": True},
                           "homis_id": "https://homis.jp/homic/?pid=patient_detail&patient_id=1234567&p=5",
                           "s": s, "o": o, "doc_type": "検査結果", "route": "垂水FAX"}).encode("utf-8")
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        t0 = time.time()
        c.request("POST", "/fax/receive", body=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
        st = c.getresponse().status
        c.close()
        return st, time.time() - t0

    def records(self, log):
        time.sleep(0.3)
        with open(log, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.startswith("{")]

    def test_queued_task_content(self):
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        port, log = self.start()
        st, _ = self.send(port)
        self.assertEqual(st, 200)
        self.assertEqual(len(self.cloud.tasks), 1)
        t = self.cloud.tasks[0]
        self.assertEqual(t["path"], "/v2/" + QUEUE + "/tasks")
        self.assertEqual(t["auth"], "Bearer tok-123")
        task = t["task"]
        self.assertEqual(task["name"], QUEUE + "/tasks/FAX-MIRROR-261028090000-1")
        hr = task["httpRequest"]
        self.assertEqual(hr["url"], "https://writer.example.run.app/write")
        self.assertEqual(hr["headers"]["X-Writer-Key"], WKEY)                     # 改行は除く
        self.assertEqual(hr["oidcToken"]["serviceAccountEmail"], "homis-tasks-invoker@p.iam.gserviceaccount.com")
        self.assertEqual(hr["oidcToken"]["audience"], "https://writer.example.run.app")
        payload = json.loads(base64.b64decode(hr["body"]).decode("utf-8"))
        self.assertEqual(payload["homisId"], "2277808")                         # 必ずテスト舞子（本物の患者番号ではない）
        self.assertEqual(payload["template"], "fax_so")
        self.assertEqual(payload["orderId"], "FAX-MIRROR-261028090000-1")
        self.assertEqual(payload["sContent"], server.MIRROR_MARK + SECRET_S)
        self.assertEqual(payload["oContent"], SECRET_O)
        rec = [r for r in self.records(log) if r.get("event") == "fax_shadow"][-1]
        self.assertEqual(rec["mirror"], "queued")
        with open(log, encoding="utf-8") as f:   # 黒ヤギ 10/28 指摘1: 閉じる
            raw = f.read()
        for w in ("ZZQ", "XXQ", WKEY, "1234567"):
            self.assertNotIn(w, raw)                                            # 本文・合言葉・患者番号を記録に出さない

    def test_queue_name_with_slashes_and_spaces(self):
        # 列の名前の前後に「/」や空白・改行があっても、正しい URL と仕事の名前になる（黒ヤギ 10/28 指摘2）
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        port, log = self.start(MIRROR_QUEUE=" /" + QUEUE + "/ \n", CLOUD_TASKS_BASE=f"http://127.0.0.1:{self.cloud.port}/v2")
        self.send(port, ticket="261028090000-7")
        self.assertEqual(self.records(log)[-1]["mirror"], "queued")
        self.assertEqual(self.cloud.tasks[0]["path"], "/v2/" + QUEUE + "/tasks")
        self.assertEqual(self.cloud.tasks[0]["task"]["name"], QUEUE + "/tasks/FAX-MIRROR-261028090000-7")

    def test_only_o_empty_skips(self):
        # O だけ空でも入れない（足りないテストの指摘）
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        port, log = self.start()
        self.send(port, o="  ", ticket="261028090000-8")
        self.assertEqual(self.records(log)[-1]["mirror"], "skip:empty")
        self.assertEqual(self.cloud.tasks, [])

    def test_off_sends_nothing(self):
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        port, log = self.start(FAX_MIRROR="off")
        self.assertEqual(self.send(port)[0], 200)
        self.assertEqual(self.cloud.tasks, [])
        self.assertEqual(self.records(log)[-1]["mirror"], "off")

    def test_duplicate_is_ok(self):
        self.cloud.mode = "dup"
        port, log = self.start()
        self.assertEqual(self.send(port, ticket="261028090000-2")[0], 200)
        self.assertEqual(self.records(log)[-1]["mirror"], "duplicate")

    def test_tasks_down_still_200_quickly(self):
        # 列が応えなくても Tukusi には 200。待ちは上限5秒＋少し
        self.cloud.mode = "down"
        port, log = self.start()
        st, sec = self.send(port, ticket="261028090000-3")
        self.assertEqual(st, 200)
        self.assertLess(sec, 6.5)
        self.assertTrue(self.records(log)[-1]["mirror"].startswith("error:"))
        self.cloud.mode = "ok"

    def test_skip_cases(self):
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        port, log = self.start()
        self.send(port, s="  ", ticket="261028090000-4")
        self.assertEqual(self.records(log)[-1]["mirror"], "skip:empty")
        self.send(port, ticket="")
        self.assertEqual(self.records(log)[-1]["mirror"], "skip:no_ticket")
        self.assertEqual(self.cloud.tasks, [])

    def test_not_test_patient_refused(self):
        # 設定を間違えて本物の患者番号にしても、列に入れない
        self.cloud.mode = "ok"
        self.cloud.tasks.clear()
        port, log = self.start(MIRROR_HOMIS_ID="1234567")
        self.send(port, ticket="261028090000-5")
        self.assertEqual(self.records(log)[-1]["mirror"], "skip:not_test_patient")
        self.assertEqual(self.cloud.tasks, [])

    def test_no_config_skips(self):
        self.cloud.tasks.clear()
        port, log = self.start(WRITER_KEY="")
        self.send(port, ticket="261028090000-6")
        self.assertEqual(self.records(log)[-1]["mirror"], "skip:no_config")
        self.assertEqual(self.cloud.tasks, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
