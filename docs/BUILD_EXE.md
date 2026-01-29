# Windows EXEビルド手順

## 前提条件
- Python 3.9以上がインストールされていること
- 会社PC（Windows）で実行

## 手順

### 1. 依存パッケージのインストール

```powershell
cd T:\マイドライブ\Antigravity-PJ\Homis自動カルテ生成
pip install -r requirements.txt
```

### 2. PyInstallerでEXE作成

```powershell
cd src
pyinstaller --onefile --name HomisKarteWriter --icon=icon.ico watcher.py
```

または、アイコンなしの場合：
```powershell
pyinstaller --onefile --name HomisKarteWriter watcher.py
```

### 3. 作成されるファイル

```
src/
├── dist/
│   └── HomisKarteWriter.exe  ← 実行ファイル
├── build/                     ← ビルド一時ファイル（削除可能）
└── HomisKarteWriter.spec      ← ビルド設定ファイル
```

### 4. 配布

`dist/HomisKarteWriter.exe` と `config.json` を同じフォルダに配置して実行。

## 設定ファイル（config.json）

```json
{
    "watch_folder": "T:\\マイドライブ\\Antigravity-PJ\\Homis自動カルテ生成\\homis_queue",
    "processed_folder": "",
    "poll_interval_seconds": 10,
    "homis_url": "https://homis.jp/homic/",
    "homis_user": "71241",
    "homis_password": "xxxxx",
    "gas_web_app_url": "",
    "test_mode": true,
    "test_patient_id": "2277808",
    "headless": false
}
```

### headless設定
- `false`: ブラウザを表示（デバッグ用）
- `true`: バックグラウンド実行（本番用）

## 注意事項

1. Chrome/Chromiumがインストールされている必要があります
2. 初回実行時にChrome WebDriverが自動ダウンロードされます
3. ファイアウォールでブロックされる場合は許可してください
