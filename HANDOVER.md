# Homis自動カルテ生成 引継ぎ書

> **最終更新**: 2026-10-29 17:35
> **バージョン**: v2.1.3 GUI / Watchdog v2.1.4 / ライター Cloud Run v3.3.0（`:v11`・リビジョン 00016-stc）/ FAX 受け口 v0.3.1（00006-lsl）/ 仕様 SPEC_v3_cloud.md 0章が台帳
> **2026-10-29 FAX カルテ段3の準備が完了・本番切り替えは 11/2（月）9時**: ライター 3.2.0 で「書いたあと読み直す」（verify_karte.py・完了か・S/O が送ったとおりか・合わなければ失敗にして DX へ）、3.3.0 で本番の FAX の失敗を「カルテ失敗」スペースにも（Secret `fax-field-chat-webhook`）。受け口 0.3.0 で FAX_MODE（off／mirror／live）・0.3.1 で「おひさまシステムの患者」と「OhiScanGo の患者」の照合（same のときだけ書く）。列 `homis-fax-writer`（maxAttempts=1・同時1）を新設。今は FAX_MIRROR=on＝練習（テスト舞子だけに書く）。入れ直しの道具 tools\fax_requeue.py・空のカルテを探す道具 tools\find_stuck_kartes.py。詳細と当日の1行は docs\FAXカルテ_検討\SPEC_段3_本番切替.md 10c と HANDOVER_FAXカルテ.md
> **2026-10-28 FAX 段1b 並走の試し書きを開始**（受け口 0.2.0・列 homis-fax-mirror）。10/28〜29 で約90件すべて書けた・本物と照合できた分は S/O 一致
> **ステータス**: 🟢 **10/15 17時 レントゲンのカルテ書き込みを GCP（Cloud Tasks＋Cloud Run v3.1.1）へ切り替え**。垂水 Python v2.1.3 は往診のため稼働中。戻すときは値だけ変えない（下の表）
> **2026-10-26 FAX のカルテを GCP へ移す検討を始める**（岩城さん・別スレッド）: 引継書は docs\FAXカルテ_検討\HANDOVER_FAXカルテ.md（Google ドライブだけに置く・公開リポジトリには入れない）。現場の要望「算定不要にチェック」もそこに
> **2026-10-26 18:00 FAX 段1 の受け口を GCP に置いた**: Cloud Run `homis-fax-receiver`（v0.1.2・リビジョン 00001-dnm・誰でも届き中で合言葉・カルテは書かない・様子だけ記録）。専用アカウント `fax-receiver`・Secret `fax-receiver-key`（版2）・像は置き場 `homis-karte-writer` に `homis-fax-receiver:v0.1.2`。ソース `cloud_fax_receiver\`・突き合わせ `tools\fax_shadow_reconcile.py` v0.1.3。黒ヤギ6回【進めてよい】・テスト26件・security-check 問題なし。段0 は a・b・d・e 合格、残り c。本番 WF1573 には未接続。今のライター `homis-karte-writer` は触っていない

---

> **2026-10-21 確認**: 10/18〜10/21 は撮影完了が0件（書く仕事が無いだけ・列 RUNNING・残り0）。v3.1.2 後の本番はまだなので、並行運用の見届けは次の撮影完了まで延長。うまくいったら **Tukusi のカルテロボットを GCP へ移す**（岩城さん 10/21）。

> **2026-10-24 中身の確かめ**: tools\verify_gcp_kartes.py（読むだけ・表示専用ページとカルテ一覧だけ GET・患者名を出さない）で GCP の10件を突き合わせ: 指示医・診察日・時刻・1枚だけ＝10件一致／外来＝8件（10/16 個別2件は定期のまま＝v3.1.2 前の件）／**A/P の LookREC リンク9件が ¤ に化けていた**＝ロボットではなく HOMIS の編集画面のせい（人が開いて保存すると化ける・テスト舞子で実証）→ レントゲンナビ v8.11.1（@91）でリンクの並びを変えて対策。集団7件は部位が手で AP（坐位）に直されていた。S 欄は読める画面が無い。種類の番号は 10＝外来・0＝定期（一覧の type を使う。表示ページの karte_type 14・15 は処方のフォーム）。黒ヤギ【進めてよい】。**次: ロボットが保存のあとに同じ確かめを毎回する（岩城さん「ロボットで画面をみるように」）**
> **2026-10-24 過去の壊れたリンク**: tools\count_broken_lookrec.py（読むだけ）で数えると 238件中 壊れている164・正しい71・リンク無し3。直す道具 tools\fix_lookrec_links.py（編集→リンクだけ入れ替え→完了・書く前に控え・6項目の確かめ）をテスト舞子で試し、直る・再編集でも壊れないまで確認。黒ヤギ【進めてよい（夜間・更新者が api に変わる合意が前提）】。**ただし岩城さん「過去のは直さなくていい」で本番には使わない**（道具は残すだけ）。これからの分は v8.11.1 @91 で防ぐ

## 🚧 2026-10-15 フェーズ0・1 完了（本番はまだ垂水 Python）

| フェーズ | 状態 |
|---|---|
| 0 ナビの JSON のファイル名に注文番号 | ✅ ナビ v8.9.4 を本番 @89（10/15 13:54）。次の撮影完了で垂水の watcher ログに新しい名前が出るか確かめる |
| 1 Cloud Run が書いたらナビに知らせる・Cloud Tasks | ✅ cloud v3.1.0（:v6・リビジョン 00010-gxq・黒ヤギ合格・テスト17本）。Cloud Tasks API 有効化、キュー `homis-karte-writer`（同時1・再試行なし・記録100%）、列専用アカウント `homis-tasks-invoker`（run.invoker だけ）、環境変数 NAVI_WEBAPP_URL＝ナビ本番 |
| 通し試験 | ✅ GCP-P1-20261015-142550: 列 → Cloud Run → テスト舞子に書けた（50.6秒・karte_id あり）→ ナビへ知らせ（1回で届く。試験用の番号なのでナビは「見つからない」）→ DX Chat 200（わざと） |
| 【確認】 | 1回目の試験タスク（GCP-P1-20261015-142239・14:22:50）は列から消えたが Cloud Run に届いていない。列の記録を有効にする前で原因不明。フェーズ3 で見張る |
| 2 ナビ側 | ✅ ナビ v8.10.0 を本番 @90（16:21・MODE 未設定＝垂水のまま）。v8.11.0（GAS エディタ用: testHomisCloudOnce・requeueHomisTasksToTarumi(_apply)）は push 済み・デプロイ不要。黒ヤギ合格 |
| ナビからの通し試験 | ✅ 16:44 岩城さんが testHomisCloudOnce → GCP-NAVI-20261015-164426: ナビ→列→Cloud Run→テスト舞子に書けた（49.5秒・karte_id）→ナビ本番へ知らせ（1回・見つからない）→DX Chat 200 |
| 3 切り替え | ✅ **10/15 17:0x 本番を GCP へ切り替え**（岩城さんが HOMIS_WRITE_MODE=3・岩城さん判断で今日の夕方）。直前に cloud v3.1.1（:v7・00011-xqv・ALLOWED_HOMIS_IDS="*"・黒ヤギ合格）、垂水のフォルダ未処理0件（17:01）、列 RUNNING・maxAttempts 1・同時1 を確認。列の一時保存は「保存しない」の範囲と岩城さん了承（10/15） |
| ✅ 10/19 外来の直し | 10/16 本番の個別2件で「外来を選択」が押せず（覆いで intercepted）種別が定期のまま保存 → cloud v3.1.2（:v8・18:12）: 押せるまで待つ・JavaScript で押す・選べたかの確認・手順の失敗は DX Chat。本物の Chrome で覆いのテスト（直す前は赤）・黒ヤギ合格・テスト舞子で確認 OK。**残り: 10/16 の2件のカルテの種別を HOMIS で外来に直す（岩城さん）／垂水（共有の配置先）への同じ版の配置は未（往診だけなので急がない）** |
| ⚠️ 垂水の版 | 垂水の Python（往診を書いている）は、押し方の部品（src/browser_actions.py・template_engine.py）が古い版のまま（共有の配置先は 10/19 時点で未更新）。往診の手順に「外来を選択」は無いので急がない。**次に垂水の Homis ライターを更新するときに一緒にそろえる**（岩城さん 10/19 了承） |
| ✅ 朝の確認 | 10/19 から朝の集計（tools/startup/morning_fetch.py v1.1.0）に「レントゲンのカルテ書き込み（GCP）」の件数が出る。⚠️ の日は報告に書く |
| ⚠️ 戻すとき | **値だけ 1 にしない**（列に残った注文を Cloud Run が後から書いて二重になる）。白ヤギが 列を PAUSED → 書いている1件を待つ → requeueHomisTasksToTarumi_apply → 岩城さんが MODE=1 の順（計画書 5章） |
| 次 | 最初の本番の撮影完了で: 列に入った・Cloud Run の RESULT・ナビへの知らせ・撮影完了 Chat を見届ける。1週間の並行運用で失敗の種類を数える（垂水 Python は往診のため動かしたまま） |

- Cloud Run は NAVI_WEBAPP_URL があるので、/write で書くとナビ本番に知らせる。書いてよい患者はテスト3人だけ（ALLOWED_HOMIS_IDS）なので、本番の注文には影響しない
- タスクの入れ方（試験）: 合言葉は `gcloud secrets versions access latest --secret=homis-writer-key` を変数に入れて画面に出さない。`gcloud tasks create-http-task <orderId> --queue=homis-karte-writer --location=asia-northeast1 --url=<サービスURL>/write --method=POST --header=Content-Type:application/json --header=X-Writer-Key:<変数> --body-file=<JSON> --oidc-service-account-email=homis-tasks-invoker@gen-lang-client-0979357970.iam.gserviceaccount.com --oidc-token-audience=<サービスURL>`

---

## 🗺️ 2026-10-14〜15 GCP 移行計画（レントゲン分）v0.4 確定

- 計画書: `docs/PLAN_v3_GCP移行計画.md`（v0.1→v0.4・黒ヤギ3回目【進めてよい】・commit 181a8c7）。今日は計画だけ（岩城さん 10/14「今週どこかで処理」）
- きっかけ: 岩城さん「homisライターも穴ないですか？運用上の」→ 今の垂水 Python に運用の穴8つ（同じ患者・同じ日の2件目が書かれない／途中で落ちると二重／ナビへの知らせ失敗で Chat が出ない ほか。計画書1章に行番号つき）
- 決めたこと: ナビ → **Cloud Tasks の列（東京・同時1・再試行0）** → Cloud Run → 書いたらナビの doPost（今の垂水と同じ流れ・時間トリガーなし）。二重 Chat は CacheService の印。集団の予備は列の予約で doPost「checkGroupComplete」。戻すときは7段の手順
- フェーズ: 0 つなぎ（ナビの JSON のファイル名に注文番号・1h）→ 1 Cloud Tasks・Cloud Run の知らせ → 2 ナビ（HomisCloud.gs ほか）→ 3 並行・切り替え（平日朝）→ 4 往診の移行は別計画（往診も垂水 Python を使うので、それまで垂水は止めない）
- 【確認】列の中の一時保存（東京・届けたら消える）が「保存はしない」（9/4 決定）の範囲に入るか（岩城さん）
- 10/14 19:23 に本番のカルテ1件（RESULT success・karte_id あり）→ ナビへの知らせ成功（ナビ @88 で doPost が通ることを確認）

---

## 📌 C1 置き場所（2026-09-07 岩城さん）

レントゲンカルテの画面操作は **GCP（Cloud Run・東京）** に置く。おひさまサーバー案は不採用（Chrome切れが残る）。HomisApi・つくしブラウザは使わない（既存の決めごと）。

切替までは垂水 Python が正。ナビの `HOMIS_WRITE_MODE=3` は「進めて」があってから。この決定だけでは Chrome を止めない。

---

## 📝 v2.1.3 詳細ログを共有へ（2026-09-07）

岩城さん指示: 成功/失敗をステップ単位で残す。人が読むログは全部 `HomisKarteWriter\logs`。フォルダ統合はしない。`config.json` は共有に置かない。

| 出す | 出さない |
|---|---|
| `STEP 名前 ok/fail 秒` | 患者名 |
| `RESULT {orderId, success, has_karte_id, error_type, total_sec, karte_id}` | S/AP本文・パスワード |

- 置き場: `G:\共有ドライブ\レントゲンオーダー\HomisKarteWriter\logs\`
  - `writer_YYYYMMDD.log` … STEP / RESULT
  - `watcher_YYYYMMDD.log` … 従来ログ（書いた日で切る。1行ごとに開いて閉じる）
  - `watchdog.log` / `heartbeat.txt` / `startup_error.log` … 閲覧用コピー
- Watchdog 判定の心拍は **`C:\HomisKarteWriter\heartbeat.txt` のまま**（Drive遅延で誤再起動しない）
- Watchdog.bat は ASCII のまま。共有へは `C:\HomisKarteWriter\shared_logs` ジャンクション経由
- 本番 CODE_DIR はこれまでどおり **Homis転記実行ファイル**。コードは両フォルダへ同じ版を置いた
- `config.json` は上書きしていない
- **C:\HomisKarteWriter のプログラムも最新にする**（2026-09-08 岩城さん。以前「設定だけ」と止めたのは誤り。2月の watcher 等が残っていた）。設定・心拍・ログは触らない。共有の `update_c_drive.bat` を垂水で1回実行

**垂水で効かせるには:** アプリを終了 → タスクの Watchdog が `start_gui.vbs` で再起動。トレイタイトルが **v2.1.3** なら新版。

---

## 🧪 v3 フェーズ2a 受け口（2026-09-08）※ナビ未切替

Cloud Run **サービス** `homis-karte-writer` を東京に出した。GAS は繋いでいない。

| 項目 | 値 |
|---|---|
| URL | `https://homis-karte-writer-dryyncl3ga-an.a.run.app` |
| イメージ | `.../homis-karte-writer/homis-karte-writer:v1` |
| 資源 | 4Gi / 2CPU / timeout 300 / concurrency 1 / max-instances 3 / min-instances 0 |
| 合言葉 Secret | `homis-writer-key`（値は書かない） |
| GET `/health` | 200 `{"ok":true,"service":"homis-karte-writer"}` |
| POST `/write` 合言葉なし／誤り | 401 |
| 書き込み | `GCP-TEST-20260908-133908` / karte_id=`18323699` / 47.4秒 |
| カルテ | https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18323699 |

