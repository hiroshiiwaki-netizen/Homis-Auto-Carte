# -*- coding: utf-8 -*-
"""
Google Chat通知モジュール
========================
Google Chat Webhook を使ってスペースにメッセージを送信する。

OhiScanと同じフォーマットで統一。

使い方:
    from chat_notifier import notify_startup, notify_shutdown, notify_error

    # 起動通知
    notify_startup(webhook_url, config)

    # 異常終了通知
    notify_error(webhook_url, "エラーメッセージ")

    # スケジュール終了通知
    notify_shutdown(webhook_url, "スケジュール終了")
"""

import os
import sys
import platform
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

# アプリ情報
APP_NAME = "Homis自動カルテ"
APP_VERSION = "1.3.0"


def _get_system_info() -> dict:
    """システム情報を取得"""
    import psutil
    
    # ホスト名
    hostname = platform.node()
    
    # OS情報
    os_info = f"Windows {platform.release()}"
    
    # Python バージョン
    python_version = platform.python_version()
    
    # メモリ情報
    try:
        memory = psutil.virtual_memory()
        memory_gb = f"{memory.total / (1024**3):.1f}GB"
    except Exception:
        memory_gb = "不明"
    
    return {
        "hostname": hostname,
        "os": os_info,
        "python": python_version,
        "memory": memory_gb,
    }


def send_chat_notification(webhook_url: str, message: str) -> bool:
    """
    Google Chat Webhookにメッセージを送信

    Args:
        webhook_url: Google Chat Webhook URL
        message: 送信するメッセージ

    Returns:
        True=送信成功, False=送信失敗
    """
    if not webhook_url:
        logger.debug("Chat Webhook URLが未設定のため通知をスキップ")
        return False

    try:
        response = requests.post(
            webhook_url,
            json={"text": message},
            headers={"Content-Type": "application/json; charset=UTF-8"},
            timeout=10
        )

        if response.status_code == 200:
            logger.info("✅ Google Chat通知を送信しました")
            return True
        else:
            logger.warning(f"⚠️ Google Chat通知失敗: HTTP {response.status_code}")
            return False

    except requests.exceptions.Timeout:
        logger.warning("⚠️ Google Chat通知タイムアウト")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Google Chat通知エラー: {e}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ Google Chat通知予期せぬエラー: {e}")
        return False


def notify_startup(webhook_url: str, config: dict) -> bool:
    """
    起動通知を送信（OhiScanフォーマット準拠）

    Args:
        webhook_url: Google Chat Webhook URL
        config: アプリの設定dict

    Returns:
        True=送信成功, False=送信失敗
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys_info = _get_system_info()

    # モード表示
    test_mode = config.get("test_mode", True)
    mode_str = "🧪 テストモード" if test_mode else "🚀 本番モード"

    # 監視フォルダ
    watch_folder = config.get("watch_folder", "未設定")

    # 自動終了時刻
    schedule = config.get("schedule", {})
    if schedule.get("auto_shutdown", False):
        shutdown_str = schedule.get("shutdown_time", "22:00")
    else:
        shutdown_str = "無効"

    message = (
        f"🚀【{APP_NAME} v{APP_VERSION}】起動しました\n"
        f"\n"
        f"⏰ 起動時刻: {now}\n"
        f"💻 環境: {sys_info['os']} / {sys_info['hostname']}\n"
        f"🐍 Python: {sys_info['python']}\n"
        f"💾 メモリ: {sys_info['memory']}\n"
        f"📁 監視フォルダ: {watch_folder}\n"
        f"🎯 モード: {mode_str}\n"
        f"⏹ 自動終了: {shutdown_str}"
    )

    return send_chat_notification(webhook_url, message)


def notify_shutdown(webhook_url: str, reason: str = "スケジュール終了") -> bool:
    """
    終了通知を送信

    Args:
        webhook_url: Google Chat Webhook URL
        reason: 終了理由

    Returns:
        True=送信成功, False=送信失敗
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys_info = _get_system_info()

    message = (
        f"🌙【{APP_NAME} v{APP_VERSION}】終了しました\n"
        f"\n"
        f"⏰ 終了時刻: {now}\n"
        f"💻 環境: {sys_info['os']} / {sys_info['hostname']}\n"
        f"📋 理由: {reason}"
    )

    return send_chat_notification(webhook_url, message)


def notify_error(webhook_url: str, error_message: str) -> bool:
    """
    異常終了・エラー通知を送信

    Args:
        webhook_url: Google Chat Webhook URL
        error_message: エラーメッセージ

    Returns:
        True=送信成功, False=送信失敗
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys_info = _get_system_info()

    message = (
        f"❌【{APP_NAME} v{APP_VERSION}】異常が発生しました\n"
        f"\n"
        f"⏰ 発生時刻: {now}\n"
        f"💻 環境: {sys_info['os']} / {sys_info['hostname']}\n"
        f"❗ エラー: {error_message}"
    )

    return send_chat_notification(webhook_url, message)


# === テスト用 ===
if __name__ == "__main__":
    import json
    import io
    from pathlib import Path

    # Windows環境でのUnicode出力対応
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    logging.basicConfig(level=logging.INFO)

    # config.jsonからWebhook URLを読み込み
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        webhook_url = config.get("chat_webhook_url", "")
    else:
        webhook_url = ""

    if not webhook_url:
        print("[ERROR] config.jsonに chat_webhook_url を設定してください")
    else:
        print("[INFO] テスト通知を送信中...")
        result = notify_startup(webhook_url, config)
        print(f"[INFO] 結果: {'成功' if result else '失敗'}")
