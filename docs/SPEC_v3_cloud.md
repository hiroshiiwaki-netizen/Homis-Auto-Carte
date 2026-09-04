# Homis自動カルテ生成 v3 仕様書（クラウド化）v0

> **版**: v0.1（GCP実書き込み試験済み）
> **作成**: 2026-09-04
> **前提決定（岩城さん 2026-09-04）**
> - 日本国内（東京 asia-northeast1）のサーバーなら患者情報の通過は可。保存はしない
> - Tukusi ブラウザ案（B案）は作らない
> - HomisApi（HTTP直POST）はルール更新者が変わるため使わない

---

## 1. 目的

レントゲン撮影完了後の HOMIS カルテ書き込みを、**垂水PC から GCP（Cloud Run）へ移す**。

| いま困っていること | v3 でどうなるか |
|---|---|
| 垂水PCが止まる／Chromeが切れると書けない | PC不要。Chrome の版は固定 |
| Python → GAS の匿名POSTが 401 で切れると Chat も AE も止まる（6/30〜8/30） | 匿名POSTを使わない。結果はシートに直接書く |
| カルテID付きURLが届かないことがある | **取れた時は必ず直リンク**。取れない時だけ患者ページ |
| コードが共有フォルダとローカルに分かれる | コードは Git → コンテナ。ローカル配置なし |

## 2. スコープ

**やる**
- レントゲンカルテ（`xray_karte.yaml`）の書き込みを Cloud Run で実行
- ナビ GAS からの呼び出し、結果の受け取り、撮影完了Chat（直リンク優先）
- スクリプトプロパティによる切替（旧Pythonへ戻せる）
- 集団検診（複数件）の逐次処理

**やらない**
- 往診カルテ（`job_id` あり）の移行（別PJ。現行のまま）
- HOMIS 以外への書き込み
- 患者情報の保存・蓄積（ログにも残さない）
- 旧 Python の削除（並行運用が終わるまで残す）

## 3. 全体の流れ

```
撮影完了ボタン（ナビ GAS）
  │ HOMIS_WRITE_MODE=3
  ▼
Cloud Run「homis-karte-writer」に JSON を POST（合言葉ヘッダー）
  │ すぐ 202 を返す（受付のみ）
  ▼
Cloud Run が Chrome（headless）で HOMIS に書く
  今の YAML どおり: 新規→外来→医師→医科カルテ→日時→S→A/P→指導(全角空白)→完了(アラート2回)
  karte_id を現在URL / copyLinkOfKarte から取得
  ▼
ナビのスプレッドシート「HOMIS書込結果」に 1 行追記（サービスアカウント）
  orderId / status / homisUrl / 処理時刻 / エラー種別
  ▼
ナビ GAS（1分トリガー）が未処理行を拾う
  ├ homisUrl に karte_id あり → AE列に書く ＋ 撮影完了Chat（直リンク）
  ├ 失敗 / karte_id なし     → 撮影完了Chat（患者ページ）。AE は空
  └ 10分たっても結果なし     → 撮影完了Chat（患者ページ）。後で結果が来たら AE だけ埋める
```

**Chat は必ず1回。** 直リンクで出せた注文は患者ページを出さない。逆も同じ。

## 4. 切替（スクリプトプロパティ）

| キー | 値 | 動き |
|---|---|---|
| `HOMIS_WRITE_MODE` | `1` または未設定 | 現行。共有フォルダに JSON → 垂水 Python |
| | `3` | Cloud Run に POST。共有フォルダには出さない |
| | それ以外 | `1` 扱い |
| `HOMIS_WRITER_URL` | Cloud Run の URL | `3` のとき必須 |
| `HOMIS_WRITER_KEY` | 合言葉 | `3` のとき必須。Cloud Run 側と一致 |

`1` に戻せば旧運用にそのまま戻る。デプロイ不要。

## 5. Cloud Run 側

| 項目 | 内容 |
|---|---|
| サービス名 | `homis-karte-writer` |
| プロジェクト | `gen-lang-client-0979357970`（既存） |
| リージョン | `asia-northeast1`（東京） |
| 中身 | Python 3.12 + Selenium + Chrome（版固定）+ 既存 `template_engine.py` / `browser_actions.py` / `clipboard_utils.py` / `templates/xray_karte.yaml` |
| 同時実行 | インスタンス最大 1・並列 1（ロボット1アカウントのため逐次） |
| タイムアウト | 1件 5分 |
| 認証（入口） | 合言葉ヘッダー `X-Writer-Key`。不一致は 401 |
| HOMIS ID/PW | Secret Manager。環境変数・コードに置かない |
| シート書き込み | サービスアカウントに「HOMIS書込結果」シートの編集権限だけ付与 |
| ログ | **しばらく細かく**（§5.3）。患者名・S/AP本文・パスワードは出さない |
| 保存 | なし。受け取った JSON はメモリだけ |

### 5.1 受け取る JSON

現行 `createHomisJSON` と同じ `data` を送る（フィールド名は変えない）。
`orderId / homisId / patientName / doctorName / shootingDate / shootingTime / shootingTimeEnd / sContent / apContent / isGroup / groupId`