ビルド時: Dockerfile の `COPY write_once.py server.py .` は Cloud Build で失敗。`./` に直した。

### 失敗の共通ルール（2026-09-08・仕様 v0.7）

正本は `docs/SPEC_v3_cloud.md` §7。レントゲンもつくしも同じ。

- 新規より前だけ、中で1回やり直す。`#karteNew` のあと（`karte_opened`）は禁止
- 外からの再送は `orderId`（2b）。旗だけでは応答なし再送を止められない
- レントゲンの通常 Chat は従来どおり（失敗しても送る）
- 空カルテ疑いは現場に「新規しない」。**現場は消さない**。そのときだけ DX エラー Chat を追加
- DX 文面（固定）: 「レントゲンナビでカルテを空で作成した可能性があるので、確認して空なら削除してください。」＋ **患者URL必須**
- DX の Incoming Webhook は Secret に置く。URL は引継書に書かない（2026-09-08 岩城さんから受領）

### §7 実装（2026-09-08・コード）

`cloud/server.py` のみ（垂水の template_engine は未変更）。

- `#karteNew` 成功で `karte_opened`。新規後は中でやり直さない
- 新規前の chrome/login/timeout だけ 1 回
- 空カルテ疑い（新規後・karte_id なし・`no_karte_id` 以外）→ DX 固定文＋患者URL
- 環境変数 `DX_EMPTY_KARTE_WEBHOOK`（Secret。値は書かない）
- 空カルテをわざと作る試験はしない

