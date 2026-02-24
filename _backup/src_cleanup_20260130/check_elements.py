# -*- coding: utf-8 -*-
"""
Homis新規カルテ画面確認スクリプト
新規ボタンクリック後の画面要素を確認
"""

import time
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

def main():
    # 設定読み込み
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # ブラウザ起動（表示モード）
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--lang=ja-JP")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        # ログイン
        print("ログインページにアクセス...")
        driver.get("https://homis.jp/homic/login.php")
        time.sleep(2)
        
        id_input = driver.find_element(By.CSS_SELECTOR, 'input[name="id"]')
        id_input.send_keys(config["homis_user"])
        
        pw_input = driver.find_element(By.CSS_SELECTOR, 'input[name="pw"]')
        pw_input.send_keys(config["homis_password"])
        
        login_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        login_btn.click()
        time.sleep(3)
        print("ログイン成功")
        
        # 患者詳細ページへ
        print("\n患者詳細ページに移動...")
        driver.get("https://homis.jp/homic/?pid=patient_detail&patient_id=2277808")
        time.sleep(3)
        
        # 新規ボタンをクリック
        print("\n「新規」ボタン（id=karteNew）をクリック...")
        new_btn = driver.find_element(By.ID, "karteNew")
        new_btn.click()
        time.sleep(3)
        
        print("\n=== 新規カルテ画面の要素確認 ===")
        
        # ラジオボタン確認
        print("\n=== ラジオボタン一覧 ===")
        radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        for i, radio in enumerate(radios):
            name = radio.get_attribute("name")
            value = radio.get_attribute("value")
            id_attr = radio.get_attribute("id")
            label_text = ""
            try:
                label = driver.find_element(By.CSS_SELECTOR, f"label[for='{id_attr}']")
                label_text = label.text
            except:
                pass
            print(f"[{i}] name='{name}', value='{value}', id='{id_attr}', label='{label_text}'")
        
        # input[type="date"]確認
        print("\n=== 日付入力欄 ===")
        date_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='date']")
        for i, inp in enumerate(date_inputs):
            name = inp.get_attribute("name")
            id_attr = inp.get_attribute("id")
            value = inp.get_attribute("value")
            print(f"[{i}] name='{name}', id='{id_attr}', value='{value}'")
        
        # input[type="text"]確認
        print("\n=== テキスト入力欄 ===")
        text_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
        for i, inp in enumerate(text_inputs[:15]):
            name = inp.get_attribute("name")
            id_attr = inp.get_attribute("id")
            placeholder = inp.get_attribute("placeholder")
            print(f"[{i}] name='{name}', id='{id_attr}', placeholder='{placeholder}'")
        
        # セレクトボックス確認
        print("\n=== セレクトボックス一覧 ===")
        selects = driver.find_elements(By.TAG_NAME, "select")
        for i, sel in enumerate(selects):
            name = sel.get_attribute("name")
            id_attr = sel.get_attribute("id")
            options_text = [opt.text for opt in sel.find_elements(By.TAG_NAME, "option")[:5]]
            print(f"[{i}] name='{name}', id='{id_attr}', options={options_text}...")
        
        # ボタン（aタグ含む）確認
        print("\n=== ボタン一覧（aタグ含む） ===")
        buttons = driver.find_elements(By.CSS_SELECTOR, "a.btn, button, input[type='button']")
        for i, btn in enumerate(buttons):
            text = btn.text.strip() if hasattr(btn, 'text') else ""
            value = btn.get_attribute("value") or ""
            id_attr = btn.get_attribute("id")
            cls = btn.get_attribute("class")
            if text or value:
                print(f"[{i}] text='{text}', value='{value}', id='{id_attr}', class='{cls[:50] if cls else ''}'")
        
        print("\n確認のため60秒待機...")
        print("画面を確認して、必要な要素のセレクタを教えてください。")
        time.sleep(60)
        
    finally:
        driver.quit()
        print("ブラウザを終了しました")

if __name__ == "__main__":
    main()
