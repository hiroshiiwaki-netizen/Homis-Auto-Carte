# Homis自動カルテ生成 引継ぎ書

> **最終更新**: 2026年2月16日 14:40
> **バージョン**: v1.4.0
> **ステータス**: ✅ 本番デプロイ済み・自動運用中

---

## ✅ 完了済み（2026/02/16）

### v1.4.0 ヘッドレスモード対応・共有ドライブ配置

| 機能 | 内容 |
|------|------|
| ヘッドレス設定GUI | 設定ダイアログに「ブラウザ非表示（ヘッドレスモード）」チェックボックスを追加 |
| 共有ドライブ配置 | 実行ファイル一式を `T:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル` にコピー |

### v1.3.0 自動化対応（2026/02/10）

| 機能 | 内容 |
|------|------|
| 自動起動 | `auto_start: true` で起動時に自動的に監視開始 |
| トレイ格納 | 起動後すぐにタスクトレイに格納（画面は非表示） |
| コマンド画面非表示 | `start_gui.vbs` でpythonwを使い黒い画面を表示しない |
| Google Chat通知 | 起動・エラー・自動終了時に通知 |
| 自動終了 | 22:00に自動シャットダウン |
| タスクスケジューラ | `setup_scheduler.bat` で毎朝8:00に自動起動 |
| 日付入力対応 | カルテの診察日にJSONの撮影日(`shootingDate`)を使用 |
| 二重検知防止 | 同じファイルを2回処理しないようにガード追加 |
| 残留ファイル処理 | 起動時に監視フォルダにあるファイルも処理対象に |
| Google Drive同期待ち | 本番環境で15秒の同期待ち後に起動 |

---

### 共有ドライブ（実行ファイル配布用）

| 項目 | 内容 |
|------|------|
| 配布フォルダ | `T:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル` |
| 内容 | 実行に必要なファイル一式（gui.py, watcher.py 等 + templates/） |
| 用途 | 他PCにセットアップする際のソース配布用 |

### 本番環境

| 項目 | 内容 |
|------|------|
| 本番フォルダ | `C:\HomisKarteWriter` |
| 起動方法 | `start_gui.vbs` ダブルクリック / タスクスケジューラ（毎朝8:00） |
| 監視フォルダ | `G:\共有ドライブ\レントゲンオーダー\Homis登録データ` |
| config.json | `test_mode: false`、`auto_start: true` |
| 自動終了時刻 | 22:00 |

### 開発環境

| 項目 | 内容 |
|------|------|
| 開発フォルダ | `T:\マイドライブ\Antigravity-PJ\Homis自動カルテ生成\src` |
| 監視フォルダ | `G:\共有ドライブ\レントゲンオーダー\Homis登録データ` |
| config.json | `test_mode: true`、`test_patient_id: 2277808` |

---

## 📂 ファイル構成

```
Homis自動カルテ生成/
├── src/
│   ├── gui.py              # GUIメイン（自動起動・トレイ格納・通知）
│   ├── watcher.py          # フォルダ監視（二重検知防止済み）
│   ├── homis_writer.py     # Homis書き込み（日付入力対応）
│   ├── template_engine.py  # テンプレートエンジン
│   ├── browser_actions.py  # ブラウザ操作
│   ├── chat_notifier.py    # Google Chat通知 ✨NEW
│   ├── gas_api.py          # GAS連携
│   ├── config.json         # 設定
│   ├── start_gui.vbs       # 起動スクリプト（コンソール非表示） ✨NEW
│   └── templates/
│       └── xray_karte.yaml # レントゲンカルテテンプレート（日付入力追加）
├── _backup/                # バックアップファイル
└── docs/
```

### 本番環境（C:\HomisKarteWriter）

```
C:\HomisKarteWriter/
├── gui.py, watcher.py, homis_writer.py 等  # src/と同じ
├── config.json             # 本番用設定（test_mode: false）
├── start_gui.vbs           # 本番起動用（15秒同期待ち付き）
├── setup_scheduler.bat     # タスクスケジューラ登録
├── templates/
│   └── xray_karte.yaml
└── _backup/
```

---

## ⚙️ config.json 設定項目

| 設定項目 | 説明 | 例 |
|---------|------|-----|
| `watch_folder` | 監視フォルダ | `G:/共有ドライブ/...` |
| `test_mode` | テストモード | `false`=本番 |
| `test_patient_id` | テスト患者ID | `2277808` |
| `auto_start` | 自動起動 | `true` |
| `schedule.auto_shutdown` | 自動終了 | `true` |
| `schedule.shutdown_time` | 終了時刻 | `22:00` |
| `chat_webhook_url` | Google Chat通知先 | Webhook URL |
| `headless` | ブラウザ非表示 | `false`（GUIの設定ダイアログから変更可能） |

---

## 🔄 処理フロー

```
1. タスクスケジューラ（毎朝8:00） → start_gui.vbs 起動
2. 15秒待機（Google Drive同期）→ pythonw gui.py 起動
3. GUI起動 → 即座にタスクトレイに格納
4. 自動起動チェック → フォルダ監視開始
5. Google Chatに起動通知送信
6. ファイル検知 → テンプレートエンジン → Homisにカルテ登録
7. GAS APIにカルテURL通知 → スプレッドシート更新
8. 22:00 自動終了 → Google Chatに終了通知
```

---

## ⚠️ 注意事項

- **依頼日と撮影日を絶対に取り違えないこと**
  - `requestDate`（依頼日）: オーダーが作成された日（スプレッドシートのCREATED_AT列）
  - `shootingDate`（撮影日）: 実際に撮影が行われた日（撮影完了時の日時）
  - JSON手動作成時は特に注意。GAS自動生成時は正しく設定される
- **ドライブレター**: 自宅(T:)と会社(Q:)でマイドライブのレターが異なる
  - 共有ドライブは `G:` で共通（ただしPCによって `T:` 等になる場合あり）
- **タスクスケジューラ**: `setup_scheduler.bat` は管理者権限で1回だけ実行
- **pythonwのパス**: `C:\Users\setup\AppData\Local\Programs\Python\Python314\pythonw.exe`
  - PCが変わる場合はVBSのパスを修正する必要あり

---

**Good Luck!** 🚀
