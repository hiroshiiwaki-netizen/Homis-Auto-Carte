# -*- coding: utf-8 -*-
"""
compare_fax_mirror.py — FAX の試し書き（テスト舞子）と、Tukusi が書いた本物のカルテを HOMIS で読んで、S と O が同じか比べる（読むだけ）

バージョン: 0.1.0 / 最終更新: 2026-10-28
改定履歴:
  v0.1.0 10/28 新規（岩城さん「中身の照合もできてますか」→「1 ができるなら 1 がありがたい」）。仕様 docs/FAXカルテ_検討/SPEC_段1b_並走試し書き.md 6章

読み方: HOMIS の表示専用ページ pdetail_karte.php とカルテ一覧 getKarteList.php だけ（GET）。編集画面は開かない＝カルテを書き換えない
流れ:
  1 カルテライターの記録（Cloud Logging）から、試し書き FAX-MIRROR-<札番号> のテスト舞子のカルテ番号を集める
  2 p281 の「カルテ順番札: 渡しました（HOMIS ID ・札 ）」から、その札がどの患者さんの書類かを引く
  3 その患者さんのその日のカルテを読み、S と O が試し書きと同じカルテを探す（試し書きの S は先頭の印を除いて比べる）
画面に出すのは札番号の末尾と結果だけ。患者さんの名前・番号・カルテの文章は出さない
使い方（PowerShell）: py -3.12 -X utf8 tools/compare_fax_mirror.py [日付 yyyy-mm-dd（既定は今日）]
"""
import datetime as dt
import html as htmlmod
import json
import re
import subprocess
import sys
from pathlib import Path

import requests

VERSION = "0.1.0"
BASE = "https://homis.jp/homic/"
TEST_MAIKO = "2277808"
MARK = "【GCP試し書き・本物は別の患者さん】"
P281_LOG = r"G:\共有ドライブ\OhiscanGo\logs\ohisama-p281_app_{date}.log"
HOMISAPI_TOOLS = r"G:\マイドライブ\Antigravity-PJ\HomisApi\tools"
RE_GIVEN = re.compile(r"カルテ順番札: 渡しました（HOMIS ID (\d+)・札 ([0-9A-Za-z\-]+)")


def norm(t):
    t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(x.rstrip() for x in t.split("\n")).strip()


def shown_block(view, head):
    """表示専用ページの見出し（Ｓ・Ｏ）のすぐ下の <p>（改行は <br>）"""
    m = re.search(r'<h4 class="box_body_title">\s*' + head + r'\s*</h4>\s*<p>([\s\S]*?)</p>', view)
    if not m:
        return None
    return htmlmod.unescape(re.sub(r"<br\s*/?>", "\n", m.group(1)))


def textarea(view, ident):
    m = re.search(r'<textarea[^>]*\b(?:id|name)="' + ident + r'"[^>]*>([\s\S]*?)</textarea>', view)
    return htmlmod.unescape(m.group(1)) if m else None


def read_so(s, pid, kid):
    view = s.get(BASE + "functions/pdetail_karte.php", params={"patient_id": pid, "karte_id": kid}, timeout=30).text
    sv = textarea(view, "subjective")
    if sv is None:
        sv = shown_block(view, "Ｓ")
    ov = textarea(view, "objective")
    if ov is None:
        ov = shown_block(view, "Ｏ")
    return sv, ov


def mirror_results(date):
    """カルテライターの記録から 札番号 → テスト舞子のカルテ番号（成功したものだけ）"""
    d0 = dt.datetime.fromisoformat(date) - dt.timedelta(hours=9)
    q = ('resource.type="cloud_run_revision" AND resource.labels.service_name="homis-karte-writer" '
         f'AND textPayload:"FAX-MIRROR" AND textPayload:"RESULT" AND timestamp>="{d0:%Y-%m-%dT%H:%M:%SZ}" '
         f'AND timestamp<"{(d0 + dt.timedelta(days=1)):%Y-%m-%dT%H:%M:%SZ}"')
    out = subprocess.run(["gcloud", "logging", "read", q, "--project", "gen-lang-client-0979357970", "--limit", "500",
                          "--format=value(textPayload)"], capture_output=True, text=True, encoding="utf-8", shell=True, timeout=120).stdout
    res = {}
    for line in out.splitlines():
        i = line.find("{")
        if i < 0:
            continue
        try:
            j = json.loads(line[i:])
        except ValueError:
            continue
        oid = str(j.get("orderId", ""))
        if oid.startswith("FAX-MIRROR-"):
            res[oid[len("FAX-MIRROR-"):]] = (bool(j.get("success")), str(j.get("karte_id") or ""))
    return res


def ticket_patients(date):
    path = Path(P281_LOG.format(date=date))
    m = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            g = RE_GIVEN.search(line)
            if g:
                m[g.group(2)] = g.group(1)
    return m


def main():
    date = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else dt.date.today().isoformat()
    sys.path.insert(0, HOMISAPI_TOOLS)
    from replay_post import load_account

    mirrors = mirror_results(date)
    tickets = ticket_patients(date)
    print(f"compare_fax_mirror v{VERSION}  {date}  試し書き {len(mirrors)} 件")
    user, pw = load_account("api")
    s = requests.Session()
    s.post(BASE + "auth.php", data={"id": user, "pw": pw, "jaddr": ""}, allow_redirects=False, timeout=30)

    counts = {"一致": 0, "O が違う": 0, "S が違う": 0, "本物が見つからない": 0, "試し書きが読めない": 0, "試し書き失敗": 0, "患者が分からない": 0}
    for ticket in sorted(mirrors):
        ok, mk = mirrors[ticket]
        tag = "…" + ticket[-6:]
        if not ok or not mk:
            counts["試し書き失敗"] += 1
            print(f"  {tag}: 試し書き失敗（ライターの記録）")
            continue
        pid = tickets.get(ticket)
        if not pid:
            counts["患者が分からない"] += 1
            print(f"  {tag}: 患者が分からない（p281 の札の記録に無い・ドライブの同期待ちかも）")
            continue
        ms, mo = read_so(s, TEST_MAIKO, mk)
        if ms is None or mo is None:
            counts["試し書きが読めない"] += 1
            print(f"  {tag}: 試し書きのカルテが読めない（S {'あり' if ms is not None else '無し'}・O {'あり' if mo is not None else '無し'}）")
            continue
        ms_body = norm(ms)
        if ms_body.startswith(MARK):
            ms_body = ms_body[len(MARK):].strip()
        if not ms_body or not norm(mo):
            # 空どうしで「一致」にしない
            counts["試し書きが読めない"] += 1
            print(f"  {tag}: 試し書きの S か O が空（比べない）")
            continue
        klist = s.get(BASE + "functions/getKarteList.php", params={"patient_id": pid}, timeout=30).json()
        cands = [k for k in klist if str(k.get("act_date")) == date]
        best = None
        for k in cands:
            rs, ro = read_so(s, pid, str(k.get("karte_id")))
            s_ok = rs is not None and norm(rs) == ms_body
            o_ok = ro is not None and norm(ro) == norm(mo)
            if s_ok and o_ok:
                best = "一致"
                break
            if s_ok and best is None:
                best = "O が違う"
        if best is None:
            best = "S が違う" if cands else "本物が見つからない"
        counts[best] += 1
        print(f"  {tag}: {best}（その日の本物の候補 {len(cands)} 件）")
    print("まとめ: " + "・".join(f"{k} {v}" for k, v in counts.items() if v))


main()
