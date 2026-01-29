# -*- coding: utf-8 -*-
"""
Homis カルテ作成 改良版サンプルスクリプト
==========================================
マクロで検証済みのセレクタ + JavaScript の柔軟性を組み合わせ。
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

# 設定読み込み
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

# テストデータ
TEST_PATIENT_ID = "2277808"
TEST_S_TEXT = "Test S - Selenium v2"
TEST_AP_TEXT = "Test AP Summary - Selenium v2"
TEST_DOCTOR = "青木 浩"  # 医師名で検索


def create_driver(headless=False):
    """Chrome WebDriverを作成"""
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--window-size=1200,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)


def wait_for_element(driver, by, value, timeout=10):
    """要素を待機して取得"""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )


def main():
    print("=" * 60)
    print("Homis カルテ作成 改良版テスト")
    print("=" * 60)
    
    driver = create_driver(headless=False)
    
    try:
        # ===== 1. ログイン =====
        print("\n[1/8] ログイン中...")
        url = f"https://homis.jp/homic/?pid=patient_detail&patient_id={TEST_PATIENT_ID}"
        driver.get(url)
        time.sleep(2)
        
        # ログイン画面なら認証
        if "login" in driver.current_url:
            driver.find_element(By.CSS_SELECTOR, 'input[name="id"]').send_keys(config["homis_user"])
            driver.find_element(By.CSS_SELECTOR, 'input[name="pw"]').send_keys(config["homis_password"])
            driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
            time.sleep(3)
        
        print(f"  → URL: {driver.current_url}")
        
        # ===== 2. 新規ボタン（マクロ検証済み: a#karteNew）=====
        print("\n[2/8] 新規ボタンをクリック...")
        new_btn = wait_for_element(driver, By.CSS_SELECTOR, "a#karteNew")
        new_btn.click()
        time.sleep(2)
        print("  → 新規ダイアログ表示")
        
        # ===== 3. 外来ラジオボタン（Seleniumネイティブクリック）=====
        print("\n[3/8] 外来ラジオボタンを選択...")
        
        # 方法: Seleniumでラベルを直接クリック（より確実）
        try:
            # 外来ラジオボタンのラベルを探してクリック
            labels = driver.find_elements(By.TAG_NAME, "label")
            for label in labels:
                if "外来" in label.text:
                    label.click()
                    print("  → ラベル「外来」をクリック成功")
                    break
            else:
                # フォールバック: input要素を直接クリック (マクロではvalue=9)
                radio = driver.find_element(By.CSS_SELECTOR, 'input[name="karte_type"][value="9"]')
                driver.execute_script("arguments[0].scrollIntoView(true);", radio)
                time.sleep(0.3)
                radio.click()
                print(f"  → ラジオボタンvalue=9をクリック成功")
        except Exception as e:
            print(f"  → 外来ラジオボタン選択エラー: {e}")
        
        time.sleep(1)
        
        # ===== 4. 医師選択（JavaScript プルダウン操作）=====
        print(f"\n[4/8] 医師「{TEST_DOCTOR}」を選択...")
        result = driver.execute_script("""
            const select = document.getElementById('doctor018');
            if (!select) return "医師プルダウンが見つかりません";
            
            // 指定された医師名で検索
            const targetName = arguments[0];
            const option = Array.from(select.options).find(o => o.text.includes(targetName));
            
            if (option) {
                select.value = option.value;
                select.dispatchEvent(new Event('change', { bubbles: true }));
                return "医師選択成功: " + option.text;
            } else if (select.options.length > 1) {
                // 見つからなければ最初の医師を選択
                select.selectedIndex = 1;
                select.dispatchEvent(new Event('change', { bubbles: true }));
                return "フォールバック: " + select.options[1].text;
            }
            return "医師選択失敗";
        """, TEST_DOCTOR)
        print(f"  → {result}")
        time.sleep(1)
        
        # ===== 5. 医科カルテボタン =====
        print("\n[5/8] 医科カルテボタンをクリック...")
        result = driver.execute_script("""
            // 方法1: マクロのセレクタ
            let btn = document.querySelector('tr:nth-of-type(2) > td:nth-of-type(5) > a:nth-of-type(1)');
            
            // 方法2: テキストで検索
            if (!btn) {
                const links = Array.from(document.querySelectorAll('a'));
                btn = links.find(a => a.innerText.includes('医科カルテ'));
            }
            
            // 方法3: btn-action クラス
            if (!btn) {
                btn = document.querySelector('.btn-action');
            }
            
            if (btn) {
                btn.click();
                return "医科カルテボタンクリック成功";
            }
            return "医科カルテボタンが見つかりません";
        """)
        print(f"  → {result}")
        time.sleep(3)
        
        # ===== 6. 時刻入力（マクロ検証済み: input#start_time, input#end_time）=====
        print("\n[6/8] 開始/終了時刻を入力...")
        driver.execute_script("""
            const now = new Date();
            const pad = n => n.toString().padStart(2, '0');
            const formatTime = d => pad(d.getHours()) + ':' + pad(d.getMinutes());
            
            const start = document.getElementById('start_time');
            const end = document.getElementById('end_time');
            
            if (start) {
                start.value = formatTime(new Date(now.getTime() - 600000)); // 10分前
                start.dispatchEvent(new Event('input', { bubbles: true }));
                start.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (end) {
                end.value = formatTime(now);
                end.dispatchEvent(new Event('input', { bubbles: true }));
                end.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """)
        print("  → 時刻設定完了")
        
        # ===== 7. S欄・A/P Summary入力（マクロ検証済み: textarea#subjective, textarea#ap）=====
        print("\n[7/8] S欄・A/P Summaryを入力...")
        
        # S欄
        driver.execute_script("""
            const s = document.querySelector('textarea#subjective');
            if (s) {
                s.scrollIntoView();
                s.focus();
                s.value = arguments[0];
                s.dispatchEvent(new Event('input', { bubbles: true }));
                s.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, TEST_S_TEXT)
        time.sleep(0.5)
        
        # A/P Summary（複数の#apがある可能性を考慮）
        driver.execute_script("""
            // 可視状態の#apを探す
            const aps = Array.from(document.querySelectorAll('textarea#ap'));
            const visibleAp = aps.find(el => el.offsetWidth > 0 && el.offsetHeight > 0) || aps[0];
            
            if (visibleAp) {
                visibleAp.scrollIntoView();
                visibleAp.focus();
                visibleAp.value = arguments[0];
                visibleAp.dispatchEvent(new Event('input', { bubbles: true }));
                visibleAp.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, TEST_AP_TEXT)
        time.sleep(0.5)
        
        print(f"  → S欄: {TEST_S_TEXT}")
        print(f"  → A/P: {TEST_AP_TEXT}")
        
        # ===== 8. 中断ボタン（マクロ検証済み: a#karteInterruption）=====
        print("\n[8/8] 中断ボタンで保存...")
        
        # アラート自動承認
        driver.execute_script("""
            window.confirm = () => true;
            window.alert = () => true;
        """)
        
        # 中断ボタンクリック
        interrupt_btn = driver.find_element(By.CSS_SELECTOR, "a#karteInterruption")
        interrupt_btn.click()
        time.sleep(3)
        
        # ===== 結果確認 =====
        final_url = driver.current_url
        print("\n" + "=" * 60)
        print("テスト完了!")
        print("=" * 60)
        print(f"最終URL: {final_url}")
        
        if "karte_id=" in final_url:
            karte_id = final_url.split("karte_id=")[1].split("&")[0]
            print(f"作成されたカルテID: {karte_id}")
        
        input("\n[確認] Enterキーで終了...")
        
    except Exception as e:
        print(f"\n[エラー] {e}")
        import traceback
        traceback.print_exc()
        input("\n[エラー] Enterキーで終了...")
    
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
