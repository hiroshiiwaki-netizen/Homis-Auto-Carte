// 実行リスト 0.3.2 クリニックで絞った数字の試験（偽の画面部品で public/app.js を動かす。node だけで動く）
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
const ctx = {
  document: { getElementById: el, querySelector: () => robot, querySelectorAll: () => [], addEventListener() {}, createElement: () => ({ style: {} }), hidden: false },
  navigator: {}, setInterval() {}, console,
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
st.clinic = ""; ctx.__render();
eq("すべてのときは注意書きなし", el("barsLabel").textContent, "8時〜19時の時間ごと");

console.log(bad ?`FAIL ${bad}` : "ALL OK");
process.exit(bad ? 1 : 0);
