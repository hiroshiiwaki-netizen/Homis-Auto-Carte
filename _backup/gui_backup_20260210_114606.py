# -*- coding: utf-8 -*-
"""
Homis自動カルテ生成 - GUI
=========================
フォルダ監視の起動/停止、ステータス表示、ログ表示
タスクトレイ機能対応

v1.1.0 - タスクトレイ対応 (2026/01/26)
"""

import os
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
        self.dialog.geometry("500x350")
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
        
        # 注意事項
        note_frame = ttk.LabelFrame(main_frame, text="注意", padding="5")
        note_frame.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=10)
        ttk.Label(
            note_frame,
            text="※ Homisの認証情報（homis_user, homis_password）はconfig.jsonで設定してください。",
            font=("メイリオ", 8),
            foreground="gray"
        ).pack()
        
        # ボタン
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=3, pady=10)
        ttk.Button(button_frame, text="保存", command=self._save, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="キャンセル", command=self._cancel, width=10).pack(side=tk.LEFT, padx=5)
    
    def _browse_watch_folder(self):
        """監視フォルダを選択"""
        folder = filedialog.askdirectory(title="監視フォルダを選択")
        if folder:
            self.watch_folder_var.set(folder)
    
    def _save(self):
        """設定を保存"""
        self.config["watch_folder"] = self.watch_folder_var.get()
        self.config["test_mode"] = self.test_mode_var.get()
        self.config["test_patient_id"] = self.test_patient_id_var.get()
        self.config["poll_interval_seconds"] = self.poll_interval_var.get()
        self.config["gas_web_app_url"] = self.gas_url_var.get()
        
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
        self.root.title("Homis自動カルテ生成 v1.1")
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
        
        # UI構築
        self._build_ui()
        
        # ステータスを初期化
        self._update_status()
        
        # 終了確認ダイアログを設定
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # 最小化時にタスクトレイに格納
        self.root.bind("<Unmap>", self._on_minimize)
    
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
        
        # 別スレッドで監視開始
        self.watcher = FolderWatcher(self.config)
        self.watcher_thread = threading.Thread(target=self._run_watcher, daemon=True)
        self.watcher_thread.start()
    
    def _run_watcher(self):
        """フォルダ監視を実行（別スレッド）"""
        try:
            import time
            while self.is_running:
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
                
                # 待機
                time.sleep(self.watcher.poll_interval)
                
        except Exception as e:
            self._add_log(f"エラー: {e}", "ERROR")
            self.is_running = False
            self._update_status()
    
    def _stop_watcher(self):
        """フォルダ監視を停止"""
        self.is_running = False
        if self.watcher:
            self.watcher.stop()
        
        self._update_status()
        self._add_log("フォルダ監視を停止しました", "WARNING")


def main():
    """メイン関数"""
    root = tk.Tk()
    app = HomisCardGeneratorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
