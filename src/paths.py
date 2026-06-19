# -*- coding: utf-8 -*-
"""
パス管理モジュール
==================
HOMISカルテライターの全パスを一元管理する。

v2.0.2 - 新規作成 (2026/06/19)

パス設計:
  - CODE_DIR: コードの場所（共有ドライブ）= Path(__file__).parent
  - STATE_DIR: 状態ファイルの場所（ローカル C:\HomisKarteWriter）
    heartbeat.txt, homis_writer.pid, last_restart.txt, watchdog.log
  - LOG_DIR: ログの場所 = CODE_DIR / "logs"（共有ドライブ）
  - CONFIG_FILE: 設定ファイル = STATE_DIR / "config.json"（ローカル）
    ※ ローカルの config.json を正として読む

使い方:
    from paths import CODE_DIR, STATE_DIR, LOG_DIR, CONFIG_FILE
"""

import os
from pathlib import Path

# コードの場所（共有ドライブ上）
CODE_DIR = Path(__file__).parent

# 状態ファイルの場所（ローカル）
# C:\HomisKarteWriter が存在すればそこ、なければコードと同じ場所（開発用）
_LOCAL_STATE = Path(r"C:\HomisKarteWriter")
if _LOCAL_STATE.exists():
    STATE_DIR = _LOCAL_STATE
else:
    STATE_DIR = CODE_DIR

# ログの場所（コードと同じ場所 = 共有ドライブ）
LOG_DIR = CODE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 設定ファイル（ローカル優先、なければ共有ドライブ）
_local_config = STATE_DIR / "config.json"
_code_config = CODE_DIR / "config.json"
if _local_config.exists():
    CONFIG_FILE = _local_config
else:
    CONFIG_FILE = _code_config

# 状態ファイルのパス
HEARTBEAT_FILE = STATE_DIR / "heartbeat.txt"
PID_FILE = STATE_DIR / "homis_writer.pid"
LAST_RESTART_FILE = STATE_DIR / "last_restart.txt"
