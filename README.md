# Homis自動カルテ生成 v1.0

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
| `gui.py` | **メイン（推奨）** - GUI画面＋タスクトレイ常駐 |
| `watcher.py` | コマンドライン版 - フォルダ監視 |
| `template_engine.py` | テンプレートエンジン（テスト用） |
| `config.json` | 設定ファイル |

### 補助ファイル（自動で呼ばれる）
| ファイル | 説明 |
|---|---|
| `browser_actions.py` | ブラウザ操作 |
| `homis_writer.py` | Homisカルテ書き込み |
| `gas_api.py` | GAS連携（カルテURL送信） |

### 使わないファイル（開発用/レガシー）
| ファイル | 説明 |
|---|---|
| `main.py` | 旧方式（Google Drive API経由、現在未使用） |
| `check_elements.py` | デバッグ用 |
| `debug_karte.py` | デバッグ用 |
| `sample_karte.py` | サンプル（参考用） |
| `sample_karte_v2.py` | サンプル（参考用） |
| `test_local.py` | ローカルテスト用 |

---

## 🚀 使い方

### 初回セットアップ
1. `install_deps.bat` をダブルクリック

### GUI版（推奨）
1. `start_gui.bat` をダブルクリック
2. 設定画面で監視フォルダ・認証情報を設定
3. 「開始」ボタンで監視開始
4. タスクトレイに常駐

### コマンドライン版
1. `start_watcher.bat` をダブルクリック

### テスト実行
1. `test_template.bat` でテスト

---

## ⚙️ 設定（config.json）

```json
{
    "watch_folder": "G:\\共有ドライブ\\レントゲンオーダー\\Homis登録データ",
    "gas_web_app_url": "https://script.google.com/macros/s/.../exec",
    "test_mode": true,
    "test_patient_id": "2277808",
    "headless": false
}
```

| 項目 | 説明 |
|------|------|
| `watch_folder` | 監視フォルダ（GASがJSON出力する場所） |
| `gas_web_app_url` | GAS Web AppのURL（カルテURL送信先） |
| `test_mode` | テストモード（true=テスト患者IDを使用） |
| `test_patient_id` | テスト用の患者ID |
| `headless` | true=バックグラウンド実行 |

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
| v1.0.0 | 2026/01/27 | GAS連携追加、テストモード対応 |
| v0.9.0 | 2026/01/26 | 初版リリース |
