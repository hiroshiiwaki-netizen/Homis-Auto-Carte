# -*- coding: utf-8 -*-
"""
GAS API連携モジュール
=====================
レントゲンナビのGASにカルテURLを通知する

使用方法:
    from gas_api import notify_karte_url
    
    result = notify_karte_url("R-202601261500-001", "https://homis.jp/...")
"""

import requests
import logging

logger = logging.getLogger(__name__)

# レントゲンナビのWebアプリURL（デプロイ後のexec URL）
# ============================================================
# 【重要】clasp deployで取得したURLをここに設定
# 形式: https://script.google.com/macros/s/AKfycb.../exec
# ============================================================
GAS_WEB_APP_URL = ""


def notify_karte_url(order_id: str, homis_url: str, gas_url: str = None) -> dict:
    """
    GASにカルテURLを通知
    
    Args:
        order_id: レントゲンナビのオーダーID (例: R-202601261500-001)
        homis_url: HomisのカルテURL
        gas_url: GASのWebアプリURL（省略時は設定ファイルから取得）
    
    Returns:
        dict: {"success": bool, "message": str}
    """
    try:
        url = gas_url or GAS_WEB_APP_URL
        
        if not url:
            logger.warning("GAS_WEB_APP_URLが設定されていません")
            return {"success": False, "message": "GAS_WEB_APP_URLが未設定"}
        
        payload = {
            "action": "updateHomisLink",
            "orderId": order_id,
            "homisUrl": homis_url
        }
        
        logger.info(f"GAS API呼び出し: {order_id} -> {homis_url}")
        
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                logger.info(f"✅ GAS連携成功: {result.get('message')}")
            else:
                logger.warning(f"⚠️ GAS連携警告: {result.get('message')}")
            return result
        else:
            logger.error(f"❌ GAS API HTTPエラー: {response.status_code}")
            return {"success": False, "message": f"HTTP {response.status_code}"}
            
    except requests.exceptions.Timeout:
        logger.error("GAS API タイムアウト")
        return {"success": False, "message": "タイムアウト"}
    except requests.exceptions.RequestException as e:
        logger.error(f"GAS API リクエストエラー: {e}")
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.error(f"GAS API 予期せぬエラー: {e}")
        return {"success": False, "message": str(e)}


def send_group_complete_notification(group_id: str, gas_url: str = None) -> dict:
    """
    集団検診の一括通知を送信（v7.7.6追加）
    
    全員分のHOMIS連携が完了した後に呼び出す
    
    Args:
        group_id: グループID (例: G-202602041000-001)
        gas_url: GASのWebアプリURL（省略時は設定ファイルから取得）
    
    Returns:
        dict: {"success": bool, "message": str}
    """
    try:
        url = gas_url or GAS_WEB_APP_URL
        
        if not url:
            logger.warning("GAS_WEB_APP_URLが設定されていません")
            return {"success": False, "message": "GAS_WEB_APP_URLが未設定"}
        
        payload = {
            "action": "sendGroupCompleteNotification",
            "groupId": group_id
        }
        
        logger.info(f"集団検診一括通知呼び出し: {group_id}")
        
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                logger.info(f"✅ 集団検診通知成功: {result.get('message')}")
            else:
                logger.warning(f"⚠️ 集団検診通知警告: {result.get('message')}")
            return result
        else:
            logger.error(f"❌ GAS API HTTPエラー: {response.status_code}")
            return {"success": False, "message": f"HTTP {response.status_code}"}
            
    except requests.exceptions.Timeout:
        logger.error("GAS API タイムアウト")
        return {"success": False, "message": "タイムアウト"}
    except requests.exceptions.RequestException as e:
        logger.error(f"GAS API リクエストエラー: {e}")
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.error(f"GAS API 予期せぬエラー: {e}")
        return {"success": False, "message": str(e)}


# === テスト用コード ===
if __name__ == "__main__":
    import json
    from pathlib import Path
    
    logging.basicConfig(level=logging.INFO)
    
    # config.jsonからGAS URLを読み込み
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        gas_url = config.get("gas_web_app_url", "")
    else:
        gas_url = ""
    
    if not gas_url:
        print("❌ config.jsonに gas_web_app_url を設定してください")
        print("   例: https://script.google.com/macros/s/AKfycb.../exec")
    else:
        # テスト呼び出し
        result = notify_karte_url(
            order_id="TEST-001",
            homis_url="https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=TEST",
            gas_url=gas_url
        )
        print(f"結果: {result}")