### 2b 試験ブック（2026-09-08・案B）

本番ナビのブックは触っていない。

- ブック: `HOMIS書込結果_試験_CloudRun`  
  https://docs.google.com/spreadsheets/d/1_K0W0r_1HT7EzZz0QsMVbw6MDL7bVMGRChPI28xRI7w/edit
- ロボットSA（Compute）に編集権限済み
- 先に `accepted` 行 → HOMIS → 同じ行を更新。同じ orderId は書かない
- 環境変数 `RESULT_SPREADSHEET_ID`
- GAS は未接続

二重防止テスト（2026-09-08 14:49）:

| 回 | HTTP | 所要 | 結果 |
|---|---|---|---|
| 1 | 200 | 48.7秒 | karte_id=`18324342`。シート `ok` 1行 |
| 2 | 409 | 1秒 | HOMIS未ログイン。シートは1行のまま |

オーダー: `GCP-DUP-20260908-144932`  
カルテ: https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18324342

### fax_so 実装（2026-09-08）

- `src/templates/fax_so.yaml`（電話再診・S/O・空欄は全角スペース）
- `POST /write` の `template`。未知名は 400。無いときは `xray_karte`
- 試験: 未知名 400。`FAX-SO-20260908-150917` → 200 / karte_id=`18324540` / 47.1秒
- カルテ: https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18324540
- つくし WF は未接続。垂水共有は未更新（クラウドのみ）
- 目視: 種別「電話」・S/O 一致（岩城さん 2026-09-08）
- Cloud Run の HOMIS は **おひさまロボット GCP** に差し替え（Secret のみ。PWは書かない）。垂水 `config.json` は未変更
### bot_s_interrupt 実装（2026-09-08）

