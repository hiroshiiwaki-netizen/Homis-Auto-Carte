# -*- coding: utf-8 -*-
"""
fax_requeue.py — 段3 の切り替えの間に来た FAX を、本物の患者さんあてに入れ直す（既定は見るだけ）

バージョン: 0.1.1 / 最終更新: 2026-10-29
改定履歴:
  v0.1.1 10/29 黒ヤギ段3実装レビュー（【進めてよい】）指摘1: 照合の道具を読むファイルを with で閉じる。
               動かす人の gcloud に Secret の読み取り（homis-writer-key）と列への投入（homis-fax-writer）の権限が要る（指摘2・手順の確認の一覧へ）
  v0.1.0 10/29 新規。仕様 docs/FAXカルテ_検討/SPEC_段3_本番切替.md v0.3 7章 3 a〜d（黒ヤギ 10/29 段3仕様 2回目 指摘3「当日その場で組み立てない」）

流れ（札番号ごと）:
  a 札番号を受け取る（受け口の記録で、切り替えの間に mirror の仕事になったもの）
  b p281 の「カルテ順番札: 渡しました（HOMIS ID ・札 ）」で患者さんを引く
  c 試し書き（テスト舞子・注文番号 FAX-MIRROR-<札>）のカルテから S・O を読む（S の先頭の試し書きの印は外す）
  d 本物の患者さんのその日のカルテに同じ S・O が無いことを確かめ、--go のときだけ列 homis-fax-writer に FAX-<札> で入れる
    同じ札の仕事がもう列にあれば Cloud Tasks が 409 で断る（二重にならない）
切り替えてから 15分以上たってから使う（p281 の写しは約10分遅れ・試し書きは1件約50秒）
画面に出すのは札の末尾・判断・文字数だけ。患者さんの名前・番号・本文は出さない。合言葉は Secret Manager から読み、表に出さない
使い方（PowerShell・Homis自動カルテ生成 フォルダ）:
  py -3.12 -X utf8 tools/fax_requeue.py 2026-10-29 261029100244-1 261029100244-2          見るだけ
  py -3.12 -X utf8 tools/fax_requeue.py 2026-10-29 261029100244-1 --go                    列に入れる
"""
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request

import requests

VERSION = "0.1.1"
PROJECT = "gen-lang-client-0979357970"
LIVE_QUEUE = f"projects/{PROJECT}/locations/asia-northeast1/queues/homis-fax-writer"
WRITER_URL = "https://homis-karte-writer-932889871898.asia-northeast1.run.app"
INVOKER = f"homis-tasks-invoker@{PROJECT}.iam.gserviceaccount.com"
CMP = r"G:\マイドライブ\Antigravity-PJ\Homis自動カルテ生成\tools\compare_fax_mirror.py"


def load_cmp():
    """照合の道具の部品（ログイン・読み方・札の記録・試し書きの記録）を借りる"""
    with open(CMP, encoding="utf-8") as f:   # 黒ヤギ 10/29 段3実装 指摘1: 閉じる
        src = f.read().replace("\nmain()\n", "\n")
    g = {}
    exec(compile(src, CMP, "exec"), g)
    return g


def build_task(ticket: str, homis_id: str, s: str, o: str, key: str) -> dict:
    """受け口 0.3.0 の live と同じ形の仕事（注文番号 FAX-<札>）"""
    order_id = "FAX-" + ticket
    payload = {"orderId": order_id, "homisId": homis_id, "patientName": "", "template": "fax_so", "sContent": s, "oContent": o}
    return {"task": {
        "name": LIVE_QUEUE + "/tasks/" + order_id,
        "httpRequest": {
            "url": WRITER_URL + "/write", "httpMethod": "POST",
            "headers": {"Content-Type": "application/json", "X-Writer-Key": key},
            "body": base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii"),
            "oidcToken": {"serviceAccountEmail": INVOKER, "audience": WRITER_URL},
        }}}


def gcloud_out(args) -> str:
    return subprocess.run(["gcloud"] + args, capture_output=True, text=True, encoding="utf-8", shell=True, timeout=60).stdout.strip()


def post_task(task: dict) -> str:
    token = gcloud_out(["auth", "print-access-token"])
    req = urllib.request.Request(f"https://cloudtasks.googleapis.com/v2/{LIVE_QUEUE}/tasks", method="POST",
                                 data=json.dumps(task).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return "列に入れた"
    except urllib.error.HTTPError as e:
        return "もう列にある（同じ札・入れない）" if e.code == 409 else f"列の失敗 HTTP {e.code}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    go = "--go" in sys.argv
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    date, tickets = args[0], args[1:]
    g = load_cmp()
    sys.path.insert(0, g["HOMISAPI_TOOLS"])
    from replay_post import load_account
    user, pw = load_account("api")
    s = requests.Session()
    s.post(g["BASE"] + "auth.php", data={"id": user, "pw": pw, "jaddr": ""}, allow_redirects=False, timeout=30)
    norm, mark = g["norm"], g["MARK"]
    patients = g["ticket_patients"](date)
    mirrors = g["mirror_results"](date)
    key = ""
    print(f"fax_requeue v{VERSION}  {date}  {'列に入れる' if go else '見るだけ'}  札 {len(tickets)} 枚")
    for t in tickets:
        tag = "…" + t[-8:]
        pid = patients.get(t)
        if not pid:
            print(f"  {tag}: p281 の札の記録に無い（写しの遅れなら15分待つ）→ 入れない")
            continue
        ok, mk = mirrors.get(t, (False, ""))
        if not ok or not mk:
            print(f"  {tag}: 試し書きが無い・失敗 → 中身が分からないので入れない（FAX の原本から人が書く）")
            continue
        ms, mo = g["read_so"](s, g["TEST_MAIKO"], mk)
        sv = norm(ms)
        sv = sv[len(mark):].strip() if sv.startswith(mark) else ""
        ov = (mo or "").replace("\r\n", "\n").strip()
        if not sv or not ov:
            print(f"  {tag}: 試し書きの S か O が読めない → 入れない")
            continue
        lst = s.get(g["BASE"] + "functions/getKarteList.php", params={"patient_id": pid}, timeout=30).json()
        same = 0
        for k in [k for k in lst if str(k.get("act_date")) == date]:
            rs, ro = g["read_so"](s, pid, str(k.get("karte_id")))
            if norm(rs) == sv and norm(ro) == norm(ov):
                same += 1
        if same:
            print(f"  {tag}: 本物のその日のカルテに同じ S・O がある（{same}枚）→ 入れない")
            continue
        if not go:
            print(f"  {tag}: 入れてよい（S {len(sv)}字・O {len(ov)}字）。--go で列に入れる")
            continue
        if not key:
            key = gcloud_out(["secrets", "versions", "access", "latest", "--secret", "homis-writer-key", "--project", PROJECT])
            if not key:
                print("  合言葉を読めない → 止める")
                sys.exit(2)
        print(f"  {tag}: {post_task(build_task(t, pid, sv, ov, key))}（S {len(sv)}字・O {len(ov)}字）")


if __name__ == "__main__":
    main()
