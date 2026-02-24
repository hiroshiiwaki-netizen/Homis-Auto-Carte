# -*- coding: utf-8 -*-
"""
Homis カルテ作成 サンプルスクリプト
===================================
ブラウザテストで検証済みのフローをSeleniumで実行するサンプル。
テスト患者ID: 2277808 (テスト舞子)
"""

import time
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

# 設定読み込み
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

# テストデータ
TEST_PATIENT_ID = "2277808"
TEST_S_TEXT = "Test input for S column - Selenium"
TEST_AP_TEXT = "Test AP summary - Selenium"


def create_driver(headless=False):
    """Chrome WebDriverを作成"""
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--window-size=1200,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)


def wait_and_click(driver, by, value, timeout=10):
    """要素を待機してクリック"""
    element = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )
    element.click()
    return element


def main():
    print("=" * 50)
    print("Homis カルテ作成 サンプルテスト")
    print("=" * 50)
    
    driver = create_driver(headless=False)
    
    try:
        # ===== 1. ログイン =====
        print("\n[1/7] ログイン中...")
        url = f"https://homis.jp/homic/?pid=patient_detail&patient_id={TEST_PATIENT_ID}"
        driver.get(url)
        time.sleep(2)
        
        # ログイン画面なら認証
        if "login" in driver.current_url:
            driver.find_element(By.CSS_SELECTOR, 'input[name="id"]').send_keys(config["homis_user"])
            driver.find_element(By.CSS_SELECTOR, 'input[name="pw"]').send_keys(config["homis_password"])
            driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
            time.sleep(3)
        
        print(f"  → 患者詳細画面: {driver.current_url}")
        
        # ===== 2. 新規ボタン =====
        print("\n[2/7] 新規ボタンをクリック...")
        wait_and_click(driver, By.ID, "karteNew")
        time.sleep(2)
        
        # ===== 3. 外来ラジオボタン =====
        print("\n[3/7] 外来ラジオボタンを選択...")
        driver.execute_script("""
            const radio = document.querySelector('input[name="karte_type"][value="10"]');
            if (radio) radio.click();
        """)
        time.sleep(1)
        
        # ===== 4. 医師選択 =====
        print("\n[4/7] 医師を選択...")
        driver.execute_script("""
            const select = document.getElementById('doctor018');
            if (select && select.options.length > 1) {
                select.selectedIndex = 1;
                select.dispatchEvent(new Event('change'));
            }
        """)
        time.sleep(1)
        
        # ===== 5. 医科カルテボタン =====
        print("\n[5/7] 医科カルテボタンをクリック...")
        driver.execute_script("""
            const buttons = Array.from(document.querySelectorAll('a.btn'));
            const targetBtn = buttons.find(b => b.innerText.includes('医科カルテ'));
            if (targetBtn) targetBtn.click();
        """)
        time.sleep(3)
        
        # ===== 6. S欄・A/P入力 =====
        print("\n[6/7] S欄・A/P Summaryを入力...")
        
        # 時刻設定（必要に応じて）
        driver.execute_script("""
            const start = document.getElementById('start_time');
            const end = document.getElementById('end_time');
            const now = new Date();
            const pad = n => n.toString().padStart(2, '0');
            const formatTime = d => pad(d.getHours()) + ':' + pad(d.getMinutes());
            
            if (start && !start.value) {
                start.value = formatTime(new Date(now.getTime() - 600000));
                start.dispatchEvent(new Event('change'));
            }
            if (end && !end.value) {
                end.value = formatTime(now);
                end.dispatchEvent(new Event('change'));
            }
        """)
        
        # S欄入力
        driver.execute_script("""
            const s = document.getElementById('subjective');
            if (s) {
                s.value = arguments[0];
                s.dispatchEvent(new Event('input', { bubbles: true }));
                s.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, TEST_S_TEXT)
        
        # A/P Summary入力（スクロール＋イベント発火が重要！）
        driver.execute_script("""
            const ap = document.getElementById('ap');
            if (ap) {
                ap.scrollIntoView();
                ap.value = arguments[0];
                ap.dispatchEvent(new Event('input', { bubbles: true }));
                ap.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, TEST_AP_TEXT)
        time.sleep(1)
        
        print(f"  → S欄: {TEST_S_TEXT}")
        print(f"  → A/P: {TEST_AP_TEXT}")
        
        # ===== 7. 中断ボタン =====
        print("\n[7/7] 中断ボタンで保存...")
        
        # アラート自動承認
        driver.execute_script("""
            window.confirm = () => true;
            window.alert = () => true;
        """)
        
        wait_and_click(driver, By.ID, "karteInterruption")
        time.sleep(3)
        
        # ===== 結果確認 =====
        final_url = driver.current_url
        print("\n" + "=" * 50)
        print("テスト完了!")
        print("=" * 50)
        print(f"最終URL: {final_url}")
        
        # カルテIDを抽出
        if "karte_id=" in final_url:
            karte_id = final_url.split("karte_id=")[1].split("&")[0]
            print(f"作成されたカルテID: {karte_id}")
        
        input("\nEnterキーで終了...")
        
    except Exception as e:
        print(f"\n[エラー] {e}")
        import traceback
        traceback.print_exc()
        input("\nEnterキーで終了...")
    
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
