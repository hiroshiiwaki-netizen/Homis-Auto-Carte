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
| server.py | 3.12.0（未配置。本番は 3.11.0＋browser_actions 1.5.0 の v22・00029-ht7） | 2026/11/06 | 受け口（/health・/write・/check-group）・失敗ガード。3.1.3: 途中の手順の失敗を DX に知らせる文を型紙ごとに。3.2.0: FAX は書いたあと読み直して確かめる（合わなければ失敗・DX へ）。3.3.0: 本番の FAX（FAX-…）が書けなかったら現場用スペースにも。3.4.0: 新規が開かなければ止める。3.5.0: 問い合わせ（BOT-…・中断）を読み直し・現場の知らせを型紙ごとに。3.6.0: 型紙の stop_on_fail の手順が失敗したら保存せずに止め、1回だけやり直す（2回とも止まれば stopped:unverified_input）。3.7.0: 前の書きかけが新規で戻ったら書く前に止める（blocked:reused_editing・全型紙）。3.8.0: 新規で「入力途中のカルテ」と止められたら 90 秒あけて1回だけやり直す（FAX・問い合わせだけ・時間が足りなければやらない）。3.9.0: 患者さんごとの札（patient_lock）を新規の前に取り、書き終わりで外す。取れなければ locked:busy／locked:error で書かない。3.11.0: 実行リストの記録（run_record）に accepted と結果・left_in_homis を足す。3.12.0: 書込失敗の自動やり直し（auto_retry）・書込後確認を記録 |
| auto_retry.py | 1.0.0（未配置） | 2026/11/06 | 書込失敗の自動やり直し。やってよい失敗（left none＋locked・入力途中・知らせ・ログイン等）だけ -A1/-A2/-A3 を 5/15/30 分後に同じ列へ予約。回数は ^(.*)-A([1-3])$・上限 3。カルテ一覧の一番大きい番号で人が書いた見込みを見る（数で比べる・読めなければ止める）。RETRY_MODE=on のときだけ |
| run_record.py | 1.0.0（未配置・受け口と同じ中身） | 2026/11/06 | 実行リストの記録（1注文＝1 JSON・Cloud Storage RECORD_BUCKET の records/<日付>/<注文番号>.json）。空なら何もしない。create（無いときだけ）・update（世代つき・先を越されたら1回やり直す）。1回 5 秒まで（受け口は 3 秒）・失敗後 60 秒は書かない・例外は外に出さない |
| patient_lock.py | 1.0.1（本番 v19） | 2026/11/05 | 患者さんごとの札。Cloud Storage（LOCK_BUCKET）に locks/<患者番号> を「無いときだけ作る」で置く。期限 300 秒（作成時刻＋）・札待ち 320 秒・5 秒おき。期限切れは世代指定で消して取り直す。404/412 は正常な競合、401/403・5xx 連続だけ error |
| verify_karte.py | 1.3.0（未配置。本番は 1.2.0） | 2026/11/06 | 書いたカルテを別のログインで ajax_karte_show（読むだけ）から読み直し、完了（状態 3・5・6・7）か・S/O が送ったとおりかを返す。編集画面は開かない。1.1.0: 問い合わせは中断・更新者がライター自身を合格の条件に。1.3.0: 問い合わせで、読み直したときもう完了・更新者がライター以外・S 一致なら ok_processed（書いた直後に人が処理・書込成功） |
| navi_callback.py | 3.2.0（本番 v20） | 2026/11/05 | ナビの doPost への知らせ（再送・DX Chat） |
| result_sheet.py | 3.0.0 | 2026/09/08 | 結果シート（orderId の二重を断る）。先頭の版は次に直すときに書く |
| write_once.py | 3.0.0 | 2026/09/04 |
| src/templates/fax_so.yaml（同上） | 1.1 | 2026/10/27 | FAX カルテ（電話再診・S/O）。1.1 で「算定不要を押す」を足し、電話再診に verify_checked。未配置（cloud v3.1.3 で配置予定） |
| src/templates/bot_s_interrupt.yaml（同上） | 1.3（未配置。本番は 1.2） | 2026/11/06 | 問い合わせ・疑義照会（電話再診・S だけ・中断）。1.3: 医科カルテのあと「算定不要が付いていれば外す」（verify_unchecked）。1.1: 電話再診に verify_checked・S に verify_value・保存の直前に「S欄をもう一度確かめる」（11/4 問い合わせ 0017 で S が空のまま中断で保存された）。1.2: S の2手順に stop_on_fail（確かめられなければ保存しない） |
| src/browser_actions.py（cloud にコピー・垂水と共通） | 1.5.0（未配置。本番は 1.4.0・垂水は古いまま） | 2026/11/06 | 1.5.0: click に verify_unchecked（印が付いていれば外して確かめる・無ければ押さない・箱が3秒無ければ何もしない）。1.4.0: js_input に verify_value（見える欄が出るまで最大10秒待つ・0.5秒おいて読み返す・違えば入れ直す・入らなければ手順の失敗。無い js_input は今までと同じ）。1.3.0: id で探して押す click にも verify_checked（押す前から印があれば押さない・JavaScript で押しても onclick が動く）。未配置。1.2.0 までの説明: | 文字で探して押す: 待つ・JavaScript で押す・選べたかの確かめ・かぶさった物の記録 |
| src/template_engine.py（同上） | 1.1.0 | 2026/10/19 | 失敗した手順を failed_steps で全部返す |
| src/templates/xray_karte.yaml（同上） | 2026/10/19 | 2026/10/19 | 「外来を選択」に verify_checked | Job の手動試験。先頭の版は次に直すときに書く |

FAX カルテの受け口（cloud_fax_receiver/・別の Cloud Run・仕様 `docs/FAXカルテ_検討/SPEC_受け口_横付け_v0.md`）

| ファイル | 版 | 最終更新 | 役割 |
|---|---|---|---|
| cloud_fax_receiver/server.py | 0.6.0（未配置。本番は 0.5.2・00013-2c2・BOT_MODE=live・BOT_QUEUE=homis-bot-writer） | 2026/11/06 | 段1: Tukusi WF1573 の横付けから受け取り、様子だけ記録。0.2.0（段1b）: FAX_MIRROR=on のとき同じ中身をテスト舞子あての仕事として列 homis-fax-mirror に入れる。0.3.0（段3）: FAX_MODE＝off／mirror／live。live は本物の患者さんあての仕事を列 homis-fax-writer へ・仕事にできなければ現場と DX に知らせる。0.4.0: 問い合わせの口 /bot/receive（BOT_MODE＝off／test／live・既定 off）。0.5.0: 仕事に dispatchDeadline 900s・問い合わせは BOT_QUEUE（空なら LIVE_QUEUE）。0.6.0: 実行リストの記録（received・rejected）・仕事に recordDay |
| cloud_fax_receiver/run_record.py | 1.0.0（cloud/run_record.py の写し） | 2026/11/06 | 上と同じ |
| tools/fax_requeue.py | 0.1.1 | 2026/10/29 | 段3 の切り替えの間に来た FAX を、札番号→p281 の札の記録で患者さん→試し書きの S・O→本物に同じものが無いのを見てから列に入れる（既定は見るだけ・--go で入れる） |
| tools/compare_fax_mirror.py | 0.1.0 | 2026/10/28 | 試し書き（テスト舞子）と Tukusi の本物のカルテを HOMIS の表示専用ページで読み、S・O が同じか比べる（読むだけ・結果は札番号の末尾と一致／不一致だけ） |
| tools/fax_shadow_reconcile.py | 0.1.3 | 2026/10/26 | 受け口のログと p281 の「カルテ順番札」を札番号で突き合わせる（読むだけ） |
| app-kartelog/（main.go・auth.go・store.go・api.go・patient.go・public/） | 0.3.0（未配置。本番は 0.2.2・kartelog-00008-jqj） | 2026/11/06 | 実行リスト（app.nhw.jp/kartelog/・PWA・仕様 docs/SPEC_実行リスト_v0.md v0.4）。第1段は読むだけ: 記録の JSON を日ごとに読み、タブ・しぼり込み・詳しい窓。IAP の署名を箱でも確かめる・試験の行は DX推進部だけ（DX_ADMINS）・列が読めれば「止まっているかも」を列と時刻で決める |
| tools/find_stuck_kartes.py | 0.1.0 | 2026/10/29 | Tukusi が開いたまま保存できずに残った「空のカルテ」（S も O も空・状態 編集中／中断／完了）を、p281 の札と HOMIS の ajax_karte_show で探す（読むだけ・番号は --ids のときだけ） |

