# Homis自動カルテ生成 v3 仕様書（クラウド化）v0

> **版**: v0.20（0章「版の管理」を新設・v3.1.0 ナビへの知らせ。ナビ未切替）
> **作成**: 2026-09-04 / 更新 2026-09-08
> **前提決定（岩城さん 2026-09-04）**
> - 日本国内（東京 asia-northeast1）のサーバーなら患者情報の通過は可。保存はしない
> - Tukusi ブラウザ案（B案）は作らない
> - HomisApi（HTTP直POST）はルール更新者が変わるため使わない

---

## 0. 版の管理（2026-10-15 新設・coding-style.md「モジュールの版と改定履歴」）

> 計画の正本: `docs/PLAN_v3_GCP移行計画.md` v0.4。この PJ の版の台帳はこの章（VERSION.md は置かない）。
> ファイルを直したら、そのファイルの先頭・この表・改定履歴を同じ commit でそろえる。

### 0.1 モジュール別の版（cloud/）

| ファイル | 版 | 最終更新 | 役割 |
|---|---|---|---|
| server.py | 3.1.0 | 2026/10/15 | 受け口（/health・/write・/check-group）・失敗ガード |
| navi_callback.py | 3.1.0 | 2026/10/15 | ナビの doPost への知らせ（再送・DX Chat） |
| result_sheet.py | 3.0.0 | 2026/09/08 | 結果シート（orderId の二重を断る）。先頭の版は次に直すときに書く |
| write_once.py | 3.0.0 | 2026/09/04 | Job の手動試験。先頭の版は次に直すときに書く |

### 0.2 改定履歴（新しい順）

| 版 | 日付 | 主な変更 | 変えたファイル |
|---|---|---|---|
| v3.1.0 | 2026/10/15 | 書き終えたらナビの doPost（updateHomisLink）に知らせる（NAVI_WEBAPP_URL があるときだけ・xray_karte だけ・応答なし／5xx だけ最大3回・だめなら DX Chat）。POST /check-group（集団の確かめ役）。断るときも本文を読み切る。テスト `cloud/tests/test_phase1.py` 17本（黒ヤギ合格・知らせの例外の囲い・受け取りの待ち60秒） | server.py・navi_callback.py（新）・Dockerfile・prepare_cloud_build.ps1 |
| v3.0.x | 2026/09/04〜09/08 | Job 試験・受け口2a・失敗ガード（7章）・結果シート（2b）・fax_so・bot_s_interrupt（9.5・9.6 章） | server.py・result_sheet.py・write_once.py |

### 0.3 Cloud Run のデプロイ履歴（`homis-karte-writer`・東京）

> 10/15 GCP の準備（フェーズ1）: Cloud Tasks API を有効化。キュー `homis-karte-writer`（東京・maxConcurrentDispatches 1・maxAttempts 1・1件/秒・記録 100%）。
> 列専用のアカウント `homis-tasks-invoker`（Cloud Run の run.invoker だけ）。タスクは OIDC（宛先＝サービスの URL）＋合言葉ヘッダーで Cloud Run を呼ぶ。

| イメージ | 日付 | 版 | 中身 |
|---|---|---|---|
| `:v6` | 2026/10/15 14:21 | v3.1.0（commit 1c981d8） | ナビへの知らせ・/check-group。リビジョン homis-karte-writer-00010-gxq。環境変数 NAVI_WEBAPP_URL（ナビ本番の exec）を追加。書いてよい患者はテスト3人のまま |
| `:v5` | 2026/09/08 | v3.0.x | 別患者3同時の試験まで（引継書 9/8） |

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

