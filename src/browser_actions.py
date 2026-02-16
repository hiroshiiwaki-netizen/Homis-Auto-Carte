# -*- coding: utf-8 -*-
"""
ブラウザアクション定義
======================
YAMLテンプレートで指定されたアクションを実行

v1.1.0 - A/P Summary欄の選択ロジック修正 (2026/01/26)
"""

import time
import logging
from typing import Dict, Any, Optional
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoAlertPresentException

logger = logging.getLogger(__name__)


class BrowserActions:
    """ブラウザ操作アクションクラス"""
    
    def __init__(self, driver, timeout: int = 10):
        self.driver = driver
        self.timeout = timeout
    
    def execute_action(self, action: Dict[str, Any], data: Dict[str, Any]) -> bool:
        """
        アクションを実行
        
        Args:
            action: アクション定義 (name, action, selector, value, etc.)
            data: 変数展開用データ
        
        Returns:
            bool: 成功/失敗
        """
        action_type = action.get("action", "")
        name = action.get("name", action_type)
        
        try:
            logger.info(f"アクション実行: {name}")
            
            # 変数を展開
            selector = self._expand_variables(action.get("selector", ""), data)
            value = self._expand_variables(action.get("value", ""), data)
            selector_type = action.get("selector_type", "css")  # css or xpath
            text_contains = action.get("text_contains", "")  # ラベルテキスト検索用
            
            # アクション実行
            if action_type == "click":
                self._action_click(selector, selector_type, text_contains)
            elif action_type == "input":
                trigger_event = action.get("trigger_input_event", False)
                self._action_input(selector, value, trigger_event, selector_type)
            elif action_type == "js_input":
                self._action_js_input(selector, value)
            elif action_type == "select":
                self._action_select(selector, value, selector_type)
            elif action_type == "navigate":
                self._action_navigate(value)
            elif action_type == "wait":
                time.sleep(action.get("ms", 1000) / 1000)
            else:
                logger.warning(f"未対応のアクション: {action_type}")
                return False
            
            # アラート確認
            if action.get("confirm_alert"):
                self._confirm_alert()
            
            # 待機
            wait_after = action.get("wait_after", 0)
            if wait_after > 0:
                time.sleep(wait_after / 1000)
            
            logger.info(f"✅ {name} 完了")
            return True
            
        except Exception as e:
            logger.error(f"❌ {name} 失敗: {e}")
            return False
    
    def _expand_variables(self, text: str, data: Dict[str, Any]) -> str:
        """変数を展開 {varName} -> data[varName]"""
        if not text:
            return text
        
        result = text
        for key, value in data.items():
            placeholder = "{" + key + "}"
            if placeholder in result:
                result = result.replace(placeholder, str(value) if value else "")
        
        return result
    
    def _find_element(self, selector: str, clickable: bool = False, selector_type: str = "css"):
        """要素を検索（XPath対応）"""
        wait = WebDriverWait(self.driver, self.timeout)
        
        # XPathの場合
        if selector_type == "xpath":
            if clickable:
                return wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
            else:
                return wait.until(EC.presence_of_element_located((By.XPATH, selector)))
        
        # :contains() 疑似セレクタ対応
        if ":contains(" in selector:
            import re
            match = re.match(r"(.+):contains\('(.+)'\)", selector)
            if match:
                tag = match.group(1)
                text = match.group(2)
                xpath = f"//{tag}[contains(text(), '{text}')]"
                
                if clickable:
                    return wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                else:
                    return wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        
        # 通常のCSSセレクタ
        if clickable:
            return wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        else:
            return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
    
    def _action_click(self, selector: str, selector_type: str = "css", text_contains: str = ""):
        """クリックアクション（ラベルテキスト検索対応）"""
        # text_containsが指定されている場合、ラベル要素からテキスト検索
        if text_contains:
            elements = self.driver.find_elements(By.TAG_NAME, selector)
            for elem in elements:
                if text_contains in elem.text:
                    elem.click()
                    logger.info(f"'{text_contains}' を含む要素をクリック")
                    return
            raise Exception(f"'{text_contains}' を含む要素が見つかりません")
        
        element = self._find_element(selector, clickable=True, selector_type=selector_type)
        element.click()
    
    def _action_input(self, selector: str, value: str, trigger_event: bool = False, selector_type: str = "css"):
        """入力アクション"""
        element = self._find_element(selector, selector_type=selector_type)
        element.clear()
        element.send_keys(value)
        
        # Reactなどのフレームワーク用にinputイベントを発火
        if trigger_event:
            self.driver.execute_script("""
                var event = new Event('input', { bubbles: true });
                arguments[0].dispatchEvent(event);
            """, element)
    
    def _action_select(self, selector: str, value: str, selector_type: str = "css"):
        """プルダウン選択アクション"""
        element = self._find_element(selector, selector_type=selector_type)
        select = Select(element)
        
        # テキストで選択を試みる
        try:
            # 空白を除去した値でマッチング
            normalized_value = value.replace(" ", "").replace("　", "")
            for option in select.options:
                normalized_option = option.text.replace(" ", "").replace("　", "")
                if normalized_value in normalized_option or normalized_option in normalized_value:
                    select.select_by_visible_text(option.text)
                    return
            
            # 見つからない場合は値で選択
            select.select_by_value(value)
        except Exception:
            # 最後の手段: 部分一致
            for option in select.options:
                if value in option.text:
                    select.select_by_visible_text(option.text)
                    return
            raise
    
    def _action_js_input(self, selector: str, value: str):
        """JavaScriptで入力（複数要素の場合は最後の可視要素を選択）"""
        self.driver.execute_script("""
            // 複数の要素がある場合は可視状態のものをすべて取得
            const elements = Array.from(document.querySelectorAll(arguments[0]));
            const visibleElements = elements.filter(el => el.offsetWidth > 0 && el.offsetHeight > 0);
            
            // 最後の可視要素を選択（最新のカルテ）
            const targetElem = visibleElements.length > 0 ? visibleElements[visibleElements.length - 1] : elements[0];
            
            if (targetElem) {
                targetElem.scrollIntoView();
                targetElem.focus();
                targetElem.value = arguments[1];
                targetElem.dispatchEvent(new Event('input', { bubbles: true }));
                targetElem.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, selector, value)
        logger.info(f"JavaScript入力完了: {selector}")
    
    def _action_navigate(self, url: str):
        """ページ遷移アクション"""
        self.driver.get(url)
    
    def _confirm_alert(self):
        """アラートでOKをクリック"""
        try:
            time.sleep(0.5)
            alert = self.driver.switch_to.alert
            alert.accept()
            logger.info("アラートでOKをクリック")
        except NoAlertPresentException:
            pass
