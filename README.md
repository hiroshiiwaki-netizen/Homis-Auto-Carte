# Homis自動カルテ生成 (Homis-Auto-Chart)

> [!IMPORTANT]
> **GitHubリポジトリ**: [Link](https://github.com/hiroshiiwaki-netizen/Homis-Auto-Chart)  
> **開発標準**: [DEVELOPMENT_STANDARDS.md](../docs/DEVELOPMENT_STANDARDS.md) 準拠  
> **バージョン管理**: セマンティックバージョニング (`MAJOR.MINOR.PATCH`)
> **バージョン**: v1.3.0 | **最終更新**: 2026/02/10

レントゲンナビと連携し、撮影完了時にHomisカルテを自動登録するツール。

## 🔄 処理フロー

1. **GAS** (レントゲンナビ) が撮影完了時にJSONファイルを生成
2. **Python** (watcher.py) がフォルダを監視、JSONを検知
3. **Selenium** でHomisにログイン、カルテを自動登録
4. **GAS API** に登録結果（カルテURL）を送信
5. **GAS** がスプレッドシートのAE列を更新

---

## 📁 ファイル構成

### 使用するファイル（重要）
| ファイル | 説明 |
|---|---|
| `gui.py` | **メイン（推奨）** - GUI画面＋タスクトレイ常駐＋自動起動 |
| `watcher.py` | フォルダ監視（二重検知防止対応） |
| `template_engine.py` | テンプレートエンジン |
| `chat_notifier.py` | **NEW** Google Chat通知 |
| `config.json` | 設定ファイル |
| `start_gui.vbs` | **NEW** コンソール非表示で起動 |
| `setup_scheduler.bat` | **NEW** タスクスケジューラ登録 |

### 補助ファイル（自動で呼ばれる）
| ファイル | 説明 |
|---|---|
| `browser_actions.py` | ブラウザ操作 |
| `homis_writer.py` | Homisカルテ書き込み（日付入力対応） |
| `gas_api.py` | GAS連携（カルテURL送信） |
| `templates/xray_karte.yaml` | レントゲンカルテテンプレート |

---

## 🚀 使い方

### 初回セットアップ
1. `install_deps.bat` をダブルクリック
2. `setup_scheduler.bat` を管理者として実行（毎朝8:00自動起動）

### 通常運用（自動）
- 毎朝8:00にタスクスケジューラが `start_gui.vbs` を自動起動
- 15秒の同期待ち後、タスクトレイに常駐して監視開始
- 22:00に自動終了
- Google Chatに起動・終了・エラー通知

### 手動起動
1. `start_gui.vbs` をダブルクリック（コマンド画面なし）
2. タスクトレイに自動格納、監視自動開始
3. トレイアイコン右クリック →「表示」でログ画面

---

## ⚙️ 設定（config.json）

| 項目 | 説明 | 本番値 |
|------|------|--------|
| `watch_folder` | 監視フォルダ | `G:/共有ドライブ/.../Homis登録データ` |
| `gas_web_app_url` | GAS Web AppのURL | 設定済み |
| `test_mode` | テストモード | `false` |
| `auto_start` | 自動起動 | `true` |
| `schedule.auto_shutdown` | 自動終了 | `true` |
| `schedule.shutdown_time` | 終了時刻 | `22:00` |
| `chat_webhook_url` | Google Chat通知 | 設定済み |
| `headless` | ブラウザ非表示 | `false` |

---

## 🔗 GAS連携

### リクエスト形式
```json
POST {gas_web_app_url}
{
    "action": "updateHomisLink",
    "orderId": "R-202601271710-218",
    "homisUrl": "https://homis.jp/..."
}
```

### レスポンス
```json
{"success": true, "message": "更新完了"}
```

---

## 📝 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|----------|
| v1.3.0 | 2026/02/10 | 自動起動、トレイ格納、Google Chat通知、自動終了、日付入力修正、二重検知防止、VBS起動 |
| v1.2.0 | 2026/02/04 | 集団検診グループ追跡・一括通知 |
| v1.0.0 | 2026/01/27 | GAS連携追加、テストモード対応 |
| v0.9.0 | 2026/01/26 | 初版リリース |
