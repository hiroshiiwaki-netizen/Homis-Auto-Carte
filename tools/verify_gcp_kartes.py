# -*- coding: utf-8 -*-
"""
verify_gcp_kartes.py — GCP のカルテライターが書いたカルテを、HOMIS で読んで注文どおりか確かめる（読むだけ）

バージョン: 0.1.1 / 最終更新: 2026-10-24
改定履歴:
  v0.1.1 10/24 黒ヤギの指摘: 一覧に無いときは外来を判定しない・時刻を秒で丸める・ORCA の空白を削らない・指示医が職員マスターに無いときはメールのまま
  v0.1.0 10/24 新規（岩城さん「GCP で書いたものは内容も含めて大丈夫？そこまでやっての合格」）

読み方: HOMIS の表示専用ページ pdetail_karte.php とカルテ一覧 getKarteList.php だけ（GET）。編集画面は開かない＝カルテを書き換えない
  （表示専用ページは編集の鍵を取らない。HomisApi 10/15 の調べ）
比べるもの: 外来（karte_type=10）・指示医（職員マスターの HOMIS医師ID）・診察日・開始/終了時刻（撮影時刻と +10分）・A/P 欄の全文・同じ時刻のカルテが1枚か
  S 欄は表示専用ページに無いので確かめられない
画面に出すのは注文番号の末尾と一致・不一致だけ。患者さんの名前・番号・カルテの文章は出さない
使い方: python -X utf8 verify_gcp_kartes.py <作業フォルダ> <HomisApi\\tools> [撮影日の始め yyyy-mm-dd] [終わり]
  作業フォルダ: orders.json（レントゲン管理 A:BC・UNFORMATTED・SERIAL）・staff.json（職員 A:B と J）・patients.json（患者 A と K）
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import requests

BASE = "https://homis.jp/homic/"
GAIRAI = "10"  # 新しいカルテの画面の karte_type: 10=外来・0=定期診療（HomisApi docs\_har の控え）
C = dict(ID=0, CREATED_AT=1, HOMIS_ID=2, DOCTOR_EMAIL=24, STATUS=26, LOOKREC=27, HOMIS_LINKED=30, PATIENT_NAME=31,
         SHOOTING_DATE=40, SC1=47, SC2=48, SC3=49, GROUP_ID=52, IS_GROUP=53)
ORDER = [(4, 5, 6, 7, 8), (11, 12, 13, 14, 15), (18, 19, 20, 21, 22)]  # 部位・左右・体位・方向・目的


def serial_to_dt(v):
    """スプレッドシートの日時（シリアル値・日本時間）を datetime に"""
    if v in ("", None):
        return None
    # 秒に丸める（float のままだと 10:14:59.99 になり 1分ずれる。黒ヤギ 10/24 指摘3）
    return dt.datetime(1899, 12, 30) + dt.timedelta(seconds=round(float(v) * 86400))


def cell(r, i):
    return r[i] if i < len(r) and r[i] is not None else ""


def norm(t):
    t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(x.rstrip() for x in t.split("\n")).strip()


def nospace(t):
    return re.sub(r"[\s　]+", "", t or "")


def expected_ap(r, orca, doctor_name):
    """レントゲンナビ PDF.gs createHomisJSON_ と同じ組み立て（集団は Order.gs completeGroupExam の既定値）"""
    shoot = serial_to_dt(cell(r, C["SHOOTING_DATE"]))
    created = serial_to_dt(cell(r, C["CREATED_AT"])) or shoot
    is_group = str(cell(r, C["IS_GROUP"])).upper() == "TRUE"
    if is_group:
        s, side, pos, dirn, _ = ORDER[0]
        orders = [dict(site=cell(r, s) or "胸部正面", pos=cell(r, pos) or "立位", dirn=cell(r, dirn) or "PA", purpose="集団検診")]
        counts = [int(cell(r, C["SC1"]) or 1)]
    else:
        orders, counts = [], []
        for k, (s, side, pos, dirn, pur) in enumerate(ORDER):
            if cell(r, s):
                orders.append(dict(site=cell(r, s), pos=cell(r, pos), dirn=cell(r, dirn), purpose=cell(r, pur)))
                counts.append(int(cell(r, [C["SC1"], C["SC2"], C["SC3"]][k]) or 0))
    ap = "指示医：" + doctor_name + "\n"
    ap += (orca or "") + str(cell(r, C["PATIENT_NAME"])) + "様XP " + shoot.strftime("%Y_%m_%d") + " XP依頼日: " + created.strftime("%Y_%m_%d") + "\n"
    total = 0
    for idx, o in enumerate(orders):
        n = counts[idx] if idx < len(counts) else 0
        total += n
        site = o["site"] + (o["dirn"] or "") + ("（" + o["pos"] + "）" if o["pos"] else "")
        if o["purpose"]:
            ap += "目的：" + o["purpose"] + "\n"
        ap += "部位：" + site + "\n"
        ap += "撮影枚数：" + str(n) + "枚\n"
        if idx == 0 and cell(r, C["LOOKREC"]):
            ap += str(cell(r, C["LOOKREC"])) + "\n"
        ap += "\n"
    ap += "合計：" + str(total) + "枚"
    return ap, shoot


def hidden(html, name):
    m = re.search(r'<input[^>]*name="' + name + r'"[^>]*value="([^"]*)"', html) or re.search(r'<input[^>]*value="([^"]*)"[^>]*name="' + name + '"', html)
    return m.group(1) if m else None


def textarea(html, ident):
    m = re.search(r'<textarea[^>]*\b(?:id|name)="' + ident + r'"[^>]*>([\s\S]*?)</textarea>', html)
    if not m:
        return None
    return m.group(1).replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#039;", "'").replace("&amp;", "&")


def main():
    work, tools = Path(sys.argv[1]), sys.argv[2]
    d0 = sys.argv[3] if len(sys.argv) > 3 else "2026-10-16"
    d1 = sys.argv[4] if len(sys.argv) > 4 else dt.date.today().isoformat()
    sys.path.insert(0, tools)
    from replay_post import load_account

    rows = json.loads((work / "orders.json").read_text(encoding="utf-8"))["values"][1:]
    st = json.loads((work / "staff.json").read_text(encoding="utf-8"))["valueRanges"]
    staff = {}
    for a, j in zip(st[0].get("values", []), st[1].get("values", []) + [[]] * 5000):
        if a and a[0]:
            staff[a[0].strip().lower()] = (a[1] if len(a) > 1 else "", (j[0] if j else "").strip())
    pt = json.loads((work / "patients.json").read_text(encoding="utf-8"))["valueRanges"]
    orca = {}
    for a, k in zip(pt[0].get("values", []), pt[1].get("values", []) + [[]] * 30000):
        if a and a[0]:
            orca[str(a[0]).strip()] = str(k[0]) if k else ""  # 空白は削らない（Order.gs も String(pRow[10]) のまま。指摘4）

    user, pw = load_account("api")
    s = requests.Session()
    s.post(BASE + "auth.php", data={"id": user, "pw": pw, "jaddr": ""}, allow_redirects=False, timeout=30)

    targets = []
    for r in rows:
        shoot = serial_to_dt(cell(r, C["SHOOTING_DATE"]))
        if not shoot or not (d0 <= shoot.date().isoformat() <= d1):
            continue
        if cell(r, C["STATUS"]) not in ("撮影済", "完了"):
            continue
        targets.append(r)
    print(f"対象（撮影日 {d0}〜{d1}・撮影済/完了）: {len(targets)} 件")
    bad_total = 0
    for r in targets:
        oid = str(cell(r, C["ID"]))
        tag = "…" + oid[-6:]
        url = str(cell(r, C["HOMIS_LINKED"]))
        m = re.search(r"patient_id=(\d+).*?karte_id=(\d+)", url)
        if not m:
            print(f"  {tag}: ❌ カルテの URL が表に無い")
            bad_total += 1
            continue
        pid, kid = m.group(1), m.group(2)
        email = str(cell(r, C["DOCTOR_EMAIL"])).strip().lower()
        dname, did = staff.get(email, (str(cell(r, C["DOCTOR_EMAIL"])), ""))  # 無ければメールのまま（lookupNameByEmail_ と同じ）
        ap_exp, shoot = expected_ap(r, orca.get(str(cell(r, C["HOMIS_ID"])).strip(), ""), dname)
        view = s.get(BASE + "functions/pdetail_karte.php", params={"patient_id": pid, "karte_id": kid}, timeout=30).text
        klist = s.get(BASE + "functions/getKarteList.php", params={"patient_id": pid}, timeout=30).json()
        me = next((k for k in klist if str(k.get("karte_id")) == kid), None)
        res = {}
        # 表示ページには処方を写す小さなフォームの karte_type（14・15）もあるので、カルテ一覧の type を使う（無いときは最後の karte_type）
        ktype = str(me.get("type")) if me else None
        res["外来"] = (ktype == GAIRAI) if me else None   # 一覧に無いときは判定しない（表示ページの karte_type は処方のフォームのもの。指摘2）
        kdoc = str(me.get("doctor")) if me else hidden(view, "doctor")
        res["指示医"] = bool(did) and kdoc == did
        res["診察日"] = hidden(view, "act_date") == shoot.strftime("%Y-%m-%d")
        if me:
            res["時刻"] = me.get("start_time") == shoot.strftime("%H:%M") and me.get("end_time") == (shoot + dt.timedelta(minutes=10)).strftime("%H:%M")
            same = [k for k in klist if k.get("act_date") == me.get("act_date") and k.get("start_time") == me.get("start_time")]
            res["1枚だけ"] = len(same) == 1
        else:
            res["時刻"] = None   # 一覧の新しい10件に入っていない（そのあとにカルテが増えた）
            res["1枚だけ"] = None
        ap_act = textarea(view, "ap")
        if ap_act is None:
            res["A/P"] = None
        else:
            a_lines, e_lines = norm(ap_act).split("\n"), norm(ap_exp).split("\n")
            body_ok = a_lines[1:] == e_lines[1:]
            doc_ok = a_lines[0].startswith("指示医：") and nospace(a_lines[0]) == nospace(e_lines[0])
            res["A/P"] = body_ok and doc_ok
            if not res["A/P"]:
                diff = [i for i in range(max(len(a_lines), len(e_lines))) if (a_lines[i:i + 1] != e_lines[i:i + 1])]
                res["A/P違う行"] = ",".join(str(i + 1) for i in diff[:6])
                if "--show-site" in sys.argv:  # 患者さんの情報が入らない「部位」「撮影枚数」「目的」「合計」の行だけ見せる。URL は形と長さだけ
                    for i in diff[:6]:
                        for lab, L in (("実", a_lines), ("予", e_lines)):
                            x = L[i] if i < len(L) else "(無い)"
                            if x.startswith(("部位：", "撮影枚数：", "目的：", "合計：")) or x in ("", "(無い)"):
                                print(f"      {i + 1}行目 {lab}: {x}")
                            else:
                                print(f"      {i + 1}行目 {lab}: （{'URL' if x.startswith('http') else '文字'}・{len(x)}字）")
                    if len(diff) and all(i < len(a_lines) and i < len(e_lines) for i in diff):
                        for i in diff:
                            x, y = a_lines[i], e_lines[i]
                            if x.startswith("http") and y.startswith("http"):
                                k = next((j for j in range(min(len(x), len(y))) if x[j] != y[j]), min(len(x), len(y)))
                                rest_a, rest_e = x[k:], y[k:]
                                kinds = lambda t: "".join(sorted(set("%" if c == "%" else ("英数" if c.isalnum() else c) for c in t)))
                                print(f"      {i + 1}行目 URL: 先頭 {k} 字まで同じ。違う部分の長さ 実{len(rest_a)}・予{len(rest_e)}。予の残りの字の種類 {kinds(rest_e[:40])}・実 {kinds(rest_a[:40])}・予が実で終わる {y.endswith(x[k:]) if k < len(x) else '－'}")
        mark = lambda v: "✅" if v is True else ("❌" if v is False else "－")
        line = "  ".join(f"{k}{mark(v)}" for k, v in res.items() if k != "A/P違う行")
        extra = f"（A/P の違う行: {res['A/P違う行']}行目）" if res.get("A/P違う行") else ""
        kind = "集団" if str(cell(r, C["IS_GROUP"])).upper() == "TRUE" else "個別"
        if res["外来"] is False:
            extra += f"（種類の番号 {ktype}）"
        print(f"  {tag} {shoot:%m/%d} {kind}: {line}  S欄－{extra}")
        bad_total += sum(1 for k, v in res.items() if v is False)
    print(f"不一致の項目の数: {bad_total}（－＝確かめられない）")


main()
