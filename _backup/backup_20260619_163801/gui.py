# -*- coding: utf-8 -*-
"""
Homis自動カルテ生成 - GUI
=========================
フォルダ監視の起動/停止、ステータス表示、ログ表示
タスクトレイ機能対応

v1.1.0 - タスクトレイ対応 (2026/01/26)
v1.3.0 - 自動起動・自動終了・Google Chat通知 (2026/02/10)
v1.4.0 - ヘッドレスモード設定・共有ドライブ配置 (2026/02/16)
v1.5.0 - カルテ保存「中断」→「完了」に変更 (homis_writer.py変更) (2026/02/24)
v1.6.0 - 24時間稼働: 日次リスタート(0:00)・ハートビートWatchdog・エラー自動復帰 (2026/06/19)
v2.0.0 - リスタートループ修正・単一インスタンスロック・起動時ハートビート (2026/06/19)
v2.0.1 - リスタート永続化+5分ウィンドウ・PIDロック解放修正 (2026/06/19)

※バージョン更新ルール:
  - GUIや設定の変更時: 下記 self.root.title() のバージョンも必ず更新すること
  - サーバー側（homis_writer.py等）のみの変更時: GUIバージョンはそのままでOK
  - HANDOVER.md も必ず同時に更新すること
"""

import os
import logging
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from pathlib import Path
from datetime import datetime

# タスクトレイ用
try:
    import pystray
    from PIL import Image, ImageDraw
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    pystray = None

# watcherモジュールをインポート
from watcher import FolderWatcher, load_config, save_config

# Google Chat通知モジュール
from chat_notifier import notify_startup, notify_shutdown, notify_error

# v1.6.0: ロガー設定
logger = logging.getLogger(__name__)

# ============================================================
# 設定ダイアログ
# ============================================================

