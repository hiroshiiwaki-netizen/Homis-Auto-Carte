# -*- coding: utf-8 -*-
"""
テンプレートエンジン
====================
YAMLテンプレートを読み込み、ブラウザ操作を実行

v1.0.0 - 初版 (2026/01/26)
"""

import yaml
import logging
import pyperclip
from pathlib import Path
from typing import Dict, Any, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from browser_actions import BrowserActions

logger = logging.getLogger(__name__)

# テンプレートディレクトリ
TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateEngine:
    """テンプレートエンジン"""
    
    def __init__(self, config: Dict[str, Any], headless: bool = False):
        self.config = config
        self.headless = headless
        self.driver = None
        self.actions = None
    
    def load_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """テンプレートを読み込み"""
        template_path = TEMPLATES_DIR / f"{template_name}.yaml"
        
        if not template_path.exists():
            logger.error(f"テンプレートが見つかりません: {template_path}")
            return None
        
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template = yaml.safe_load(f)
            logger.info(f"テンプレート読み込み: {template.get('name', template_name)}")
            return template
        except Exception as e:
            logger.error(f"テンプレート読み込みエラー: {e}")
            return None
    
    def _init_driver(self):
        """WebDriverを初期化"""
        if self.driver:
            return
        
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1200,900")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.actions = BrowserActions(self.driver)
        
        logger.info(f"Chromeブラウザを起動しました（headless={self.headless}）")
    
    def _close_driver(self):
        """WebDriverを終了"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.actions = None
            logger.info("ブラウザを終了しました")
    
    def _do_login(self, auth_config: Dict[str, Any], target_url: str) -> bool:
        """ログイン処理（必要に応じて）- homis_writerと同じ方式"""
        if not auth_config.get("detect_login"):
            return True
        
        import time
        
        try:
            # URLにloginが含まれているかでログイン画面を判定（homis_writerと同じ）
            current_url = self.driver.current_url.lower()
            if "login" not in current_url:
                logger.info("既にログイン済み")
                return True
            
            logger.info("ログイン画面を検出、認証処理を実行...")
            
            # ユーザー名（homis_writerと同じセレクタ）
            user_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="id"]'))
            )
            user_field.clear()
            user_field.send_keys(self.config.get("homis_user", ""))
            time.sleep(0.5)
            
            # パスワード（homis_writerと同じセレクタ）
            password_field = self.driver.find_element(By.CSS_SELECTOR, 'input[name="pw"]')
            password_field.clear()
            password_field.send_keys(self.config.get("homis_password", ""))
            time.sleep(0.5)
            
            # ログインボタン（homis_writerと同じセレクタ）
            submit_button = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            submit_button.click()
            
            time.sleep(3)  # ログイン処理待機
            
            # ログイン成功確認（URLからloginが消える）
            WebDriverWait(self.driver, 10).until(
                lambda d: "login" not in d.current_url.lower()
            )
            
            logger.info("ログイン成功")
            
            # ログイン後にターゲットURLに再移動
            logger.info(f"ターゲットURLに再移動: {target_url}")
            self.driver.get(target_url)
            time.sleep(3)
            
            return True
            
        except Exception as e:
            logger.error(f"ログイン処理エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    def execute(self, template_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        テンプレートを実行
        
        Args:
            template_name: テンプレート名（.yaml拡張子なし）
            data: 変数展開用データ
        
        Returns:
            dict: {"success": bool, "karte_url": str or None}
        """
        result = {"success": False, "karte_url": None}
        
        try:
            # テンプレート読み込み
            template = self.load_template(template_name)
            if not template:
                return result
            
            # ドライバー初期化
            self._init_driver()
            
            # 対象URLに移動
            target_url = template.get("target_url", "")
            for key, value in data.items():
                target_url = target_url.replace("{" + key + "}", str(value) if value else "")
            
            logger.info(f"ページに移動: {target_url}")
            self.driver.get(target_url)
            
            import time
            time.sleep(3)
            
            # ログイン処理
            auth_config = template.get("auth", {})
            if auth_config:
                if not self._do_login(auth_config, target_url):
                    logger.error("ログイン失敗")
                    return result
            
            # ステップを実行
            steps = template.get("steps", [])
            for step in steps:
                if not self.actions.execute_action(step, data):
                    logger.error(f"ステップ失敗: {step.get('name', 'unknown')}")
                    # 失敗しても続行（エラー耐性）
            
            # 完了後処理
            on_complete = template.get("on_complete", [])
            for action in on_complete:
                self.actions.execute_action(action, data)
            
            # OKボタンがあれば押す（アラート処理）
            try:
                from selenium.webdriver.common.alert import Alert
                time.sleep(0.5)
                alert = Alert(self.driver)
                alert.accept()
                logger.info("OKボタンを押しました")
            except Exception:
                pass  # アラートがない場合は無視
            
            # 結果取得
            result_config = template.get("result", {})
            if result_config.get("type") == "clipboard":
                time.sleep(0.5)
                try:
                    result["karte_url"] = pyperclip.paste()
                    logger.info(f"カルテURL: {result['karte_url']}")
                except Exception:
                    pass
            
            result["success"] = True
            logger.info("✅ テンプレート実行成功")
            
            # テストモード時: 同じブラウザの新しいタブでURLを開く
            test_mode = self.config.get("test_mode", False)
            if test_mode and result.get("karte_url"):
                logger.info("🧪 テストモード: 新しいタブでカルテURLを開きます")
                # 新しいタブを開いてURLに移動
                self.driver.execute_script(f"window.open('{result['karte_url']}', '_blank');")
                time.sleep(2)  # 新しいタブの読み込みを待つ
            
        except Exception as e:
            logger.error(f"❌ テンプレート実行エラー: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            import time
            test_mode = self.config.get("test_mode", False)
            if test_mode:
                # テストモード: ブラウザを閉じずにそのまま（ユーザーが確認できるように）
                logger.info("🧪 テストモード: ブラウザを開いたままにします")
            else:
                # 本番モード: ブラウザを閉じる
                time.sleep(2)
                self._close_driver()
        
        return result


# テスト用
if __name__ == "__main__":
    import json
    
    logging.basicConfig(level=logging.INFO)
    
    # 設定読み込み
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # テストデータをtest_template.jsonから読み込み
    test_json_path = Path(__file__).parent.parent / "test_data" / "test_template.json"
    with open(test_json_path, "r", encoding="utf-8") as f:
        test_json = json.load(f)
    
    data = test_json.get("data", {})
    template_name = test_json.get("template", "xray_karte")
    
    # headless設定をconfig.jsonから読み込み
    headless = config.get("headless", False)
    
    logger.info(f"テストファイル: {test_json_path}")
    logger.info(f"テンプレート: {template_name}")
    logger.info(f"ヘッドレスモード: {headless}")
    
    # 実行
    engine = TemplateEngine(config, headless=headless)
    result = engine.execute(template_name, data)
    print(f"結果: {result}")
