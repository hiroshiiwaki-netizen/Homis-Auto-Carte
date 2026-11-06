// カルテライター 実行リスト 0.1.0（読むだけ・第1段）
// 文字はすべて esc() を通して出す（送られた中身にどんな文字があっても画面を壊さない）
"use strict";

const API = "/kartelog/api/";
const TABS = [
  ["all", "🗂️ 全記録", "all"], ["fax", "📠 OhiScanGo（FAX/SCAN）", "fax"], ["bot", "💬 問い合わせ（コール受付分）", "bot"], ["bot_g", "💊 疑義照会（Tukusiフォームから）", "gi"],
];
const SRC = { fax: "📠 OhiScanGo", bot: "💬 問い合わせ", bot_g: "💊 疑義照会", fax_mirror: "🧪 FAX 試し書き", bot_test: "🧪 問い合わせ 試験", karte_json: "🎙️ 音声カルテ", other: "その他" };
// 失敗の理由（ライター server.py の FIELD_REASON・受け口の理由と同じ言葉）
const WHY = {
  "blocked:in_progress_karte": "その患者さんに入力途中のカルテ（訪問の予定など）があり、新規が開けませんでした",
  "blocked:unexpected_alert": "新規を押したあと HOMIS から知らせが出て、新規が開けませんでした",
  "blocked:reused_editing": "前に書けずに残った書きかけのカルテが新規で戻ってきたため、書かずに止めました",
  "no_karte_id": "カルテ番号が取れませんでした（保存したかもしれません）",
  "verify:not_completed": "保存が完了していません",
  "verify:not_interrupted": "中断で保存できていません",
  "verify:not_mine": "書いたカルテを確かめられませんでした（別のカルテの見込み）",
  "verify:s_mismatch": "S が送った文と違います",
  "verify:o_mismatch": "O が送った文と違います",
  "stopped:unverified_input": "S を入れたことを確かめられず、保存しませんでした",
  "locked:busy": "同じ患者さんのカルテを別の仕事が書いていて、時間内に順番が回ってきませんでした",
  "locked:error": "同時に書くのを防ぐ札の置き場が使えず、安全のため書きませんでした",
  "login": "HOMIS にログインできませんでした",
  "sheet": "結果の表に書けず、書き込みを始めませんでした",
  "skip:no_ticket": "受け口: 札番号がありません", "skip:empty": "受け口: 本文が空です",
  "skip:bad_homis_id": "受け口: 患者番号が読めません", "skip:no_config": "受け口: 設定が足りません",
  "skip:id_mismatch": "受け口: 患者さんが食い違っています", "skip:id_missing": "受け口: 患者番号が届いていません",
  "skip:bad_id": "受け口: 問い合わせの番号がありません", "skip:bad_sent_at": "受け口: 送った時刻がありません",
  "skipped:new_karte_found": "自動やり直しの前に、新しいカルテが見つかりました（人が書いた見込み）",
  "skipped:karte_list_unreadable": "自動やり直しの前に、カルテ一覧を読めませんでした",
};
const NEXT = {
  rewrite: ["カルテは書かれていません。", "元の書類（FAX・問い合わせの画面）を見て、手で書いてください。画面から書き直すボタンは次の版で付きます。"],
  cancel_then_rewrite: ["HOMIS にライターの書きかけ（編集中）が 1 枚残っています。", "編集中のカルテを取り消してから、元の書類を見て手で書いてください。"],
  check: ["カルテが保存されているかもしれません。", "HOMIS でこの患者さんのカルテを開いて確かめ、足りなければ手で足してください（もう一度書くと 2 枚になります）。"],
  stale: ["ライターが途中で止まった見込みです。", "HOMIS でカルテを確かめ、無ければ手で書いてください。DX推進部にも知らせてください。"],
  manual: ["自動で再書込をやり直しましたが、書けませんでした。", "元の書類（FAX・問い合わせの画面）を見て、手でカルテを書いてください。"],
};