### 0.2 改定履歴（新しい順）

| 版 | 日付 | 主な変更 | 変えたファイル |
|---|---|---|---|
| v3.12.0・auto_retry 1.0.0・実行リスト 0.3.0（未配置） | 2026/11/06 | 書込失敗の自動やり直し（仕様 docs/SPEC_実行リスト_v0.md v1.2 14章・黒ヤギ仕様3回【進めてよい】・岩城さん「何回かリトライして駄目なら人間」「3回・5/15/30分」「成功は知らせない・一覧で何分以内に再試行・本当にだめな分は手動」）。ライター: 失敗を確定したら _field_notice で振り分け（1回目＝先頭に【手で書かずにお待ちください】＋自動でやり直す旨／途中＝DX だけ／3回ともだめ＝「自動で3回やり直しましたが書けませんでした。手で書いてください」）。札を外す前にカルテ一覧の一番大きい番号を控え、_schedule_retry で同じ列に予約（scheduleTime）。入れられない・控えが取れない＝「自動でやり直せませんでした。手で書いてください」＋manual。やり直し（-A1〜）は書く前に控えより新しいカルテが無いか見て、あれば skipped:new_karte_found（現場に出さない・DX に番号つき）、一覧が読めなければ skipped:karte_list_unreadable（手で・manual）。記録に handed_over・scheduled（retry_at・attempt）・manual・verify・baseline_karte_id。読み直しの結果を時刻の流れに「書込後確認 ○／×／未確認（カルテは保存済み）」。実行リスト: ↻ 自動で再書込へ（数えない）・⏳ 自動で再書込（時刻まで・あと何回）・✋ 手動でお願いします・☑ 人が書いた見込み（ボタンなし）・書込後確認の出し分け・予約から 15 分過ぎて列にも無ければ止まっているかも。音声カルテのタブはできるまで外した（2 行に折れるため）。テスト: test_auto_retry 15件（部品5: 回数・どこから始めても3回で止まる・やってよい失敗の表・予約の形・数で比べる／流れ10: 1回目の案内と A1 予約・途中は DX だけで A2 は15分後・A3 で手で・人が書いた見込みは書かず現場に出さない・一覧が読めない・入れられない・控えが取れない・RETRY_MODE off は今まで通り・やってはいけない失敗・成功は現場に出さない＋未確認）。わざと壊して赤: 途中も現場に出す・文字で比べる。go test -race（新7）OK。黒ヤギ実装1回目【進めてよい】（軽い3点は宿題）のあと、岩城さん「書いた瞬間に HIO さんが処理するときもある」（11/6 13:49 問い合わせ 0026 が中断で保存した10秒後に状態7→not_interrupted の空振り）を受けて verify_karte 1.3.0 の ok_processed を足した（案2: 3.12.0 にまとめる）。test_verify_karte 31件（新4・直す前で1件赤）・test_auto_retry 26件 | cloud/server.py・cloud/auto_retry.py（新）・cloud/verify_karte.py・cloud/Dockerfile・cloud/prepare_cloud_build.ps1・cloud/tests/test_auto_retry.py（新）・test_verify_karte.py・app-kartelog/main.go・api.go・store.go・main_test.go・public/app.js・style.css・sw.js |
| 実行リスト 0.2.2（未配置） | 2026/11/06 | 言い方（岩城さん 11/6「読み直しまで一致っておかしい」「注文番号って何？」「時刻の流れの言い回し」）: 書けた行は「カルテ書込 ○」（記録に読み直しの結果 verify=ok があれば「・書込後確認 ○」）・番号は FAX＝OhiScanGo 札番号（起動時刻＋何枚目の札・kartelog.go で確認。「FAX受付番号」は誤解を生むので使わない）・問い合わせ＝問い合わせ番号・疑義照会＝送信時刻・自動やり直しは「（自動やり直し A2）」・時刻の流れは「GCP 受付（種類）」「カルテライター受付」「カルテ書込 ○／×」「GCP 受付で止めた」。画面の文字だけ（記録の言葉は変えない）。go test OK・番号の出し方を node で 6 通り確認 | app-kartelog/main.go・store.go（verify 欄）・public/app.js・index.html・sw.js |
| 実行リスト 0.2.1（未配置） | 2026/11/06 | タブの名前を「OhiScanGo（FAX/SCAN）」「問い合わせ（コール受付分）」「疑義照会（Tukusiフォームから）」に（岩城さん「OhiscanGO って誰もわからない」）。1 行に収まるようタブの文字を 14px・音声カルテの「準備中」は札をやめてマウスを乗せたときの説明に。画面の文字だけ。go test OK・撮って目で確認 | app-kartelog/main.go・public/app.js・style.css・sw.js |
| 実行リスト 0.2.0（未配置） | 2026/11/06 | 所属クリニック・ORCA番号・患者名をおひさまシステム（FM の API_M_PATIENT_LINKINFO を homisID 完全一致 "=="）から引いて出す（岩城さん「所属クリニック orca番号 患者名」「おひさまシステムに API で」・仕様 docs/SPEC_実行リスト_v0.md v0.8 13章・黒ヤギ仕様2回【進めてよい】）。patient.go: 一覧は FM を待たない（覚えている分だけ付けてすぐ返す）・裏の係 2 つ・同じ番号は 1 回・頼みは 100 件まで（古いのを捨て新しいのを先に）・覚え 24 時間（見つからない番号は 1 時間）・3 回続けて失敗したら 60 秒休む（休み中は頼みを受けない）・セッションは 1 つを使い回し、切れたら鍵の中で 1 回だけ取り直す・止めるときに閉じる・2 件以上当たったら名前を出さない・ログに名前を出さない。画面: 1 行目にクリニックと ORCA、2 行目に患者名と書類種・クリニックのしぼり込み・検索は表示中の一覧の中（患者名・かな・ORCA・クリニック）・詳しい窓に HOMIS 番号と「見つからない番号」の一言。ロボットのアニメーション（ふだんふわふわ・書込中は揺れる・失敗ありは震える・動きを減らす設定では止める）。テスト: go test -race -count=10 OK（新 8: 見つかる・無い・2件・完全一致・形でない番号・セッション切れの取り直しが 10 同時でも 1 回・同じ番号は 1 回・FM が遅くても一覧は 0.5 秒以内・100 件で古いのを捨て新しいのを先に・休み・覚えの長さ・一覧に名前が出る・閉じる）。テストの偽の置き場の数える表に鍵が無く -race で見つかったので直した（箱の本体ではない）。わざと壊して赤: 完全一致をやめる・2 件でも出す。本物の FM（読むだけ）で手元の箱からテスト舞子を引き「おひさまクリニック舞子・ORCA 0003・テスト 舞子」、無い番号は見つからない・ログに名前なしを確認。黒ヤギ実装1回目【直してから】: 指摘1（高）FM が「見つからない」を HTTP 401 で返すとセッション切れと間違える→ code 401 を先に見る（テスト TestFMMissWithHTTP401IsNotExpiry・直す前の順番で赤）／指摘3（中）偽の FM が HTTP 401 を試していない→ miss401 を足した／指摘2（中）no-store が無い→ withHeaders で全部の返事に付いている（誤り）・一覧・1件・画面もテストに足した | app-kartelog/patient.go（新）・patient_test.go（新）・main.go・api.go・main_test.go・public/app.js・index.html・style.css・sw.js |
| browser_actions 1.5.0・bot_s_interrupt 1.3・実行リスト 0.1.3（未配置） | 2026/11/06 | ①問い合わせ・疑義照会で「算定不要（ORCA登録不要）」が付いていたら外す（DX担当「問合せはオルカ登録不要にチェックいれたらだめ」「算定できる可能性のものも含まれる」「新規では付いていないのでそのまま・もし仮についてたら外す」「付けるのは FAX・SCAN だけ」）。ログの事実: 11/5 13時以降 問い合わせ・疑義照会 40件の保存後の状態はすべて 2（中断）・FAX 135件はすべて 7（ORCA登録不要）。FAX の型紙（印を付ける）は変えない。テスト: test_checkbox_click 25件（新7: 印が無ければ押さない・付いていれば外す・かぶさっても外す・外れなければ失敗・箱が無ければ3秒で何もしない・隠れた同じ id・型紙の順番）・test_js_input_verify 9件（型紙の版を 1.3 に）・test_label_click 6件 OK。直す前の 1.4.0 で新5件が赤。黒ヤギ 1回目【進めてよい】: 指摘1（低）読み直しは算定不要の印を見ていない／指摘2（低）箱が無い画面では毎回3秒／指摘3（低）外した直後0.5秒で S へ → どれも実害なし・宿題。②実行リストのロボットを Antigravity が描いた絵（robot.png 240×420・アイコン icon-192/512.png）に替え、140px に大きく（岩城さん「もう少し大きく」「Antigravity に依頼して」）。元の絵は app-kartelog/img_source（git に入れない） | src/browser_actions.py・src/templates/bot_s_interrupt.yaml・cloud/tests/test_checkbox_click.py・test_js_input_verify.py・app-kartelog/main.go・public/（robot.png・icon-192.png・icon-512.png 新・index.html・style.css・sw.js・manifest.webmanifest） |
| 実行リスト 0.1.2 | 2026/11/06 | ヘッダーとアイコンのロボットを、法人のロボット（写真・岩城さん「このロボットを入れて」）に似せた絵（robot.svg・白ヤギが SVG で描いた）に。ヘッダーを少し高く。画面の見た目だけ。go test OK・撮って目で確認 | app-kartelog/main.go・public/robot.svg（新）・icon.svg・index.html・style.css・sw.js |
| 実行リスト 0.1.1 | 2026/11/06 | 状態の言い方を「書込成功・書込失敗・書込待機中・書込中・停止の疑い」に（岩城さん「列で待っていますという表現はない」「書込成功とか」）。数字のカード・しぼり込み・赤い知らせ・上の帯もそろえた。画面の文字だけ（判定は変えない）。go test 9件 OK・架空データで撮って目で確認 | app-kartelog/main.go・public/app.js・index.html・sw.js |
| v3.11.0・受け口 v0.6.0・run_record 1.0.0・実行リスト 0.1.0（未配置） | 2026/11/06 | 実行リストの第1段（仕様 docs/SPEC_実行リスト_v0.md v0.4・黒ヤギ仕様2回目【進めてよい】・岩城さん「よろしゅー」）。受け口: 本番の FAX と問い合わせで、列に入れる前に received（無いときだけ作る＝ライターの記録・同じ注文の2回目を上書きしない）、落としたら rejected と理由・中身（番号が無ければ FAX-NOID-…）。FAX の経路は fax_route（route は道の名前 fax と分ける・テストで見つけた）。仕事に recordDay。ライター: 札の前に accepted、終わったら ok／fail・error_type・カルテ・left_in_homis（saved＝成功・no_karte_id・verify:*／editing＝stopped・1回目の書きかけのあと止まった・reused_editing／none＝新規を開いていない／unknown＝開いたが保存を押したか分からない。仕様は editing だったが安全側に）。結果シートの失敗（sheet）は記録しない（2回目なら前の結果を上書きするため）。箱（Go・新）: 日ごとに読み、読めなかった記録は1回読み直し・それでもだめなら件数を画面に出す（12件同時読みで偽の置き場が断り、黙って2件しか出なかったのをテストで見つけた）。テスト: run_record と書き込みへの足し方 13件（test_run_record）・受け口 10件（test_records）・箱 9件（go test）・結合 1件（本物の受け口→列→ライターの記録→本物の箱・test_kartelog_e2e）。直す前の受け口で結合が赤・わざと壊した3通り（上書きにする・試験の行の権限を外す・分からないを再書き込みにする）すべて赤。黒ヤギ実装1回目【直してから】: 指摘1（高）前の回で開いたのに最後の回が開く前に止まると none → この注文で開いた番号（order_kids）があれば none とは言わない（unknown）。今のやり直しの条件では起きない筋だが守る・テスト w5 に5件・w6（_write_locked の返り値まで届く）。指摘2（中）go.sum・go.mod が正本に無い → 写し、正本だけを別のフォルダに写して go test・go build が通ることを確かめた。指摘3（低）skip:no_config の説明が無い → app.js 27行目に有る（指摘が誤り） | cloud/server.py・cloud/run_record.py（新）・cloud/Dockerfile・cloud/prepare_cloud_build.ps1・cloud/tests/fake_records.py（新）・test_run_record.py（新）・test_kartelog_e2e.py（新）・cloud_fax_receiver/server.py・run_record.py（新）・Dockerfile・tests/test_records.py（新）・app-kartelog/（新） |
| v3.10.0 の追加・navi_callback 3.2.0・受け口 v0.5.2（11/5 20:00 配置・v20／00013-2c2） | 2026/11/05 | 知らせの先頭に出どころを付ける（DX担当「エラーが流れてくるときに FAXSCAN（OhiScanGo）・問い合わせ（OhisamaBot）・疑義照会とわかるように」）。注文番号の頭で決める: FAX-→【FAX・SCAN（OhiScanGo）】・BOT-G-→【疑義照会】・ほかの BOT-→【問い合わせ（OhisamaBot）】・R-→【レントゲン】・FAX-MIRROR-／BOT-TEST-→【試し書き】。ライターの現場の知らせ（_notify_field）と DX の知らせ（navi_callback.notify_dx・全部の呼び出し）、受け口の FAX と問い合わせの失敗の知らせ（現場・DX）。疑義照会の現場の文は「疑義照会のカルテを書けませんでした…疑義照会の内容から書いてください」。送り先は変えない。黒ヤギ 2回目（3.10.0 の区切りと合わせて）【進めてよい】・写した行は5か所とも実物と一致: 指摘1（中）id が小文字 g・全角Ｇだと疑義照会を問い合わせと見分けられない→ 疑義照会の WF は半角大文字 "G" 固定（HANDOVER.md 5行目）なので今回は直さず宿題（共通 JSON 入口の版で正規化をそろえる）。指摘2（低）区切りの末尾の rstrip で予算より少し手前になる→ 上限の内側なのでそのまま。指摘3（低）区切りは FAX だけ→ 方針どおり・共通 JSON 入口で共通の守りにする。足りないテストの絵文字を含む長い1行は test_c4b を足した（コードは変えない） | cloud/navi_callback.py・cloud/server.py・cloud/tests/test_phase1.py・cloud_fax_receiver/server.py・cloud_fax_receiver/tests/test_live.py・test_bot.py |
| v3.10.0（11/5 19:58 配置 00027-6jt・v20） | 2026/11/05 | FAX（fax_so）の O が HOMIS の O 欄の上限を超えるときは区切って書く（DX担当「2 にしましょう」）。上限は UTF-8 で 65,535 バイトで、' を ’（3バイト）にしたあと・改行は LF（1バイト）で数える（11/5 テスト舞子で確認: 変換前 62,009 バイトの O が、変換後の数えでちょうど 65,535 バイトで切れた・karte_id 18668017）。64,000 バイト以内になるよう行の区切りで区切り（改行の無い長い1行は字の区切り）、末尾に「以下省略：書類が長いため、カルテにはここまでを書いています。全文は HOMIS に貼付した書類をご覧ください」を足す。読み直しは区切った文と比べる。書けたら DX にだけ知らせる（現場には出さない・本文は入れない）。レントゲン・問い合わせは変えない。テスト: test_phase1 67件（新6・直す前の 3.9.0 で新5件が赤、残り1件は変えないことの確認） | cloud/server.py・cloud/tests/test_phase1.py |
| verify_karte 1.2.0・受け口 v0.5.1（11/5 20:00 配置・v20／00013-2c2） | 2026/11/05 | 本番 FAX の失敗の原因を確かめて直す（DX担当「原因と対策を追求して処置できるならしていきましょう」）。①O が送った文と違う（11/4 札 -71・11/5 札 -39）: HOMIS は保存のとき半角の ' を ’ (U+2019) に置き換える。テスト舞子に 44 種の記号を1行ずつ書いて確かめ、変わったのはこの1字だけ（" \ < > & 丸数字・タブ・全角スペース・µ・℃ などはそのまま）。11/2〜の本番 208 枚を読むと ’ があるのは失敗の2枚だけ。直し: 読み直しで両方の ' を ’ にそろえて比べる（ほかの字はそろえない）。②11/4 札 -75（O 45,704 字）: HOMIS の O 欄は UTF-8 で 65,535 バイトまで。保存された O はちょうど 65,533 バイトで、後ろの約 1,240 字が黙って捨てられていた（読み直しが正しく見つけた）。直しは岩城さん判断待ち（コードは変えない）。③受け口が列に入れるとき 5 秒の時間切れ（11/5 17:49 札 -48・本番開始から初めて）でカルテが書かれなかった → HTTP の返事が無い失敗だけすぐ1回やり直す（同じ札の名前なので二重にならない・event=enqueue_retry を記録）。テスト: test_verify_karte 27件（新2・直す前の 1.1.0 で新1件が赤）・test_phase1 61件・受け口 test_live（新3）・test_mirror・test_bot・test_receiver・test_integration。本物（読むだけ）: 試し書き 18667874 を新しい比べ方で ok・1字変えると o_mismatch | cloud/verify_karte.py・cloud/tests/test_verify_karte.py・cloud_fax_receiver/server.py・cloud_fax_receiver/tests/test_live.py・test_mirror.py・test_bot.py |
| v3.9.0・patient_lock 1.0.1（11/5 15:07 配置 00026-lpn・v19） | 2026/11/05 | 問い合わせの列を FAX と分けるための「患者さんごとの札」（仕様 docs/FAXカルテ_検討/SPEC_問い合わせの列を分ける_v0.md v0.4・黒ヤギ仕様2回目【進めてよい】の4点を反映）。write_karte を札の前後で2つに分けた（受付 claim → patient_lock.acquire → _write_locked（3.8.0 の後半そのまま）→ finally で _release_lock）。取れなければ _locked_out（共有ログ・現場（本番）・DX・結果シート fail）。書きかけ（編集中）を残して終わった注文（stopped／left_editing かつ blocked）は札を外さず期限で消えるに任せる。やり直しの時間の見張り（v3.8.0・v3.6.0）は札を取った時刻 t_write から数え、共有ログの経過時間 t0 には札待ちも入る。返り値に lock_waited_sec。Dockerfile・prepare_cloud_build.ps1 に patient_lock.py を足した。テスト: test_patient_lock 15件（偽の Cloud Storage fake_gcs.py・取る／待つ／期限切れを拾う／読んだあと作り直された札を奪わない／世代と時刻は GET 1回／403 は即 error／500 は2回まで／2スレッドで順番）・test_stop_retry に7件（k1〜k7: 本物の Chrome 2つで同じ患者さんを同時に書くと札で順番になりカルテ2枚、3.8.0 では同じカルテ 1001 に2件が入って赤）・test_phase1 61件 OK。黒ヤギ実装1回目【直してから】: 指摘1（高）トークンを一律50分使い回し・401 で即 error→ metadata の expires_in−2分だけ使い回し・401 は捨てて1回取り直す（release も）。指摘2（中）寝ずに取り直す continue が上限 320秒を飛び越える→ 繰り返しの先頭で上限を見る・寝ずに取り直すのは続けて3回まで。指摘3（低）新規を開いたのにカルテ番号が取れずに終わった注文で札が外れる→ opened かつ kid なしも外さない（patient_lock 1.0.1・テスト l15〜l19・k8・182件 OK）。黒ヤギ実装2回目【進めてよい】: 指摘1（中）reused_editing でも札を300秒残すため同じ患者さん3件で3件目が locked:busy になりうる／指摘2（低）5xx 2回の直後の 401 で取り直さず error／指摘3（低）fast が寝たあと戻らない → 3つとも 3.9.1 の宿題（仕様 v0.5 8章） | cloud/server.py・cloud/patient_lock.py（新）・cloud/Dockerfile・cloud/prepare_cloud_build.ps1・cloud/tests/fake_gcs.py（新）・cloud/tests/test_patient_lock.py（新）・cloud/tests/test_stop_retry.py・cloud/tests/test_phase1.py |
| 受け口 v0.5.0（11/5 15:0x 配置 00011-bhn） | 2026/11/05 | 問い合わせの列を FAX と分ける準備（仕様 docs/FAXカルテ_検討/SPEC_問い合わせの列を分ける_v0.md v0.3・黒ヤギ仕様2回目【進めてよい】）。①仕事（FAX・問い合わせ・試し書きとも）に dispatchDeadline "900s"（task の直下・文字列。ライターが札待ち込みで最長 600 秒になるため、Cloud Tasks の既定 600 秒だと先に切られる）。②問い合わせは BOT_QUEUE に入れる。空なら LIVE_QUEUE（配置の前後で止まらない）。FAX は LIVE_QUEUE のまま。テスト: test_bot 20件（新4: 全仕事に 900s・BOT_QUEUE で分かれる・空なら戻る・test も同じ列）・test_receiver 23・test_live 20・test_mirror 9・test_integration 3 OK。直す前の 0.4.0 では新4件のうち3件が赤（「空なら戻る」は変わらないことの確認なので緑）。黒ヤギ実装1回目【進めてよい】（dispatchDeadline の置き場所と形は公式資料で確認・Queue には dispatchDeadline の設定が無く Task だけ）: 指摘1（中）no_config が LIVE_QUEUE だけを見る→3.9.0 の宿題。指摘2（中）記録に列の名前が無い→3.9.0 の宿題（それまでは gcloud tasks list で確認）。指摘3（中）本番の受け口に試しを送ると本番の注文番号になる→仕様 v0.4 の7章を直した（受け口を通さず列へ直接） | cloud_fax_receiver/server.py・cloud_fax_receiver/tests/test_bot.py |
| v3.8.0（11/5 12:44 配置 00025-h92・v18） | 2026/11/05 | 11/5 10:19 本番の FAX（同じ患者さんへの3枚目・注文番号 -103）で、新規を押すと HOMIS が「入力途中のカルテが存在します」と出し、v3.4.0 の守りで止めて現場に「原本から書いて」と知らせた（1・2枚目 -101・-102 は直前に書けて完了。止められた理由の書きかけは今の一覧に無く、原因は未確定）。DX担当「案2」: blocked:in_progress_karte のときだけ、90秒あけて1回だけ最初からやり直す（新規は開いていない＝何も書いていないので、やり直しても二重にならない）。FAX（fax_so）と問い合わせ（bot_s_interrupt）だけ。レントゲン（撮影完了の知らせの流れがある）と、ほかの文の知らせ（unexpected_alert）は今までどおり。Cloud Run の上限は 300 秒（11/5 確認）なので、待つ前の経過＋90秒＋やり直し1回分の見込み120秒が 280 秒を超えるならやり直さない。同じ見張りを v3.6.0 の S のやり直しにも付けた（入力途中のやり直しのあとで重なると上限で切られ、知らせが出ないまま終わるため。ふだんの流れは 170 秒ほどで収まり動きは変わらない）。2回とも止められたら今までどおり失敗・現場と DX に知らせ、DX の文に「90秒あけて1回やり直しましたが、同じ知らせで止められました」。返り値に retried_blocked。テスト: test_stop_retry.py に8件（1回目止められ2回目に書ける・2回とも止められる・ほかの文はやり直さない・時間が足りないとやり直さない・対象と待ち時間・S のやり直しを時間で飛ばす・2回目が別の理由で止まる・S のやり直しまで通したとき）。直す前の 3.7.0 では b1〜b6 すべて赤。黒ヤギ実装1回目【直してから】: 指摘1（中）S のやり直しを時間で飛ばしても DX に「やり直しても同じ」と出る→ やり直していないときは「時間が足りないため、やり直していません」・入力途中で待っていたら経緯も書く。指摘2（中）2回目が入力途中以外の理由で止まると、待ってやり直した経緯が DX に出ない→ 止めたとき（blocked）の DX の文に「1回目は入力途中…2回目で上の理由で止まりました」。指摘3（低）レントゲンは対象外の確認→ 決めたとおり（変えない）。直しを外すと b6・b7 が赤。黒ヤギ実装2回目【進めてよい】（test_stop_retry 19件・test_phase1 61件）: 指摘1（中）読み直しの不一致（verify:…）の DX の文には、90秒あけてやり直した経緯が出ない→ 次の版の宿題（今はログの「90 秒あけて1回だけやり直す」で追う）。指摘2（低）入力途中→S 失敗のとき、2回目が50秒を超えると S のやり直しは飛ぶ（どちらでも上限内で文も正しい）→ そのまま。指摘3（低）2回目で守りの欄が読めず S も失敗すると DX に2通続く→ v3.7.0 の設計どおり（そのまま） | cloud/server.py・cloud/tests/test_stop_retry.py |
| v3.7.0（11/4 17:1x 配置 00024-x69・v17） | 2026/11/04 | 前の書きかけの守り（DX担当「案①」・仕様 docs/FAXカルテ_検討/SPEC_ライター_編集中の守り_v0.md v0.5・黒ヤギ仕様2回）。HOMIS は同じアカウントが残した編集中を新規で返す。ライターが書けずに残した書きかけに、次の書き込みが入るのを防ぐ。新規のあと最初の js_input の直前に1回だけ、編集画面の #karte_id・#act_date・#start_time を読む（11/4 テスト舞子で欄を確認。30分おいた書きかけも開始時刻・日付は最初のまま＝保存後も変わらない）。日付＋開始時刻が新規を押した時刻（日本時間）より2分以上前、またはプロセスの中で覚えた「書けずに残した番号」（上限200）なら blocked:reused_editing＝以後の手順をしない・DX にカルテ番号・本番は現場にも。同じ注文の中のやり直し（v3.6.0）で1回目と同じ番号なら止めない。欄が読めなければ止めずに書き、DX に「守りの欄が読めず」。3型紙とも医科カルテのあとが最初の入力（黒ヤギ確認）なのでレントゲンも守られる。黒ヤギ実装1回目【直してから】: 指摘1 やり直しの2回目が新規の前で失敗すると1回目の番号を覚えそこねる→ 注文の中で開いた番号を全部ためて、書けなければ全部覚える（書けた番号は覚えない）。指摘2 1回目に時刻が読めないとやり直しを誤って止めうる→ 番号が読めたら1回目の番号として控える。指摘3 守りの時機が js_input 頼み→ js_input か input の最初（select は医科カルテより前のレントゲンの指示医があるので入れない）。指摘4 覚えた番号はプロセスの中だけ・ライターは最大3台（maxScale=3）→ 限界としてコードと仕様に書いた（1台に絞るかは DX担当の判断）。テスト: test_phase1 61件（新6: 判定の境目・0時またぎ・覚えた番号の上限・最初の入力の前に1回だけ・やり直しの前の番号を覚える・番号だけ読めたとき・input では見て select では見ない）・test_stop_retry 11件。黒ヤギ実装2回目【進めてよい】: 指摘1（中）覚えた番号に期限が無いことを注釈に（動きは変えない）・指摘2（低）新規〜最初の入力の間で落ちた書きかけは番号を控えられず時刻の判定だけで守る（画面の作り上やむなし）・指摘3（低）欄が読めないと待ちが最大40秒積む（DX の知らせで気づく）・test_stop_retry 11件（新5: 5分前の書きかけは書かない・やり直しの例外・覚えた番号・0時またぎ・欄が読めない） | cloud/server.py・cloud/tests/test_phase1.py・cloud/tests/test_stop_retry.py |
| v3.6.0・bot_s_interrupt 1.2（11/4 15:1x 配置 00023-8g4・v16） | 2026/11/04 | DX担当「問い合わせで S 欄が空はあかん」。1.1 までは S を確かめられなくても保存まで進んでいた（やめると編集中が残るため）。直し: 型紙の手順に stop_on_fail を足し、その手順が失敗したら以後の手順と保存（中断・on_complete）を一切しない（v3.4.0 の blocked と同じく execute_action の差し替えで飛ばす）。ライターの中で1回だけ最初からやり直す（ライター自身が残した編集中は、同じアカウントの新規で同じカルテが戻る＝11/2 テスト舞子 5b。Cloud Tasks のやり直しは同じ注文番号が二重よけで弾かれるので使えない）。2回とも止まれば失敗 stopped:unverified_input・保存しない・DX に「保存せずに止めた・書きかけ1枚」・本番の問い合わせは現場にも。やり直しの2回目で新規が開けない（blocked）ときは、DX の文に書きかけが残っていることを足す。問い合わせの型紙の S の2手順だけに付ける。FAX・レントゲンは変えない。テスト: test_stop_retry.py（新・本物の write_karte→TemplateEngine→BrowserActions→Chrome で偽の HOMIS を相手に、通常・1回目に止まり2回目に同じカルテへ保存・2回とも止まり一度も保存しない・中断ボタンはあるのに S 欄が見えない＝0017 の形で一度も保存しない・試し書きは現場に知らせない。計6件。直す前の server 3.5.0 に戻すと5件が赤で、0017 の形は S 空のまま中断で保存された）・test_phase1 55件（新5）・test_js_input_verify 9件・test_verify_karte 25件・押し方 16件 OK。黒ヤギ 1回目【進めてよい】: 指摘1（高）2回とも止まって残った編集中が翌日の新規で戻ると前の日付のカルテに書かれうる【日付の扱いは HOMIS で未確認】→ 運用で守る: DX に「保存せずに止めました」が来たら、その日のうちに白ヤギがその編集中を取り消す・朝の確認の「ライターの編集中の残り」で 0 件を見る（コードは変えない）。指摘2（中）止めたあとも karte_id 取得で約10秒空振り→ 次の版の宿題。指摘3（中）戻った Edit 画面で手順が通るかは本物で未確認→ 配置後にテスト舞子で確かめる | cloud/server.py・src/templates/bot_s_interrupt.yaml・cloud/tests/test_stop_retry.py（新）・cloud/tests/test_phase1.py・cloud/tests/test_js_input_verify.py |
| browser_actions 1.4.0・bot_s_interrupt 1.1（11/4 11:4x 配置 00022-5zv・v15） | 2026/11/04 | 問い合わせの並走（試験モード・テスト舞子）で、0017 の1件だけ S が空のまま中断で保存された（読み直しが s_mismatch で見つけて DX に知らせた）。その1件は「電話再診を選択」が 6.7秒（ふだん 1.2秒）で画面が遅く、S が見えていない欄に入ったと見ている（原因は未確定）。直し: js_input に verify_value（見える欄を最大10秒待つ・読み返す・違えば入れ直す・見えない欄には入れない）。問い合わせの型紙で S に使い、保存の直前にもう一度確かめる。電話再診に verify_checked。入らなければ手順の失敗にするが、保存はやめない（やめると新規のカルテが「編集中」で残り、次の新規で上書きされるため）。読み直しが見つけて知らせる。FAX・レントゲンの型紙は変えない。テスト: test_js_input_verify.py 8件（直す前の部品で 3件・型紙込みで 2件が赤）・既存の押し方 16件・test_phase1 50件・test_verify_karte 25件 OK。黒ヤギ 1回目【直してから】: 指摘1 \r 単体の改行をそろえていない（textarea は \n にする→読み返しが一致せず10秒で失敗）→ verify_karte と同じく \r も \n に。test_6 を足した（直しを外すと赤）9件 OK。指摘2 FAX の型紙にも入れるか→ 今回は入れない（FAX は「算定不要を押す」が見える箱を最大10秒待つので、S の前に画面を待っている。入れるかは別に判断）。指摘3 最初の S が失敗して直前の確かめで直った場合も DX に「途中の手順の失敗」が出る→ そのままにする（DX だけ・中身を見るきっかけになる）。指摘4 prepare_cloud_build.ps1 を先に動かす→ 配置の手順どおり白ヤギが動かす | src/browser_actions.py・src/templates/bot_s_interrupt.yaml・cloud/tests/test_js_input_verify.py |
| v3.5.0 ほか（11/3 配置 v14） | 2026/11/02 | 問い合わせ（OhisamaBot → Tukusi WF1133）をライターで書く準備（仕様 docs/FAXカルテ_検討/SPEC_問い合わせ_ライター移行_v0.md v0.3）。受け口 0.4.0: /bot/receive（合言葉 BOT_RECEIVER_KEY・BOT_MODE 既定 off・注文番号 BOT-<番号>-<送った時刻14桁>・homis_url と homis_id を照合して same だけ・型紙 bot_s_interrupt）。ライター 3.5.0: 問い合わせも読み直す・カルテ番号なしは失敗・現場の知らせを型紙ごと（BOT_FIELD_WEBHOOK）。verify_karte 1.1.0: expect=interrupt。FAX は S（発信元）が空でも書く（HOMIS は空の S だと完了で保存しない＝テスト舞子で編集中のまま残った→ 空なら半角スペース1つ。半角・全角とも完了まで保存できることを確認・DX担当「半角スペースを入れて」）。黒ヤギ実装1回目【進めてよい】の指摘1（名前の空白）・3（時刻の先頭14桁）を直した | cloud_fax_receiver/server.py・cloud/server.py・cloud/verify_karte.py・各テスト |
| v3.4.0（11/2 15:40 配置 00017-sxz・v12。黒ヤギ再レビュー【進めてよい】。テスト舞子で試し書き1件 OK→取消。次の宿題: レントゲンの遅い知らせ・知らない知らせの文を伏せて残す） | 2026/11/02 | 11/2 11:36 本番の FAX 1件で、「新規」を押すと HOMIS が「入力途中のカルテが存在します」と出し（その日の訪問の予定のカルテが中断であった患者）、ライターは気づかず進んで完了で失敗・成功扱いで現場に知らせが出なかった（DX担当「直してください」）。直し: 新規を押した直後の知らせを見て（2秒まで）この文なら閉じて止め、以後の手順（S・O・完了）を一切しない（BrowserActions.execute_action を差し替えて飛ばす）。失敗 error_type=blocked:in_progress_karte・DX に「何も書かずに止めた」・本番の FAX は「カルテ失敗」にも。FAX（fax_so）でカルテ番号が取れなければ必ず失敗（no_karte_id）。レントゲンは変えない。テスト: test_phase1.py 41件（新6）・test_verify_karte 17件 OK・わざと壊した4通りすべて赤。黒ヤギ 1回目【直してから】5点を直す: ①FAX の戻し方は Tukusi への送り直し（tukusi_resend・新しい札）を案内し fax_requeue は案内しない（同じ注文番号は二重よけで弾かれ・live では本文が試し書きにしか無い）②DX の文は型紙ごと（レントゲンは送り元から送り直すか手で）③編集タブの「完了」ボタンが見えたら2秒待たずに進む ④新規のあとの知らせはどんな文でも止める（blocked:unexpected_alert・文はログに出さない）⑤止めたら karte_opened を戻す。test_phase1 43件 OK・わざと壊した9通りすべて赤 | cloud/server.py・cloud/tests/test_phase1.py |
| 受け口 v0.3.1（未配置） | 2026/10/29 | 患者さんの食い違いを止める（岩城さん 10/29「上からわたる変数なので、HOMISID だけきをつけないと」）。Tukusi が書く先の homis_id（おひさまシステムで探した1件目＝data[0] の患者ページ URL）と、homis_patient（OhiScanGo が FAX から決めた番号・Tukusi の変数 homis患者）を比べ、patient_check（same／mismatch／missing）をどのモードでも記録。live は same のときだけ書き、mismatch・missing は書かずに現場と DX に知らせる（番号は出さない）。Tukusi のボディに "homis_patient" を足してもらう（10/29 済み）。黒ヤギ1回目【直してから】を全部反映: 全角数字は NFKC で半角にそろえて [0-9] だけ通す（\d は全角にも合う）・先頭 0 の番号は無効・URL は https://homis.jp/ で始まるものだけ読む・書く先が読めないときは unreadable・テストのファイルを閉じる。テスト: test_live.py 18件（新6）・test_receiver 23件・test_integration 3件・test_mirror 9件 OK・わざと壊した6通りすべて赤。黒ヤギ再レビュー【進めてよい】の3点も反映: same のときだけ書く形（想定外の値でも書かない）・URL 末尾の # を区切りに・URL の大文字小文字を問わない（test_live.py 19件 OK） | cloud_fax_receiver/server.py・cloud_fax_receiver/tests/test_live.py |
| 道具 fax_requeue v0.1.1 | 2026/10/29 | 黒ヤギ段3実装レビュー【進めてよい】。取り入れた: 道具のファイルを with で閉じる（指摘1）・動かす人の権限（Secret 読み取り・列への投入）を切り替えの確認の一覧へ（指摘2）・401/503 で弾かれた件は切り替え直後の目視と毎時の「列に入ったのにライターの結果が無い」で拾う（指摘3）。取り入れなかった: Tukusi への返事の mode を live にする（指摘4・切り替えの前後で Tukusi の画面の返事を変えない。モードは受け口の記録にある） | tools/fax_requeue.py |
| 段3 受け口 v0.3.0・ライター v3.3.0・道具 fax_requeue v0.1.0（未配置） | 2026/10/29 | 段3（本番の切り替え）の実装（岩城さん 10/29「すすめてください」・仕様 docs/FAXカルテ_検討/SPEC_段3_本番切替.md v0.3・黒ヤギ仕様レビュー2回目【進めてよい】）。受け口: FAX_MODE（FAX_MIRROR=on は mirror 扱い・知らない値は off）・live は homis_id から [?&]patient_id=(\d{1,10}) か数字だけを取り、注文番号 FAX-<札>・S/O そのままで列 LIVE_QUEUE へ。札なし・空・患者番号が読めない・設定なし・列の失敗は FAX_FIELD_WEBHOOK と DX_ALERT_WEBHOOK に札番号と理由だけ（3秒まで・Tukusi には必ず 200）。ライター: 本物の FAX が失敗（読み直しで合わない場合も）したら FAX_FIELD_WEBHOOK に直リンク・注文番号・理由。道具: 入れ直し（見るだけ／--go）。テスト: 受け口 test_live.py 12件（新）・test_receiver 23件・test_integration 3件・test_mirror 9件、ライター test_phase1.py 35件（新5）・test_verify_karte 17件 すべて OK。道具は本物で見るだけを試した（同じ中身あり→入れない・上書きされた札→入れてよい・無い札→記録に無い）・仕事の形は受け口と同じ | cloud_fax_receiver/server.py・cloud_fax_receiver/tests/test_live.py（新）・cloud/server.py・cloud/tests/test_phase1.py・tools/fax_requeue.py（新） |
| verify_karte v1.0.1（本番 v3.2.0 で配置済み） | 2026/10/29 | 黒ヤギ1回目【直してから】を反映。取り入れた: 読めなかった理由に例外の文も（80字まで・指摘3）、ログイン後も auth.php のままなら login_failed（指摘4）。取り入れなかった: 記号の実体参照を戻す（指摘1・HOMIS はそのまま返す＝試し書き122欄で実体参照0件、記号入りの本物2件も ok）。指摘2（500 でやり直して二重に書く）はコードを変えず、**FAX の列は maxAttempts=1（やり直しなし）を必須**とする（homis-fax-mirror は maxAttempts=1 を確認・ライターは結果シートで同じ注文番号を二度書かない）。テスト: test_verify_karte.py 17件・test_phase1.py 30件 OK。本物（読むだけ）: 今日の照合できる30件すべて ok・O を1字変えると30件すべて o_mismatch | cloud/verify_karte.py・cloud/tests/test_verify_karte.py |
| v3.2.0（10/29 14:53 配置・00014-n7z・像 v10・最初の読み直し 15:06 ok） | 2026/10/29 | 書いたあとの読み直し（岩城さん 10/29「実装しておきましょう」「法人内で空だとか書けてないとかうるさい」）。FAX（fax_so）だけ、カルテ番号が取れたら verify_karte.verify で ①完了か ②S・O が送ったとおりか（改行の種類・行末の空白は見ない）を確かめる。完了でなければ2秒後に1回だけ読み直す。合わなければ success=false・error_type verify:not_completed／s_mismatch／o_mismatch・DX に直リンクと画面の状態の言葉で知らせる。読めなければ成功のまま DX に一言（verify=unverified）。レントゲン・ボットは変えない。状態の対応（本物で確認）: 0 取消・1 診察中・2 診療中断・3 診察完了・5 ORCA送信済・6 ORCA登録済・7 ORCA登録不要（算定不要で書くとこれ）・70 ORCA登録不要(編集中)。テスト: test_verify_karte.py 15件（偽の HOMIS）・test_phase1.py 30件（うち新規6・結合1件＝受け口の HTTP→本物の write_karte→本物の verify_karte→偽の HOMIS）すべて OK・わざと壊した7通りすべて赤。本物の HOMIS（読むだけ）: 試し書き3件 ok・O を1字変えると o_mismatch・編集中の空のカルテは not_completed | cloud/server.py・cloud/verify_karte.py（新）・cloud/Dockerfile・cloud/prepare_cloud_build.ps1・cloud/tests/test_verify_karte.py（新）・cloud/tests/test_phase1.py |
| 道具 find_stuck_kartes v0.1.0 | 2026/10/29 | 10/28 の照合で「本物のカルテが空」が見つかったので新規。10/1〜10/29 を数えて 10/23〜10/28 の7件（中断4・編集中3）だけが見つかることを確かめた（10/6〜10/22 は札 507 枚で0件） | tools/find_stuck_kartes.py（新） |
| 受け口 v0.2.0（未配置） | 2026/10/28 | 段1b 並走の試し書き（岩城さん 10/28「homis記録と並列にして、テスト舞子に記録し、ちゃんと書けているかみる」）。FAX_MIRROR=on のとき、受け取った件の S（先頭に「【GCP試し書き・本物は別の患者さん】」）と O を、テスト舞子あての fax_so の仕事（注文番号 FAX-MIRROR-<札番号>）として列 homis-fax-mirror に入れる。書き終わりは待たない・列に入れられなくても Tukusi には 200・宛先はテスト患者3人以外なら入れない。記録は mirror の言葉だけ。仕様 `docs/FAXカルテ_検討/SPEC_段1b_並走試し書き.md` | cloud_fax_receiver/server.py・tests/test_mirror.py（新） |
| v3.1.3（未配置） | 2026/10/27 | FAX の型紙に「算定不要を押す」（岩城さん「FAX は 100% 算定不要」）・電話再診に verify_checked・部品に「id で探して押して印を確かめる」（同じ印が複数なら見えているものを選ぶ）。server.py は途中の手順の失敗を DX に知らせる文を型紙ごとに（FAX で「外来」と出ていた・黒ヤギ 1回目 指摘2）。レントゲンの型紙は変えない。テスト: test_checkbox_click.py 10件（本物の Chrome・型紙 fax_so.yaml を新規〜完了まで通す結合1件）＋ test_label_click 6件・test_phase1 24件すべて OK・わざと壊した9通りすべて赤。黒ヤギ 1回目【進めてよい】・指摘2・3 を直した。仕様 `docs/FAXカルテ_検討/SPEC_段2a_算定不要.md` | cloud/server.py・src/browser_actions.py・src/templates/fax_so.yaml・cloud/tests/test_checkbox_click.py（新）・cloud/tests/test_phase1.py |
| 道具 v0.1.3 | 2026/10/26 | 黒ヤギ5回目（【進めてよい】・低3件）を反映: --since・--until の秒・時刻の省略を補う・読めない形は分かる言葉で止める・--p281 に渡すログの範囲を説明に。制御文字の対照表を仕様書10章に。受け口は 0.1.2 のまま | tools/fax_shadow_reconcile.py・tests/test_integration.py |
| 受け口 v0.1.2 | 2026/10/26 | 黒ヤギ再レビュー（【進めてよい】・指摘3件）を反映: 道具の --since・--until を受け口のログにも（UTC → 日本時間・until は余裕300秒・時間帯の外で返された札は余りにしない）・受け口は制御文字の種類（ctrl_codes）も記録。大きすぎる本文は 413 でなく切断に見えることがある（仕様書10章に注意）。テスト: 単体24件＋結合3件＝26件・わざと壊した16通りすべて赤 | cloud_fax_receiver/server.py・tests/・tools/fax_shadow_reconcile.py |
| 受け口 v0.1.1 | 2026/10/26 | 黒ヤギ実装レビュー（【進めてよい】・指摘5件）を反映: 読み込みに10秒の上限・読めなければ返事なしで切る・起動直後の印を鍵の中で・道具は p281 側の札番号の重なりも出す・ファイルを with で閉じる。テスト: 単体23件＋結合2件＝25件・わざと壊した12通りすべて赤 | cloud_fax_receiver/server.py・tests/・tools/fax_shadow_reconcile.py |
| 受け口 v0.1.0 | 2026/10/26 | FAX カルテの受け口（段1・横付けで受け取るだけ）を新規作成。合言葉（Bearer・空白を除いて compare_digest）→ 大きさ（256KB 超 413・長さなし 411）→ JSON の順。本文と HOMIS ID は記録しない。札番号（ticket または lock）で p281 と突き合わせる。断るときも 256KB 以内は読み捨ててから返事（読まずに閉じると番号が伝わらない）。ログは鍵をかけて1回で1行（同時8件で行が混ざった）。テスト: 単体18件＋結合2件・わざと壊した9通りすべて赤。未配置 | cloud_fax_receiver/server.py・Dockerfile・tests/（新）・tools/fax_shadow_reconcile.py（新） |
| v3.1.2 | 2026/10/19 | 10/16 本番で「外来を選択」が押せず（覆いで intercepted）種別が定期のまま保存された件: 押せるまで待つ（最大10秒）・だめなら JavaScript で押す・選べたかを確かめる・失敗した手順があればカルテ番号ありでも DX Chat（直リンク付き）。テスト: 本物の Chrome で覆いをかぶせた画面 6本（test_label_click.py）＋ test_phase1.py 22本 | server.py・src/browser_actions.py・src/template_engine.py・src/templates/xray_karte.yaml |
| v3.1.1 | 2026/10/15 | ALLOWED_HOMIS_IDS="*" で全員を許可（本番の切り替え用・未設定はテスト舞子だけ）。許可の外で断ったときもナビ（空の URL）と DX に知らせる（黙って止めない）。テスト20本 | server.py |
| v3.1.0 | 2026/10/15 | 書き終えたらナビの doPost（updateHomisLink）に知らせる（NAVI_WEBAPP_URL があるときだけ・xray_karte だけ・応答なし／5xx だけ最大3回・だめなら DX Chat）。POST /check-group（集団の確かめ役）。断るときも本文を読み切る。テスト `cloud/tests/test_phase1.py` 17本（黒ヤギ合格・知らせの例外の囲い・受け取りの待ち60秒） | server.py・navi_callback.py（新）・Dockerfile・prepare_cloud_build.ps1 |
| v3.0.x | 2026/09/04〜09/08 | Job 試験・受け口2a・失敗ガード（7章）・結果シート（2b）・fax_so・bot_s_interrupt（9.5・9.6 章） | server.py・result_sheet.py・write_once.py |