**Chat は必ず1回。失敗しても撮影完了は送る（止めない）。** 直リンクで出せた注文は患者ページを出さない。逆も同じ。

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
| 同時実行 | concurrency 1 は維持。試験の蓋は 3。運用の上限は **50**（未適用） |
| タイムアウト | 1件 5分 |
| 認証（入口） | 合言葉ヘッダー `X-Writer-Key`。不一致は 401 |
| HOMIS ID/PW | Secret Manager。環境変数・コードに置かない |
| シート書き込み | サービスアカウントに「HOMIS書込結果」シートの編集権限だけ付与 |
| ログ | **しばらく細かく**（§5.3）。患者名・S/AP本文・パスワードは出さない |
| 保存 | なし。受け取った JSON はメモリだけ |

### 5.1 受け取る JSON

現行 `createHomisJSON` と同じ `data` を送る（フィールド名は変えない）。
`orderId / homisId / patientName / doctorName / shootingDate / shootingTime / shootingTimeEnd / sContent / apContent / isGroup / groupId`

### 5.2 結果シート「HOMIS書込結果」（2b・案B）

**試験用の別ブック**（本番ナビのブックには書かない）。ID は環境変数 `RESULT_SPREADSHEET_ID`。切替時は差し替えるだけ。

| 列 | 内容 |
|---|---|
| A | 受付時刻 |
| B | orderId |
| C | status（`accepted` / `ok` / `ok_no_id` / `fail`） |
| D | homisUrl（`karte_id` 付き。なければ空） |
| E | エラー種別 |
| F | 処理済フラグ（GAS が Chat 送信後に `1`。2b では `0`） |
| G | groupId |

患者名は書かない。URL に含まれる `patient_id` は既存 AE 列と同じ扱い。

流れ: **同じ orderId を探す → 無ければ `accepted` 行を先に置く → HOMIS に書く → 同じ行を結果で更新。** 既存（完了または受付のまま）なら **書かない**。同期 POST のまま（202＋裏処理はしない）。

試験ブック: https://docs.google.com/spreadsheets/d/1_K0W0r_1HT7EzZz0QsMVbw6MDL7bVMGRChPI28xRI7w/edit （ロボットSAが編集可）

### 5.3 しばらくの詳細ログ（2026-09-04 岩城さん / 2026-09-07 垂水実装）

並行運用のあいだ、成功/失敗を後から数えられるようにする。**v2.1.3 で垂水 Python に入れた。** Cloud Run はナビ切替前に同じ STEP/RESULT を載せる。

| 出す | 出さない |
|---|---|
| ステップ名、`ok`/`fail`、そのステップの秒数 | 患者名 |
| 締め1行 `RESULT`（orderId, success, has_karte_id, error_type, total_sec, karte_id） | S/AP 本文 |
| error_type: `chrome` / `login` / `step:<名前>` / `timeout` / `no_karte_id` | パスワード |

文字コードは UTF-8（`PYTHONIOENCODING=utf-8`）。

**垂水の置き場（人が読むログはここだけ）**

| ファイル | 場所 |
|---|---|
| `writer_YYYYMMDD.log` | `G:\共有ドライブ\レントゲンオーダー\HomisKarteWriter\logs\` （STEP / RESULT） |
| `watcher_YYYYMMDD.log` | 同上（書いた日でローテ。開いたままにしない） |
| `watchdog.log` / `heartbeat.txt` / `startup_error.log` | 同上にコピー。Watchdog 判定用の心拍は `C:\HomisKarteWriter\heartbeat.txt` のまま |
| `config.json` | `C:\HomisKarteWriter` のみ。共有へコピーしない |

Cloud Logging で `RESULT` を拾えば日次の成功率が出せる。

### 5.4 運用の決めごと（2026-09-08 岩城さん）

| 項目 | 決め |
|---|---|
| 最小インスタンス | **0**（都度起動。日中の待機課金はしない。急がない） |
| コンテナ内リトライ | **新規より前だけ 1回**（§7）。`#karteNew` 成功後は禁止 |
| 同じ orderId | 結果シートに既にあれば **書かない**（外からの再送ガード。§7） |
| 撮影完了 Chat | **失敗しても送る。止めない。** 患者ページで出す。空カルテ疑いは文面を分ける（§7.1） |

