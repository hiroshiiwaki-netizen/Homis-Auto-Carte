# -*- coding: utf-8 -*-
"""
Homis電子カルテ書き込みモジュール
JSONファイルの内容をHomisのカルテに登録する

使用方法:
    from homis_writer import HomisKarteWriter
    
    writer = HomisKarteWriter(config, headless=False)  # 表示モード
    
    success = writer.write_karte(
        homis_id="12345",
        karte_text="カルテに書き込むテキスト",
        shooting_date="2026-01-26"
    )
"""

# ============================================================
# バージョン情報
# ============================================================
MODULE_VERSION = "1.0"
MODULE_VERSION_DATE = "2026-01-26"

import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# ロガー設定
logger = logging.getLogger(__name__)


class HomisKarteWriter:
    """Homis電子カルテ書き込みクラス"""
    
    # 待機時間の設定（秒）
    WAIT_SHORT = 1      # 短い待機
    WAIT_MEDIUM = 2     # 中程度の待機
    WAIT_LONG = 5       # 長い待機
    WAIT_TIMEOUT = 15   # 最大待機時間
    
    def __init__(self, config: dict, headless: bool = True):
        """
        初期化
        
        Args:
            config: 設定辞書（homis_url, homis_user, homis_password等を含む）
            headless: True=非表示モード, False=表示モード（操作が見える）
        """
        self.config = config
        self.headless = headless
        self.driver = None
        self.is_logged_in = False
        
        # Homis設定
        self.base_url = config.get("homis_url", "https://homis.jp/homic/")
        self.user_id = config.get("homis_user", "")
        self.password = config.get("homis_password", "")
        
    def _create_driver(self):
        """Chromeドライバーを作成"""
        options = Options()
        
        if self.headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
        else:
            options.add_argument("--start-maximized")
        
        # 共通設定
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--lang=ja-JP")
        
        # ChromeDriverを自動管理
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(self.WAIT_LONG)
        
        logger.info(f"Chromeブラウザを起動しました（headless={self.headless}）")
        
    def _wait_and_find(self, by: By, value: str, timeout: int = None):
        """要素が出現するまで待機して取得"""
        if timeout is None:
            timeout = self.WAIT_TIMEOUT
        wait = WebDriverWait(self.driver, timeout)
        return wait.until(EC.presence_of_element_located((by, value)))
    
    def _wait_and_click(self, by: By, value: str, timeout: int = None):
        """要素が出現するまで待機してクリック"""
        if timeout is None:
            timeout = self.WAIT_TIMEOUT
        wait = WebDriverWait(self.driver, timeout)
        element = wait.until(EC.element_to_be_clickable((by, value)))
        time.sleep(self.WAIT_SHORT)
        element.click()
        time.sleep(self.WAIT_SHORT)
        
    def _safe_sleep(self, seconds: float):
        """安全な待機"""
        time.sleep(seconds)
        
    def _login_if_needed(self) -> bool:
        """
        ログイン画面が表示されている場合のみログイン処理を実行
        ============================================================
        【変更理由】2026/1/26
        ・毎回ログインページに行く必要はない
        ・患者詳細ページに直接アクセスし、ログイン画面が出た時だけ認証
        ============================================================
        """
        try:
            # 現在のURLにloginが含まれているかチェック
            if "login" not in self.driver.current_url.lower():
                logger.info("既にログイン済み")
                return True
            
            logger.info("ログイン画面を検出、認証処理を実行...")
            
            # ID入力
            id_input = self._wait_and_find(By.CSS_SELECTOR, 'input[name="id"]')
            id_input.clear()
            id_input.send_keys(self.user_id)
            self._safe_sleep(self.WAIT_SHORT)
            
            # パスワード入力
            pw_input = self._wait_and_find(By.CSS_SELECTOR, 'input[name="pw"]')
            pw_input.clear()
            pw_input.send_keys(self.password)
            self._safe_sleep(self.WAIT_SHORT)
            
            # ログインボタンクリック
            self._wait_and_click(By.CSS_SELECTOR, 'button[type="submit"]')
            self._safe_sleep(self.WAIT_MEDIUM)
            
            # ログイン成功確認
            WebDriverWait(self.driver, self.WAIT_TIMEOUT).until(
                lambda d: "login" not in d.current_url.lower()
            )
            
            logger.info("ログイン成功")
            return True
            
        except TimeoutException as e:
            logger.error(f"ログインタイムアウト: {e}")
            return False
        except Exception as e:
            logger.error(f"ログインエラー: {e}")
            return False
            
    def write_karte(self, homis_id: str, karte_data: dict) -> dict:
        """
        カルテにデータを書き込み
        
        Args:
            homis_id: 患者ID
            karte_data: 書き込みデータ
            
        Returns:
            dict: {"success": bool, "karte_url": str|None}
        """
        result = {"success": False, "karte_url": None}
        
        try:
            # ドライバーを作成していなければ作成
            if self.driver is None:
                self._create_driver()
            
            # S欄とA/P Summary欄のテキストを生成
            s_text = self._build_s_text(karte_data)
            ap_text = self._build_ap_summary_text(karte_data)
            
            logger.info(f"カルテ書き込み開始: {homis_id}")
            logger.info(f"S欄:\n{s_text}")
            logger.info(f"A/P Summary欄:\n{ap_text}")
            
            # Step 1: 患者詳細ページに直接アクセス
            patient_url = f"{self.base_url}?pid=patient_detail&patient_id={homis_id}"
            logger.info(f"患者ページに移動: {patient_url}")
            self.driver.get(patient_url)
            self._safe_sleep(self.WAIT_MEDIUM)
            
            # ログイン画面が表示された場合のみ認証
            if not self._login_if_needed():
                logger.error("ログインに失敗しました")
                return result
            
            # Step 2: 「新規」ボタンをクリック（aタグ id="karteNew"）
            logger.info("「新規」ボタンを探しています...")
            try:
                new_button = self._wait_and_find(By.ID, "karteNew")
                new_button.click()
                self._safe_sleep(self.WAIT_MEDIUM)
                logger.info("「新規」ボタンをクリック")
            except Exception as e:
                logger.error(f"「新規」ボタンが見つかりません: {e}")
                return result

            
            # Step 3: 「外来」ラジオボタンを選択
            # ============================================================
            # 【重要】JavaScriptでのradio.checked=trueは反映されないことがある
            # → ラベル「外来」をSeleniumでクリックするのが最も確実！(2026/1/26検証済み)
            # ============================================================
            logger.info("「外来」ラジオボタンを探しています...")
            try:
                # 方法1: ラベル「外来」を直接クリック（推奨）
                labels = self.driver.find_elements(By.TAG_NAME, "label")
                selected = False
                for label in labels:
                    if "外来" in label.text:
                        label.click()
                        selected = True
                        logger.info("「外来」ラベルをクリック")
                        break
                
                # 方法2: フォールバック（value=10）
                if not selected:
                    gairai_radio = self._wait_and_find(By.CSS_SELECTOR, 'input[name="karte_type"][value="10"]')
                    gairai_radio.click()
                    logger.info("「外来」ラジオボタンをクリック（フォールバック）")
                
                self._safe_sleep(self.WAIT_SHORT)
            except Exception as e:
                logger.warning(f"「外来」ラジオボタンが見つかりません: {e}")
            
            # Step 4: 指示医を選択（id="doctor018"）
            logger.info("指示医を選択しています...")
            doctor_name = karte_data.get('doctorName', '')
            
            # 医師名を加工：「【医師】\n福田 俊一 / 内科」→「福田俊一」
            if doctor_name:
                # 「【医師】」を削除
                doctor_name = doctor_name.replace('【医師】', '').strip()
                # 改行を削除
                doctor_name = doctor_name.replace('\n', '').strip()
                # 「/ 内科」などの科目情報を削除
                if '/' in doctor_name:
                    doctor_name = doctor_name.split('/')[0].strip()
                # 空白を削除（「福田 俊一」→「福田俊一」）
                doctor_name = doctor_name.replace(' ', '').replace('　', '')
                logger.info(f"加工後の医師名: {doctor_name}")
            try:
                from selenium.webdriver.support.ui import Select
                select_elem = self._wait_and_find(By.ID, "doctor018")
                select = Select(select_elem)
                # 医師名で選択
                selected = False
                for option in select.options:
                    if doctor_name in option.text:
                        select.select_by_visible_text(option.text)
                        logger.info(f"指示医を選択: {option.text}")
                        selected = True
                        break
                if not selected:
                    logger.warning(f"指示医 '{doctor_name}' が見つかりませんでした")
                self._safe_sleep(self.WAIT_SHORT)
            except Exception as e:
                logger.warning(f"指示医選択エラー: {e}")
            
            # Step 5: 「医科カルテ」ボタンをクリック（aタグ）
            logger.info("「医科カルテ」ボタンを探しています...")
            try:
                ika_button = self._wait_and_find(By.XPATH, "//a[contains(text(), '医科カルテ')]")
                ika_button.click()
                self._safe_sleep(self.WAIT_LONG)  # カルテ画面読み込みを待つ
                logger.info("「医科カルテ」ボタンをクリック")
            except Exception as e:
                logger.error(f"「医科カルテ」ボタンが見つかりません: {e}")
                return result
            
            # Step 5.5: 日付・時刻を入力
            # ============================================================
            # 【フィールド情報】
            # - 診察日: id="act_date" (type="date", YYYY-MM-DD形式)
            # - 開始時刻: id="start_time" (type="text", HH:MM形式)
            # - 終了時刻: id="end_time" (type="text", HH:MM形式)
            # ※往診カルテ作成PJと同じJavaScript方式で設定
            # ============================================================
            
            # 診察日入力（JSONの撮影日を使用）
            shooting_date = karte_data.get('shootingDate', '')
            if shooting_date:
                try:
                    self.driver.execute_script("""
                        const actDate = document.getElementById('act_date');
                        if (actDate) {
                            actDate.value = arguments[0];
                            actDate.dispatchEvent(new Event('input', { bubbles: true }));
                            actDate.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    """, shooting_date)
                    logger.info(f"診察日を入力: {shooting_date}")
                except Exception as e:
                    logger.warning(f"診察日入力エラー: {e}")
            
            # 開始時間入力（任意）
            shooting_time = karte_data.get('shootingTime', '')
            if shooting_time:
                try:
                    # 終了時間を計算（開始時間 + 10分）
                    from datetime import datetime, timedelta
                    start_dt = datetime.strptime(shooting_time, "%H:%M")
                    end_dt = start_dt + timedelta(minutes=10)
                    end_time = end_dt.strftime("%H:%M")
                    
                    self.driver.execute_script("""
                        const startTime = document.getElementById('start_time');
                        const endTime = document.getElementById('end_time');
                        
                        if (startTime) {
                            startTime.value = arguments[0];
                            startTime.dispatchEvent(new Event('input', { bubbles: true }));
                            startTime.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        
                        if (endTime) {
                            endTime.value = arguments[1];
                            endTime.dispatchEvent(new Event('input', { bubbles: true }));
                            endTime.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    """, shooting_time, end_time)
                    logger.info(f"開始時間を入力: {shooting_time}")
                    logger.info(f"終了時間を入力: {end_time}")
                except Exception as e:
                    logger.warning(f"時間入力エラー: {e}")
            
            self._safe_sleep(self.WAIT_MEDIUM)  # 画面が安定するのを待つ
            
            # Step 6: S欄に入力（id="subjective"）
            # ============================================================
            # 【重要】単純なvalue設定では保存されない！
            # → inputイベントを発火させること！(2026/1/26検証済み)
            # ============================================================
            logger.info("S欄を探しています...")
            try:
                # JavaScriptでinputイベント発火させながら入力
                self.driver.execute_script("""
                    const s = document.querySelector('textarea#subjective');
                    if (s) {
                        s.scrollIntoView();
                        s.focus();
                        s.value = arguments[0];
                        s.dispatchEvent(new Event('input', { bubbles: true }));
                        s.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                """, s_text)
                self._safe_sleep(self.WAIT_SHORT)
                logger.info("S欄に入力完了")
            except Exception as e:
                logger.warning(f"S欄入力エラー: {e}")
            
            self._safe_sleep(self.WAIT_MEDIUM)  # A/P Summary入力前に待機
            
            # Step 7: A/P Summary欄に入力（id="ap"）
            # ============================================================
            # 【重要】A/P Summary欄は画面下部にあるためスクロール必須！
            # また、複数の#apが存在する可能性があるので可視状態のものを選択
            # inputイベント発火が必須！(2026/1/26検証済み)
            # ============================================================
            logger.info("A/P Summary欄を探しています...")
            try:
                # 複数の#apがある場合を考慮し、可視状態のものを選択
                self.driver.execute_script("""
                    const aps = Array.from(document.querySelectorAll('textarea#ap'));
                    const visibleAp = aps.find(el => el.offsetWidth > 0 && el.offsetHeight > 0) || aps[0];
                    if (visibleAp) {
                        visibleAp.scrollIntoView();
                        visibleAp.focus();
                        visibleAp.value = arguments[0];
                        visibleAp.dispatchEvent(new Event('input', { bubbles: true }));
                        visibleAp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                """, ap_text)
                
                self._safe_sleep(self.WAIT_SHORT)
                logger.info("A/P Summary欄に入力完了（JavaScript）")
            except Exception as e:
                logger.warning(f"A/P Summary欄入力エラー: {e}")
            
            # Step 8: 「中断」ボタンで保存（id="karteInterruption"）
            logger.info("「中断」ボタンを探しています...")
            try:
                save_button = self._wait_and_find(By.ID, "karteInterruption")
                save_button.click()
                logger.info("「中断」ボタンをクリック")
                
                # アラートが出るのでOKを押す
                self._safe_sleep(self.WAIT_SHORT)
                try:
                    from selenium.webdriver.common.alert import Alert
                    alert = Alert(self.driver)
                    alert.accept()
                    logger.info("アラートでOKをクリック")
                except:
                    logger.info("アラートはありませんでした")
                
                self._safe_sleep(self.WAIT_LONG)  # 保存完了を待つ
                logger.info("保存完了")
            except Exception as e:
                logger.error(f"「中断」ボタンが見つかりません: {e}")
            
            # Step 9: 「リンクをコピー」ボタンでURL取得（onclick="copyLinkOfKarte"）
            logger.info("「リンクをコピー」ボタンを探しています...")
            try:
                # copyLinkOfKarte関数を持つaタグを探す
                link_button = self._wait_and_find(By.XPATH, "//a[contains(@onclick, 'copyLinkOfKarte')]")
                link_button.click()
                self._safe_sleep(self.WAIT_SHORT)
                logger.info("「リンクをコピー」ボタンをクリック")
                
                # クリップボードからURLを取得
                import pyperclip
                karte_url = pyperclip.paste()
                result["karte_url"] = karte_url
                logger.info(f"カルテURL: {karte_url}")
            except Exception as e:
                logger.warning(f"リンクコピーをスキップ: {e}")
            
            result["success"] = True
            logger.info(f"✅ カルテ書き込み成功: {homis_id}")
            return result
            
        except Exception as e:
            logger.error(f"カルテ書き込みエラー: {e}")
            return result
        finally:
            self.close()
    
    def _build_s_text(self, data: dict) -> str:
        """S欄のテキストを生成"""
        lines = []
        
        # 最初の部位と目的を表示
        orders = data.get('orders', [])
        if orders:
            first_order = orders[0]
            site_name = first_order.get('siteName', '')
            purpose = first_order.get('purpose', '')
            
            lines.append(f"{site_name}レントゲン")
            if purpose:
                lines.append(purpose)
        
        return "\n".join(lines)
    
    def _build_ap_summary_text(self, data: dict) -> str:
        """A/P Summary欄のテキストを生成"""
        lines = []
        
        # 指示医
        lines.append(f"指示医：{data.get('doctorName', '')}")
        
        # ORCA番号 + 患者名 + XP日付
        orca_prefix = data.get('orcaNumber', '')
        patient_name = data.get('patientName', '')
        shooting_date = data.get('shootingDate', '').replace('-', '_')
        request_date = data.get('requestDate', '').replace('-', '_') if data.get('requestDate') else ''
        
        xp_line = f"{orca_prefix}{patient_name}様XP {shooting_date}"
        if request_date:
            xp_line += f" XP依頼日: {request_date}"
        lines.append(xp_line)
        
        # 部位ごとの詳細
        orders = data.get('orders', [])
        for order in orders:
            if order.get('purpose'):
                lines.append(f"目的：{order['purpose']}")
            
            # 部位情報を組み立て
            site_str = order.get('siteName', '')
            if order.get('direction'):
                site_str += order['direction']
            if order.get('position'):
                site_str += f"（{order['position']}）"
            
            lines.append(f"部位：{site_str}")
            lines.append(f"撮影枚数：{order.get('shotCount', 0)}枚")
        
        # LookRECリンク
        if data.get('lookrecLink'):
            lines.append(data['lookrecLink'])
        
        # 合計
        lines.append(f"合計：{data.get('totalCount', 0)}枚")
        
        return "\n".join(lines)
        
    def close(self):
        """ブラウザを閉じる"""
        if self.driver is not None:
            try:
                self.driver.quit()
                logger.info("ブラウザを終了しました")
            except Exception as e:
                logger.warning(f"ブラウザ終了時にエラー: {e}")
            finally:
                self.driver = None
                self.is_logged_in = False
                
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# === テスト用コード ===
if __name__ == "__main__":
    import json
    from pathlib import Path
    
    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 設定読み込み
    config_path = Path(__file__).parent / "config.json"
    
    if not config_path.exists():
        print("❌ config.json が見つかりません")
        print("   以下の設定が必要です:")
        print("   - homis_url")
        print("   - homis_user")
        print("   - homis_password")
        exit(1)
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # テストデータ
    test_data = {
        "patientName": "テスト太郎",
        "shootingDate": "2026-01-26",
        "doctorName": "山口高秀",
        "orders": [
            {
                "siteName": "胸部正面",
                "direction": "PA",
                "position": "立位",
                "purpose": "テスト撮影",
                "shotCount": 2
            }
        ],
        "totalCount": 2,
        "lookrecLink": "https://example.com/test"
    }
    
    print("=" * 50)
    print("Homisカルテ書き込みテスト")
    print("=" * 50)
    
    # テスト用患者ID
    TEST_PATIENT_ID = "2277808"
    
    # 表示モードでテスト
    writer = HomisKarteWriter(config, headless=False)
    
    # カルテ書き込みテスト
    print(f"\n患者ID {TEST_PATIENT_ID} でカルテ入力テストを実行...")
    print("\nS欄テキスト:")
    print(writer._build_s_text(test_data))
    print("\nA/P Summary欄テキスト:")
    print(writer._build_ap_summary_text(test_data))
    print("\n" + "-" * 50)
    
    result = writer.write_karte(TEST_PATIENT_ID, test_data)
    
    if result["success"]:
        print("✅ カルテ書き込み成功!")
        if result["karte_url"]:
            print(f"カルテURL: {result['karte_url']}")
    else:
        print("❌ カルテ書き込み失敗")
