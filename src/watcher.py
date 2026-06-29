# -*- coding: utf-8 -*-
"""
Homis自動カルテ生成 - フォルダ監視モジュール
============================================
ローカルのGoogleDriveフォルダを監視し、JSONファイルを検知してHomisに登録

【FAX大作戦と同様の仕様】
- ローカルパス指定でGoogleDriveフォルダを監視
- 発見漏れがないようにポーリング方式を併用
- テストモードと本番モードの切り替え

v1.0.0 - 初版 (2026/01/26)
"""

import os
import sys
import json
import time
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

# ============================================================
# バージョン情報
# ============================================================
MODULE_VERSION = "1.0"
MODULE_VERSION_DATE = "2026-01-26"

# ============================================================
# パス設定（paths.py で一元管理）
# ============================================================
from paths import CODE_DIR, STATE_DIR, LOG_DIR, CONFIG_FILE

SRC_DIR = CODE_DIR  # 後方互換

# ============================================================
# ログ設定
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"watcher_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8"
        )
    ]
)
logger = logging.getLogger(__name__)
# 起動時にパス情報をログ出力（どのコードが動いているか追跡用）
logger.info(f"CODE_DIR: {CODE_DIR}")
logger.info(f"STATE_DIR: {STATE_DIR}")
logger.info(f"LOG_DIR: {LOG_DIR}")
logger.info(f"CONFIG_FILE: {CONFIG_FILE}")

# ============================================================
# デフォルト設定
# ============================================================
DEFAULT_CONFIG = {
    # 監視設定
    "watch_folder": "",              # JSONファイル監視フォルダ（GAS出力先）
    "processed_folder": "",          # 処理済みフォルダ（監視フォルダ内にprocessedを作成）
    "poll_interval_seconds": 10,     # ポーリング間隔（秒）
    
    # Homis設定
    "homis_url": "https://homis.jp/homic/",
    "homis_user": "",
    "homis_password": "",
    
    # GAS連携設定
    "gas_web_app_url": "",           # レントゲンナビのWebアプリURL
    
    # モード設定
    "test_mode": True,               # True=テストモード, False=本番モード
    "test_patient_id": "2277808",    # テストモード時のHomis患者ID
    
    # 自動起動・スケジュール設定
    "auto_start": True,              # 起動時に自動でフォルダ監視を開始
    "schedule": {
        "auto_shutdown": True,       # スケジュール自動終了
        "shutdown_time": "22:00",    # 自動終了する時刻（HH:MM）
    },
    
    # Google Chat通知設定
    "chat_webhook_url": "",          # Google Chat Webhook URL
}


def load_config() -> dict:
    """設定ファイルを読み込み"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(saved)
                return config
        except Exception as e:
            logger.error(f"設定ファイル読み込みエラー: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> bool:
    """設定をファイルに保存"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"設定保存エラー: {e}")
        return False