### 5.5 受け口（フェーズ2a・2026-09-08）

ナビ切替の前に、Cloud Run **サービス** だけ置く。GAS はまだ呼ばない。

| 項目 | 内容 |
|---|---|
| サービス名 | `homis-karte-writer`（Job `homis-karte-writer-test` はそのまま残す） |
| GET `/health` | 合言葉不要。生きているかだけ |
| POST `/write` | ヘッダー `X-Writer-Key`。JSON を受けて **同期で書く**（応答後の裏処理はしない） |
| タイムアウト | Cloud Run 300秒。GAS の60秒制限は 2b（結果シート＋受付202）で避ける |
| 書いてよい患者 | 試験中はテスト3人（舞子 `2277808` / 西宮 `2080376` / 芦屋 `2196689`） |
| 最小インスタンス | 0 |
| 同時実行 | **concurrency 1 は維持**（1箱1 Chrome）。いまの蓋は **3**。運用の上限は **50**（岩城さん 2026-09-08。届かない見込み。蓋の変更は次の指示で） |
| メモリ / CPU | **4Gi / 2**（省略すると 512MB で Chrome が落ちる） |
| タイムアウト | 300秒 |
| 認証（入口） | 合言葉必須。IAM 未認証拒否（`--no-allow-unauthenticated`）も可。2a 試験は curl＋IDトークン |
| デプロイ | 先に `cloud/prepare_cloud_build.ps1` → `C:\HomisKarteCloud` で `gcloud builds submit --tag` → `gcloud run deploy --image`（`--source` は使わない） |
| 2a の試験 | **curl / PowerShell のみ。GAS は繋がない**（UrlFetch 60秒で切れる） |

合言葉・HOMIS ID/PW は Secret Manager。コードに書かない。

### 5.6 同じアカウントの同時書き（2026-09-08 試験）

岩城さん: HOMIS は1アカウントで複数セッション可。Tukusi も並行稼働している。

**2件同時（テスト舞子・同じ患者・`bot_s_interrupt`）**

| 項目 | 結果 |
|---|---|
| Cloud Run | 箱が2つ立った。壁時計 44.8秒（1件ずつなら約85秒） |
| HTTP | 両方 200。手順 STEP も両方 ok |
| karte_id | **両方とも `18325155`**（別カルテになっていない） |

ログイン切れは起きなかった。岩城さん目視: カルテ1枚。Sは「同時書き確認 B」のみ（Aは上書き）。

**時差1件（同じ患者・Bのあと）:** `BOT-GAP-C-20260908-162756` → 200 / karte_id=`18325240`（B とは別）。同じ患者でも **前の1件が終わってから** なら新しいカルテが立つ。

**3秒おき3件（同じ患者・開始 0/3/6秒）:** D・E は両方 200 だが karte_id は同じ `18325289`。F は **429 Rate exceeded**（箱の上限2で3件目が弾かれた見込み）。1件が約40秒なので、3秒差は「終わってから」ではなく同時に近い。

**別患者3人同時（2026-09-08 16:39）:** 舞子 `18325357` / 西宮 `18325358` / 芦屋 `18325356`。3つとも違う。壁時計 46.2秒。同じ患者の同時新規だけが上書き。違う患者なら並行して別カルテが立つ。

運用の上限は **50**（同時に50件まで。min-instances=0 のまま。50件試験はしない）。いまのサービスは蓋 3 のまま。蓋を50にするのは次の指示で。

## 6. ナビ GAS 側の変更

| ファイル | 変更 |
|---|---|
| `Order.gs` | 撮影完了処理で `HOMIS_WRITE_MODE` を見て分岐。`3` なら Cloud Run へ POST し、`HOMIS書込待ち` に orderId と時刻を記録 |
| `HomisCloud.gs`（新規） | Cloud Run 呼び出し、結果シート読み取り、1分トリガー `pollHomisWriteResults`、10分フォールバック |
| `Notification.gs` | 変更なし（`getHomisLink` の直リンク優先をそのまま使う） |
| `Code.gs` | 変更なし（`doPost` は旧Python用に残す） |