### 0.3b Cloud Run のデプロイ履歴（`homis-fax-receiver`・東京・FAX カルテの受け口 段1）

> 誰でも届く（allUsers）・中で合言葉（Secret Manager `fax-receiver-key`）を確かめる。専用アカウント `fax-receiver`（その合言葉を読む権限だけ）。
> 像は今のライターと同じ置き場 `homis-karte-writer` に別名 `homis-fax-receiver` で置く（このプロジェクトは `--source` が使えない）。
> 箱 最大2・最小0・同時20・256Mi・タイムアウト30秒。手順と戻し方: `docs/FAXカルテ_検討/配置手順_受け口_段1.md`

| イメージ | 日付 | 版 | 中身 |
|---|---|---|---|
| `homis-fax-receiver:v0.5.2` | 2026/11/05 20:00 | 受け口 v0.5.2（commit 3ac6aa5） | リビジョン 00013-2c2。列への投入の時間切れを1回やり直す・知らせの先頭に出どころ。像だけ差し替え（gcloud run deploy --image のみ・設定 15 個はそのまま）。/health 0.5.2 確認。黒ヤギ 1回目・2回目【進めてよい】。DX担当「大丈夫すすめてください」。戻し方: gcloud run services update-traffic homis-fax-receiver --to-revisions homis-fax-receiver-00012-bdg=100 |
| `homis-fax-receiver:v0.5.0` | 2026/11/05 15:0x | 受け口 v0.5.0（commit ba49c54） | リビジョン 00011-bhn。仕事に dispatchDeadline 900s・問い合わせは BOT_QUEUE（まだ空＝LIVE_QUEUE）。/health 0.5.0 確認。黒ヤギ【進めてよい】（指摘1・2 は 0.5.1 の宿題）。15:17 列 homis-bot-writer を作り（同時1・maxAttempts 1・1件/秒・fax-receiver に cloudtasks.enqueuer）BOT_QUEUE を足して 00012-bdg＝問い合わせが別の列に |
| `homis-fax-receiver:v0.1.2` | 2026/10/26 14:04 | 受け口 v0.1.2（commit d4b2508） | リビジョン homis-fax-receiver-00001-dnm。黒ヤギ実装レビュー6回目【進めてよい】・security-check 問題なし。確認: /health 200（0.1.2）・合言葉なし 401・違う 401・ほかの入口 404・正しい合言葉のダミー 200・起動の記録 key_configured true・ダミーの記録に本文と番号なし。WF1573 にはまだ横付けしていない |

