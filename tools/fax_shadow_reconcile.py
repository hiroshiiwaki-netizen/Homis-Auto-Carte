# -*- coding: utf-8 -*-
"""FAX カルテの受け口（段1）と p281 の「カルテ順番札」を札番号で突き合わせる（読むだけ）

==============================================================================
バージョン: 0.1.3
最終更新: 2026/10/26
改定履歴（新しい順・全体は docs/SPEC_v3_cloud.md 0章「モジュール別の版」）:
  v0.1.3 10/26 黒ヤギ5回目の指摘1・2: --since・--until の秒・時刻の省略を補う（読めない形は分かる言葉で止める）・--p281 に渡すログの範囲を説明に
  v0.1.2 10/26 黒ヤギ再レビューの指摘1: --since・--until を受け口のログにも効かせる（UTC → 日本時間にそろえる・
               until は --margin-sec だけ広げる・時間帯の外で札が返された件は「余り」にしない）
  v0.1.1 10/26 黒ヤギ実装レビューの指摘: p281 側の同じ札番号の重なりも数えて出す・ファイルを with で閉じる
  v0.1.0 10/26 初版
==============================================================================

仕様: docs/FAXカルテ_検討/SPEC_受け口_横付け_v0.md 5章
  札が返された件（「返されました」＋「返された札 … は使われていませんでした」）＝ 受け口に届いた件 か

使い方（PowerShell）:
  py -3.12 -X utf8 tools/fax_shadow_reconcile.py --p281 "<p281 のログ（*.log・複数可）>" --receiver <受け口のログ.json>
  受け口のログは gcloud logging read の --format=json の出力、または受け口が出した JSON の行（JSONL）
  --since・--until は日本時間。'YYYY-MM-DD HH:MM:SS'・'YYYY-MM-DD HH:MM'・'YYYY-MM-DD'（その日の 00:00:00）のどれでも可
  --p281 には、突き合わせる日とその前後1日のログだけを渡す（札番号は起動時刻＋連番で重ならないが、読む量を抑えるため）

出すもの: 件数と、合わなかった札番号だけ。HOMIS ID・患者名は出さない
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

VERSION = "0.1.3"
MARGIN_SEC = 300   # 札を返してから横付けが届くまでの余裕（秒）。until の側だけ広げる
# p281 のログの行（例は番号を伏せたもの）
#   ... info: 🎫 カルテ順番札: 返されました（札 261021120224-54）
#   ... info: 🎫 カルテ順番札: 返された札 261021120224-19 は使われていませんでした（期限で回収済みなど）
RE_TIME = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]")
RE_RETURNED = re.compile(r"カルテ順番札: 返されました（札 ([0-9A-Za-z\-]+)）")
RE_UNUSED = re.compile(r"カルテ順番札: 返された札 ([0-9A-Za-z\-]+) は使われていませんでした")


def read_p281(paths: list[str], since: str = "", until: str = "") -> dict[str, str]:
    """札番号 → 種類（returned / unused）。since・until は 'YYYY-MM-DD HH:MM:SS'（含む・含まない）"""
    return read_p281_counted(paths, since, until)[0]


def read_p281_counted(paths: list[str], since: str = "", until: str = "") -> tuple[dict[str, str], Counter]:
    """札番号 → 種類 と、札番号ごとの記録の数（同じ札番号が2回以上なら p281 側の重なり）"""
    out: dict[str, str] = {}
    seen: Counter = Counter()
    files: list[str] = []
    for p in paths:
        files.extend(sorted(glob.glob(p)) or [p])
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "カルテ順番札" not in line:
                    continue
                m = RE_TIME.search(line)
                t = m.group(1) if m else ""
                if since and t and t < since:
                    continue
                if until and t and t >= until:
                    continue
                r = RE_RETURNED.search(line)
                if r:
                    out[r.group(1)] = "returned"
                    seen[r.group(1)] += 1
                    continue
                u = RE_UNUSED.search(line)
                if u:
                    out[u.group(1)] = "unused"
                    seen[u.group(1)] += 1
    return out, seen


JST = timezone(timedelta(hours=9))


def to_jst_text(iso: str) -> str:
    """受け口の時刻（UTC の ISO 形式）を p281 のログと同じ日本時間の 'YYYY-MM-DD HH:MM:SS' に。読めなければ空"""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")


def normalize_time_arg(text: str) -> str:
    """--since・--until を 'YYYY-MM-DD HH:MM:SS' にそろえる。秒・時刻の省略を補う。読めなければ ValueError"""
    s = (text or "").strip()
    if not s:
        return ""
    for fmt, add in (("%Y-%m-%d %H:%M:%S", ""), ("%Y-%m-%d %H:%M", ":00"), ("%Y-%m-%d", " 00:00:00")):
        try:
            datetime.strptime(s, fmt)
            return s + add
        except ValueError:
            continue
    raise ValueError(f"時刻の形が読めません: {s}（例 2026-10-26 12:00:00）")


def _add_sec(text: str, sec: int) -> str:
    return (datetime.strptime(text, "%Y-%m-%d %H:%M:%S") + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M:%S")


def read_receiver(path: str, since: str = "", until: str = "", margin_sec: int = MARGIN_SEC) -> tuple[Counter, Counter]:
    """受け口のログから (札番号の数え, ticket_from の数え)。gcloud の JSON 配列でも JSONL でも読む。
    since・until は日本時間（p281 と同じ）。横付けは札を返したあとに届くので、until の側は margin_sec 秒だけ広げて読む"""
    until_wide = _add_sec(until, margin_sec) if until else ""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read().strip()
    records: list[dict] = []
    if text.startswith("["):
        for e in json.loads(text):
            records.append(e.get("jsonPayload", e))
    else:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    records.append(json.loads(line))
                except ValueError:
                    pass
    tickets: Counter = Counter()
    sources: Counter = Counter()
    for r in records:
        if r.get("event") != "fax_shadow" or not r.get("json_ok"):
            continue
        t = to_jst_text(r.get("time", "")) if r.get("time") else ""
        if t and since and t < since:
            continue
        if t and until_wide and t >= until_wide:
            continue
        sources[r.get("ticket_from", "")] += 1
        tickets[r.get("ticket") or "(札番号なし)"] += 1
    return tickets, sources


def reconcile(p281: dict[str, str], tickets: Counter, p281_seen: Counter | None = None,
              p281_outside: set[str] | None = None) -> dict:
    """p281_outside: 指定した時間帯の外で札が返された札番号（境目で受け口だけ時間帯に入った件を「余り」にしない）"""
    received = {t for t in tickets if t != "(札番号なし)"} - (p281_outside or set())
    expected = set(p281)
    return {
        "p281_duplicated": sorted(t for t, n in (p281_seen or Counter()).items() if n > 1),
        "p281_returned": sum(1 for v in p281.values() if v == "returned"),
        "p281_unused": sum(1 for v in p281.values() if v == "unused"),
        "receiver_total": sum(tickets.values()),
        "receiver_no_ticket": tickets.get("(札番号なし)", 0),
        "missing": sorted(expected - received),            # 札は返されたのに受け口に届いていない
        "extra": sorted(received - expected),              # 受け口に届いたのに p281 に札の返却が無い
        "duplicated": sorted(t for t, n in tickets.items() if n > 1 and t != "(札番号なし)"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="受け口と p281 の札を突き合わせる（読むだけ）")
    ap.add_argument("--p281", nargs="+", required=True)
    ap.add_argument("--receiver", required=True)
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="")
    ap.add_argument("--margin-sec", type=int, default=MARGIN_SEC, dest="margin_sec")
    a = ap.parse_args(argv)
    try:
        a.since, a.until = normalize_time_arg(a.since), normalize_time_arg(a.until)
    except ValueError as e:
        ap.error(str(e))
    p281, p281_seen = read_p281_counted(a.p281, a.since, a.until)
    p281_all = read_p281(a.p281) if (a.since or a.until) else p281
    outside = set(p281_all) - set(p281)
    tickets, sources = read_receiver(a.receiver, a.since, a.until, a.margin_sec)
    res = reconcile(p281, tickets, p281_seen, outside)
    print(f"fax_shadow_reconcile v{VERSION}")
    print(f"p281 返されました {res['p281_returned']}件 ＋ 使われていませんでした {res['p281_unused']}件")
    print(f"受け口に届いた {res['receiver_total']}件（札番号なし {res['receiver_no_ticket']}件・取り出し元 {dict(sources)}）")
    print(f"欠け {len(res['missing'])}件  余り {len(res['extra'])}件  重なり {len(res['duplicated'])}件  "
          f"p281 側の重なり {len(res['p281_duplicated'])}件")
    for k in ("missing", "extra", "duplicated", "p281_duplicated"):
        if res[k]:
            print(f"  {k}: {', '.join(res[k])}")
    ok = not (res["missing"] or res["extra"] or res["duplicated"] or res["receiver_no_ticket"] or res["p281_duplicated"])
    print("判定: " + ("一致" if ok else "不一致（上の札番号で p281 のログを引いて調べる）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
