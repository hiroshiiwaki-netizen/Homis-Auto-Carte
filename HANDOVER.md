# Homis自動カルテ生成 引継ぎ書

> **最終更新**: 2026-09-04 10:50
> **バージョン**: v2.1.2（本番垂水） / v3 クラウド試験成功・ナビ未切替
> **ステータス**: 🟢 東京 Cloud Run からテスト舞子へ書けた。**来週実装**（詳細ログ先行）

---

## 🧪 v3 GCP試験（2026-09-04）※今日はここまで

Cloud Run Job から、レントゲンナビと同じ JSON 形でテスト舞子（2277808）に1件書けた。岩城さん目視で S/AP・時刻・指示医「山口 高秀 // 内科」まで入っていた。

| 項目 | 値 |
|---|---|
| オーダー | `GCP-TEST-20260904-104419` |
| karte_id | `18302640` |
| URL | https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18302640 |
| 所要 | 約45秒 |
| 仕様 | `docs/SPEC_v3_cloud.md` |

本番の垂水 Python（v2.1.2）は**止めていない**。ナビ切替もしていない。

### 来週やること（岩城さん 2026-09-04）

1. **先に詳細ログ**（しばらく成功/失敗が取れるようにする）
   - 各 YAML ステップ（Chrome起動・ログイン・新規・外来・指示医・医科カルテ・日時・S・AP・指導・完了・karte_id取得）を `ok/fail` と秒数で出す
   - 1件の締めは1行: `RESULT {orderId, success, has_karte_id, error_type, total_sec, karte_id}`
   - Cloud Logging で件数集計できること
   - **出さない**: 患者名、S/AP本文、パスワード。`config.json` はコンテナに入れない
   - 文字化け対策: `PYTHONIOENCODING=utf-8`（今日のログは日本語が `????` になった）
2. そのあとナビ切替（`HOMIS_WRITE_MODE=3`）と結果シート。切替までは垂水 Python を正とする

### GCP設定（プロジェクト `gen-lang-client-0979357970` / 東京）

| 種類 | 名前 |
|---|---|
| Secret Manager | `homis-karte-user` / `homis-karte-password`（東京のみ複製） |
| Artifact Registry | `homis-karte-writer`（Cloud Build SA と Compute SA に writer） |
| イメージ | `asia-northeast1-docker.pkg.dev/gen-lang-client-0979357970/homis-karte-writer/homis-karte-writer-test:v0` |
| Cloud Run Job | `homis-karte-writer-test`（4Gi / 2CPU / 5分 / 再試行0） |
| ビルド置き場 | リポジトリ `cloud/` ＋作業コピー `C:\HomisKarteCloud` |

**ハマり**: このプロジェクトはプロジェクト単位 IAM が狭い。`gcloud run deploy --source` と `cloud-run-source-deploy` への push は拒否される。`dx-web` と同じく **専用リポジトリへ `gcloud builds submit --tag` → Job は `--image`**。

再実行（来週・テスト舞子のみ）:

```
gcloud run jobs execute homis-karte-writer-test --region=asia-northeast1 --project=gen-lang-client-0979357970 --wait
```

---

## 🔧 v2.1.2 Watchdogが拾い直せない件（2026-09-03）

9/1 9:07 以降プロセスが落ち、トレイが空のまま 9/3 朝まで戻らなかった。

- 9/1 3:24〜9:34 の `watchdog.log` は旧英語版で正常（心拍OK）
- 9/1 9:36 に共有の `watchdog.bat` を日本語UTF-8へ差し替えた直後から記録が途切れた
- `HomisKarteWriter\watchdog.bat` は UTF-8 BOM 付きで、タスクの `cmd` が先頭を読めない
- `HomisKarteWriter\start_gui.vbs` は `C:\HomisKarteWriter\gui.py` を起動していた

### 修正

- Watchdog を英語・BOMなしに戻す（ログ形式は 9/1 朝と同じ英語）
- 起動は VBS と同じフォルダの `launch_gui.py` → `gui.py`（共有の版）
- 失敗時だけ `C:\HomisKarteWriter\startup_error.log` に書く
- 今動いている画面は止めない。次の日次リスタートまたは Watchdog 再起動で v2.1.2 になる

`config.json` は未変更。

### 2026-09-03 15:15 失敗時の通知は止めない（方針確定）

- 15:12 に「失敗時は GAS を呼ばない」に変えたが、**撮影完了の事実が医師に届かなくなる**ため **取り消し**
- 失敗時は従来どおり空URLで GAS を呼ぶ。ナビが患者詳細URL付きで撮影完了を通知する（`Order.gs updateHomisLink` の救済設計）
- `watcher.py` / `clipboard_utils.py` / `homis_writer.py` / `template_engine.py` を共有2フォルダへ揃えた
- 14:55 の失敗原因はカルテ側ではなく **Chrome が起動直後に切れた**（`invalid session id`、chromedriver 152 を新規取得した直後）。ここを直すのが本筋

---

## 🔧 v2.1.1 監視停止の自動復帰（2026-09-01）

日次リスタート後にプロセスだけ生きて「停止中」のままになる件。