- `src/templates/bot_s_interrupt.yaml`（電話再診・Sのみ・中断・半角スペース）
- 試験: `BOT-INT-20260908-153206` → 200 / karte_id=`18324776` / 43.6秒
- カルテ: https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18324776
- 中断でも karte_id は取れた。目視（電話・中断・更新者 GCP）は岩城さん待ち
- おひさまボット／つくし本番は未接続

### 2件同時試験（2026-09-08 16:13）

`max-instances=2`（concurrency 1 のまま）。同じアカウント・同じテスト舞子へ `bot_s_interrupt` を2本同時。

| 項目 | A | B |
|---|---|---|
| orderId | `BOT-DUAL-A-20260908-161323` | `BOT-DUAL-B-20260908-161323` |
| HTTP | 200 | 200 |
| 箱の中の秒 | 40.9 | 43.8 |
| karte_id | `18325155` | **同じ** `18325155` |
| 壁時計 | 両方合わせて **44.8秒**（1件ずつなら約85秒） | |

箱は2つ（インスタンスIDが違う）。ログイン切れなし。STEP は両方とも最後まで ok。

岩城さん目視: カルテ1枚。Sは「同時書き確認 B」のみ。Aは上書き。

**やっていない:** `max-instances=10`。違う患者同士の同時書き。