class SettingsDialog:
    """設定ダイアログ"""
    
    def __init__(self, parent, config):
        self.result = None
        self.config = config.copy()
        
        # ダイアログウィンドウ
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("設定")
        self.dialog.geometry("500x560")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self._build_ui()
        
        # ウィンドウを中央に配置
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")
    
    def _build_ui(self):
        """UIを構築"""
        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 監視フォルダ
        ttk.Label(main_frame, text="監視フォルダ:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.watch_folder_var = tk.StringVar(value=self.config.get("watch_folder", ""))
        watch_entry = ttk.Entry(main_frame, textvariable=self.watch_folder_var, width=40)
        watch_entry.grid(row=0, column=1, pady=5, padx=5)
        ttk.Button(main_frame, text="参照", command=self._browse_watch_folder, width=8).grid(row=0, column=2, pady=5)
        
        # テストモード
        ttk.Label(main_frame, text="モード:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.test_mode_var = tk.BooleanVar(value=self.config.get("test_mode", True))
        mode_frame = ttk.Frame(main_frame)
        mode_frame.grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Radiobutton(mode_frame, text="🧪 テストモード", variable=self.test_mode_var, value=True).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="🚀 本番モード", variable=self.test_mode_var, value=False).pack(side=tk.LEFT, padx=5)
        
        # テスト患者ID
        ttk.Label(main_frame, text="テスト患者ID:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.test_patient_id_var = tk.StringVar(value=self.config.get("test_patient_id", "2277808"))
        ttk.Entry(main_frame, textvariable=self.test_patient_id_var, width=20).grid(row=2, column=1, sticky=tk.W, pady=5, padx=5)
        
        # ポーリング間隔
        ttk.Label(main_frame, text="ポーリング間隔（秒）:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.poll_interval_var = tk.IntVar(value=self.config.get("poll_interval_seconds", 10))
        ttk.Spinbox(main_frame, from_=5, to=60, textvariable=self.poll_interval_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5, padx=5)
        
        # GAS WebアプリURL
        ttk.Label(main_frame, text="GAS WebアプリURL:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.gas_url_var = tk.StringVar(value=self.config.get("gas_web_app_url", ""))
        ttk.Entry(main_frame, textvariable=self.gas_url_var, width=40).grid(row=4, column=1, pady=5, padx=5)
        
        # ============================================================
        # スケジュール設定エリア
        # ============================================================
        schedule_frame = ttk.LabelFrame(main_frame, text="スケジュール設定", padding="5")
        schedule_frame.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        # 自動起動
        self.auto_start_var = tk.BooleanVar(value=self.config.get("auto_start", True))
        ttk.Checkbutton(schedule_frame, text="起動時にフォルダ監視を自動開始", variable=self.auto_start_var).pack(anchor=tk.W, pady=2)
        
        # v1.6.0: 日次リスタート設定（旧: 自動終了）
        schedule_config = self.config.get("schedule", {})
        restart_frame = ttk.Frame(schedule_frame)
        restart_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(restart_frame, text="🔄 日次リスタート:").pack(side=tk.LEFT)
        
        # v1.6.0: configフォールバック（restart_time優先、なければ 00:00）
        restart_default = schedule_config.get("restart_time", "00:00")
        self.restart_time_var = tk.StringVar(value=restart_default)
        ttk.Entry(restart_frame, textvariable=self.restart_time_var, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Label(restart_frame, text="（HH:MM形式・デフォルト00:00）", font=("メイリオ", 7), foreground="gray").pack(side=tk.LEFT)
        
        # ============================================================
        # ブラウザ設定エリア
        # ============================================================
        browser_frame = ttk.LabelFrame(main_frame, text="ブラウザ設定", padding="5")
        browser_frame.grid(row=6, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        self.headless_var = tk.BooleanVar(value=self.config.get("headless", False))
        ttk.Checkbutton(browser_frame, text="ブラウザを非表示で実行する（ヘッドレスモード）", variable=self.headless_var).pack(anchor=tk.W, pady=2)
        ttk.Label(browser_frame, text="※ ONにするとブラウザ画面が表示されずにバックグラウンドで処理します", font=("メイリオ", 7), foreground="gray").pack(anchor=tk.W)
        
        # ============================================================
        # 通知設定エリア
        # ============================================================
        notify_frame = ttk.LabelFrame(main_frame, text="Google Chat通知", padding="5")
        notify_frame.grid(row=7, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        ttk.Label(notify_frame, text="Webhook URL:").pack(anchor=tk.W)
        self.chat_webhook_var = tk.StringVar(value=self.config.get("chat_webhook_url", ""))
        ttk.Entry(notify_frame, textvariable=self.chat_webhook_var, width=55).pack(fill=tk.X, pady=2)
        ttk.Label(notify_frame, text="※ 空欄の場合は通知しません", font=("メイリオ", 7), foreground="gray").pack(anchor=tk.W)
        
        # 注意事項
        note_frame = ttk.LabelFrame(main_frame, text="注意", padding="5")
        note_frame.grid(row=8, column=0, columnspan=3, sticky=tk.EW, pady=5)
        ttk.Label(
            note_frame,
            text="※ Homisの認証情報（homis_user, homis_password）はconfig.jsonで設定してください。",
            font=("メイリオ", 8),
            foreground="gray"
        ).pack()
        
        # ボタン
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=9, column=0, columnspan=3, pady=10)
        ttk.Button(button_frame, text="保存", command=self._save, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="キャンセル", command=self._cancel, width=10).pack(side=tk.LEFT, padx=5)
    
    def _browse_watch_folder(self):
        """監視フォルダを選択"""
        folder = filedialog.askdirectory(title="監視フォルダを選択")
        if folder:
            self.watch_folder_var.set(folder)
    
    def _save(self):
        """設定を保存"""
        # v1.6.0: リスタート時刻のバリデーション
        restart_time = self.restart_time_var.get()
        try:
            datetime.strptime(restart_time, "%H:%M")
        except ValueError:
            messagebox.showerror("入力エラー", "リスタート時刻はHH:MM形式で入力してください（例: 00:00）")
            return
        
        self.config["watch_folder"] = self.watch_folder_var.get()
        self.config["test_mode"] = self.test_mode_var.get()
        self.config["test_patient_id"] = self.test_patient_id_var.get()
        self.config["poll_interval_seconds"] = self.poll_interval_var.get()
        self.config["gas_web_app_url"] = self.gas_url_var.get()
        self.config["auto_start"] = self.auto_start_var.get()
        self.config["schedule"] = {
            "restart_time": restart_time,
        }
        # v2.0.0: 旧キーを明示削除（configをクリーンに保つ）
        self.config["schedule"].pop("auto_shutdown", None)
        self.config["schedule"].pop("shutdown_time", None)
        self.config["chat_webhook_url"] = self.chat_webhook_var.get()
        self.config["headless"] = self.headless_var.get()
        
        self.result = self.config
        self.dialog.destroy()
    
    def _cancel(self):
        """キャンセル"""
        self.result = None
        self.dialog.destroy()
    
    def show(self):
        """ダイアログを表示して結果を返す"""
        self.dialog.wait_window()
        return self.result


# ============================================================
# GUIアプリケーション
# ============================================================

class HomisCardGeneratorGUI:
    """Homis自動カルテ生成 GUI"""
    
    # おひさまデザインガイド カラーパレット
    OHISAMA_ORANGE = "#ff5100"
    GREEN = "#6abf4b"
    RED = "#d64123"
    GRAY = "#a7a8a9"
    
    def __init__(self, root):
        self.root = root
        self.root.title("Homis自動カルテ生成 v2.0.1")  # GUI変更時は必ずここも更新すること！
        self.root.geometry("450x350")
        
        # 設定読み込み
        self.config = load_config()
        
        # フォルダ監視スレッド
        self.watcher = None
        self.watcher_thread = None
        self.is_running = False
        
        # タスクトレイ関連
        self.tray_icon = None
        self.is_hidden = False
        
        # v1.6.0: スケジュールタイマーID（リスタート用）
        self._shutdown_timer_id = None
        
        # v1.6.0: ハートビート用タイマーID
        self._heartbeat_timer_id = None
        
        # v1.6.0: エラー自動復帰のリトライカウンター
        self._error_retry_count = 0
        self._max_error_retries = 3
        
        # v2.0.1: 日次リスタートガード（ファイル永続化）
        self._last_restart_date = self._load_last_restart_date()
        
        # UI構築
        self._build_ui()
        
        # ステータスを初期化
        self._update_status()
        
        # 終了確認ダイアログを設定
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # 最小化時にタスクトレイに格納
        self.root.bind("<Unmap>", self._on_minimize)
        
        # 起動時にタスクトレイに格納（ウィンドウを非表示にする）
        if PYSTRAY_AVAILABLE:
            self.root.after(300, self._hide_to_tray)
        
        # 起動時の自動開始チェック（タスクトレイ格納後に実行）
        self.root.after(800, self._auto_start_check)
        
        # v2.0.0: 起動直後にハートビートを書く（Watchdogが「死んだ」と誤判定しないよう）
        self._write_heartbeat("starting")
    
    def _auto_start_check(self):
        """起動時に設定をチェックして自動的にフォルダ監視を開始"""
        if not self.config.get("auto_start", False):
            self._add_log("自動起動: 無効（手動で開始してください）")
            return
        
        # 監視フォルダの存在チェック（Google Drive同期待ち対応）
        watch_folder = self.config.get("watch_folder", "")
        if watch_folder and not Path(watch_folder).exists():
            self._add_log("⏳ 監視フォルダの同期を待機中...(Google Drive)")
            # リトライ処理を開始（5秒間隔×6回 = 最大30秒）
            self._retry_auto_start(watch_folder, retry_count=0, max_retries=6)
            return
        
        # フォルダがすでに存在する場合は即座にバリデーション→開始
        self._do_auto_start()
    
    def _retry_auto_start(self, watch_folder: str, retry_count: int, max_retries: int):
        """Google Drive同期待ちリトライ"""
        if Path(watch_folder).exists():
            self._add_log(f"✅ 監視フォルダを確認しました（{retry_count * 5}秒後）", "SUCCESS")
            self._do_auto_start()
            return
        
        if retry_count >= max_retries:
            self._add_log(f"⚠️ 監視フォルダが{max_retries * 5}秒経っても見つかりません", "WARNING")
            self._add_log(f"  フォルダ: {watch_folder}", "WARNING")
            self._add_log("手動で開始してください")
            return
        
        self._add_log(f"⏳ 待機中... ({(retry_count + 1) * 5}秒/{max_retries * 5}秒)")
        # 5秒後にリトライ
        self.root.after(5000, self._retry_auto_start, watch_folder, retry_count + 1, max_retries)
    
    def _do_auto_start(self):
        """バリデーション後に自動開始を実行"""
        # 設定のバリデーション
        errors = self._validate_config()
        if errors:
            self._add_log("⚠️ 設定に問題があるため自動起動できません:", "WARNING")
            for err in errors:
                self._add_log(f"  ❌ {err}", "ERROR")
            self._add_log("設定を修正して手動で開始してください")
            return
        
        # 設定OK → 自動開始
        self._add_log("✅ 設定確認OK → 自動的にフォルダ監視を開始します", "SUCCESS")
        self._start_watcher()
    
    def _validate_config(self) -> list:
        """設定ファイルのバリデーション（エラーのリストを返す。空ならOK）"""
        errors = []
        
        # 監視フォルダ
        watch_folder = self.config.get("watch_folder", "")
        if not watch_folder:
            errors.append("監視フォルダが未設定です")
        elif not Path(watch_folder).exists():
            errors.append(f"監視フォルダが存在しません: {watch_folder}")
        
        # 認証情報
        if not self.config.get("homis_user"):
            errors.append("Homisユーザー名が未設定です")
        if not self.config.get("homis_password"):
            errors.append("Homisパスワードが未設定です")
        
        return errors
    
    def _create_tray_icon(self):
        """タスクトレイアイコンを作成"""
        # icon.pngが存在すればそれを使用
        icon_path = Path(__file__).parent / "icon.png"
        if icon_path.exists():
            try:
                image = Image.open(icon_path)
                # 64x64にリサイズ
                image = image.resize((64, 64), Image.LANCZOS)
                return image
            except Exception:
                pass
        
        # フォールバック: 動的に作成（おひさまオレンジの円）
        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # おひさまオレンジの丸
        draw.ellipse([4, 4, size-4, size-4], fill="#ff5100")
        
        # 中央に「H」
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 32)
        except:
            font = ImageFont.load_default()
        
        draw.text((size//2, size//2), "H", fill="white", anchor="mm", font=font)
        
        return image
    
    def _on_minimize(self, event):
        """最小化時にタスクトレイに格納"""
        if not PYSTRAY_AVAILABLE:
            return
        
        # 最小化イベントのみ処理
        if self.root.state() == 'iconic':
            self._hide_to_tray()
    
    def _hide_to_tray(self):
        """ウィンドウを隠してタスクトレイに格納"""
        if not PYSTRAY_AVAILABLE:
            return
        
        if self.tray_icon is None:
            # メニュー作成
            menu = pystray.Menu(
                pystray.MenuItem("開く", self._show_from_tray, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("開始", self._tray_start, enabled=lambda item: not self.is_running),
                pystray.MenuItem("停止", self._tray_stop, enabled=lambda item: self.is_running),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("終了", self._tray_quit)
            )
            
            # アイコン作成
            self.tray_icon = pystray.Icon(
                "Homis自動カルテ",
                self._create_tray_icon(),
                "Homis自動カルテ生成",
                menu
            )
            
            # 別スレッドでトレイアイコンを実行
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        
        self.root.withdraw()
        self.is_hidden = True
    
    def _show_from_tray(self, icon=None, item=None):
        """タスクトレイからウィンドウを表示"""
        self.root.after(0, self._restore_window)
    
    def _restore_window(self):
        """ウィンドウを復元"""
        self.root.deiconify()
        self.root.state('normal')
        self.root.lift()
        self.root.focus_force()
        self.is_hidden = False
    
    def _tray_start(self, icon=None, item=None):
        """タスクトレイから監視開始"""
        self.root.after(0, self._start_watcher)
    
    def _tray_stop(self, icon=None, item=None):
        """タスクトレイから監視停止"""
        self.root.after(0, self._stop_watcher)
    
    def _tray_quit(self, icon=None, item=None):
        """タスクトレイから終了"""
        if self.tray_icon:
            self.tray_icon.stop()
        self.is_running = False
        if self.watcher:
            self.watcher.stop()
        self.root.after(0, self.root.destroy)
    
    def _on_closing(self):
        """ウィンドウを閉じる時の処理"""
        if self.is_running:
            result = messagebox.askyesno(
                "確認",
                "監視が実行中です。\n終了しますか？",
                icon='warning'
            )
            if result:
                self._cleanup_and_quit()
        else:
            result = messagebox.askyesno(
                "確認",
                "終了しますか？"
            )
            if result:
                self._cleanup_and_quit()
    
    def _cleanup_and_quit(self):
        """リソースを解放して終了"""
        self.is_running = False
        if self.watcher:
            self.watcher.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        # スケジュールタイマーをキャンセル
        if self._shutdown_timer_id:
            self.root.after_cancel(self._shutdown_timer_id)
        self.root.destroy()
    
    def _build_ui(self):
        """UIを構築"""
        # ============================================================
        # タイトルエリア
        # ============================================================
        title_frame = ttk.Frame(self.root, padding="8")
        title_frame.pack(fill=tk.X)
        
        # タイトル（おひさまオレンジ）
        title_label = tk.Label(
            title_frame,
            text="Homis自動カルテ生成",
            font=("メイリオ", 11, "bold"),
            foreground=self.OHISAMA_ORANGE
        )
        title_label.pack(side=tk.LEFT)
        
        # 設定ボタン
        ttk.Button(
            title_frame,
            text="⚙ 設定",
            command=self._open_settings,
            width=7
        ).pack(side=tk.RIGHT, padx=5)
        
        # モード表示
        mode = "🧪 テスト" if self.config.get("test_mode", True) else "🚀 本番"
        mode_color = "blue" if self.config.get("test_mode", True) else self.GREEN
        self.mode_label = tk.Label(
            title_frame,
            text=mode,
            font=("メイリオ", 9),
            foreground=mode_color
        )
        self.mode_label.pack(side=tk.RIGHT, padx=8)
        
        # ============================================================
        # 設定エリア（コンパクト）
        # ============================================================
        config_frame = ttk.LabelFrame(self.root, text="設定", padding="3")
        config_frame.pack(fill=tk.X, padx=8, pady=3)
        
        # 監視フォルダ（短縮表示）
        watch_folder = self.config.get("watch_folder", "未設定")
        if len(watch_folder) > 40:
            watch_folder = "..." + watch_folder[-37:]
        self.watch_folder_label = ttk.Label(config_frame, text=f"監視: {watch_folder}", font=("メイリオ", 7))
        self.watch_folder_label.pack(anchor=tk.W)
        
        # スケジュール表示
        schedule = self.config.get("schedule", {})
        restart_time = schedule.get("restart_time", "00:00")
        schedule_text = f"🔄 日次リスタート: {restart_time}"
        self.schedule_label = ttk.Label(config_frame, text=schedule_text, font=("メイリオ", 7))
        self.schedule_label.pack(anchor=tk.W)
        
        # ============================================================
        # コントロールエリア
        # ============================================================
        control_frame = ttk.Frame(self.root, padding="8")
        control_frame.pack(fill=tk.X)
        
        # 開始ボタン
        self.start_button = ttk.Button(
            control_frame,
            text="▶ 開始",
            command=self._start_watcher,
            width=10
        )
        self.start_button.pack(side=tk.LEFT, padx=3)
        
        # 停止ボタン
        self.stop_button = ttk.Button(
            control_frame,
            text="⏸ 停止",
            command=self._stop_watcher,
            state=tk.DISABLED,
            width=10
        )
        self.stop_button.pack(side=tk.LEFT, padx=3)
        
        # ステータス
        self.status_label = ttk.Label(
            control_frame,
            text="停止中",
            font=("メイリオ", 8),
            foreground=self.GRAY
        )
        self.status_label.pack(side=tk.LEFT, padx=10)
        
        # ============================================================
        # ログエリア（メイン）
        # ============================================================
        log_frame = ttk.LabelFrame(self.root, text="ログ", padding="3")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=3)
        
        # ログテキストエリア
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            width=50,
            height=10,
            font=("Consolas", 7)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # ログクリアボタン
        clear_button = ttk.Button(
            log_frame,
            text="クリア",
            command=self._clear_log,
            width=7
        )
        clear_button.pack(anchor=tk.E, pady=2)
        
        # ============================================================
        # フッター
        # ============================================================
        footer_frame = ttk.Frame(self.root, padding="2")
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        ttk.Label(
            footer_frame,
            text="© 2026 おひさま会",
            font=("メイリオ", 6),
            foreground=self.GRAY
        ).pack()
    
    def _open_settings(self):
        """設定ダイアログを開く"""
        if self.is_running:
            messagebox.showwarning("警告", "監視中は設定を変更できません。\n監視を停止してから設定を変更してください。")
            return
        
        dialog = SettingsDialog(self.root, self.config)
        result = dialog.show()
        
        if result:
            # 設定を保存
            if save_config(result):
                self.config = result
                messagebox.showinfo("保存完了", "設定を保存しました。")
                
                # UIを再読み込み
                self._reload_ui()
            else:
                messagebox.showerror("エラー", "設定の保存に失敗しました。")
    
    def _reload_ui(self):
        """UIを再読み込み"""
        # モード表示を更新
        mode = "🧪 テスト" if self.config.get("test_mode", True) else "🚀 本番"
        mode_color = "blue" if self.config.get("test_mode", True) else self.GREEN
        self.mode_label.config(
            text=mode,
            foreground=mode_color
        )
        
        # 監視フォルダ表示を更新
        watch_folder = self.config.get("watch_folder", "未設定")
        if len(watch_folder) > 40:
            watch_folder = "..." + watch_folder[-37:]
        self.watch_folder_label.config(text=f"監視: {watch_folder}")
        
        # スケジュール表示を更新
        schedule = self.config.get("schedule", {})
        restart_time = schedule.get("restart_time", "00:00")
        schedule_text = f"🔄 日次リスタート: {restart_time}"
        self.schedule_label.config(text=schedule_text)
        
        self._add_log("設定を更新しました", "SUCCESS")
    
    def _add_log(self, message: str, level: str = "INFO"):
        """ログを追加"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 色分け
        if level == "ERROR":
            tag = "error"
            color = "red"
        elif level == "WARNING":
            tag = "warning"
            color = "orange"
        elif level == "SUCCESS":
            tag = "success"
            color = "green"
        else:
            tag = "info"
            color = "black"
        
        # ログに追加
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
        self.log_text.tag_config(tag, foreground=color)
        self.log_text.see(tk.END)
    
    def _clear_log(self):
        """ログをクリア"""
        self.log_text.delete(1.0, tk.END)
        self._add_log("ログをクリアしました")
    
    def _update_status(self):
        """ステータスを更新"""
        if self.is_running:
            self.status_label.config(text="監視中...", foreground=self.GREEN)
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
        else:
            self.status_label.config(text="停止中", foreground=self.GRAY)
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
    
    def _start_watcher(self):
        """フォルダ監視を開始"""
        # 設定確認
        watch_folder = self.config.get("watch_folder", "")
        if not watch_folder:
            messagebox.showerror(
                "設定エラー",
                "監視フォルダが設定されていません。\nconfig.jsonを確認してください。"
            )
            return
        
        if not Path(watch_folder).exists():
            messagebox.showerror(
                "フォルダエラー",
                f"監視フォルダが存在しません:\n{watch_folder}"
            )
            return
        
        # 認証情報確認
        if not self.config.get("homis_user") or not self.config.get("homis_password"):
            messagebox.showerror(
                "設定エラー",
                "Homisの認証情報が設定されていません。\nconfig.jsonに homis_user, homis_password を設定してください。"
            )
            return
        
        # 監視開始
        self.is_running = True
        self._update_status()
        
        mode = "テストモード" if self.config.get("test_mode", True) else "本番モード"
        self._add_log(f"フォルダ監視を開始しました（{mode}）", "SUCCESS")
        self._add_log(f"監視フォルダ: {watch_folder}")
        
        # Google Chat起動通知（別スレッドで送信して画面をブロックしない）
        webhook_url = self.config.get("chat_webhook_url", "")
        if webhook_url:
            threading.Thread(
                target=self._send_startup_notification,
                args=(webhook_url,),
                daemon=True
            ).start()
        
        # スケジュール自動終了タイマーを開始
        self._start_shutdown_timer()
        
        # 別スレッドで監視開始
        self.watcher = FolderWatcher(self.config)
        self.watcher_thread = threading.Thread(target=self._run_watcher, daemon=True)
        self.watcher_thread.start()
    
    def _send_startup_notification(self, webhook_url: str):
        """起動通知を送信（別スレッドから呼ぶ）"""
        try:
            result = notify_startup(webhook_url, self.config)
            if result:
                self.root.after(0, lambda: self._add_log("📤 Google Chat起動通知を送信しました", "SUCCESS"))
            else:
                self.root.after(0, lambda: self._add_log("⚠️ Google Chat通知の送信に失敗しました", "WARNING"))
        except Exception as e:
            self.root.after(0, lambda: self._add_log(f"⚠️ Chat通知エラー: {e}", "WARNING"))
    
    def _start_shutdown_timer(self):
        """v1.6.0: 日次リスタートタイマーを開始（旧: 自動終了タイマー）"""
        schedule = self.config.get("schedule", {})
        
        # v1.6.0: configフォールバック
        # 新キー restart_time を優先、なければ "00:00"（24時間稼働デフォルト）
        restart_time_str = schedule.get("restart_time", "00:00")
        
        # 旧キー auto_shutdown が残っている場合、警告を1回だけ出す
        if "shutdown_time" in schedule and "restart_time" not in schedule:
            old_time = schedule.get("shutdown_time", "22:00")
            self._add_log(
                f"⚠️ 旧設定 shutdown_time: {old_time} を検出。"
                f"v1.6.0以降は restart_time を使用してください。"
                f"デフォルト 00:00 で日次リスタートします。",
                "WARNING"
            )
        
        self._add_log(f"🔄 日次リスタートタイマー設定: {restart_time_str}")
        
        # 1分ごとに時刻をチェック
        self._check_restart_time(restart_time_str)
        
        # v1.6.0: ハートビート書き込み開始
        self._start_heartbeat()
    
    def _check_restart_time(self, restart_time_str: str):
        """v2.0.1: 現在時刻とリスタート時刻を比較（永続化+5分ウィンドウ）"""
        if not self.is_running:
            return
        
        try:
            now = datetime.now()
            restart_time = datetime.strptime(restart_time_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            
            # v2.0.1: ファイル永続化でプロセス再起動後も同日リスタートをブロック
            if self._last_restart_date == now.date():
                # 今日はもうリスタート済み → 翌日までスキップ
                pass
            elif now >= restart_time:
                # v2.0.1: 5分ウィンドウ — 8:00起動で即リスタートしない
                elapsed = (now - restart_time).total_seconds()
                if elapsed < 300:  # 5分以内のみ発火
                    self._last_restart_date = now.date()
                    self._save_last_restart_date(now.date())
                    self._add_log(f"🔄 日次リスタート時刻（{restart_time_str}）になりました", "WARNING")
                    self._scheduled_restart()
                    return
        except ValueError:
            self._add_log(f"⚠️ リスタート時刻の形式が不正: {restart_time_str}", "ERROR")
            return
        
        # 60秒後に再チェック
        self._shutdown_timer_id = self.root.after(60000, self._check_restart_time, restart_time_str)
    
    def _get_restart_date_path(self):
        """v2.0.1: last_restart.txt のパスを返す"""
        if os.path.exists("C:\\HomisKarteWriter"):
            return Path("C:\\HomisKarteWriter\\last_restart.txt")
        return Path(os.path.dirname(os.path.abspath(__file__))) / "last_restart.txt"
    
    def _load_last_restart_date(self):
        """v2.0.1: ファイルから最終リスタート日を読み込む"""
        try:
            path = self._get_restart_date_path()
            if path.exists():
                date_str = path.read_text().strip()
                from datetime import date
                return datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            pass
        return None
    
    def _save_last_restart_date(self, d):
        """v2.0.1: 最終リスタート日をファイルに保存"""
        try:
            path = self._get_restart_date_path()
            path.write_text(str(d))
        except Exception as e:
            logger.warning(f"リスタート日保存失敗: {e}")
    
    def _start_heartbeat(self):
        """v1.6.0: ハートビートファイルを60秒ごとに更新（Watchdog用）"""
        self._write_heartbeat("running")
        # 60秒後に再度書き込み
        self._heartbeat_timer_id = self.root.after(60000, self._heartbeat_tick)
    
    def _heartbeat_tick(self):
        """v1.6.0: ハートビート定期更新"""
        if not self.is_running:
            self._write_heartbeat("stopped")
            return
        self._write_heartbeat("running")
        self._heartbeat_timer_id = self.root.after(60000, self._heartbeat_tick)
    
    def _write_heartbeat(self, status: str):
        """v1.6.0: ハートビートファイルを書き込む"""
        try:
            import json
            heartbeat_path = Path(os.path.dirname(os.path.abspath(__file__))) / "heartbeat.txt"
            # 本番環境ではC:\HomisKarteWriter\heartbeat.txt
            if os.path.exists("C:\\HomisKarteWriter"):
                heartbeat_path = Path("C:\\HomisKarteWriter\\heartbeat.txt")
            with open(heartbeat_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "status": status,
                    "version": "2.0.1",
                    "pid": os.getpid()
                }))
        except Exception as e:
            logger.warning(f"ハートビート書き込み失敗: {e}")
    
    def _scheduled_restart(self):
        """v1.6.0: 日次リスタート（0:00）— Watchdogが再起動してくれる"""
        self._add_log("🔄 日次リスタート処理を開始します...", "WARNING")
        
        # ハートビートに restarting ステータスを書く（Watchdogが2分待つ用）
        self._write_heartbeat("restarting")
        
        # 監視停止
        self.is_running = False
        if self.watcher:
            self.watcher.stop()
        
        # Google Chat通知
        webhook_url = self.config.get("chat_webhook_url", "")
        if webhook_url:
            try:
                notify_shutdown(webhook_url, "🔄 日次リスタート（0:00）— Watchdogが再起動します")
                self._add_log("📤 Google Chat日次リスタート通知を送信しました", "SUCCESS")
            except Exception as e:
                self._add_log(f"⚠️ リスタート通知エラー: {e}", "WARNING")
        
        # 3秒後にアプリを終了（Watchdogが再起動する）
        self.root.after(3000, self._cleanup_and_quit)
    
    def _run_watcher(self):
        """フォルダ監視を実行（別スレッド）"""
        import time
        
        while self.is_running:
            try:
                # フォルダをスキャン
                files = self.watcher.scan_folder()
                
                if files:
                    self._add_log(f"新規ファイル検出: {len(files)}件", "INFO")
                    for file in files:
                        success = self.watcher.process_file(file)
                        if success:
                            self._add_log(f"処理成功: {file.name}", "SUCCESS")
                        else:
                            self._add_log(f"処理失敗: {file.name}", "ERROR")
                
                # v7.7.6: 集団検診グループの完了チェック
                self.watcher.check_groups()
                
                # v1.6.0: エラーリトライカウンターをリセット（正常動作中）
                self._error_retry_count = 0
                
                # 待機
                time.sleep(self.watcher.poll_interval)
                
            except Exception as e:
                error_msg = str(e)
                self._error_retry_count += 1
                self._add_log(
                    f"❌ 異常エラー（{self._error_retry_count}/{self._max_error_retries}）: {error_msg}",
                    "ERROR"
                )
                
                # Google Chatにエラー通知
                webhook_url = self.config.get("chat_webhook_url", "")
                if webhook_url:
                    try:
                        notify_error(webhook_url, f"エラー({self._error_retry_count}/{self._max_error_retries}): {error_msg}")
                    except Exception:
                        pass
                
                # v1.6.0: 最大リトライ回数に達したらプロセス終了（Watchdog任せ）
                if self._error_retry_count >= self._max_error_retries:
                    self._add_log(
                        f"💀 {self._max_error_retries}回連続エラー — プロセスを終了します（Watchdogが再起動）",
                        "ERROR"
                    )
                    self.is_running = False
                    self.root.after(0, self._update_status)
                    # ハートビートを error に更新
                    self._write_heartbeat("error_exit")
                    self.root.after(3000, self._cleanup_and_quit)
                    return
                
                # v1.6.0: 30秒待機後にリトライ
                self._add_log(f"⏳ 30秒後に自動復帰します...", "WARNING")
                time.sleep(30)
    
    def _stop_watcher(self):
        """フォルダ監視を停止"""
        self.is_running = False
        if self.watcher:
            self.watcher.stop()
        
        # スケジュールタイマーをキャンセル
        if self._shutdown_timer_id:
            self.root.after_cancel(self._shutdown_timer_id)
            self._shutdown_timer_id = None
        
        self._update_status()
        self._add_log("フォルダ監視を停止しました", "WARNING")


def _acquire_instance_lock():
    """v2.0.1: 単一インスタンスロック（PIDファイル方式）"""
    # 本番環境の場合はC:\HomisKarteWriter\
    if os.path.exists("C:\\HomisKarteWriter"):
        pid_path = Path("C:\\HomisKarteWriter\\homis_writer.pid")
    else:
        pid_path = Path(os.path.dirname(os.path.abspath(__file__))) / "homis_writer.pid"
    
    my_pid = os.getpid()
    
    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text().strip())
            # 古いPIDのプロセスが生きているかチェック
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, old_pid)
            if handle:
                kernel32.CloseHandle(handle)
                # プロセスが生きている → 二重起動
                logger.warning(f"⚠️ 別のインスタンスが稼働中です（PID: {old_pid}）")
                return False
            # プロセスが死んでいる → 古いPIDファイルを削除
        except Exception:
            pass  # PIDファイルが壊れている場合は上書き
    
    # PIDファイルを書き込む
    pid_path.write_text(str(my_pid))
    logger.info(f"インスタンスロック取得（PID: {my_pid}）")
    return True


def _release_instance_lock():
    """v2.0.1: PIDファイルを削除（自 PID と一致するときのみ）"""
    if os.path.exists("C:\\HomisKarteWriter"):
        pid_path = Path("C:\\HomisKarteWriter\\homis_writer.pid")
    else:
        pid_path = Path(os.path.dirname(os.path.abspath(__file__))) / "homis_writer.pid"
    
    try:
        if pid_path.exists():
            # v2.0.1: 自 PID と一致するときのみ削除（他インスタンスのPIDを消さない）
            stored_pid = pid_path.read_text().strip()
            if stored_pid == str(os.getpid()):
                pid_path.unlink()
    except Exception:
        pass


def main():
    """メイン関数"""
    # v2.0.1: 単一インスタンスチェック
    if not _acquire_instance_lock():
        print("別のインスタンスが既に稼働中です。終了します。")
        return
    
    try:
        root = tk.Tk()
        app = HomisCardGeneratorGUI(root)
        root.mainloop()
    finally:
        _release_instance_lock()


if __name__ == "__main__":
    main()