### 5.2 結果シート「HOMIS書込結果」

| 列 | 内容 |
|---|---|
| A | 受付時刻 |
| B | orderId |
| C | status（`ok` / `ok_no_id` / `fail`） |
| D | homisUrl（`karte_id` 付き。なければ空） |
| E | エラー種別（`login` / `chrome` / `timeout` / `template` / その他） |
| F | 処理済フラグ（GAS が Chat 送信後に `1`） |
| G | groupId |

患者名は書かない。URL に含まれる `patient_id` は既存 AE 列と同じ扱い。

### 5.3 しばらくの詳細ログ（2026-09-04 岩城さん）

並行運用のあいだ、成功/失敗を後から数えられるようにする。来週ここから実装。

| 出す | 出さない |
|---|---|
| ステップ名、`ok`/`fail`、そのステップの秒数 | 患者名 |
| 締め1行 `RESULT`（orderId, success, has_karte_id, error_type, total_sec, karte_id） | S/AP 本文 |
| error_type: `chrome` / `login` / `step:<名前>` / `timeout` / `no_karte_id` | パスワード |

文字コードは UTF-8（`PYTHONIOENCODING=utf-8`）。Cloud Logging で `RESULT` を拾えば日次の成功率が出せる。

## 6. ナビ GAS 側の変更

| ファイル | 変更 |
|---|---|
| `Order.gs` | 撮影完了処理で `HOMIS_WRITE_MODE` を見て分岐。`3` なら Cloud Run へ POST し、`HOMIS書込待ち` に orderId と時刻を記録 |
| `HomisCloud.gs`（新規） | Cloud Run 呼び出し、結果シート読み取り、1分トリガー `pollHomisWriteResults`、10分フォールバック |
| `Notification.gs` | 変更なし（`getHomisLink` の直リンク優先をそのまま使う） |
| `Code.gs` | 変更なし（`doPost` は旧Python用に残す） |

集団検診は、全員分の結果が揃った時点（または最後の1件から10分）で既存の一括通知を出す。

## 7. 失敗時の振る舞い

| 事象 | Chat | AE列 | 再試行 |
|---|---|---|---|
| ログイン失敗・Chrome切断 | 患者ページで撮影完了 | 空 | Cloud Run 内で 1回だけ再試行。だめなら `fail` |
| 完了ボタンまで行ったが karte_id 取れず | 患者ページ | 空 | しない（二重カルテ防止） |
| Cloud Run が応答しない | 10分後に患者ページ | 空 | しない |
| 結果は来たが GAS トリガーが止まっていた | 次回トリガーで送る | 埋まる | — |

いずれも**撮影完了の事実は必ず届く**（2026-09-03 方針）。

## 8. フェーズ

| フェーズ | 成果物 | 完了条件 | 目安 |
|---|---|---|---|
| **0** | この仕様 v0 | 岩城さん承認 | 2h |
| **1** | Dockerfile・`server.py`・ローカル Docker でテスト舞子（2277808）に 1 件 | headless で完了保存・karte_id 取得 | 6〜8h |
| **2** | Cloud Run デプロイ・Secret・結果シート・サービスアカウント | 外から合言葉付き POST で 1 件書け、結果シートに行が増える | 6〜8h |
| **3** | ナビ GAS：切替・呼び出し・1分トリガー・10分フォールバック | `HOMIS_WRITE_MODE=3` でテスト舞子 1 件が直リンク Chat まで通る | 4〜6h |
| **4** | 並行運用（垂水 Python は止めない）→ 実患者で確認 → 切替 → 垂水停止 | 1週間、失敗種別ゼロまたは説明可能 | 2〜4h |

各フェーズは **実装報告 → 停止 → テスト → 報告 → 停止** を守る。

## 9. 費用

Cloud Run 逐次1インスタンス・1件約1分・月100〜150件 → 無料枠内か数十円。Secret Manager は無料枠内。

## 9.5 2026-09-04 GCP実書き込み試験

Cloud Run Job `homis-karte-writer-test`（東京）からテスト舞子へ1件作成できた。

| 項目 | 値 |
|---|---|
| orderId | `GCP-TEST-20260904-104419` |
| karte_id | `18302640` |
| URL | https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18302640 |
| 内容 | ナビと同じ形（胸部正面PA・2枚・指示医欄・ORCA 000003） |
| 所要 | 起動〜完了 約45秒 |

岩城さん目視で指示医「山口 高秀 // 内科」まで入っていることを確認。ナビ切替は未着手。

## 10. 未決事項

- 結果シートをナビのブックに置くか、別ブックにするか（v0 はナビのブック内）
- 集団検診の一括通知タイミング（v0 は「全員揃う or 最後から10分」）
- 旧 Python の停止時期（フェーズ4で決める）

## 更新履歴

| 版 | 日付 | 内容 |
|---|---|---|
| v0.1 | 2026-09-04 | GCP試験成功。karte_id=18302640。来週は詳細ログ先行 |
| v0 | 2026-09-04 | 初版。構想・スコープ・流れ・切替・フェーズ |