カルテB: https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18325155

### 時差確認 C（2026-09-08 16:27）

同じテスト舞子へ、Bのあと時間を空けて1件だけ。

| 項目 | 値 |
|---|---|
| orderId | `BOT-GAP-C-20260908-162756` |
| HTTP | 200 |
| 秒 | 37.8（壁時計 40.2） |
| karte_id | **`18325240`**（B の `18325155` とは別） |

同じ患者でも、間を空ければ新しいカルテが立つ。

カルテC: https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18325240

### 3秒おき3件（2026-09-08 16:31）

同時一発ではなく、開始を 0秒 / 3秒 / 6秒。同じテスト舞子。1件が約40秒なので、後ろは前の書き込み中に始まる。

| | D | E | F |
|---|---|---|---|
| orderId | `BOT-GAP3-D-20260908-163148` | `BOT-GAP3-E-20260908-163148` | `BOT-GAP3-F-20260908-163148` |
| HTTP | 200 | 200 | **429 Rate exceeded** |
| 箱の中の秒 | 39.3 | 40.9 | （書いていない） |
| karte_id | `18325289` | **同じ** `18325289` | なし |

壁時計 44.9秒。箱の上限が2のため、3件目は待ち行列で弾かれた見込み。同じ患者の3秒差は、同時と同じく1枚に寄る。

