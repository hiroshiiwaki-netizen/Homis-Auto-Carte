# -*- coding: utf-8 -*-
"""
find_stuck_kartes.py — Tukusi が開いたまま保存できずに残った「空のカルテ」を探す（読むだけ）

バージョン: 0.1.0 / 最終更新: 2026-10-29
改定履歴:
  v0.1.0 10/29 新規。10/28 の並走の照合で「本物のカルテが空」が見つかり、10/23〜10/28 に7件あると分かった
               （Tukusi の homis記録 が新規を開いたあと、完了の保存が HOMIS に届かないまま成功で終わる）

探し方:
  1 p281 の「カルテ順番札: 渡しました（HOMIS ID ・札 ）」から、その日にカルテを書きに行った患者さんを集める
  2 その患者さんのその日のカルテ（種別 1＝電話）を HOMIS の ajax_karte_show で読む（表示用のデータ。カルテには触れない）
  3 S も O も空のものを「空のカルテ」とする。状態 1＝編集中（HOMIS で編集画面が開けない）・2＝中断・3＝完了だが空
  あわせて、そのカルテの札が他の札と時間が重なっていたか（同時に書いていたか）を出す
画面に出すのは日付・時刻・札の末尾・状態だけ。患者さんの名前と本文は出さない。HOMIS ID とカルテ番号は --ids を付けたときだけ出す
使い方（PowerShell）: py -3.12 -X utf8 tools/find_stuck_kartes.py [開始日 [終了日]] [--ids]   日付は yyyy-mm-dd（既定は今日）
"""
import datetime as dt
import re
import sys
from pathlib import Path

import requests

VERSION = "0.1.0"
BASE = "https://homis.jp/homic/"
P281_LOG = r"G:\共有ドライブ\OhiscanGo\logs\ohisama-p281_app_{date}.log"
HOMISAPI_TOOLS = r"G:\マイドライブ\Antigravity-PJ\HomisApi\tools"
RE_GIVEN = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] info: 🎫 カルテ順番札: 渡しました（HOMIS ID (\d+)・札 ([0-9A-Za-z\-]+)")
RE_BACK = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] info: 🎫 カルテ順番札: 返されました（札 ([0-9A-Za-z\-]+)）")
STATUS = {"1": "編集中", "2": "中断", "3": "完了だが空"}


def tickets_of(date):
    """札番号 → (渡した時刻, 返した時刻, HOMIS ID)。ログが無い日は空"""
    path = Path(P281_LOG.format(date=date))
    if not path.exists():
        return {}
    given, back = {}, {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RE_GIVEN.search(line)
            if m:
                given[m.group(3)] = (dt.datetime.fromisoformat(m.group(1)), m.group(2))
                continue
            m = RE_BACK.search(line)
            if m:
                back[m.group(2)] = dt.datetime.fromisoformat(m.group(1))
    return {t: (g, back.get(t), pid) for t, (g, pid) in given.items()}


def overlapped(t, tk):
    """札 t の渡し〜返しの間に、別の札も出ていたか"""
    g, b, _ = tk[t]
    b = b or g + dt.timedelta(minutes=4)
    for u, (g2, b2, _) in tk.items():
        b2 = b2 or g2 + dt.timedelta(minutes=4)
        if u != t and g2 < b and g < b2:
            return True
    return False


def nearest_ticket(pid, start, tk):
    """その患者さんの札のうち、カルテの開始時刻にいちばん近いもの"""
    cands = [(abs((g - start).total_seconds()), t) for t, (g, _, p) in tk.items() if p == pid]
    return min(cands)[1] if cands else ""


def scan(s, date, show_ids):
    tk = tickets_of(date)
    found = []
    for pid in sorted({p for _, _, p in tk.values()}):
        lst = s.get(BASE + "functions/getKarteList.php", params={"patient_id": pid}, timeout=30).json()
        for k in lst:
            if str(k.get("act_date")) != date or str(k.get("type")) != "1":
                continue
            j = s.get(BASE, params={"qid": "ajax_karte_show", "patient_id": pid, "karte_id": k["karte_id"]}, timeout=30).json()["this_karte"]
            if (j.get("subjective") or "").strip() or (j.get("objective") or "").strip():
                continue
            st = str(j.get("status"))
            start = dt.datetime.fromisoformat(date + " " + str(j.get("start_time") or "00:00:00")[:8])
            t = nearest_ticket(pid, start, tk)
            found.append((start.strftime("%H:%M"), t, st, pid, str(k["karte_id"])))
    print(f"{date}  札 {len(tk)} 枚・空のカルテ {len(found)} 件")
    for hm, t, st, pid, kid in sorted(found):
        ids = f"  HOMIS ID {pid}・カルテ {kid}" if show_ids else ""
        lap = "同時に書いていた" if t and overlapped(t, tk) else "単独"
        print(f"  {hm}  札…{t[-7:] if t else '（札なし）'}  {STATUS.get(st, '状態' + st)}  {lap}{ids}")
    return len(found)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_ids = "--ids" in sys.argv
    d0 = dt.date.fromisoformat(args[0]) if args else dt.date.today()
    d1 = dt.date.fromisoformat(args[1]) if len(args) > 1 else d0
    sys.path.insert(0, HOMISAPI_TOOLS)
    from replay_post import load_account
    user, pw = load_account("api")
    s = requests.Session()
    s.post(BASE + "auth.php", data={"id": user, "pw": pw, "jaddr": ""}, allow_redirects=False, timeout=30)
    print(f"find_stuck_kartes v{VERSION}  {d0} 〜 {d1}")
    total, d = 0, d0
    while d <= d1:
        total += scan(s, d.isoformat(), show_ids)
        d += dt.timedelta(days=1)
    print(f"合計 空のカルテ {total} 件")


main()
