# -*- coding: utf-8 -*-
"""受け口の結合テスト（本物のサーバーを別プロセスで立て、Tukusi と同じ形で送る → ログ → 突き合わせ）

本番と同じ順番:
  WF1573: 札をください → homis記録 → 札を返します（p281 のログ）→ 横付けの HTTPリクエスト（受け口のログ）
  → tools/fax_shadow_reconcile.py で札番号を突き合わせる
すべてダミーの値。本物の患者情報は使わない。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import http.client

HERE = os.path.dirname(os.path.abspath(__file__))
PJ = os.path.abspath(os.path.join(HERE, "..", ".."))
SERVER = os.path.join(PJ, "cloud_fax_receiver", "server.py")
sys.path.insert(0, os.path.join(PJ, "tools"))
import fax_shadow_reconcile as rec  # noqa: E402

KEY = "integration-key-0002"
SECRET_WORDS = ("ダミー患者名QQZ", "8765432", KEY)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def tukusi_post(port: int, payload: dict, key: str = KEY) -> int:
    """Tukusi（aiohttp）と同じ形: application/json・日本語は \\uXXXX・Content-Length 付き・Bearer"""
    body = json.dumps(payload).encode("utf-8")
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", "/fax/receive", body=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "Python/3.11 aiohttp/3.12.12",
        "Accept": "*/*",
        "Authorization": "Bearer " + key,
    })
    st = c.getresponse().status
    c.close()
    return st


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="faxrecv_")
        cls.port = free_port()
        cls.logpath = os.path.join(cls.tmp, "receiver.jsonl")
        env = dict(os.environ, PORT=str(cls.port), FAX_RECEIVER_KEY=KEY + " ", PYTHONIOENCODING="utf-8")  # 設定側に空白
        cls.logf = open(cls.logpath, "w", encoding="utf-8")
        cls.proc = subprocess.Popen([sys.executable, "-u", SERVER], env=env, stdout=cls.logf, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=1)
                c.request("GET", "/health")
                if c.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("サーバーが立ち上がらない")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.logf.close()

    def records(self) -> list[dict]:
        self.logf.flush()
        time.sleep(0.3)
        out = []
        with open(self.logpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("{"):
                    out.append(json.loads(line))
        return out

    def test_flow_and_reconcile(self):
        # 1) 本番の順番の再現: 札を返したあとに横付けが送る。8件同時（10/15・10/22 の最大と同じ）
        tickets = [f"261026090000-{i}" for i in range(1, 9)]
        hard_text = '患者記録 "引用" と \\ と 改行\n二行目「かぎ」 &curren; & 単体\t タブ ' + SECRET_WORDS[0]
        results = {}

        def send(t):
            results[t] = tukusi_post(self.port, {
                "source": "WF1573", "ticket": t, "homis_id": SECRET_WORDS[1],
                "s": "ダミー送り元", "o": hard_text, "doc_type": "検査結果", "route": "垂水FAX",
            })
        ths = [threading.Thread(target=send, args=(t,)) for t in tickets]
        for th in ths:
            th.start()
        for th in ths:
            th.join()
        self.assertEqual(set(results.values()), {200})
        # 2) ticket の差し込みが効かず、lock（札をください.result まるごと・文字の JSON）から取る件
        lock = json.dumps({"ticket": "261026090000-9", "granted": True, "waited_sec": 0, "timed_out": False})
        self.assertEqual(tukusi_post(self.port, {"source": "WF1573", "ticket": "{{札をください.result.ticket}}",
                                                  "lock": lock, "homis_id": SECRET_WORDS[1], "s": "x", "o": "y"}), 200)
        # 3) 期限で回収されたあとに返しに来た件（p281 は「使われていませんでした」・横付けは動く）
        self.assertEqual(tukusi_post(self.port, {"source": "WF1573", "ticket": "261026090000-10",
                                                  "homis_id": SECRET_WORDS[1], "s": "x", "o": "y"}), 200)
        # 4) 合言葉違い（数に入らない）
        self.assertEqual(tukusi_post(self.port, {"ticket": "261026090000-99"}, key="wrong"), 401)

        recs = self.records()
        shadow = [r for r in recs if r.get("event") == "fax_shadow"]
        self.assertEqual(len(shadow), 10)
        hard = [r for r in shadow if r["ticket"] in tickets]
        for r in hard:
            self.assertTrue(r["json_ok"])
            self.assertEqual(r["content_type"], "application/json")
            self.assertEqual(r["o"]["len"], len(hard_text))          # 記号・改行入りでも1文字も欠けずに届く
            self.assertEqual(r["o"]["newlines"], 1)
            self.assertEqual(r["o"]["fffd"], 0)
            self.assertEqual(r["o"]["ctrl"], 0)
            self.assertTrue(r["o"]["amp_entity"])
            self.assertEqual(r["homis_id"], {"empty": False, "digits_only": True, "len": 7})
            self.assertEqual(r["ticket_from"], "ticket")
        self.assertEqual([r["ticket_from"] for r in shadow if r["ticket"] == "261026090000-9"], ["lock"])
        self.assertEqual(sum(1 for r in recs if r.get("event") == "fax_shadow_reject"), 1)
        self.assertEqual(sum(1 for r in shadow if r["first_request"]), 1)
        # 本文・患者番号・合言葉がログに出ていない
        with open(self.logpath, encoding="utf-8") as f:
            raw = f.read()
        for w in SECRET_WORDS + ("引用", "かぎ", "ダミー送り元"):
            self.assertNotIn(w, raw)

        # 5) p281 のログの写し（番号はダミー）と突き合わせる
        p281 = os.path.join(self.tmp, "ohisama-p281_app_2026-10-26.log")
        with open(p281, "w", encoding="utf-8") as f:
            for i, t in enumerate(tickets + ["261026090000-9"]):
                f.write(f"[ohisama-p281] [2026-10-26 09:00:{i:02d}] info: 🎫 カルテ順番札: 渡しました（HOMIS ID 1111111・札 {t}）\n")
                f.write(f"[ohisama-p281] [2026-10-26 09:01:{i:02d}] info: 🎫 カルテ順番札: 返されました（札 {t}）\n")
            f.write("[ohisama-p281] [2026-10-26 09:05:00] warning: ⚠️ カルテ順番札: 返されないまま 210 秒たったので回収しました（HOMIS ID 1111111・札 261026090000-10）\n")
            f.write("[ohisama-p281] [2026-10-26 09:05:10] info: 🎫 カルテ順番札: 返された札 261026090000-10 は使われていませんでした（期限で回収済みなど）\n")
        res = rec.reconcile(rec.read_p281([p281]), rec.read_receiver(self.logpath)[0])
        self.assertEqual((res["p281_returned"], res["p281_unused"], res["receiver_total"]), (9, 1, 10))
        self.assertEqual((res["missing"], res["extra"], res["duplicated"]), ([], [], []))
        self.assertEqual(rec.main(["--p281", p281, "--receiver", self.logpath]), 0)

        # 6) 欠けがあれば見つける（p281 に1件足す＝受け口に届かなかった件）
        with open(p281, "a", encoding="utf-8") as f:
            f.write("[ohisama-p281] [2026-10-26 09:06:00] info: 🎫 カルテ順番札: 返されました（札 261026090000-11）\n")
        res2 = rec.reconcile(rec.read_p281([p281]), rec.read_receiver(self.logpath)[0])
        self.assertEqual(res2["missing"], ["261026090000-11"])
        self.assertEqual(rec.main(["--p281", p281, "--receiver", self.logpath]), 1)

        # 7) p281 側で同じ札番号が2回記録されていたら重なりとして出す（v0.1.1・黒ヤギ実装レビュー 指摘4）
        p281b = os.path.join(self.tmp, "ohisama-p281_app_2026-10-27.log")
        with open(p281b, "w", encoding="utf-8") as f:
            f.write(f"[ohisama-p281] [2026-10-27 09:00:00] info: 🎫 カルテ順番札: 返されました（札 {tickets[0]}）\n")
        p281_map, seen = rec.read_p281_counted([p281, p281b])
        res3 = rec.reconcile(p281_map, rec.read_receiver(self.logpath)[0], seen)
        self.assertEqual(res3["p281_duplicated"], [tickets[0]])

    def test_time_window(self):
        """v0.1.2: --since・--until を受け口にも効かせる（UTC → 日本時間・境目の件は余りにしない）（黒ヤギ再レビュー 指摘1）"""
        recv = os.path.join(self.tmp, "recv_window.jsonl")
        rows = [  # 受け口の time は UTC。日本時間 = +9時間
            ("2026-10-26T00:30:00+00:00", "W-1"),   # 09:30 JST 時間帯の中
            ("2026-10-26T02:59:30+00:00", "W-2"),   # 11:59:30 JST 中
            ("2026-10-26T03:00:20+00:00", "W-3"),   # 12:00:20 JST 札は 11:59:50 に返された（境目）→ 数える
            ("2026-10-26T03:00:40+00:00", "W-4"),   # 12:00:40 JST 札は 12:00:10 に返された（時間帯の外）→ 余りにしない
            ("2026-10-25T23:00:00+00:00", "W-0"),   # 08:00 JST 時間帯の前 → 読まない
            ("2026-10-26T05:00:00+00:00", "W-9"),   # 14:00 JST until＋余裕の後 → 読まない
        ]
        with open(recv, "w", encoding="utf-8") as f:
            for t, k in rows:
                f.write(json.dumps({"event": "fax_shadow", "json_ok": True, "time": t, "ticket": k, "ticket_from": "ticket"}) + "\n")
        p281 = os.path.join(self.tmp, "ohisama-p281_app_window.log")
        with open(p281, "w", encoding="utf-8") as f:
            for t, k in (("09:29:50", "W-1"), ("11:59:20", "W-2"), ("11:59:50", "W-3"), ("12:00:10", "W-4"), ("07:59:50", "W-0"), ("13:59:50", "W-9")):
                f.write(f"[ohisama-p281] [2026-10-26 {t}] info: 🎫 カルテ順番札: 返されました（札 {k}）\n")
        args = ["--p281", p281, "--receiver", recv, "--since", "2026-10-26 09:00:00", "--until", "2026-10-26 12:00:00"]
        self.assertEqual(rec.main(args), 0)                                   # 時間帯で絞っても一致
        tickets, _ = rec.read_receiver(recv, "2026-10-26 09:00:00", "2026-10-26 12:00:00")
        self.assertEqual(sorted(tickets), ["W-1", "W-2", "W-3", "W-4"])
        self.assertEqual(rec.to_jst_text("2026-10-26T03:00:20+00:00"), "2026-10-26 12:00:20")
        # v0.1.3: 秒・時刻を省いても同じ結果（黒ヤギ5回目 指摘1）。読めない形は止める（終了番号 2）
        self.assertEqual(rec.main(["--p281", p281, "--receiver", recv, "--since", "2026-10-26 09:00", "--until", "2026-10-26 12:00"]), 0)
        self.assertEqual(rec.normalize_time_arg("2026-10-26"), "2026-10-26 00:00:00")
        with self.assertRaises(SystemExit) as cm:
            import contextlib, io as _io
            with contextlib.redirect_stderr(_io.StringIO()):
                rec.main(["--p281", p281, "--receiver", recv, "--until", "10/26 12時"])
        self.assertEqual(cm.exception.code, 2)
        # 時間帯の中で札が返されたのに受け口に無い件は「欠け」
        with open(p281, "a", encoding="utf-8") as f:
            f.write("[ohisama-p281] [2026-10-26 10:00:00] info: 🎫 カルテ順番札: 返されました（札 W-5）\n")
        self.assertEqual(rec.main(args), 1)

    def test_gcloud_json_format(self):
        """gcloud logging read --format=json の形（jsonPayload の中）でも読める"""
        path = os.path.join(self.tmp, "gcloud.json")
        entries = [{"jsonPayload": {"event": "fax_shadow", "json_ok": True, "ticket": "A-1", "ticket_from": "ticket"}},
                   {"jsonPayload": {"event": "fax_shadow_reject", "status": 401}}]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        tickets, sources = rec.read_receiver(path)
        self.assertEqual(dict(tickets), {"A-1": 1})


if __name__ == "__main__":
    unittest.main()
