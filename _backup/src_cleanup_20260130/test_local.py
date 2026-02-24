# -*- coding: utf-8 -*-
"""
ローカルJSONファイルテスト
===========================
Google Drive監視を使わず、ローカルのJSONファイルを直接読み込んでテスト
"""

import json
import logging
from pathlib import Path

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# パス設定
SRC_DIR = Path(__file__).parent
CONFIG_FILE = SRC_DIR / "config.json"
TEST_JSON_FILE = SRC_DIR.parent / "test_data" / "test_karte.json"


def main():
    print("=" * 60)
    print("ローカルJSONファイル テスト")
    print("=" * 60)
    
    # 設定読み込み
    if not CONFIG_FILE.exists():
        print(f"❌ 設定ファイルがありません: {CONFIG_FILE}")
        return
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    print(f"✅ 設定ファイル読み込み完了")
    
    # テストJSONファイル読み込み
    if not TEST_JSON_FILE.exists():
        print(f"❌ テストファイルがありません: {TEST_JSON_FILE}")
        return
    
    with open(TEST_JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"✅ テストファイル読み込み完了: {TEST_JSON_FILE.name}")
    print(f"   患者名: {data['data']['patientName']}")
    print(f"   HOMIS ID: {data['data']['homisId']}")
    print(f"   アクション: {data['action']}")
    
    # アクション確認
    if data.get('action') != 'homis_karte_write':
        print(f"❌ 未対応のアクション: {data.get('action')}")
        return
    
    print("\n" + "-" * 60)
    print("Homis書き込み開始...")
    print("-" * 60)
    
    # Homis書き込み
    from homis_writer import HomisKarteWriter
    
    homis_config = {
        "homis_url": config.get("homis_url", "https://homis.jp/homic/"),
        "homis_user": config.get("homis_user", ""),
        "homis_password": config.get("homis_password", "")
    }
    
    writer = HomisKarteWriter(homis_config, headless=False)
    
    result = writer.write_karte(
        homis_id=data['data']['homisId'],
        karte_data=data['data']
    )
    
    print("\n" + "=" * 60)
    if result["success"]:
        print("✅ テスト成功!")
        if result["karte_url"]:
            print(f"📋 カルテURL: {result['karte_url']}")
            
            # GAS連携テスト（URLが設定されていれば）
            gas_url = config.get("gas_web_app_url", "")
            order_id = data.get("orderId", "")
            
            if gas_url and order_id:
                print("\n🔗 GAS連携テスト...")
                from gas_api import notify_karte_url
                gas_result = notify_karte_url(order_id, result["karte_url"], gas_url)
                if gas_result.get("success"):
                    print(f"✅ GAS連携成功: {gas_result.get('message')}")
                else:
                    print(f"⚠️ GAS連携: {gas_result.get('message')}")
            elif not gas_url:
                print("ℹ️ gas_web_app_url未設定のためGAS連携をスキップ")
    else:
        print("❌ テスト失敗")
    print("=" * 60)


if __name__ == "__main__":
    main()