const st = { tab: "all", d: 0, from: "", s: "all", q: "", err: "", clinic: "", tests: false, rows: [], me: {}, data: null };
const pi = (r) => (r.pinfo && r.pinfo.found ? r.pinfo : null);   // 0.2.0: おひさまシステムの患者さんの情報
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hm = (iso) => (iso || "").slice(11, 16);
const md = (iso) => { const m = (iso || "").slice(5, 10).split("-"); return m.length === 2 ? `${+m[0]}月${+m[1]}日` : ""; };
const reason = (e) => WHY[e] || (e ? (e.startsWith("error:") ? "受け口: 列に入れられませんでした（" + e + "）" : e) : "");
const tabOf = (r) => (r.route === "fax" || r.route === "fax_mirror" ? "fax" : r.route === "bot_g" ? "bot_g" : r.route === "bot" || r.route === "bot_test" ? "bot" : "other");
const isRun = (r) => r.view === "running" || r.view === "waiting" || r.view === "scheduled";
const counted = (r) => r.view !== "handed";   // 0.3.0: 自動で再書込へ回した元の行は数えない（最後の結果だけ）
const isFail = (r) => r.view === "fail" || r.view === "stale";
const homisPatientURL = (id) => (/^[1-9][0-9]{0,9}$/.test(id || "") ? `https://homis.jp/homic/?pid=patient_detail&patient_id=${id}&p=5` : "");
const safeURL = (u) => (/^https:\/\/homis\.jp\//.test(u || "") ? u : "");

async function getJSON(path) {
  const r = await fetch(API + path, { credentials: "same-origin", cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

function todayStr() {
  const n = new Date(Date.now() + 9 * 3600 * 1000);
  return n.toISOString().slice(0, 10);
}
function shift(day, n) {
  const t = new Date(day + "T00:00:00Z");
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}

async function load() {
  $("upd").textContent = "読み込み中…";
  const from = st.from || todayStr();
  const days = st.d === 7 ? 7 : 1;
  try {
    const qs = `from=${from}&days=${days}` + (st.tests ? "&tests=1" : "");
    const [data, status] = await Promise.all([getJSON("list?" + qs), getJSON("status")]);
    st.data = data;
    st.rows = data.rows || [];
    showAlive(status);
    const msg = [];
    if ((data.failed_days || []).length) msg.push("読めなかった日があります: " + data.failed_days.join("・"));
    if (data.missing) msg.push(`読めなかった記録が ${data.missing} 件あります（一覧に出ていません）`);
    $("err").classList.toggle("on", msg.length > 0);
    $("err").textContent = msg.length ? msg.join("／") + "。少しして「読み直す」を押してください。" : "";
    $("upd").textContent = "更新 " + hm(data.now);
  } catch (e) {
    $("err").classList.add("on");
    $("err").textContent = "読み込めませんでした（" + e.message + "）。少しして「読み直す」を押してください。";
    $("upd").textContent = "読み込めませんでした";
  }
  render();
}

function showAlive(s) {
  const q = s.queues || {};
  const waiting = Object.values(q).reduce((a, b) => a + b, 0);
  const last = s.last_finished_at;
  const ageMin = last ? (Date.parse(s.now) - Date.parse(last)) / 60000 : null;
  const stuck = s.queue_ok && waiting > 0 && (ageMin == null || ageMin > 15);
  const parts = [];
  parts.push(`<span class="chipx ${stuck ? "bad" : ""}">🤖 ライター: ${last ? "最後の書込 " + hm(last) : "今日はまだ書込なし"}${stuck ? "（書込待機があるのに進んでいません）" : ""}</span>`);
  if (s.queue_ok) {
    const name = { "homis-fax-writer": "FAX", "homis-bot-writer": "問い合わせ・疑義照会" };
    for (const k of Object.keys(name)) parts.push(`<span class="chipx">書込待機 ${name[k]} ${q[k] || 0}件</span>`);
  } else {
    parts.push(`<span class="chipx">書込待機の件数は読めませんでした</span>`);
  }
  $("alive").innerHTML = parts.join("");
}

function filtered(rows) {
  const q = st.q.toLowerCase();
  return rows.filter((r) => (st.tab === "all" || tabOf(r) === st.tab)
    && (st.s === "all" || (st.s === "fail" && isFail(r)) || (st.s === "ok" && r.view === "ok") || (st.s === "run" && isRun(r)))
    && (!st.err || r.error_type === st.err)
    && (!st.clinic || (pi(r) && pi(r).clinic === st.clinic))
    && (!q || [r.order_id, r.patient && r.patient.homis_id, pi(r) && pi(r).name, pi(r) && pi(r).kana, pi(r) && pi(r).orca, pi(r) && pi(r).clinic, r.doc_type, r.source, r.sender].some((v) => String(v || "").toLowerCase().includes(q))));
}

function render() {
  const rows = st.rows;
  const counts = { all: rows.length };
  for (const r of rows) counts[tabOf(r)] = (counts[tabOf(r)] || 0) + 1;
  $("tabs").innerHTML = TABS.map(([k, label, dot]) => `<button class="tab ${st.tab === k ? "on" : ""}" data-tab="${k}" type="button"><span class="dot ${dot}"></span>${label}<span class="n">${counts[k] || 0}</span></button>`).join("")
    ;   // 音声カルテのタブは、共通 JSON の入口ができたら足す（0.3.0 で外した: 5 つ目で 2 行に折れるため）

  const base = rows.filter((r) => (st.tab === "all" || tabOf(r) === st.tab) && counted(r));
  const ok = base.filter((r) => r.view === "ok").length;
  const ng = base.filter(isFail);
  const run = base.filter(isRun).length;
  $("kLabel").textContent = st.d === 7 ? "7日の件数" : (st.from && st.from !== todayStr() ? md(st.from + "T") + "の件数" : "今日の件数");
  const robot = document.querySelector(".robot");   // 0.2.0: 書込中・待機中があればせっせと揺れる・書込失敗があれば震える
  if (robot) {
    robot.classList.toggle("robot-busy", rows.some(isRun));
    robot.classList.toggle("robot-alert", !rows.some(isRun) && rows.some(isFail));   // "alert" は赤い枠の名前とぶつかる（0.2.x で消えた）
  }
  $("kAll").textContent = base.length; $("kOk").textContent = ok; $("kNg").textContent = ng.length; $("kRun").textContent = run;
  const done = ok + ng.length;
  const pct = done ? Math.round((ok / done) * 1000) / 10 : 0;
  $("ring").setAttribute("stroke-dasharray", `${pct * 0.942} 100`);
  $("ringT").textContent = done ? pct + "%" : "－";
  const bars = $("bars");
  bars.textContent = "";
  for (let h = 8; h <= 19; h++) {
    const a = base.filter((r) => +(r.received_at || "").slice(11, 13) === h);
    const i = document.createElement("i");
    if (a.some(isFail)) i.className = "f";
    i.style.height = Math.min(46, Math.max(3, a.length * 3)) + "px";
    i.title = `${h}時 ${a.length}件`;
    bars.appendChild(i);
  }

  const alertBox = $("alertBox");
  alertBox.classList.toggle("on", ng.length > 0);
  alertBox.innerHTML = ng.length ? `<span class="big">🚨</span><div><b>書込失敗が ${ng.length} 件あります。</b><br><span class="why">いちばん新しいもの：${esc(hm(ng[0].received_at))}　${esc(SRC[ng[0].route] || "")}　${esc(ng[0].view === "stale" ? "停止の疑い" : reason(ng[0].error_type))}</span></div><button class="go" id="onlyFail" type="button">書込失敗だけ見る</button>` : "";

  const errs = [...new Set(rows.map((r) => r.error_type).filter(Boolean))].sort();
  $("err_type").innerHTML = `<option value="">エラーの種類：すべて</option>` + errs.map((e) => `<option value="${esc(e)}" ${st.err === e ? "selected" : ""}>${esc(reason(e).slice(0, 26))}</option>`).join("");
  const clinics = [...new Set(rows.map((r) => pi(r) && pi(r).clinic).filter(Boolean))].sort();
  $("clinic").innerHTML = `<option value="">クリニック：すべて</option>` + clinics.map((c) => `<option value="${esc(c)}" ${st.clinic === c ? "selected" : ""}>${esc(c)}</option>`).join("");
  $("tests").classList.toggle("hidden", !st.me.admin);
  $("tests").classList.toggle("on", st.tests);

  const list = filtered(rows);
  let html = "", lastDay = "";
  for (const r of list) {
    if (r.day !== lastDay) {
      lastDay = r.day;
      html += `<div class="day">${esc(md(r.day + "T"))}　${list.filter((x) => x.day === r.day).length} 件</div>`;
    }
    html += rowHTML(r);
  }
  $("list").innerHTML = html || `<div class="empty">この条件の記録はありません。</div>`;
}

function badge(r) {
  return { ok: `<span class="badge ok">✅ 書込成功</span>`, fail: `<span class="badge fail">⚠️ 書込失敗</span>`, stale: `<span class="badge stale">⚠ 停止の疑い</span>`,
    waiting: `<span class="badge waiting">⏳ 書込待機中</span>`, running: `<span class="badge running">✍️ 書込中</span>`, done: `<span class="badge done">☑ 対応済み</span>`,
    handed: `<span class="badge handed">↻ 自動で再書込へ</span>`, human: `<span class="badge human">☑ 人が書いた見込み</span>`,
    scheduled: `<span class="badge scheduled">⏳ 自動で再書込（${esc(hm(r.retry_at))} まで・あと ${Math.max(1, 4 - (r.attempt || 1))} 回）</span>` }[r.view] || "";
}

// 0.2.2: 番号の名前（岩城さん「注文番号って何？」）。FAX＝OhiScanGo の FAX受付番号、問い合わせ＝問い合わせ番号、疑義照会＝送信時刻
function idText(r) {
  const o = r.order_id || "";
  const base = o.replace(/-A[1-3]$/, "");
  const tail = base === o ? "" : `（自動やり直し ${o.slice(-2)}）`;
  let m;
  if ((m = base.match(/^FAX-(?:MIRROR-)?(.+)$/))) return `OhiScanGo 札番号 ${m[1]}${tail}`;   // 起動時刻＋何枚目の札（OhiScanGo kartelock.go）
  if ((m = base.match(/^BOT-(?:TEST-)?G-(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})/))) return `疑義照会の送信時刻 ${m[1]}/${m[2]}/${m[3]} ${m[4]}:${m[5]}:${m[6]}${tail}`;
  if ((m = base.match(/^BOT-(?:TEST-)?(.+)-\d{14}$/))) return `問い合わせ番号 ${m[1]}${tail}`;
  return `番号 ${o}`;
}
// FAX の札番号の読み方（OhiScanGo を起動した時刻＋起動してから何枚目のカルテ順番札か）
function faxNote(r) {
  const m = (r.order_id || "").match(/^FAX-(?:MIRROR-)?(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\d{2}-(\d+)/);
  return m ? `<div class="why">（OhiScanGo を ${+m[2]}/${+m[3]} ${+m[4]}:${m[5]} に起動してから ${m[6]} 枚目の札）</div>` : "";
}
// 0.2.2: 時刻の流れの言い方（記録の言葉を、画面ではこう出す）
const KIND = { fax: "FAX", fax_mirror: "FAX 試し書き", bot: "問い合わせ", bot_g: "疑義照会", bot_test: "問い合わせ 試験" };
function tlText(what, r) {
  if (what === "受け口が受けた") return `GCP 受付（${KIND[r.route] || "受付"}）`;
  if (what === "ライターが受け取った") return "カルテライター受付";
  if (what === "書けた") return "カルテ書込 ○";
  if (what === "書けなかった") return "カルテ書込 ×";
  if (what.startsWith("受け口で落とした")) return what.replace("受け口で落とした", "GCP 受付で止めた");
  return what;
}

// 0.3.0: 書込後確認（ok＝○・unverified＝未確認（保存済み）・それ以外＝×）。記録に無ければ出さない
function verifyText(v) {
  if (!v) return "";
  return "　・　書込後確認 " + (v === "ok" ? "○" : v === "ok_processed" ? "○（そのあと人が処理）" : v === "unverified" ? "未確認（カルテは保存済み）" : "×");
}

function whyText(r) {
  if (r.view === "fail" && r.action === "manual") return `<span class="badge manual">✋ 手動でお願いします</span> <span class="why ng">${esc(reason(r.error_type))}</span>`;
  if (r.view === "fail") return `<span class="why ng">${esc(reason(r.error_type))}</span>`;
  if (r.view === "handed") return `<span class="why">自動の再書込を予約しました（${esc((r.retried_as || "").slice(-2))}）</span>`;
  if (r.view === "human") return `<span class="why">新しいカルテが見つかったので、自動の再書込を止めました（DX推進部が確かめます）</span>`;
  if (r.view === "scheduled") return `<span class="why">${esc(hm(r.retry_at))} に自動で書き直します（手で書かずにお待ちください）</span>`;
  if (r.view === "stale") return `<span class="why ng">書込中のまま 15 分を過ぎ、書込待機にもありません</span>`;
  if (r.view === "waiting") return `<span class="why">書込の順番を待っています</span>`;
  if (r.view === "running") return `<span class="why">${r.status === "received" ? "受け口が受けました" : "ライターが HOMIS に書いています"}</span>`;
  if (r.view === "ok") return `<span class="why">カルテ書込 ○${verifyText(r.verify)}</span>`;
  return "";
}

function actionHTML(r, i) {
  const url = safeURL(r.karte_url);
  if (r.view === "ok" && url) return `<a class="open" href="${esc(url)}" target="_blank" rel="noopener noreferrer" data-stop="1">カルテを開く ↗</a>`;
  if (isFail(r)) return `<button class="chk" type="button" data-open="${i}">🔍 次にすること</button>`;
  if (isRun(r)) return `<span class="wait">${r.view === "waiting" ? "書込待機中" : "書込中"}</span>`;
  return "";
}

function rowHTML(r) {
  const i = st.rows.indexOf(r);
  const p = r.patient || {};
  const f = pi(r);
  const name = f ? `${esc(f.name)} 様` : (p.homis_id ? `患者番号 ${esc(p.homis_id)}` : "患者さん不明");
  const pl = f ? `<div class="pl"><span class="cl">${esc(f.clinic)}</span><span class="orca">ORCA ${esc(f.orca)}</span></div>` : "";
  const who = r.route === "fax" || r.route === "fax_mirror" ? (r.source ? "差出元：" + esc(r.source) : "") : (r.sender ? "送った人：" + esc(r.sender) : "");
  return `<div class="row ${esc(r.view)} ${r.test ? "test" : ""}" data-open="${i}">
    <div class="tm">${esc(hm(r.received_at))}${st.d === 7 ? `<small>${esc(md(r.day + "T"))}</small>` : ""}</div>
    <div>${badge(r)}</div>
    <div>${pl}<div class="who"><b>${name}</b>${r.doc_type ? `<span class="dt">${esc(r.doc_type)}</span>` : ""}</div>
      <div><span class="src ${esc(tabOf(r) === "other" ? "other" : r.route.replace("_mirror", "").replace("_test", ""))}">${esc(SRC[r.route] || r.route)}</span><span class="sd">${who}</span></div>
      <div class="oid">${esc(idText(r))}</div></div>
    <div>${whyText(r)}</div>
    <div>${actionHTML(r, i)}</div></div>`;
}

async function openDrawer(i) {
  const r = st.rows[i];
  if (!r) return;
  const nextKey = r.view === "stale" ? "stale" : r.action;
  const nx = isFail(r) ? NEXT[nextKey] || NEXT.check : null;
  const url = safeURL(r.karte_url);
  const purl = homisPatientURL(r.patient && r.patient.homis_id);
  $("dbody").innerHTML = `<h2>${esc(SRC[r.route] || r.route)}　${esc(md(r.day + "T"))} ${esc(hm(r.received_at))}</h2><div>${badge(r)}</div>
    <dl class="dl">
      <dt>患者さん</dt><dd>${pi(r) ? esc(pi(r).name) + " 様（" + esc(pi(r).kana) + "）　" : ""}${purl ? `<a href="${esc(purl)}" target="_blank" rel="noopener noreferrer">患者ページ ↗</a>` : "（患者番号なし）"}</dd>
      <dt>所属クリニック</dt><dd>${esc(pi(r) ? pi(r).clinic : "－")}</dd>
      <dt>ORCA 番号</dt><dd>${esc(pi(r) ? pi(r).orca : "－")}</dd>
      <dt>HOMIS 番号</dt><dd>${esc((r.patient && r.patient.homis_id) || "－")}${r.pinfo && !r.pinfo.found ? `<div class="why">おひさまシステムで見つからない番号です（2 つ目のクリニックの番号など）</div>` : ""}</dd>
      <dt>書類種</dt><dd>${esc(r.doc_type || "－")}</dd>
      <dt>${r.route === "fax" ? "差出元" : "送った人"}</dt><dd>${esc((r.route === "fax" ? r.source : r.sender) || "－")}</dd>
      <dt>番号</dt><dd>${esc(idText(r))}${faxNote(r)}<div class="oid">${esc(r.order_id)}</div></dd>
      <dt>理由</dt><dd>${esc(r.view === "stale" ? "停止の疑い（途中で止まった見込み）" : reason(r.error_type) || "なし")}</dd>
      <dt>カルテ</dt><dd>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">HOMIS で開く ↗</a>` : "（書込できていません）"}</dd>
    </dl>
    ${nx ? `<div class="next ng"><b>🧭 次にすること</b>${esc(nx[0])}<br>${esc(nx[1])}</div>` : ""}
    <div id="detail"><p class="why">送られた中身を読み込み中…</p></div>`;
  $("drawer").classList.add("on");
  $("shade").classList.add("on");
  try {
    const d = await getJSON(`record?day=${encodeURIComponent(r.day)}&id=${encodeURIComponent(r.order_id)}`);
    const p = d.payload || {};
    const tl = (d.timeline || []).map((t) => `<li>${esc(hm(t.at))}　${esc(tlText(t.what, r))}</li>`).join("");   // 書込後確認はライター 3.12.0 が時刻の流れに書く
    $("detail").innerHTML = `<h3>時刻の流れ</h3><ul class="tl">${tl || "<li>（記録なし）</li>"}</ul>
      <h3>送られた S</h3><div class="body">${esc(p.sContent || "（なし）")}</div>
      ${p.oContent != null ? `<h3>送られた O</h3><div class="body">${esc(p.oContent || "（なし）")}</div>` : ""}`;
  } catch (e) {
    $("detail").innerHTML = `<p class="why">中身を読めませんでした（${esc(e.message)}）</p>`;
  }
}

function closeDrawer() { $("drawer").classList.remove("on"); $("shade").classList.remove("on"); }

document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-tab],[data-d],[data-s],[data-open],#onlyFail,#tests,#reload,#close,#shade,[data-stop]");
  if (!t) return;
  if (t.dataset.stop) return; // カルテを開く（リンク）
  if (t.dataset.tab) { st.tab = t.dataset.tab; render(); return; }
  if (t.dataset.d != null) {
    st.d = +t.dataset.d;
    st.from = st.d === 1 ? shift(todayStr(), -1) : "";
    $("day").value = st.from || todayStr();
    document.querySelectorAll("[data-d]").forEach((b) => b.classList.toggle("on", b === t));
    load(); return;
  }
  if (t.dataset.s) { setS(t.dataset.s); return; }
  if (t.dataset.open != null) { openDrawer(+t.dataset.open); return; }
  if (t.id === "onlyFail") { setS("fail"); return; }
  if (t.id === "tests") { st.tests = !st.tests; load(); return; }
  if (t.id === "reload") { load(); return; }
  if (t.id === "close" || t.id === "shade") closeDrawer();
});
function setS(s) { st.s = s; document.querySelectorAll("[data-s]").forEach((b) => b.classList.toggle("on", b.dataset.s === s)); render(); }
$("q").addEventListener("input", (e) => { st.q = e.target.value.trim(); render(); });
$("err_type").addEventListener("change", (e) => { st.err = e.target.value; render(); });
$("clinic").addEventListener("change", (e) => { st.clinic = e.target.value; render(); });
$("day").addEventListener("change", (e) => {
  st.from = e.target.value; st.d = 0;
  document.querySelectorAll("[data-d]").forEach((b) => b.classList.toggle("on", b.dataset.d === "0" && st.from === todayStr()));
  load();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

(async function start() {
  $("day").value = todayStr();
  try { st.me = await getJSON("me"); } catch (e) { st.me = {}; }
  await load();
  setInterval(() => { if (!document.hidden && !$("drawer").classList.contains("on")) load(); }, 60000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/kartelog/sw.js", { scope: "/kartelog/" }).catch(() => {});
})();
