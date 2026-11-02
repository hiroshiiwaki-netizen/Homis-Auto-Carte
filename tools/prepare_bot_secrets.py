# -*- coding: utf-8 -*-
"""問い合わせの口（受け口 0.4.0 /bot/receive）の鍵2つを、一時ファイルに用意する（画面には値を出さない）

バージョン: 0.1.0 / 最終更新: 2026-11-03
改定履歴:
  v0.1.0 11/03 新規。手順 docs/FAXカルテ_検討/手順_問い合わせ_ライター入替_2026-11-04.md の 2

作るもの（C:\\Users\\setup\\_bot_secrets\\）:
  bot_key.txt   受け口の合言葉（ランダム 32 バイト）。Secret bot-receiver-key に入れ、Tukusi の HTTP 節にも貼る
  bot_hook.txt  問い合わせ用 Chat の Webhook。OhisamaBot の CsvExporter.gs（Tukusi API 送信の知らせ）から取り出す
使い終わったら、フォルダごと消す（手順のとおり）。
使い方（PowerShell）: py -3.12 tools\\prepare_bot_secrets.py
"""
import os
import re
import secrets
import sys

OUT = r"C:\Users\setup\_bot_secrets"
GS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "OhisamaBot", "gas", "CsvExporter.gs")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    key = "bot-" + secrets.token_urlsafe(32)
    with open(os.path.join(OUT, "bot_key.txt"), "w", encoding="ascii", newline="") as f:
        f.write(key)
    with open(GS, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"function notifyTukusiApiToChat_[\s\S]*?var webhookUrl = '([^']+)'", src)
    if not m or not m.group(1).startswith("https://chat.googleapis.com/"):
        print("NG: CsvExporter.gs から知らせ先を読めませんでした（値は出していません）")
        return 1
    with open(os.path.join(OUT, "bot_hook.txt"), "w", encoding="ascii", newline="") as f:
        f.write(m.group(1))
    print("OK: 2つ作りました（値は出していません）")
    print("  合言葉   ", os.path.join(OUT, "bot_key.txt"), len(key), "字")
    print("  知らせ先 ", os.path.join(OUT, "bot_hook.txt"), len(m.group(1)), "字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