class FolderWatcher:
    """
    フォルダ監視クラス
    FAX大作戦と同様、ポーリング方式で発見漏れを防止
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.watch_folder = Path(config.get("watch_folder", ""))
        self.processed_folder = self._get_processed_folder()
        self.poll_interval = config.get("poll_interval_seconds", 10)
        self.test_mode = config.get("test_mode", True)
        self.processed_files: set = set()  # 処理済みファイルのセット
        self.running = False
        
        # v7.7.6: 集団検診グループ追跡用
        # {groupId: {"count": 処理済数, "expected": 予想数（不明なら-1）, "last_update": 最終更新時刻}}
        self.group_pending: dict = {}
        
        # 起動時点でフォルダにあるファイルを記録（これらは処理しない）
        self._record_existing_files()
    
    def _record_existing_files(self):
        """起動時点で監視フォルダに存在するファイルを確認
        ※v1.3.0: 既存ファイルも処理対象にする（残留ファイルを拾う）
        """
        if self.watch_folder.exists():
            existing = [f for f in self.watch_folder.glob("*.json") if not f.name.startswith(".")]
            if existing:
                logger.info(f"📂 起動時に{len(existing)}件の未処理ファイルを検出 → 処理対象にします")
        
    def _get_processed_folder(self) -> Path:
        """処理済みフォルダを取得（なければ作成）"""
        processed = self.config.get("processed_folder", "")
        if processed:
            folder = Path(processed)
        else:
            folder = self.watch_folder / "済"  # 「済」フォルダに変更
        
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            logger.info(f"処理済みフォルダを作成: {folder}")
        
        return folder
    
    def scan_folder(self) -> List[Path]:
        """
        監視フォルダをスキャンしてJSONファイル一覧を取得
        ※起動後にフォルダに追加されたファイルのみ処理
        """
        if not self.watch_folder.exists():
            logger.warning(f"監視フォルダが存在しません: {self.watch_folder}")
            return []
        
        json_files = []
        for file in self.watch_folder.glob("*.json"):
            if file.name.startswith("."):  # 隠しファイルはスキップ
                continue
            if file.name in self.processed_files:  # 処理済み/起動時存在はスキップ
                continue
            json_files.append(file)
        
        return json_files
    
    def process_file(self, file_path: Path) -> bool:
        """
        JSONファイルを処理
        Returns: True=成功, False=失敗
        """
        logger.info(f"📄 ファイル処理開始: {file_path.name}")
        
        # 即座に処理済みセットに追加（二重検知防止）
        self.processed_files.add(file_path.name)
        
        try:
            # JSONを読み込み
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # アクション確認
            action = data.get("action", "")
            if action != "homis_karte_write":
                logger.warning(f"未対応のアクション: {action}")
                self._move_to_processed(file_path, success=False)
                return False
            
            # v7.7.6: 集団検診かどうかをチェック
            is_group = data.get("isGroup", False)
            group_id = data.get("groupId", "")
            
            # Homis書き込み
            result = self._write_to_homis(data)
            
            # orderIdはdata.data内にある
            karte_data = data.get("data", {})
            order_id = karte_data.get("orderId", "")
            
            # job_idはdata直下にある（往診カルテの場合のみ存在）
            job_id = data.get("job_id", "")

            if result["success"]:
                logger.info(f"✅ 処理成功: {file_path.name}")
                
                # カルテURL
                karte_url = result.get("karte_url", "")
                
                # v2.0.4: 成功 + 空URL → GAS通知スキップ（karte_idなし誤通知を防ぐ）
                # ※ JSONは済へ移動して再処理しない（二重カルテ防止）
                # ※ Chatでエラーアラートを送信（運用向け）
                if not karte_url and order_id and not job_id:
                    patient_name = karte_data.get("patientName", "不明")
                    logger.error(
                        f"⚠️ カルテ作成済み・URL取得失敗: {patient_name} / "
                        f"orderId={order_id} — GAS通知をスキップします"
                    )
                    # 運用向けChatアラート
                    webhook_url = self.config.get("chat_webhook_url", "")
                    if webhook_url:
                        try:
                            from chat_notifier import notify_error
                            notify_error(
                                webhook_url,
                                f"⚠️ カルテ作成済み・URL取得失敗\n"
                                f"👤 {patient_name}\n"
                                f"📋 orderId: {order_id}\n"
                                f"💡 HOMISにカルテは作成されていますが、"
                                f"URLを取得できなかったためChat撮影完了通知は送信されません。\n"
                                f"🔧 SSのAE列を手動確認してください。"
                            )
                        except Exception as e:
                            logger.warning(f"⚠️ エラーChatアラート送信失敗: {e}")
                    
                    # 集団検診の場合はグループ追跡だけ行う（通知はしない）
                    if is_group and group_id:
                        self._track_group(group_id)
                    
                    # 済へ移動（再処理しない）
                    self._move_to_processed(file_path, success=True)
                    return True
                
                # GAS連携（既存：レントゲンナビ向け）
                # ※往診カルテ（job_idあり）はレントゲンナビGASに通知しない
                if order_id and not job_id:
                    if is_group and group_id:
                        # 集団検診の場合：個別通知はスキップ、グループ追跡のみ
                        self._notify_gas(order_id, karte_url)
                        self._track_group(group_id)
                        logger.info(f"📊 集団検診グループ追跡: {group_id}")
                    else:
                        # 通常オーダーの場合：通常通り通知
                        self._notify_gas(order_id, karte_url)
                
                # 往診カルテ用：結果ファイル書き込み（job_idがある場合のみ）
                if job_id:
                    self._write_result_file(job_id, karte_url or "", success=True)
                    # 往診専用チャット通知（成功）
                    karte_data_for_notify = data.get("data", {})
                    self._notify_oushin_chat(
                        success=True,
                        homis_id=karte_data_for_notify.get("homisId", ""),
                        visit_date=karte_data_for_notify.get("visitDate", ""),
                        doctor_name=karte_data_for_notify.get("doctorName", ""),
                        karte_url=karte_url or "",
                        next_visit_date=karte_data_for_notify.get("nextVisitDate", "")
                    )
                
                # 処理済みフォルダに移動
                self._move_to_processed(file_path, success=True)
                return True
            else:
                logger.error(f"❌ 処理失敗: {file_path.name}")
                
                # 失敗時もGAS連携（空のURLで通知）
                # ※往診カルテ（job_idあり）はレントゲンナビGASに通知しない
                if order_id and not job_id:
                    self._notify_gas(order_id, "")
                    if is_group and group_id:
                        self._track_group(group_id)
                
                # 往診カルテ用：失敗も結果ファイルに書き込む
                if job_id:
                    err_msg = result.get("error", "HOMIS操作が失敗しました")
                    self._write_result_file(job_id, "", success=False, error=err_msg)
                    # 往診専用チャット通知（失敗）
                    karte_data_for_notify = data.get("data", {})
                    self._notify_oushin_chat(
                        success=False,
                        homis_id=karte_data_for_notify.get("homisId", ""),
                        visit_date=karte_data_for_notify.get("visitDate", ""),
                        doctor_name=karte_data_for_notify.get("doctorName", ""),
                        error=err_msg
                    )
                
                self._move_to_processed(file_path, success=False)
                return False
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析エラー: {file_path.name} - {e}")
            self._move_to_processed(file_path, success=False)
            return False
        except Exception as e:
            logger.error(f"処理エラー: {file_path.name} - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _track_group(self, group_id: str):
        """v7.7.6: 集団検診グループを追跡"""
        if group_id not in self.group_pending:
            self.group_pending[group_id] = {"count": 0, "last_update": time.time()}
        
        self.group_pending[group_id]["count"] += 1
        self.group_pending[group_id]["last_update"] = time.time()
        logger.info(f"📊 グループ {group_id}: {self.group_pending[group_id]['count']}件処理済み")
    
    def check_groups(self):
        """
        v7.7.6: 集団検診グループの完了チェック
        一定時間（30秒）新しいファイルが来なければ完了とみなして一括通知
        """
        if not self.group_pending:
            return
        
        current_time = time.time()
        complete_groups = []
        
        for group_id, info in self.group_pending.items():
            # v7.7.6修正: 60秒に延長（ファイル生成遅延への対応）
            if current_time - info["last_update"] > 60:
                complete_groups.append(group_id)
        
        for group_id in complete_groups:
            info = self.group_pending.pop(group_id)
            logger.info(f"📣 集団検診一括通知送信: {group_id} ({info['count']}名)")
            self._send_group_notification(group_id)
    
    def _send_group_notification(self, group_id: str):
        """v7.7.6: 集団検診一括通知をGASに送信"""
        gas_url = self.config.get("gas_web_app_url", "")
        if not gas_url:
            logger.info("ℹ️ gas_web_app_url未設定のため一括通知をスキップ")
            return
        
        try:
            from gas_api import send_group_complete_notification
            result = send_group_complete_notification(group_id, gas_url)
            if result.get("success"):
                logger.info(f"🔗 集団検診一括通知成功: {result.get('message')}")
            else:
                logger.warning(f"⚠️ 集団検診一括通知: {result.get('message')}")
        except Exception as e:
            logger.warning(f"⚠️ 集団検診一括通知エラー: {e}")
    
    def _write_to_homis(self, data: dict) -> dict:
        """Homisにカルテを書き込み（テンプレートエンジン対応）"""
        karte_data = data.get("data", {})
        template_name = data.get("template", "")
        
        # テストモード時は患者IDを固定
        if self.test_mode:
            homis_id = self.config.get("test_patient_id", "2277808")
            logger.info(f"🧪 テストモード: 患者ID={homis_id}を使用")
            karte_data["homisId"] = homis_id
        else:
            homis_id = karte_data.get("homisId", "")
        
        if not homis_id:
            logger.error("Homis患者IDが指定されていません")
            return {"success": False, "karte_url": None}
        
        # テンプレート指定がある場合はテンプレートエンジンを使用
        if template_name:
            logger.info(f"📋 テンプレート使用: {template_name}")
            try:
                from template_engine import TemplateEngine
                headless = self.config.get("headless", False)
                engine = TemplateEngine(self.config, headless=headless)
                result = engine.execute(template_name, karte_data)
                return result
            except Exception as e:
                logger.error(f"テンプレートエンジンエラー: {e}")
                import traceback
                traceback.print_exc()
                return {"success": False, "karte_url": None}
        
        # 従来のhomis_writerを使用（後方互換性）
        logger.info("📋 従来方式（homis_writer）を使用")
        from homis_writer import HomisKarteWriter
        
        # Homis設定
        homis_config = {
            "homis_url": self.config.get("homis_url", "https://homis.jp/homic/"),
            "homis_user": self.config.get("homis_user", ""),
            "homis_password": self.config.get("homis_password", "")
        }
        
        # カルテ書き込み
        headless = self.config.get("headless", False)
        writer = HomisKarteWriter(homis_config, headless=headless)
        result = writer.write_karte(homis_id=homis_id, karte_data=karte_data)
        
        return result
    
    def _notify_gas(self, order_id: str, karte_url: str):
        """GASにカルテURLを通知"""
        gas_url = self.config.get("gas_web_app_url", "")
        if not gas_url:
            logger.info("ℹ️ gas_web_app_url未設定のためGAS連携をスキップ")
            return
        
        try:
            from gas_api import notify_karte_url
            result = notify_karte_url(order_id, karte_url, gas_url)
            if result.get("success"):
                logger.info(f"🔗 GAS連携成功: {result.get('message')}")
            else:
                logger.warning(f"⚠️ GAS連携: {result.get('message')}")
        except Exception as e:
            logger.warning(f"⚠️ GAS連携エラー: {e}")
    
    def _write_result_file(self, job_id: str, karte_url: str, success: bool, error: str = ""):
        """
        往診カルテ専用：GASポーリング用の結果ファイルをフォルダに書き込む
        
        ※ config.json に "oushin_result_folder" が設定されている場合のみ動作。
        ※ 既存のレントゲンカルテ処理には一切影響しない（job_idがある場合のみ呼ばれる）。
        
        書き込むファイル: result_{job_id}.json
        書き込む内容: { "success": bool, "karte_url": str, "error": str }
        """
        result_folder = self.config.get("oushin_result_folder", "")
        if not result_folder:
            logger.info("ℹ️ oushin_result_folder未設定のため結果ファイル書き込みをスキップ")
            return
        
        try:
            result_dir = Path(result_folder)
            result_dir.mkdir(parents=True, exist_ok=True)
            
            result_data = {
                "job_id": job_id,
                "success": success,
                "karte_url": karte_url,
                "error": error,
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            
            result_file = result_dir / f"result_{job_id}.json"
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"📝 結果ファイル書き込み完了: {result_file.name} (success={success})")
        except Exception as e:
            logger.error(f"⚠️ 結果ファイル書き込みエラー: {e}")
    
    def _notify_oushin_chat(self, success: bool, homis_id: str = "",
                             visit_date: str = "", doctor_name: str = "",
                             karte_url: str = "", next_visit_date: str = "",
                             error: str = ""):
        """
        往診カルテ専用：Google Chatに完了通知を送る

        ※ config.json に "oushin_chat_webhook_url" が設定されている場合のみ動作。
        ※ 既存のレントゲンカルテ通知（chat_webhook_url）とは別のWebhookを使用。
        """
        webhook_url = self.config.get("oushin_chat_webhook_url", "")
        if not webhook_url:
            logger.info("ℹ️ oushin_chat_webhook_url未設定のためチャット通知をスキップ")
            return

        try:
            import urllib.request
            
            if success:
                next_info = f"\n📅 次回往診日: {next_visit_date}" if next_visit_date else ""
                karte_info = f"\n🔗 カルテURL: {karte_url}" if karte_url else ""
                text = (
                    f"✅ 往診白紙カルテ作成完了\n"
                    f"👨‍⚕️ 担当医: {doctor_name}\n"
                    f"🏥 患者ID（HOMIS）: {homis_id}\n"
                    f"📆 往診日: {visit_date}"
                    f"{next_info}"
                    f"{karte_info}"
                )
            else:
                text = (
                    f"❌ 往診白紙カルテ作成失敗\n"
                    f"👨‍⚕️ 担当医: {doctor_name}\n"
                    f"🏥 患者ID（HOMIS）: {homis_id}\n"
                    f"📆 往診日: {visit_date}\n"
                    f"⚠️ エラー内容: {error}"
                )
            
            payload = json.dumps({"text": text}).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f"💬 往診チャット通知送信完了 (status={resp.status})")

        except Exception as e:
            logger.warning(f"⚠️ 往診チャット通知エラー（続行）: {e}")

    def _move_to_processed(self, file_path: Path, success: bool = True):
        """処理済みフォルダに移動（ファイル名はそのまま）"""
        try:
            # ファイル名はそのままで移動
            dest = self.processed_folder / file_path.name
            
            shutil.move(str(file_path), str(dest))
            self.processed_files.add(file_path.name)
            logger.info(f"📁 済フォルダに移動: {file_path.name}")
        except Exception as e:
            logger.error(f"ファイル移動エラー: {e}")
    
    def start(self):
        """監視を開始"""
        self.running = True
        mode_str = "🧪 テストモード" if self.test_mode else "🚀 本番モード"
        
        print("=" * 60)
        print(f"Homis自動カルテ生成 - フォルダ監視")
        print("=" * 60)
        print(f"モード: {mode_str}")
        print(f"監視フォルダ: {self.watch_folder}")
        print(f"処理済みフォルダ: {self.processed_folder}")
        print(f"ポーリング間隔: {self.poll_interval}秒")
        if self.test_mode:
            print(f"テスト患者ID: {self.config.get('test_patient_id')}")
        print("=" * 60)
        print("監視を開始します... (Ctrl+C で終了)")
        print()
        
        logger.info(f"📡 フォルダ監視開始: {self.watch_folder}")
        logger.info(f"モード: {mode_str}")
        
        try:
            while self.running:
                # フォルダをスキャン
                files = self.scan_folder()
                
                if files:
                    logger.info(f"📬 新規ファイル検出: {len(files)}件")
                    for file in files:
                        self.process_file(file)
                
                # v7.7.6: 集団検診グループの完了チェック
                self.check_groups()
                
                # 待機
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            logger.info("👋 監視を終了します")
            self.running = False
    
    def stop(self):
        """監視を停止"""
        self.running = False


def main():
    """メイン関数"""
    # 設定読み込み
    config = load_config()
    
    # 監視フォルダの確認
    watch_folder = config.get("watch_folder", "")
    if not watch_folder:
        print("❌ 監視フォルダが設定されていません")
        print("   config.jsonの watch_folder を設定してください")
        print()
        print("例:")
        print('   "watch_folder": "T:\\\\マイドライブ\\\\Antigravity-PJ\\\\Homis自動カルテ生成\\\\homis_queue"')
        return
    
    if not Path(watch_folder).exists():
        print(f"❌ 監視フォルダが存在しません: {watch_folder}")
        create = input("フォルダを作成しますか？ (y/n): ")
        if create.lower() == "y":
            Path(watch_folder).mkdir(parents=True, exist_ok=True)
            print(f"✅ フォルダを作成しました: {watch_folder}")
        else:
            return
    
    # 認証情報の確認
    if not config.get("homis_user") or not config.get("homis_password"):
        print("❌ Homisの認証情報が設定されていません")
        print("   config.jsonに homis_user, homis_password を設定してください")
        return
    
    # 監視開始
    watcher = FolderWatcher(config)
    watcher.start()


if __name__ == "__main__":
    main()