集団検診は、全員分の結果が揃った時点（または最後の1件から10分）で既存の一括通知を出す。

## 7. 失敗時の振る舞い（共通マスター・レントゲン／つくし）

レントゲンもつくしも、同じロボット（Cloud Run）で HOMIS に書く。この章が正。個別仕様は参照するだけ。

**原則:** 新規（`#karteNew`）を押したあとは、自動でもう一度書かない。空でもカルテが立つ。

### 7.0 二重防御

| 場所 | 鍵 | 守ること |
|---|---|---|
| コンテナの中 | `karte_opened` | `#karteNew` のクリック成功直後に `True`。以降は中でのやり直し禁止 |
| コンテナの外 | `orderId` | 同じ番号は2回目を書かない（2b の結果シート）。応答なしの再送を止める |

`karte_opened` は **その1回の処理の中** だけ有効。コンテナが落ちると消える。外の再送は orderId が本体。

中のやり直し対象（`karte_opened` が False のときだけ、1回）:

- Chrome 起動失敗
- HOMIS のページに届かない
- ログイン失敗

タイムアウトを種類だけで許可しない。新規後の切れまでやり直すから。

`cloud/server.py` で実装済み（2026-09-08）。`#karteNew` 成功で `karte_opened`。新規前の chrome/login/timeout だけ 1 回。空カルテ疑いは DX エラーChat。受け口は止めない。ナビは未切替。

### 7.1 通知（2026-09-08 岩城さん）

現場は空カルテを消さない／迷う。削除は DX（岩城さん）が行う。

| 行き先 | いつ | 文面の要点 |
|---|---|---|
| **レントゲンの通常 Chat** | 成功も失敗も。従来どおり。止めない | 成功＝直リンク。失敗＝患者ページ。空カルテ疑いなら「新規はしない」 |
| **DX 用エラー Chat** | **空カルテ疑いのときだけ** 追加 | **必ず URL を付ける。** 本文は下の固定文 |

DX 用の送り先は岩城さん指定の Incoming Webhook。**Webhook の key・token は仕様書にもコードにも書かない。** Secret Manager（仮名 `dx-empty-karte-chat-webhook`）に置く。未作成。実装はナビ切替または 2b のとき。

付ける URL は患者ページ（`patient_id`）。`karte_id` が取れていればその直リンク。取れなければ患者ページだけ。

つくしも原則は同じ。DX 固定文だけ変える（§11.4）。

レントゲン通常 Chat の例（空カルテ疑い）:

> 【撮影完了】自動作成が途中で止まりました。**新しく作り直さないでください。** 空カルテの確認は DX が見ます。
> https://homis.jp/homic/?pid=patient_detail&patient_id=（ID）

DX エラー Chat の固定文（レントゲン）:

> レントゲンナビでカルテを空で作成した可能性があるので、確認して空なら削除してください。
> https://homis.jp/homic/?pid=patient_detail&patient_id=（ID）

orderId はログ用に1行足してよい。本文の意味は変えない。

### 7.2 ポイント表

