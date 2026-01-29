"""
Homis自動カルテ生成 - メインスクリプト
Google Driveを監視し、JSONファイルを検知してHomisにデータ登録

v1.0.0 - 初版
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime

# Google Drive API
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

# ブラウザ操作
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# 設定
CONFIG_FILE = Path(__file__).parent / 'config.json'
LOG_FILE = Path(__file__).parent / 'logs' / f'app_{datetime.now().strftime("%Y%m%d")}.log'

# Google Drive API スコープ
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# ロガー設定
def setup_logger():
    """ロガーをセットアップ"""
    LOG_FILE.parent.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logger()


def load_config():
    """設定ファイルを読み込み"""
    if not CONFIG_FILE.exists():
        default_config = {
            "folder_id": "1huz-srSrLEOT8izRuVwZSkkKVsAj_miL",
            "poll_interval_seconds": 30,
            "homis_url": "https://homis.jp/",
            "processed_folder_id": ""
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        logger.info(f"設定ファイルを作成しました: {CONFIG_FILE}")
    
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_drive_service():
    """Google Drive APIサービスを取得"""
    creds = None
    token_file = Path(__file__).parent / 'token.pickle'
    credentials_file = Path(__file__).parent / 'credentials.json'
    
    if token_file.exists():
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_file.exists():
                logger.error(f"認証ファイルが見つかりません: {credentials_file}")
                logger.info("Google Cloud Consoleからcredentials.jsonをダウンロードして配置してください")
                return None
            
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)
    
    return build('drive', 'v3', credentials=creds)


def get_pending_files(service, folder_id):
    """未処理のJSONファイル一覧を取得"""
    try:
        query = f"'{folder_id}' in parents and mimeType='text/plain' and name contains '.json' and trashed=false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name, createdTime)'
        ).execute()
        
        return results.get('files', [])
    except Exception as e:
        logger.error(f"ファイル一覧取得エラー: {e}")
        return []


def download_file(service, file_id):
    """ファイルの内容をダウンロード"""
    try:
        content = service.files().get_media(fileId=file_id).execute()
        return json.loads(content.decode('utf-8'))
    except Exception as e:
        logger.error(f"ファイルダウンロードエラー: {e}")
        return None


def move_to_processed(service, file_id, processed_folder_id):
    """処理済みフォルダに移動"""
    if not processed_folder_id:
        # 処理済みフォルダがない場合は削除
        try:
            service.files().delete(fileId=file_id).execute()
            logger.info(f"ファイルを削除しました: {file_id}")
        except Exception as e:
            logger.error(f"ファイル削除エラー: {e}")
    else:
        try:
            # フォルダ移動
            file = service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            service.files().update(
                fileId=file_id,
                addParents=processed_folder_id,
                removeParents=previous_parents
            ).execute()
            logger.info(f"ファイルを処理済みフォルダに移動: {file_id}")
        except Exception as e:
            logger.error(f"ファイル移動エラー: {e}")


def write_to_homis(data, config):
    """Homisにデータを書き込み"""
    logger.info(f"Homis書き込み開始: {data['data']['patientName']}")
    
    try:
        from homis_writer import HomisKarteWriter
        
        # Homis設定をconfigに追加（config.jsonから読み込み済みの場合はスキップ）
        homis_config = {
            "homis_url": config.get("homis_url", "https://homis.jp/homic/"),
            "homis_user": config.get("homis_user", ""),
            "homis_password": config.get("homis_password", "")
        }
        
        # 認証情報の確認
        if not homis_config["homis_user"] or not homis_config["homis_password"]:
            logger.error("Homisの認証情報がconfig.jsonに設定されていません")
            logger.info("config.jsonに homis_user, homis_password を追加してください")
            return {"success": False, "karte_url": None}
        
        # Homisカルテ書き込み
        writer = HomisKarteWriter(homis_config, headless=False)  # テスト時は表示モード
        
        result = writer.write_karte(
            homis_id=data['data']['homisId'],
            karte_data=data['data']
        )
        
        if result["success"]:
            logger.info(f"✅ Homis書き込み成功: {data['data']['patientName']}")
            if result["karte_url"]:
                logger.info(f"📋 カルテURL: {result['karte_url']}")
                
                # GAS API連携: カルテURLをレントゲンナビに通知
                gas_url = config.get("gas_web_app_url", "")
                order_id = data.get("orderId", "")
                
                if gas_url and order_id:
                    try:
                        from gas_api import notify_karte_url
                        gas_result = notify_karte_url(order_id, result["karte_url"], gas_url)
                        if gas_result.get("success"):
                            logger.info(f"🔗 GAS連携成功: {gas_result.get('message')}")
                        else:
                            logger.warning(f"⚠️ GAS連携: {gas_result.get('message')}")
                    except Exception as gas_error:
                        logger.warning(f"⚠️ GAS連携エラー（カルテ作成は成功）: {gas_error}")
                elif not gas_url:
                    logger.info("ℹ️ gas_web_app_url未設定のためGAS連携をスキップ")
                elif not order_id:
                    logger.info("ℹ️ orderIdがないためGAS連携をスキップ")
        else:
            logger.error(f"❌ Homis書き込み失敗: {data['data']['patientName']}")
        
        return result
        
    except ImportError:
        logger.error("homis_writer モジュールが見つかりません")
        return {"success": False, "karte_url": None}
    except Exception as e:
        logger.error(f"Homis書き込みエラー: {e}")
        return {"success": False, "karte_url": None}


def process_file(service, file, config):
    """1ファイルを処理"""
    logger.info(f"処理開始: {file['name']}")
    
    # JSONをダウンロード
    data = download_file(service, file['id'])
    if not data:
        return False
    
    # アクション判定
    if data.get('action') != 'homis_karte_write':
        logger.warning(f"未対応のアクション: {data.get('action')}")
        return False
    
    # Homisに書き込み
    result = write_to_homis(data, config)
    
    if result["success"]:
        # 処理済みに移動
        move_to_processed(service, file['id'], config.get('processed_folder_id', ''))
    
    return result["success"]


def main():
    """メイン処理"""
    logger.info("=" * 50)
    logger.info("Homis自動カルテ生成 起動")
    logger.info("=" * 50)
    
    # 設定読み込み
    config = load_config()
    logger.info(f"監視フォルダID: {config['folder_id']}")
    logger.info(f"ポーリング間隔: {config['poll_interval_seconds']}秒")
    
    # Google Drive API接続
    service = get_drive_service()
    if not service:
        logger.error("Google Drive APIに接続できません")
        return
    
    logger.info("Google Drive API接続成功")
    logger.info("監視を開始します... (Ctrl+C で終了)")
    
    try:
        while True:
            # 未処理ファイルを取得
            files = get_pending_files(service, config['folder_id'])
            
            if files:
                logger.info(f"未処理ファイル: {len(files)}件")
                for file in files:
                    process_file(service, file, config)
            
            # 待機
            time.sleep(config['poll_interval_seconds'])
            
    except KeyboardInterrupt:
        logger.info("終了します")


if __name__ == '__main__':
    main()
