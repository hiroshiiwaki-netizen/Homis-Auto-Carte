# -*- coding: utf-8 -*-
"""起動ラッパー。失敗時だけ C:\\HomisKarteWriter\\startup_error.log に書く。"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(r"C:\HomisKarteWriter")
if not STATE_DIR.exists():
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        STATE_DIR = CODE_DIR
ERR_LOG = STATE_DIR / "startup_error.log"


def _log(text: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(ERR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {text}\n")
    except Exception:
        pass


os.chdir(str(CODE_DIR))
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

try:
    import runpy
    runpy.run_path(str(CODE_DIR / "gui.py"), run_name="__main__")
except Exception:
    _log(traceback.format_exc())
    raise
