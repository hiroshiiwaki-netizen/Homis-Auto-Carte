# -*- coding: utf-8 -*-
"""
Homisカルテ - デバッグ用スクリプト
各ステップで停止してブラウザを確認できる
"""

import json
import time
import logging
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def wait_for_user(step_name):
    """ステップごとに待機"""
    print(f"\n{'='*50}")
    print(f"🔵 {step_name}")
    print("ブラウザを確認してから Enter を押してください")
    print("="*50)
    input(">>> ")

def main():
    # 設定読み込み
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # ブラウザ起動
    print("\n🚀 ブラウザを起動...")
    options = Options()
    options.add_argument("--start-maximized")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 10)
    
    try:
        # ステップ1: ログイン
        print("\n📌 ログインページにアクセス...")
        driver.get("https://homis.jp/homic/login.php")
        time.sleep(2)
        
        id_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="id"]')))
        id_input.send_keys(config["homis_user"])
        
        password_input = driver.find_element(By.CSS_SELECTOR, 'input[name="pw"]')
        password_input.send_keys(config["homis_password"])
        
        login_button = driver.find_element(By.ID, "btn_login")
        login_button.click()
        time.sleep(3)
        
        wait_for_user("✅ ログイン完了")
        
        # ステップ2: 患者ページへ移動
        TEST_PATIENT_ID = "2277808"
        patient_url = f"https://homis.jp/homic/?pid=patient_detail&patient_id={TEST_PATIENT_ID}"
        driver.get(patient_url)
        time.sleep(3)
        
        wait_for_user(f"✅ 患者ページ表示: ID={TEST_PATIENT_ID}")
        
        # ステップ3: 新規ボタンをクリック
        print("\n📌 「新規」ボタンを探しています...")
        new_button = wait.until(EC.presence_of_element_located((By.ID, "karteNew")))
        new_button.click()
        time.sleep(2)
        
        wait_for_user("✅ 「新規」ボタンをクリック - ダイアログが表示されたか確認")
        
        # ステップ4: 外来ラジオボタン
        print("\n📌 「外来」ラジオボタンを探しています...")
        print("   セレクタ: input[name='karte_type'][value='10']")
        
        try:
            # まずラジオボタンの状態を確認
            radio = driver.find_element(By.CSS_SELECTOR, 'input[name="karte_type"][value="10"]')
            print(f"   要素発見: displayed={radio.is_displayed()}, enabled={radio.is_enabled()}")
            
            # クリックを試みる（通常）
            try:
                radio.click()
                print("   ✅ 通常クリック成功")
            except:
                print("   ⚠️ 通常クリック失敗、JavaScriptで試行...")
                driver.execute_script("arguments[0].click();", radio)
                print("   ✅ JavaScriptクリック成功")
        except Exception as e:
            print(f"   ❌ エラー: {e}")
        
        time.sleep(1)
        wait_for_user("✅ 「外来」ラジオボタン - 選択されているか確認")
        
        # ステップ5: 指示医選択
        print("\n📌 指示医を選択...")
        doctor_dropdown = wait.until(EC.presence_of_element_located((By.ID, "doctor018")))
        
        from selenium.webdriver.support.ui import Select
        select = Select(doctor_dropdown)
        
        # 山口高秀を検索
        for option in select.options:
            if "山口" in option.text and "高秀" in option.text:
                select.select_by_value(option.get_attribute("value"))
                print(f"   ✅ 医師選択: {option.text}")
                break
        
        time.sleep(1)
        wait_for_user("✅ 指示医を選択 - 正しく選択されているか確認")
        
        # ステップ6: 医科カルテボタン
        print("\n📌 「医科カルテ」ボタンを探しています...")
        ika_button = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(text(), '医科カルテ')]")
        ))
        ika_button.click()
        time.sleep(2)
        
        wait_for_user("✅ 「医科カルテ」ボタンをクリック - 画面が切り替わったか確認")
        
        # ステップ7: S欄入力
        print("\n📌 S欄に入力...")
        s_text = "胸部正面レントゲン\nテスト撮影"
        
        s_textarea = wait.until(EC.presence_of_element_located((By.ID, "subjective")))
        print(f"   S欄発見: displayed={s_textarea.is_displayed()}")
        
        # スクロールして表示
        driver.execute_script("arguments[0].scrollIntoView(true);", s_textarea)
        time.sleep(0.5)
        
        s_textarea.clear()
        time.sleep(0.3)
        s_textarea.send_keys(s_text)
        time.sleep(0.5)
        
        wait_for_user("✅ S欄に入力 - テキストが入力されているか確認")
        
        # ステップ8: A/P Summary入力
        print("\n📌 A/P Summary欄に入力...")
        ap_text = "指示医：山口高秀\nテスト太郎様XP 2026_01_26\n目的：テスト撮影\n部位：胸部正面PA（立位）\n撮影枚数：2枚"
        
        ap_textarea = wait.until(EC.presence_of_element_located((By.ID, "ap")))
        print(f"   A/P欄発見: displayed={ap_textarea.is_displayed()}")
        
        # スクロールして表示
        driver.execute_script("arguments[0].scrollIntoView(true);", ap_textarea)
        time.sleep(0.5)
        
        # 方法1: 通常の入力
        print("   方法1: 通常入力を試行...")
        ap_textarea.clear()
        time.sleep(0.3)
        ap_textarea.send_keys(ap_text)
        
        # 入力されたかチェック
        current_value = ap_textarea.get_attribute("value")
        if current_value:
            print(f"   ✅ 入力成功: {len(current_value)}文字")
        else:
            print("   ⚠️ 入力されていません、JavaScriptで再試行...")
            
            # 方法2: JavaScript直接入力
            escaped = ap_text.replace("\\", "\\\\").replace("\n", "\\n").replace("'", "\\'")
            driver.execute_script(f"document.getElementById('ap').value = '{escaped}';")
            driver.execute_script("document.getElementById('ap').dispatchEvent(new Event('input'));")
            driver.execute_script("document.getElementById('ap').dispatchEvent(new Event('change'));")
            
            current_value = ap_textarea.get_attribute("value")
            if current_value:
                print(f"   ✅ JavaScript入力成功: {len(current_value)}文字")
            else:
                print("   ❌ JavaScript入力も失敗")
        
        wait_for_user("✅ A/P Summary欄に入力 - テキストが入力されているか確認")
        
        # ステップ9: 中断ボタン
        print("\n📌 「中断」ボタンを押す準備...")
        wait_for_user("⚠️ 「中断」ボタンを押しますか？（保存されます）")
        
        save_button = wait.until(EC.element_to_be_clickable((By.ID, "karteInterruption")))
        save_button.click()
        time.sleep(1)
        
        # アラート処理
        from selenium.webdriver.common.alert import Alert
        try:
            alert = Alert(driver)
            alert.accept()
            print("   ✅ アラートでOKをクリック")
        except:
            print("   ℹ️ アラートはありませんでした")
        
        time.sleep(3)
        wait_for_user("✅ 保存完了 - カルテが保存されたか確認")
        
        print("\n🎉 デバッグ完了!")
        
    except Exception as e:
        print(f"\n❌ エラー発生: {e}")
        import traceback
        traceback.print_exc()
        wait_for_user("エラー発生 - ブラウザを確認")
    
    finally:
        print("\nブラウザを閉じます...")
        input("Enter で閉じる >>> ")
        driver.quit()

if __name__ == "__main__":
    main()
