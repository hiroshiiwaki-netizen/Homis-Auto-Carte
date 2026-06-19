# Homis自動カルテ生成 引継ぎ書

> **最終更新**: 2026年6月19日 17:07
> **バージョン**: v2.0.3
> **ステータス**: ✅ 本番デプロイ済み・24時間自動運用中

---

## ✅ デプロイ済み（2026/06/19）

### v2.0.3 OhiScanGo方式URL取得 (2026/06/19 17:07)

| 機能 | 内容 |
|------|------|
| カルテURL取得 | クリップボード → **ブラウザ直接取得**に変更（headless対応） |
| 優先度1 | `driver.current_url` に `karte_id` があればそれを返す |
| 優先度2 | `copyLinkOfKarte` ボタンの onclick 属性からURL抽出 |
| フォールバック | `karte_id` なし → 空文字（誤通知防止） |
| 対象 | `template_engine.py` + `homis_writer.py` 両方 |

### v2.0.2 パス一元管理 (2026/06/19 16:40)

| 機能 | 内容 |
|------|------|
| `paths.py` 新規 | CODE_DIR / STATE_DIR / LOG_DIR / CONFIG_FILE を一元管理 |
| ログ出力先 | 共有ドライブ `logs/`（`CODE_DIR / "logs"`） |
| config読み込み | `C:\HomisKarteWriter\config.json` 優先 |
| 起動ログ | CODE_DIR, STATE_DIR, LOG_DIR, CONFIG_FILE を出力（追跡用） |

### v2.0.1 24時間稼働 + クリップボード修正 + 堅牢性強化

| 機能 | 内容 |
|------|------|
| クリップボード修正 | `clipboard_utils.py` 新規。事前クリア + URL検証（homis.jp + /homic/） |
| 適用箇所 | `homis_writer.py` + `template_engine.py` 両方修正 |
| 日次リスタート | 22:00終了 → **0:00日次リスタート**に変更（`restart_time` 設定） |
| ハートビートWatchdog | `heartbeat.txt` を60秒更新、`watchdog.bat` で5分死活監視 |
| エラー自動復帰 | 30秒待機×3回リトライ。3回失敗→プロセス終了→Watchdog再起動 |
| 7日24時間稼働 | ログオン時起動 + 5分Watchdog（旧: 月～金8:00起動） |
| config後方互換 | 旧 `shutdown_time` → 新 `restart_time` フォールバック |
| リスタート競合防止 | `restarting` ステータスで Watchdog が2分待機 |
| リスタートループ防止 | `_last_restart_date` で1日1回ガード（v2.0.0） |
| 単一インスタンス | PIDファイル方式で二重起動防止（v2.0.0） |
| 起動時ハートビート | 起動直後に `starting` ステータスを書く（v2.0.0） |

#### デプロイ手順（本番）
1. **配置済み**: 共有ドライブ `G:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル` にコード一式
2. 実行PCに `C:\HomisKarteWriter` フォルダを作成（状態ファイル用）
3. 実行PCに config.json を `C:\HomisKarteWriter\` にコピー（`"restart_time": "00:00"` 設定済み）
4. 実行PCで管理者権限で `setup_watchdog.bat` を実行（旧タスク削除 + 新タスク2本登録）
5. 動作確認: `C:\HomisKarteWriter\heartbeat.txt` が更新されるか確認

---

## ✅ 完了済み（2026/02/25）

### v1.5.1 完了ボタン操作修正 + GAS API疎通確認

| 機能 | 内容 |
|------|------|
| 指導内容入力追加 | `textarea#report` に全角スペースを入力（空だと完了時エラー） |
| アラート2回対応 | 完了ボタン後のアラートを1回→2回対応に修正 |
| 対象ファイル | `xray_karte.yaml`(v1.4), `browser_actions.py`, `homis_writer.py` |
| テスト結果 | ✅ テストモードで全ステップ成功（カルテURL取得済み） |
| GAS API疎通 | ✅ HTTP 200で正常応答確認済み（401エラー解消） |

### v1.5.0 カルテ保存「中断」→「完了」変更（2026/02/24）

| 機能 | 内容 |
|------|------|
| 保存ボタン変更 | `karteInterruption`（中断）→ `karteCompletion`（完了） |
| GAS API 401修正 | デプロイ権限を「全員」に変更 |

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