| # | 何が起きた | カルテ | 中のやり直し | 通常 Chat | DX 追加 | AE |
|---|---|---|---|---|---|---|
| 1 | GCPが応答しない | 不明 | しない | 患者ページ。「書いたか未確認。新規しない」 | **する** | 空 |
| 2 | HOMISが開かない | 無い | 1回まで | 患者ページ。「届いていない」 | しない | 空 |
| 3 | ログインできない | 無い | 1回まで | 同上（ロボットログイン） | しない | 空 |
| 4 | Chromeが起動しない | 無い | 1回まで | 同上 | しない | 空 |
| 5 | 患者ページは開いたが新規前 | 無い | 1回まで | 同上 | しない | 空 |
| 6 | **新規のあと**切れた | 空の可能性 | **しない** | 患者ページ。新規しない | **する** | 空 |
| 7 | 入力途中で切れた | 途中の可能性 | **しない** | 同上 | **する** | 空 |
| 8 | 完了したが karte_id なし | **ある** | **しない** | 患者ページ。「書けたが直リンクなし」 | しない | 空 |
| 9 | 同じ orderId の再送 | 1件目があるかも | 2回目は書かない | 1件目の結果に従う | 1件目に従う | — |
| 10 | 許可外の患者ID | 無い | 書かない（403） | 試験中は出ない | しない | 空 |
| 11 | 合言葉誤り | 無い | 書かない（401） | 運用ミス | しない | 空 |
| 12 | 先の1件がまだ書いている | まだ | 待ってから1件。並べて新規は押さない | 待ちすぎたら #1 | #1 ならする | 空 |
| 13 | 垂水 Python と同時ログイン | 不定 | しない（切替まで注意） | ぶつかり疑い | しない | 空 |
| 14 | 呼び出し側だけ先に切れた | 書いてる最中かも | しない。2b で受付と結果を分ける | #1 に同じ | **する** | 空 |

`error_type` の例: `chrome` / `login` / `timeout` / `step:<名前>` / `no_karte_id` / `opened_then_fail`（#6 #7）。ログに患者名・本文・パスワードは出さない。

空カルテの削除は人がやる。自動削除はしない。

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

## 9.6 2026-09-08 受け口2a（サービス）試験

Cloud Run サービス `homis-karte-writer` を出し、curl のみで確認した。GAS は未接続。ナビ切替はしていない。

| 項目 | 値 |
|---|---|
| URL | https://homis-karte-writer-dryyncl3ga-an.a.run.app |
| GET `/health` | 200 |
| POST `/write` 合言葉なし／誤り | 401 |
| orderId | `GCP-TEST-20260908-133908` |
| karte_id | `18323699` |
| URL | https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18323699 |
| 所要 | 47.4秒 |

失敗共通ルール（§7）とつくし呼び方（§11）は仕様済み。2b 試験ブックは `:v3`。二重防止テスト（`GCP-DUP-20260908-144932`）は 1件目 200／2件目 409。ナビ切替は「進めて」待ち。

## 10. 未決事項

- 結果シートは **案B（試験用別ブック）** で確定（2026-09-08）。本番切替時に ID を差し替える
- 集団検診の一括通知タイミング（v0 は「全員揃う or 最後から10分」）
- 旧 Python の停止時期（フェーズ4で決める）

## 11. つくしの呼び方（`fax_so`・仕様のみ・コード未着手）

失敗・二重防止・空カルテは **§7 と 2b が正**。この章は「何を送るか／どのボタンを押すか」だけ。おひさまサーバーのブラウザ操作は使わない。

### 11.1 レントゲンとの違い

| 項目 | レントゲン `xray_karte` | つくし `fax_so` |
|---|---|---|
| 受け口 | 同じ `POST /write` | 同じ。`template` で選ぶ |
| ログイン | 同じロボット1アカウント | 同じ。箱を増やせば並行の余地あり（§5.6） |
| 開くページ | `patient_detail&patient_id={homisId}` | 同じ。つくしキャプチャは `&p=5` 付き。実装はキャプチャに合わせる |
| 新規 | `#karteNew` | 同じ。ここで `karte_opened` |
| 種別 | 外来 | **電話再診**（キャプチャはラジオに `1`） |
| 指示医・日時 | 入れる | **入れない** |
| カルテボタン | 「医科カルテ」 | 同じ（キャプチャは表の5列目リンク） |
| S | `#subjective` ← `sContent` | 同じ（発信元テキスト） |
| O | 触らない | `#objective` ← `oContent` |
| A/P・本日A/P・指導 | A/P に本文。指導は全角スペース | 三つとも全角スペース `　` |
| 完了 | `#karteCompletion` | 同じ |
| 結果 | `karte_id` | 同じ。シート＋HTTP応答 |

