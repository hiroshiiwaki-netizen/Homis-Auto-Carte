# -*- coding: utf-8 -*-
"""
カルテURL取得ユーティリティ
============================
HOMISカルテURLの安全な取得を提供する共通ヘルパー。

v2.0.2 - OhiScanGo方式追加 (2026/06/19)
  - extract_karte_url(): ブラウザから直接URL取得（クリップボード不要）
    優先度1: ブラウザ現在URL（karte_id含む場合）
    優先度2: DOM要素（copyLinkOfKarteのonclick属性）から抽出
    優先度3: フォールバック（現在URLをそのまま返す）

v1.6.0 - 新規作成 (2026/06/19)
  - クリップボード事前クリア（直前の内容混入防止）
  - URL検証（homis.jp + /homic/ + karte_id= を含むかチェック）

使い方（推奨 - OhiScanGo方式）:
    from clipboard_utils import extract_karte_url
    karte_url = extract_karte_url(driver)

使い方（旧方式 - クリップボード経由、非headless時のフォールバック）:
    from clipboard_utils import clear_clipboard, get_validated_karte_url
    clear_clipboard()
    karte_url = get_validated_karte_url()
"""

import logging

logger = logging.getLogger(__name__)

# URL検証に使うキーワード（homis.jpのカルテURLに含まれるべき文字列）
HOMIS_URL_MARKERS = ["homis.jp", "/homic/"]


def clear_clipboard() -> None:
    """
    クリップボードを空にする。
    「リンクをコピー」ボタンをクリックする直前に呼び出すこと。
    これにより、直前のクリップボード内容が混入するのを防ぐ。
    """
    try:
        import pyperclip
        pyperclip.copy("")
        logger.debug("クリップボードをクリアしました")
    except Exception as e:
        logger.warning(f"クリップボードクリア失敗（処理は続行）: {e}")


def get_validated_karte_url() -> str:
    """
    クリップボードからHOMISカルテURLを取得し、検証する。
    「リンクをコピー」ボタンのクリック + 待機後に呼び出すこと。

    Returns:
        str: 検証済みのカルテURL。無効な場合は空文字列。
    """
    try:
        import pyperclip
        raw = pyperclip.paste()
    except Exception as e:
        logger.warning(f"クリップボード読み取り失敗: {e}")
        return ""

    # 空の場合（クリアされたまま＝ボタンが機能しなかった）
    if not raw or not raw.strip():
        logger.warning("⚠️ クリップボードが空です（リンクコピーが機能しなかった可能性）")
        return ""

    # URL検証: 単一行で、http始まりで、homis.jp と /homic/ を含む
    raw_stripped = raw.strip()

    # 複数行 = URLではない（テンプレート全文などの混入防止）
    if '\n' in raw_stripped or '\r' in raw_stripped:
        preview = raw_stripped[:80].replace('\n', ' ').replace('\r', '')
        logger.warning(f"⚠️ クリップボードに複数行テキストを検出（URLではない）: {preview}...")
        return ""

    # http始まりでなければURLではない
    if not raw_stripped.startswith("http"):
        preview = raw_stripped[:80] + "..." if len(raw_stripped) > 80 else raw_stripped
        logger.warning(f"⚠️ クリップボードの内容がURLではありません: {preview}")
        return ""

    # homis.jp + /homic/ の両方を含むか
    if all(marker in raw_stripped for marker in HOMIS_URL_MARKERS):
        # karte_id= が含まれているか（患者詳細URLとカルテURLの区別）
        if "karte_id=" not in raw_stripped:
            logger.warning(f"⚠️ karte_id がないURL（患者詳細ページの可能性）: {raw_stripped}")
            return ""
        logger.info(f"✅ カルテURL取得成功: {raw_stripped}")
        return raw_stripped

    # 検証失敗 — homis以外のURL
    preview = raw_stripped[:80] + "..." if len(raw_stripped) > 80 else raw_stripped
    logger.warning(f"⚠️ HOMIS以外のURLを検出: {preview}")
    return ""


