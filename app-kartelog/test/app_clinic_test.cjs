// 実行リスト 0.3.2〜0.3.6 クリニックで絞った数字・版・自動の読み直しの試験（偽の画面部品で public/app.js を動かす。node だけで動く）
// 使い方: node app-kartelog/test/app_clinic_test.cjs [app.js のパス]（省略時は ../public/app.js）
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2] || require("path").join(__dirname, "..", "public", "app.js"), "utf8");
const els = {};
const el = (id) => els[id] || (els[id] = {
  id, textContent: "", innerHTML: "", value: "", dataset: {}, style: {},
  classList: { _s: new Set(), toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); }, add(c) { this._s.add(c); }, contains(c) { return this._s.has(c); } },
  setAttribute() {}, appendChild() {}, addEventListener() {},
});
const robot = el("robot");
const timers = [], vis = [];   // 0.3.6: 自動の読み直しのタイマーと「画面に戻った」の受け手
const clicks = [];   // 0.3.4: 画面のクリックの受け手（document の click）を拾って、ボタンを押したことにする
const press = (id) => clicks.forEach((fn) => fn({ target: { closest: () => ({ id, dataset: {} }) } }));
const ctx = {
  document: { getElementById: el, querySelector: () => robot, querySelectorAll: () => [], addEventListener(type, fn) { if (type === "click") clicks.push(fn); if (type === "visibilitychange") vis.push(fn); }, createElement: () => ({ style: {} }), hidden: false },
  navigator: {}, setInterval(fn, ms) { timers.push([fn, ms]); }, console, Date,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
};
vm.createContext(ctx);
vm.runInContext(src + "\n;globalThis.__st = st; globalThis.__render = render;", ctx);

const row = (clinic, view, h) => ({ route: "fax", view, received_at: `2026-11-06T${h}:00:00`, day: "2026-11-06", pinfo: clinic ? { found: true, clinic } : { found: false } });
const st = ctx.__st;
st.rows = [row("垂水", "ok", "09"), row("垂水", "fail", "10"), row("舞子", "ok", "11"), row("舞子", "running", "12"), row(null, "ok", "13")];

let bad = 0;
const eq = (name, a, b) => { if (String(a) !== String(b)) { bad++; console.log("NG", name, a, "!=", b); } else console.log("OK", name, a); };

st.clinic = ""; ctx.__render();
eq("全院 件数", els.kAll.textContent, 5); eq("全院 失敗", els.kNg.textContent, 1); eq("全院 見出し", els.kLabel.textContent, "今日の件数");

st.clinic = "舞子"; ctx.__render();
eq("舞子 件数", els.kAll.textContent, 2); eq("舞子 成功", els.kOk.textContent, 1); eq("舞子 失敗", els.kNg.textContent, 0); eq("舞子 書込中", els.kRun.textContent, 1);
eq("舞子 見出し", els.kLabel.textContent, "今日の件数（舞子）");
eq("舞子 赤い知らせなし", els.alertBox.classList.contains("on"), false);
eq("舞子 タブ件数", /全記録<span class="n">2</.test(els.tabs.innerHTML), true);
eq("選択欄に垂水も残る", els.clinic.innerHTML.includes("垂水"), true);
eq("ロボットは全体の様子（書込中あり）", robot.classList.contains("robot-busy"), true);

st.clinic = "垂水"; ctx.__render();
eq("垂水 件数", els.kAll.textContent, 2); eq("垂水 失敗", els.kNg.textContent, 1); eq("垂水 赤い知らせ", els.alertBox.classList.contains("on"), true);

st.d = 7; ctx.__render();
eq("7日でも見出しに院名", els.kLabel.textContent, "7日の件数（垂水）");
st.d = 0;
// 選んだ院がその日に 0 件でも、選択欄に選んだまま残る
st.rows = [row("舞子", "ok", "09")]; st.clinic = "垂水"; ctx.__render();
eq("0件の日も院が選ばれたまま", /value="垂水" selected/.test(els.clinic.innerHTML), true);
eq("0件の日の件数", els.kAll.textContent, 0);
st.err = "login"; ctx.__render();
eq("エラーの種類も選ばれたまま", /value="login" selected/.test(els.err_type.innerHTML), true);