### 11.2 送る JSON

必須:

```json
{
  "orderId": "FAX-20260908-001",
  "homisId": "2277808",
  "sContent": "発信元のテキスト",
  "oContent": "患者記録の文章",
  "template": "fax_so"
}
```

| キー | 意味 |
|---|---|
| `orderId` | つくし側で一意。同じ番号は 2b で書かない |
| `homisId` | 患者の入口。つくし `HOMISID.テキスト`。**karte_id 付きURLではない** |
| `sContent` | S欄 |
| `oContent` | O欄 |
| `template` | 必ず `fax_so`。無い／`xray_karte` はレントゲン手順 |

患者名は送ってもよいが、ログとシートには書かない。

### 11.3 手順（YAML に落とす内容・ファイルはまだ作らない）

1. 患者ページへ移動  
2. `#karteNew`  
3. 電話再診（value=`1`。ラベル「電話再診」でも可）  
4. 「医科カルテ」  
5. `#subjective` ← `{sContent}`  
6. `#objective` ← `{oContent}`  
7. `#ap` `#ap_today` `#report` ← 全角スペース  
8. `#karteCompletion`（アラートはレントゲンと同じく自動OK）  
9. `copyLinkOfKarte` で `karte_id`（取れなければ §7 の #8）

### 11.4 通知

通常のつくし側通知（成功／失敗）は、つくし実装時に決める。  
空カルテ疑いの DX 追加は §7.1 と同じ送り先。文面だけこれ:

> つくしでカルテを空で作成した可能性があるので、確認して空なら削除してください。  
> https://homis.jp/homic/?pid=patient_detail&patient_id=（ID）

### 11.5 やること／やらないこと

**やる（実装フェーズ）**

- `templates/fax_so.yaml`
- `POST /write` が `template` を見て YAML を選ぶ
- 試験はテスト舞子のみ。同じ orderId で 409 になること

**やらない**

- おひさまサーバーでのブラウザ操作
- SCAN の本文書き込み（添付＋Chat のまま）
- ナビ切替（フェーズ3）と同時にやらない
- レントゲンと手順を混ぜること
- 人間確認前の自動送信

`templates/fax_so.yaml` と受け口の `template` 分岐は 2026-09-08 実装。未知名は 400。試験はテスト舞子のみ。ナビ未切替。目視: 種別「電話」・S/O 一致（karte_id=18324540）。

### 11.6 GCP 用ログイン（2026-09-08 岩城さん）

Cloud Run の HOMIS ログインは **GCP 用ロボット**（画面上の氏名「おひさまロボット GCP」）。ID/パスワードは Secret Manager のみ。コード・仕様書・引継書に書かない。垂水 Python の `config.json` は触らない。

## 12. おひさまボット（Sのみ・中断）仕様のみ・コード未着手

おひさまボット → つくし（文章）→ 人間確認 → 同じ `POST /write`。今はつくしブラウザ。これも FAX と同じく Cloud Run に寄せる。

キャプチャ名: `HOMIS新規電話再診Sのみ入力中断`（2025/2/14）。失敗ルールは §7。orderId は 2b。

| 項目 | `fax_so`（完了） | `bot_s_interrupt`（中断） |
|---|---|---|
| 種別 | 電話再診 | 同じ（ラジオ `1`） |
| S | 文章 | 文章（ボット本文） |
| O / A/P / 本日A/P / 指導 | Oは文章。他は全角スペース | **半角スペースだけ**（キャプチャどおり） |
| 保存 | `#karteCompletion` | **`#karteInterruption`** |
| JSON | S と O 必須 | **S だけ**（`oContent` 不要） |

