# Homis自動カルテ生成 システム仕様書

> **バージョン**: v1.5.1
> **最終更新**: 2026-02-25
> **ステータス**: ✅ 本番運用中

---

## 1. 概要

レントゲンナビ（GAS）でオーダー撮影完了時にJSONファイルを生成し、
本システムがそのJSONを検知してHomis電子カルテに自動書き込みを行う。

### 対象業務
- レントゲン撮影完了後のカルテ転記作業を自動化

### 処理フロー

```
レントゲンナビ(GAS)
  → JSONファイル生成（共有ドライブに出力）
    → watcher.py がファイル検知（ポーリング方式）
      → template_engine.py がYAMLテンプレートを読み込み
        → browser_actions.py がSeleniumでHomisを操作
          → カルテ書き込み完了
            → gas_api.py がカルテURLをレントゲンナビに通知
              → スプレッドシートのステータス更新
```

---

## 2. アーキテクチャ設計

### 2.1 YAML駆動テンプレート方式（重要）

> **設計方針**: ブラウザ操作はすべてYAMLテンプレートに定義し、
> プログラム（template_engine.py / browser_actions.py）は汎用的なエンジンとして使う。

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  xray_karte.yaml │───▶│ template_engine  │───▶│ browser_actions  │
│  (操作手順定義)   │    │  (汎用エンジン)   │    │  (汎用アクション) │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

**メリット**:
- 画面変更時はYAMLだけ修正すれば良い（Pythonコードの変更不要）
- 新しいカルテ種別を追加する場合もYAMLを追加するだけ
- セレクタや操作手順が一覧で見やすい

### 2.2 後方互換（homis_writer.py）

`watcher.py` はJSON内の `template` フィールドの有無で分岐する：

| JSON | 実行エンジン | 説明 |
|------|-------------|------|
| `"template": "xray_karte"` あり | TemplateEngine（YAML駆動） | **推奨** |
| `template` なし | HomisKarteWriter（ハードコード） | 後方互換用 |

---

## 3. YAMLテンプレート仕様

### 3.1 対応アクション一覧

| action | 説明 | 必須パラメータ |
|--------|------|--------------|
| `click` | 要素をクリック | `selector` |
| `input` | テキスト入力（send_keys） | `selector`, `value` |
| `js_input` | JavaScript経由入力（inputイベント発火） | `selector`, `value` |
| `select` | プルダウン選択 | `selector`, `value` |
| `navigate` | URL遷移 | `value` |
| `wait` | 指定ミリ秒待機 | `ms` |

### 3.2 オプション

| オプション | 説明 | 例 |
|-----------|------|-----|
| `selector_type` | `css`（デフォルト）or `xpath` | `xpath` |
| `text_contains` | ラベル内テキスト検索 | `"外来"` |
| `confirm_alert` | アラートを1回OK | `true` |
| `confirm_alert_count` | アラートをN回OK | `2` |
| `wait_after` | アクション後の待機（ms） | `2000` |
| `description` | ステップの説明（ドキュメント用） | `"指導内容が空だと..."` |

### 3.3 変数展開

YAMLの `{変数名}` はJSONデータの対応するキーの値に置換される。

```yaml
selector: "#doctor018"
value: "{doctorName}"      # → JSONのdoctorNameの値に置換
```

---

## 4. Homisカルテ操作手順（xray_karte.yaml v1.4）

### 4.1 操作ステップ一覧

| # | ステップ名 | action | セレクタ | 値 |
|---|-----------|--------|---------|-----|
| 1 | 新規ボタンをクリック | click | `#karteNew` | - |
| 2 | 外来を選択 | click | `label` (text=外来) | - |
| 3 | 指示医を選択 | select | `#doctor018` | `{doctorName}` |
| 4 | 医科カルテボタン | click | `//a[contains(text(),'医科カルテ')]` | - |
| 5 | 診察日を入力 | js_input | `#act_date` | `{shootingDate}` |
| 6 | 開始時間を入力 | input | `#start_time` | `{shootingTime}` |
| 7 | 終了時間を入力 | input | `#end_time` | `{shootingTimeEnd}` |
| 8 | S欄に入力 | js_input | `textarea#subjective` | `{sContent}` |
| 9 | A/P Summary欄 | js_input | `textarea#ap` | `{apContent}` |
| 10 | **指導内容に全角スペース** | js_input | `textarea#report` | `　`（全角スペース） |
| 11 | 完了ボタンで保存 | click | `#karteCompletion` | アラート2回OK |

### 4.2 完了後の処理

| # | ステップ名 | action | セレクタ |
|---|-----------|--------|---------|
| 12 | リンクをコピー | click | `//a[contains(@onclick,'copyLinkOfKarte')]` |

### 4.3 Homis完了ボタンの注意事項

> **重要**: 以下の3つの欄がすべて入力されていないと完了時にエラーになる
> - S欄（`textarea#subjective`）
> - A/P Summary欄（`textarea#ap`）
> - 指導内容（`textarea#report`）← **v1.5.1で対応**
>
> 完了ボタンクリック後、**アラートが2回**表示される。両方OKを押す必要がある。
> アラート後に画面が遷移し、「リンクをコピー」ボタンが表示される。

---

## 5. GAS API連携

### 5.1 エンドポイント

レントゲンナビのGAS WebApp（デプロイ権限: **全員**）

### 5.2 リクエスト

```json
{
  "action": "updateHomisLink",
  "orderId": "R-202601261500-001",
  "homisUrl": "https://homis.jp/homic/?pid=patient_detail&patient_id=xxx&karte_id=yyy"
}
```

### 5.3 レスポンス

```json
// 成功時
{"success": true, "message": "更新完了"}
// オーダーが見つからない場合  
{"success": false, "message": "オーダー xxx が見つかりません"}
```

---

## 6. ファイル構成

```
Homis自動カルテ生成/
├── src/
│   ├── gui.py              # GUI（自動起動・トレイ格納・設定ダイアログ）
│   ├── watcher.py          # フォルダ監視（ポーリング方式）
│   ├── template_engine.py  # 【汎用】YAMLテンプレート実行エンジン
│   ├── browser_actions.py  # 【汎用】ブラウザアクション定義
│   ├── homis_writer.py     # 【後方互換】ハードコード方式
│   ├── gas_api.py          # GAS連携（カルテURL通知）
│   ├── chat_notifier.py    # Google Chat通知
│   ├── config.json         # 設定ファイル
│   ├── start_gui.vbs       # 起動スクリプト
│   └── templates/
│       └── xray_karte.yaml # 【操作定義】レントゲンカルテ v1.4
├── test_data/              # テストデータ
├── _backup/                # バックアップ
├── docs/
│   └── system_spec.md      # ← この仕様書
├── HANDOVER.md             # 引継ぎ書
└── README.md
```

---

## 7. 変更履歴

| バージョン | 日付 | 内容 |
|-----------|------|------|
| v1.5.1 | 2026/02/25 | 指導内容全角スペース入力追加、アラート2回対応、GAS API疎通確認 |
| v1.5.0 | 2026/02/24 | カルテ保存「中断」→「完了」変更、GAS API 401修正 |
| v1.4.0 | 2026/02/16 | ヘッドレスモードGUI対応、共有ドライブ配置 |
| v1.3.0 | 2026/02/10 | 自動起動・トレイ格納・Chat通知・自動終了・日付入力 |
| v1.0.0 | 2026/01/26 | 初版リリース |
