# -*- coding: utf-8 -*-
"""起動ラッパー。失敗時は C:\\ と共有 logs の両方に書く。"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

CODE_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(r"C:\HomisKarteWriter")
if not STATE_DIR.exists():
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        STATE_DIR = CODE_DIR
ERR_LOG = STATE_DIR / "startup_error.log"
SHARED_ERR = Path(r"G:\共有ドライブ\レントゲンオーダー\HomisKarteWriter\logs\startup_error.log")


def _log(text: str) -> None:
    line = f"{datetime.now().isoformat()} {text}\n"
    for path in (ERR_LOG, SHARED_ERR):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
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
