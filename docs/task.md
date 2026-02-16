# Homis自動カルテ生成 タスクリスト

## 完了
- [x] レントゲンナビ側：JSON生成機能追加
  - [x] PDF.gs: `createHomisJSON`関数追加
  - [x] Order.gs: 撮影完了時に呼び出し追加
  - [x] clasp push完了
- [x] ローカル監視ツール作成
  - [x] 基本構造 (`main.py`)
  - [x] Google Drive監視 (`main.py`)
- [x] Seleniumブラウザ操作実装 (`homis_writer.py`)
  - [x] ログイン処理
  - [x] カルテ内容入力 (S, A/P)
  - [x] URLコピー機能
- [x] **デバッグ・検証** (2026/1/26 完了)
  - [x] ログインボタンセレクタ: `button[type="submit"]`
  - [x] 外来ラジオボタン: ラベル「外来」をクリック
  - [x] A/P Summary: inputイベント発火で保存確認
  - [x] `sample_karte_v2.py` で全フロー動作確認済み

## 進行中
- [ ] **homis_writer.py 更新** ← 次のタスク
  - [ ] `sample_karte_v2.py` のロジックを反映
- [ ] **機能追加**
  - [ ] GAS API連携実装 (PythonからGASコールしURL通知)
- [ ] テスト・検証
  - [ ] `homis_writer.py` 単体テスト
  - [ ] `main.py` 結合テスト (Drive連携確認)
- [ ] exe化 (PyInstaller)
- [ ] 配布・デプロイ

## 未着手
- [ ] 運用マニュアル作成