- 心拍は監視中でなくても更新する
- `auto_start` ON なのに停止なら開始し直す
- Watchdog は `running` 以外を再起動対象にする
- 画面タイトル: `Homis自動カルテ生成 v2.1.1`
- 配置先（**両方更新済み**・`config.json` は未変更）:
  - `G:\共有ドライブ\レントゲンオーダー\HomisKarteWriter`
  - `G:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル`
- 垂水はアプリ終了 → Watchdog 再起動が必要。`HomisKarteWriter\start_gui.vbs` は `C:\HomisKarteWriter` 起動のまま
- **2026-09-01 岩城指示**: プログラム修正時はリポジトリだけでなく共有フォルダも同じ版にする

### 次にやること（9/4 朝）

- 垂水で画面タイトルが **v2.1.2**、状態が **監視中**
- 撮影完了Chatが届いていること（失敗時も患者トップURLで届く）
- 14:55 型の Chrome `invalid session id` が再発していないかログ確認

---

## 🎧 2026-08-31 GASコールバック401（撮影完了Chat途絶）

カルテ書き込みは成功していたが、`updateHomisLink` が **HTTP 401** で落ち、ナビの撮影完了Chatと Homis列が止まっていた。

| 項目 | 内容 |
|------|------|
| 原因 | レントゲンナビ Webアプリが匿名POSTを拒否。ライター側のバグではない |
| 本番URL | `https://script.google.com/macros/s/AKfycbzfiJcoERAk8vReS-2yx7QtrsUuJh2OOrFSWeNtcOdoXxpXTm7Ofzy3cmw0JlomMISm/exec`（`/macros/s/`。`/a/macros/nhw.jp/` は使わない） |
| 垂水 | 監視フォルダは `G:/共有ドライブ/レントゲンオーダー/Homis登録データ`。**新しいファイル投入は不要** |
| 復旧 | 岩城さんが GAS「全員」に変更。8/31 茨木・清水・田中の完了Chatで確認 |
| 取りこぼし再通知 | やらない（方針） |
| OhiScanGo統合 | 今はやらない |

リポジトリの `src/config.json` はまだ `/a/macros/nhw.jp/s/` 形式。**本番へ上書きコピーすると401が再発する。**

---


## 🔧 v2.1.0 カルテID取得安定化（2026/06/29）

> ⚠️ **未デプロイ**: 開発ソース（src/）のみ更新済み。本番へのコピーは岩城さん手動。

### 問題（Go版OhiScanGoとの比較で判明）

| 原因 | 旧（Python版） | 新（v2.1.0） |
|------|--------------|-------------|
| アラート処理 | `Alert().accept()` でタイミング依存 | **JS上書き**（`window.confirm = () => true`） |
| 画面遷移待ち | `sleep(5)` 固定 | **目的ベース待機**（karte_id or copyLinkOfKarte 出現まで最大20秒） |
| リトライ | 3回×3秒 | **5回×2秒** |

### 変更ファイル

| ファイル | 変更 |
|---------|------|
| `homis_writer.py` | Step 8: JS上書き + sleep(2秒) + WebDriverWait(20秒) |
| `clipboard_utils.py` | `extract_karte_url_with_retry()` のデフォルト 5回×2秒 |

### デプロイ手順

1. `src/homis_writer.py` → `G:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル\homis_writer.py` にコピー
2. `src/clipboard_utils.py` → 同上フォルダにコピー
3. タスクトレイの HOMISカルテライターを終了 → 自動再起動（Watchdog）を待つ
4. **検証**: 次のカルテ書き込みで `watcher_YYYYMMDD.log` に `✅ 保存完了・画面遷移確認` が出るか確認

### 次のステップ

- `template_engine.py` にも同じ修正を適用（v2.1.1 または同時）
- 1週間のログ監視で失敗率を確認

---

## ✅ デプロイ済み（2026/06/24）

### v2.0.4 URL取得リトライ + 空URL誤通知防止 (2026/06/24)

| 機能 | 内容 |
|------|------|
| A: リトライ付きURL取得 | `extract_karte_url_with_retry()` を `clipboard_utils.py` に追加。3回・3秒間隔で再試行 |
| 呼び出し元 | `template_engine.py` + `homis_writer.py` 両方で使用 |
| B: 空URL時GAS通知スキップ | カルテ作成成功 + URL取得失敗時は `_notify_gas()` を呼ばない（karte_idなし誤通知を防止） |
| 二重カルテ防止 | URL取得失敗でもJSONは「済」フォルダへ移動（再処理しない） |
| 運用アラート | URL取得失敗時に `chat_notifier.notify_error()` でChatに通知（手動確認を促す） |
| 失敗パス変更なし | `success=False` 時の空URL GAS通知は維持（撮影完了を伝える必要があるため） |

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
├── cloud/                  # v3 Cloud Run 試験（Dockerfile / write_once.py）
├── docs/SPEC_v3_cloud.md   # v3 仕様
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

- **プログラム修正時は共有フォルダも更新する**（2026-09-01 岩城指示）
  - `HomisKarteWriter` と `Homis転記実行ファイル` の両方
  - 画面タイトルと HANDOVER の版を上げる
  - `config.json` は上書き禁止
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