// 0.3.3: 院の分からない行（pinfo が無い・found が false）
st.err = ""; st.s = "all";
st.rows = [row("垂水", "ok", "09"), row(null, "fail", "10"), { ...row(null, "running", "11"), pinfo: undefined }];
st.clinic = "垂水"; ctx.__render();
eq("院の分からない行は院の数に入らない", els.kAll.textContent, 1);
eq("院の分からない件数を出す", el("barsLabel").textContent, "8時〜19時の時間ごと／院の分からない 2 件は入っていません");
eq("院の分からない書込失敗で赤い知らせ", els.alertBox.classList.contains("on"), true);
eq("すべてのクリニックへのボタン", els.alertBox.innerHTML.includes('id="allClinic"'), true);
st.rows.push(row("垂水", "fail", "12")); ctx.__render();
eq("院の失敗とあわせて書く", /書込失敗が 1 件[\s\S]*ほかに院の分からない行に書込失敗が 1 件/.test(els.alertBox.innerHTML), true);
eq("院の失敗があってもすべてのクリニックへのボタン", els.alertBox.innerHTML.includes('id="allClinic"') && els.alertBox.innerHTML.includes('id="onlyFail"'), true);
st.clinic = ""; ctx.__render();
eq("すべてのときは注意書きなし", el("barsLabel").textContent, "8時〜19時の時間ごと");

// 0.3.4: 患者様は見つかったが院の名前が空の行も「院の分からない」に入る（黒ヤギ2回目 指摘1）
st.rows = [row("垂水", "ok", "09"), { ...row("垂水", "fail", "10"), pinfo: { found: true, clinic: "" } }];
st.clinic = "垂水"; ctx.__render();
eq("院の名前が空の行も院の分からないに入る", el("barsLabel").textContent, "8時〜19時の時間ごと／院の分からない 1 件は入っていません");
eq("院の名前が空の書込失敗で赤い知らせ", els.alertBox.classList.contains("on"), true);

// 0.3.4: すべてのクリニックで見る を押すと、院・エラーの種類・検索語を外して書込失敗だけ（指摘2）
st.err = "login"; st.q = "abc"; el("q").value = "abc";
press("allClinic");
eq("押すと院の絞りが外れる", st.clinic, "");
eq("押すとエラーの種類が外れる", st.err, "");
eq("押すと検索語が外れる", st.q + "|" + el("q").value, "|");
eq("押すと書込失敗だけ", st.s, "fail");
eq("押したあと一覧に書込失敗の行が出る", /class="row/.test(els.list.innerHTML), true);

// 0.3.5: 画面の版（見出しの横）と、版が 3 か所でそろっているか（main.go・app.js・sw.js）
if (!process.argv[2]) {
  const p = require("path");
  const goV = (fs.readFileSync(p.join(__dirname, "..", "main.go"), "utf8").match(/^const version = "([^"]+)"/m) || [])[1];
  const jsV = (src.match(/const APP_VERSION = "([^"]+)"/) || [])[1];
  const swV = (fs.readFileSync(p.join(__dirname, "..", "public", "sw.js"), "utf8").match(/kartelog-([0-9.]+)"/) || [])[1];
  eq("版 main.go と app.js が同じ", goV + "|" + jsV, goV + "|" + goV);
  eq("版 main.go と sw.js が同じ", swV, goV);
  ctx.showVersion(goV);
  eq("見出しに版", el("ver").textContent, "版 " + goV);
  eq("同じ版なら目立たせない", el("ver").classList.contains("old"), false);
  ctx.showVersion("9.9.9");
  eq("箱が新しいと F5 を案内", el("ver").textContent.includes("新しい版 9.9.9") && el("ver").textContent.includes("F5"), true);
  eq("古い画面は目立たせる", el("ver").classList.contains("old"), true);
  ctx.showVersion(undefined);
  eq("版が読めないときは画面の版だけ", el("ver").textContent, "版 " + goV);
}

// 0.3.6: 自動の読み直し（start() の await のあとで登録されるので、少し待ってから見る）
setTimeout(() => {
  if (typeof ctx.maybeLoad !== "function") { eq("自動の読み直しの関数がある", false, true); }
  else {
    eq("10 秒ごとに見る", timers.length === 1 && timers[0][1] === 10000, true);
    eq("画面に戻ったときの受け手", vis.length, 1);
    const drawer = el("drawer"), d = ctx.document;
    d.hidden = false; drawer.classList.toggle("on", false); st.loading = false;
    st.loadedAt = Date.now() - 61000;
    eq("60 秒たてば読む", ctx.maybeLoad(60000), true);
    st.loading = false; st.loadedAt = Date.now() - 20000;
    eq("60 秒たっていなければ読まない", ctx.maybeLoad(60000), false);
    st.loadedAt = Date.now() - 61000; drawer.classList.toggle("on", true);
    eq("窓を開いているあいだは読まない", ctx.maybeLoad(60000), false);
    drawer.classList.toggle("on", false); d.hidden = true;
    eq("画面が裏のあいだは読まない", ctx.maybeLoad(60000), false);
    d.hidden = false; st.loading = true;
    eq("読み込み中は重ねない", ctx.maybeLoad(60000), false);
    st.loading = false; st.loadedAt = Date.now() - 31000;
    eq("画面に戻ったとき 30 秒たっていれば読む", ctx.maybeLoad(30000), true);
  }
  console.log(bad ?`FAIL ${bad}` : "ALL OK");
  process.exit(bad ? 1 : 0);
}, 50);