```json
{
  "orderId": "BOT-20260908-001",
  "homisId": "2277808",
  "sContent": "おひさまボットの本文",
  "template": "bot_s_interrupt"
}
```

手順: 患者ページ（`&p=5`）→ `#karteNew` → 電話再診 → 医科カルテ → S → O/AP/本日AP/指導に半角スペース → `#karteInterruption` → 可能なら `karte_id`。

中断なので「診察完了」にならない。`karte_id` が取れるかは舞子1件で確認する。取れなければ患者ページだけ返す（§7 #8 に近い）。

DX 空カルテ文面（中断の失敗時）:

> おひさまボットでカルテを空で作成した可能性があるので、確認して空なら削除してください。

**やらない:** おひさまサーバーのブラウザ、人間確認前の送信、`fax_so` と手順を混ぜること。

`templates/bot_s_interrupt.yaml` は 2026-09-08 実装。試験はテスト舞子のみ。

## 更新履歴

| 版 | 日付 | 内容 |
|---|---|---|
| v0.20 | 2026-10-15 | 0章「版の管理」を新設（モジュール別の版・改定履歴・Cloud Run のデプロイ履歴）。v3.1.0: 書き終えたらナビの doPost に知らせる・/check-group（GCP 移行計画 v0.4 フェーズ1） |
| v0.19 | 2026-09-08 | 運用上限は50件で考える。蓋の適用と50件試験はしない |
| v0.18 | 2026-09-08 | §5.6 別患者3人同時。karte_idが3つ。max-instances=3 |
| v0.17 | 2026-09-08 | §5.6 3秒おき3件。D/E同ID、Fは429。箱上限2 |
| v0.16 | 2026-09-08 | §5.6 時差Cは別カルテ 18325240。同時は同じ患者だと上書き |
| v0.15 | 2026-09-08 | §5.6 同じアカウント2件同時。箱は並行、karte_idは同一。max-instances=2。10は未実施 |
| v0.14 | 2026-09-08 | §12 実装。bot_s_interrupt.yaml。中断＋半角スペース |
| v0.13 | 2026-09-08 | §11.6 GCP用ログインはSecret。§12 ボット中断 `bot_s_interrupt`。コードなし |
| v0.12 | 2026-09-08 | §11 実装。fax_so.yaml・template分岐。未知名400 |
| v0.11 | 2026-09-08 | §11 つくし `fax_so` を手順・JSON・DX文面まで書いた。コードなし |
| v0.10 | 2026-09-08 | §5.2 案B。受付行先行。RESULT_SPREADSHEET_ID。GAS未接続 |
| v0.9 | 2026-09-08 | §7 を server.py に実装。karte_opened・DX固定文。デプロイは同日 |
| v0.8 | 2026-09-08 | §7.1 DXエラーChat。固定文＋患者URL必須 |
| v0.7 | 2026-09-08 | §7 失敗共通マスター。新規前だけ1回。orderIdは外の再送。空カルテは現場に新規禁止＋DX追加連絡。§11 つくし `fax_so` |
| v0.6 | 2026-09-08 | §9.6 2aサービス試験。舞子 karte_id=18323699。Dockerfile COPY を `./` に修正 |
| v0.5 | 2026-09-08 | §5.5 デプロイ条件。4Gi/concurrency1/max-instances1。準備スクリプト |
| v0.4 | 2026-09-08 | §5.5 受け口2a。同期POST。舞子のみ。ナビ未切替 |
| v0.3 | 2026-09-08 | §5.4。min-instances=0。Chatは止めない。orderId二重防止 |
| v0.2 | 2026-09-07 | §5.3 垂水実装。共有 HomisKarteWriter\\logs に STEP/RESULT |
| v0.1 | 2026-09-04 | GCP試験成功。karte_id=18302640。来週は詳細ログ先行 |
| v0 | 2026-09-04 | 初版。構想・スコープ・流れ・切替・フェーズ |