カルテ: https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18325289

### 別患者3人同時（2026-09-08 16:39）

許可リストをテスト3人に拡大。箱の上限を3。同じ瞬間に3本。

| 患者 | homisId | orderId | HTTP | karte_id |
|---|---|---|---|---|
| テスト舞子 | 2277808 | `BOT-3P-MAIKO-20260908-163917` | 200 | **18325357** |
| テスト西宮 | 2080376 | `BOT-3P-NISHI-20260908-163917` | 200 | **18325358** |
| テスト芦屋（あしや） | 2196689 | `BOT-3P-ASHIYA-20260908-163917` | 200 | **18325356** |

壁時計 **46.2秒**（1件ずつなら約2分）。カルテIDは3つとも違う。

- 舞子: https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18325357
- 西宮: https://homis.jp/homic/?pid=patient_detail&patient_id=2080376&karte_id=18325358
- 芦屋: https://homis.jp/homic/?pid=patient_detail&patient_id=2196689&karte_id=18325356

### 運用上限（2026-09-08 岩城さん）

同時の上限は **50件** で考える。届かない見込み。いまのサービスは蓋 **3** のまま（50にはしていない。50件試験もしない）。蓋を50にするのは次の指示で。`min-instances=0` は変えない。

### 次にやること

1. **垂水デスクトップ確認は来週へ**（急ぎではない。岩城さん 9/11: Python は動いていそう）。見るならタイトル v2.1.3／監視中／Chrome・心拍。`config.json` は触らない
2. 蓋を `max-instances=50` にするかは指示待ち（今日の検証は停止）
3. つくし／ボット側の JSON 送信は別指示
4. ナビ切替（`HOMIS_WRITE_MODE=3`）は「進めて」があってから

---

## 🧪 v3 GCP Job試験（2026-09-04）※ナビ未切替

Cloud Run Job から、レントゲンナビと同じ JSON 形でテスト舞子（2277808）に1件書けた。岩城さん目視で S/AP・時刻・指示医「山口 高秀 // 内科」まで入っていた。

| 項目 | 値 |
|---|---|
| オーダー | `GCP-TEST-20260904-104419` |
| karte_id | `18302640` |
| URL | https://homis.jp/homic/?pid=patient_detail&patient_id=2277808&karte_id=18302640 |
| 所要 | 約45秒 |
| 仕様 | `docs/SPEC_v3_cloud.md` |

本番の垂水 Python は**止めていない**。ナビ切替もしていない。

### GCP設定（プロジェクト `gen-lang-client-0979357970` / 東京）

| 種類 | 名前 |
|---|---|
| Secret Manager | `homis-karte-user` / `homis-karte-password` / `homis-writer-key`（東京） |
| Artifact Registry | `homis-karte-writer`（Cloud Build SA と Compute SA に writer） |
| サービス | `homis-karte-writer`（受け口 2a。`--no-allow-unauthenticated`） |
| いまの蓋 | **max-instances=3** / concurrency 1 / min-instances 0。運用上限は **50**（未適用） |
| 書いてよい患者 | `ALLOWED_HOMIS_IDS=2277808,2080376,2196689`（テスト舞子／西宮／芦屋） |
| Job（残置） | `homis-karte-writer-test`（4Gi / 2CPU / 5分 / 再試行0） |
| イメージ | `.../homis-karte-writer/homis-karte-writer:v1`（サービス）／ `...-test:v0`（Job） |
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