def extract_karte_url(driver) -> str:
    """
    v2.0.2: ブラウザから直接カルテURLを取得する（OhiScanGo方式）。
    クリップボードを使わないため、headlessモードでも動作する。

    OhiScanGo の extractKarteURL() (karte_writer.go L319-344) と同じロジック:
      優先度1: ブラウザの現在URLに karte_id が含まれていればそれを返す
      優先度2: 「リンクをコピー」ボタンの onclick 属性からURLを抽出
      優先度3: フォールバックとして現在URLを返す

    Args:
        driver: Selenium WebDriver インスタンス

    Returns:
        str: カルテURL（karte_id付き）。取得失敗時は空文字列。
    """
    try:
        # === 優先度1: 現在のURLから取得 ===
        current_url = driver.current_url
        if "karte_id" in current_url:
            logger.info(f"✅ カルテURL取得成功（現在URL）: {current_url}")
            return current_url

        # === 優先度2: DOM要素から取得 ===
        # 「リンクをコピー」ボタンの onclick 属性にカルテURLが含まれている
        # 例: onclick="copyLinkOfKarte('https://homis.jp/homic/?pid=patient_detail&patient_id=xxx&karte_id=yyy&p=5')"
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            link_btn = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'a[onclick*="copyLinkOfKarte"]')
                )
            )
            onclick_attr = link_btn.get_attribute("onclick")
            if onclick_attr:
                # onclick="copyLinkOfKarte('https://...')" からURL部分を抽出
                start = onclick_attr.find("http")
                if start >= 0:
                    # 閉じクォートを探す（シングルまたはダブル）
                    end = onclick_attr.find("'", start)
                    if end < 0:
                        end = onclick_attr.find('"', start)
                    if end > start:
                        extracted_url = onclick_attr[start:end]
                        if "karte_id" in extracted_url:
                            logger.info(f"✅ カルテURL取得成功（DOM属性）: {extracted_url}")
                            return extracted_url
                        else:
                            logger.warning(f"⚠️ DOM属性のURLにkarte_idがありません: {extracted_url}")
        except Exception as e:
            logger.debug(f"DOM要素からの取得失敗（フォールバックへ）: {e}")

        # === 優先度3: karte_id なし → 空文字を返す ===
        # karte_idがないURLをGASに送ると誤通知になるため、空で返す
        logger.warning(f"⚠️ karte_id付きURL取得失敗（現在URL: {current_url}）")
        return ""

    except Exception as e:
        logger.error(f"カルテURL取得エラー: {e}")
        return ""


def extract_karte_url_with_retry(driver, max_attempts: int = 3, interval_sec: int = 3) -> str:
    """
    v2.0.4: リトライ付きカルテURL取得。

    extract_karte_url() を最大 max_attempts 回試行する。
    1回目の失敗後、interval_sec 秒待ってから再試行。
    各回で current_url + DOM の両方をチェックする。

    Args:
        driver: Selenium WebDriver インスタンス
        max_attempts: 最大試行回数（デフォルト3）
        interval_sec: 試行間の待機秒数（デフォルト3）

    Returns:
        str: karte_id 付きカルテURL。全試行失敗時は空文字列。
    """
    import time

    for attempt in range(1, max_attempts + 1):
        url = extract_karte_url(driver)
        if url and "karte_id" in url:
            if attempt > 1:
                logger.info(f"✅ リトライ成功（{attempt}/{max_attempts}回目）")
            return url

        if attempt < max_attempts:
            logger.warning(
                f"⚠️ カルテURL取得 試行 {attempt}/{max_attempts} 失敗 — "
                f"{interval_sec}秒後にリトライします"
            )
            time.sleep(interval_sec)
        else:
            logger.error(
                f"❌ カルテURL取得 全{max_attempts}回失敗 — "
                f"karte_id付きURLを取得できませんでした"
            )

    return ""
