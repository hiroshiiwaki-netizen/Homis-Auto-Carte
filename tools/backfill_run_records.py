# -*- coding: utf-8 -*-
"""実行リストの記録を、前の版（ライター 3.11.0 より前）のログから作る（後から埋める）

版: 0.1.0（2026-11-06 新規・岩城さん「前の分も一覧で見たい」）
- 材料: ライターの RESULT ログ（時刻・成否・エラー・カルテ番号）、受け口のログ（FAX の書類種・差出元・経路・受けた時刻、
  問い合わせの受けた時刻）、結果シート（カルテの URL）。送られた中身（S・O）は前の版では残していないので入れない
- 置き場には「無いときだけ作る」（gcloud storage cp --if-generation-match=0）。新しい版が作った記録は上書きしない
- 既定は作る JSON の一覧を出すだけ。--go で置き場に書く
- 患者さんの名前・本文は扱わない。画面に出すのは注文番号と状態だけ

使い方（Bash・ログインは岩城さんの gcloud・gws）:
  py -3.12 -X utf8 tools/backfill_run_records.py --since 2026-11-06T00:00:00+09:00 --until 2026-11-06T09:33:00+09:00
  py -3.12 -X utf8 tools/backfill_run_records.py --since ... --until ... --go
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

PROJECT = "gen-lang-client-0979357970"
BUCKET = "gen-lang-client-0979357970-homis-run-records"
JST = timezone(timedelta(hours=9))
GCLOUD = "gcloud.cmd" if os.name == "nt" else "gcloud"
GWS = "gws.cmd" if os.name == "nt" else "gws"


def run(args: list[str]) -> str:
    # gcloud（中身は Python）は Windows で画面の文字コードで出すので、UTF-8 で出させる（書類種が ??? に化けた）
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", check=True, env=env).stdout


def logs(service: str, extra: str, since: str, until: str) -> list[dict]:
    flt = (f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" AND {extra} '
           f'AND timestamp>="{since}" AND timestamp<"{until}"')
    return json.loads(run([GCLOUD, "logging", "read", flt, "--limit=2000", "--format=json", "--project", PROJECT]) or "[]")


def jst(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST).isoformat(timespec="seconds")


def sheet_urls() -> dict:
    """結果シートの orderId → homisUrl（シートの番号は画面に出さない）"""
    svc = json.loads(run([GCLOUD, "run", "services", "describe", "homis-karte-writer", "--region=asia-northeast1",
                          "--format=json", "--project", PROJECT]))
    sid = [e["value"] for e in svc["spec"]["template"]["spec"]["containers"][0]["env"] if e["name"] == "RESULT_SPREADSHEET_ID"][0]
    out = run([GWS, "sheets", "spreadsheets", "values", "get", "--params", json.dumps({"spreadsheetId": sid, "range": "A2:E"})])
    rows = json.loads(out[out.index("{"):]).get("values", [])
    return {r[1]: (r[3] if len(r) > 3 else "") for r in rows if len(r) > 1}


def route_of(o: str) -> str:
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
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    since = datetime.fromisoformat(a.since).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = datetime.fromisoformat(a.until).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = logs("homis-karte-writer", 'textPayload:"INFO RESULT {"', since, until)
    recv_since = (datetime.fromisoformat(a.since) - timedelta(hours=2)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recv = logs("homis-fax-receiver", '(jsonPayload.event="fax_shadow" OR jsonPayload.event="bot_receive")', recv_since, until)
    fax_meta, bot_meta = {}, {}
    for e in recv:
        j = e.get("jsonPayload") or {}
        if j.get("event") == "fax_shadow" and j.get("ticket"):
            fax_meta["FAX-" + j["ticket"]] = {"doc_type": j.get("doc_type", ""), "source": j.get("source", ""),
                                             "fax_route": j.get("route", ""), "received_at": jst(e["timestamp"])}
        elif j.get("event") == "bot_receive" and j.get("order_id"):
            bot_meta[j["order_id"]] = {"received_at": jst(e["timestamp"])}
    urls = sheet_urls()
    now = datetime.now(JST).isoformat(timespec="seconds")
    recs = []
    for e in results:
        d = json.loads(re.search(r"\{.*\}", e["textPayload"], re.S).group(0))
        o = str(d.get("orderId") or "")
        if not re.match(r"^[0-9A-Za-z\-]{1,80}$", o):
            continue
        ok = bool(d.get("success"))
        fin = jst(e["timestamp"])
        meta = dict(fax_meta.get(o) or bot_meta.get(o) or {})
        received = meta.pop("received_at", "") or fin
        url = urls.get(o, "")
        hid = (parse_qs(urlparse(url).query).get("patient_id") or [""])[0] if url else ""
        doc = meta.pop("doc_type", "") or ("疑義照会" if o.startswith("BOT-G-") else "問い合わせ" if o.startswith("BOT-") else "")
        rec = {"order_id": o, "route": route_of(o), "status": "ok" if ok else "fail", "received_at": received,
               "finished_at": fin, "error_type": str(d.get("error_type") or ""), "karte_id": str(d.get("karte_id") or ""),
               "karte_url": url, "left_in_homis": "saved" if ok else "unknown",   # 前の版の失敗は残したものが分からない＝安全側
               "doc_type": doc, "patient": {"homis_id": hid}, "total_sec": d.get("total_sec"), "backfilled": True,
               "timeline": [{"at": received, "what": "受け口が受けた"}, {"at": fin, "what": "書けた" if ok else "書けなかった"},
                            {"at": now, "what": "前の版のログから後で作った（送られた中身は残っていない）"}], **meta}
        recs.append((received[:10], o, rec))
    for day, o, rec in sorted(recs, key=lambda x: x[2]["received_at"]):
        print(day, o, rec["status"], rec["doc_type"] or "－", "URLあり" if rec["karte_url"] else "URLなし")
    print(f"{len(recs)} 件")
    if not a.go:
        print("（見るだけ。置き場に書くには --go）")
        return 0
    made = skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        for day, o, rec in recs:
            p = os.path.join(tmp, o + ".json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
            r = subprocess.run([GCLOUD, "storage", "cp", p, f"gs://{BUCKET}/records/{day}/{o}.json", "--if-generation-match=0",
                                "--project", PROJECT], capture_output=True, text=True, encoding="utf-8")
            if r.returncode == 0:
                made += 1
            else:
                skipped += 1
                print("書かなかった（もう有る・または失敗）:", o)
    print(f"作った {made} 件・書かなかった {skipped} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