### 0.3 Cloud Run のデプロイ履歴（`homis-karte-writer`・東京）

> 10/15 GCP の準備（フェーズ1）: Cloud Tasks API を有効化。キュー `homis-karte-writer`（東京・maxConcurrentDispatches 1・maxAttempts 1・1件/秒・記録 100%）。
> 列専用のアカウント `homis-tasks-invoker`（Cloud Run の run.invoker だけ）。タスクは OIDC（宛先＝サービスの URL）＋合言葉ヘッダーで Cloud Run を呼ぶ。

| イメージ | 日付 | 版 | 中身 |
|---|---|---|---|
| `:v20` | 2026/11/05 19:58 | v3.10.0＋verify_karte 1.2.0＋navi_callback 3.2.0 | O の区切り・' と ’ をそろえる読み直し・知らせの出どころ。commit 3ac6aa5 → ビルド 19:56 → 00027-6jt（白ヤギ・像だけ差し替え・timeout 900 そのまま）。確認: テスト舞子に記号 44 種の文（18668490）→ 読み直し ok（直す前は o_mismatch）、74,411 バイトの文（18668494）→ 63,983 バイトに区切り・末尾に省略の一言・読み直し ok・DX に知らせ。戻し方: gcloud run services update-traffic homis-karte-writer --to-revisions homis-karte-writer-00026-lpn=100 |
| `:v19` | 2026/11/05 15:0x | v3.9.0＋patient_lock 1.0.1 | 患者さんごとの札（Cloud Storage gen-lang-client-0979357970-homis-writer-locks・東京・外から見えない・1日で消す・compute SA に objectAdmin）。黒ヤギ 仕様2回・実装2回（2回目【進めてよい】・3点は 3.9.1 の宿題）→ commit 4b2b58c → ビルド 15:01/15:06 → 00026-lpn（DX担当・--timeout 900・LOCK_BUCKET）。確認: 本番 FAX -46 で札 0.1秒→書けた→外した／テスト舞子に FAX の形と問い合わせの形を2つの列へ同時投入→FAX が札を取り 48秒、問い合わせは 46.1秒待って別のカルテ（18665916・18665921）・読み直し ok |
| `:v18` | 2026/11/05 12:41 | v3.8.0 | 新規で「入力途中のカルテ」と止められたら90秒あけて1回だけやり直す（FAX・問い合わせ・案2）。黒ヤギ 実装2回（2回目【進めてよい】）→ commit bc0094d → ビルド 12:41 → 00025-h92（DX担当・設定は v17 から引き継ぎ・12:44 起動）。配置後の最初の本番 FAX で確認する |
| `:v17` | 2026/11/04 17:1x | v3.7.0 | 前の書きかけ（自分が残した編集中）が新規で戻ったら書く前に止める（案①・全型紙）。黒ヤギ 仕様2回・実装2回（2回目【進めてよい】）→ commit 54ff6b2 → ビルド 17:0x → 00024-x69（DX担当）。配置後の確認は 11/5 朝（テスト舞子で問い合わせ1件・レントゲン・本番の最初の FAX） |
| `:v16` | 2026/11/04 15:1x | v3.6.0＋bot_s_interrupt 1.2 | 問い合わせの S を確かめられなければ保存せず1回やり直す。黒ヤギ【進めてよい】→ commit f8e3820 → ビルド 15:08 → 00023-8g4（DX担当）。配置後にテスト舞子で確認: ロボット(API) の手元の Chrome で、新規〜医科カルテまで押して書きかけを残し、同じアカウントで型紙 1.2 を最初から流す → 戻ったカルテ 18657821 に S を入れて中断で保存（手順の失敗 0・編集中の残り 0）＝黒ヤギ指摘3 |
| `:v15` | 2026/11/04 11:4x | v3.5.0＋browser_actions 1.4.0・bot_s_interrupt 1.1 | 問い合わせの S を「見える欄を待つ・読み返す」で入れ、保存の直前にもう一度確かめる（11/4 0017 の S 空保存）。黒ヤギ 2回目【進めてよい】→ commit 5753077 → ビルド 11:38 → 00022-5zv（DX担当・設定は v14 のまま引き継ぎ）。FAX の型紙は変えていない |
| `:v14` | 2026/11/03 08:1x | v3.5.0＋直し | S が空の FAX は半角スペース1つで書く・更新者の名前の空白をそろえる。黒ヤギ【進めてよい】→ 00020-v4k（岩城さん）→ 受け口 0.4.0（00008-tzq）。テスト舞子で S 空が完了まで保存できた。00021-p5t で BOT_FIELD_WEBHOOK をつないだ |
| `:v13` | 2026/11/02 17:05 | v3.5.0 | 問い合わせ（bot_s_interrupt）の読み直し・知らせを型紙ごと・FAX の S 空を受ける。リビジョン 00019-4f4（同じ行を2回実行し 00018-dfc も同じ中身）。DX担当が配置 |
| `:v12` | 2026/11/02 15:40 | v3.4.0 | 新規が開かなければ止める。リビジョン 00017-sxz。黒ヤギ再レビュー【進めてよい】。テスト舞子で試し書き OK |
| `:v8` | 2026/10/19 18:12 | v3.1.2（commit 07b4eb8・c293560） | 「外来を選択」を確実に・手順の失敗は DX へ。リビジョン 00012-xpt。黒ヤギ【進めてよい】。確認 GCP-TEST-20261019-181254: 外来を選択 ok（click・選べた確認あり）・カルテ番号あり 54.5秒・ナビへ知らせ1回 |
| `:v7` | 2026/10/15 17:00 | v3.1.1（commit dad8c30） | 全員を許可（ALLOWED_HOMIS_IDS="*"・同時に設定）。リビジョン 00011-xqv。この直後にナビ HOMIS_WRITE_MODE=3（本番切り替え） |
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
| v0.21 | 2026-10-26 | 0章に FAX カルテの受け口（cloud_fax_receiver/ v0.1.0）の版と改定履歴を追加 |
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
