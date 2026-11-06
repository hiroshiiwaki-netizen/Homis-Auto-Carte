// main_test.go — 実行リストの箱のテスト（すべてダミーの値）
package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

var fixedNow = time.Date(2026, 11, 6, 10, 0, 0, 0, jst)

type fakeSource struct {
	days     map[string][]Record
	full     map[string]map[string]any
	q        QueueInfo
	qerr     error
	listCall int
	missing  map[string]int
}

func (f *fakeSource) ListDay(ctx context.Context, day string) ([]Record, int, error) {
	f.listCall++
	if day == "2026-11-01" {
		return nil, 0, errors.New("boom")
	}
	return f.days[day], f.missing[day], nil
}
func (f *fakeSource) Get(ctx context.Context, day, id string) (map[string]any, error) {
	m, ok := f.full[day+"/"+id]
	if !ok {
		return nil, errNotFound
	}
	return m, nil
}
func (f *fakeSource) Queues(ctx context.Context) (QueueInfo, error) { return f.q, f.qerr }

type headerVerifier struct{}

// テスト用: X-Test-User があればその人（無ければ断る）
func (headerVerifier) Email(r *http.Request) (string, error) {
	if u := r.Header.Get("X-Test-User"); u != "" {
		return u, nil
	}
	return "", errors.New("no_token")
}

func newTestApp(src Source) *App {
	cfg := Config{Admins: parseAllowList("dx@nhw.jp")}
	a := newApp(cfg, headerVerifier{}, src)
	a.now = func() time.Time { return fixedNow }
	return a
}

func call(t *testing.T, h http.Handler, path, user string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest("GET", path, nil)
	if user != "" {
		req.Header.Set("X-Test-User", user)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	return w
}

func sample() *fakeSource {
	return &fakeSource{
		days: map[string][]Record{"2026-11-06": {
			{OrderID: "FAX-1", Route: "fax", Status: "ok", ReceivedAt: "2026-11-06T09:00:00+09:00", KarteURL: "https://homis.jp/k?karte_id=1"},
			{OrderID: "FAX-MIRROR-1", Route: "fax_mirror", Status: "ok", ReceivedAt: "2026-11-06T09:01:00+09:00"},
			{OrderID: "BOT-G-2", Route: "bot_g", Status: "fail", ErrorType: "locked:busy", LeftInHomis: "none", ReceivedAt: "2026-11-06T09:02:00+09:00"},
		}},
		full: map[string]map[string]any{
			"2026-11-06/FAX-1":        {"order_id": "FAX-1", "route": "fax", "payload": map[string]any{"sContent": "本文ダミー"}},
			"2026-11-06/FAX-MIRROR-1": {"order_id": "FAX-MIRROR-1", "route": "fax_mirror"},
		},
		q: QueueInfo{Counts: map[string]int{"homis-fax-writer": 0}, Names: map[string]bool{}},
	}
}

func TestAuthRequired(t *testing.T) {
	h := newTestApp(sample()).routes()
	for _, p := range []string{"/kartelog/", "/kartelog/app.js", "/kartelog/api/list", "/kartelog/api/record?day=2026-11-06&id=FAX-1", "/kartelog/api/status"} {
		if w := call(t, h, p, ""); w.Code != 403 {
			t.Fatalf("%s 署名なしで %d（403 のはず）", p, w.Code)
		}
	}
	if w := call(t, h, "/kartelog/", "a@nhw.jp"); w.Code != 200 || !strings.Contains(w.Body.String(), "実行リスト") {
		t.Fatalf("画面が出ない %d", w.Code)
	}
	if w := call(t, h, "/other", "a@nhw.jp"); w.Code != 404 {
		t.Fatalf("決めた道以外は 404 のはず %d", w.Code)
	}
}

func TestIAPVerifierRejectsForged(t *testing.T) {
	v := iapVerifier{audience: "/projects/1/locations/asia-northeast1/services/app-kartelog"}
	req := httptest.NewRequest("GET", "/kartelog/", nil)
	if _, err := v.Email(req); err == nil {
		t.Fatal("署名なしを通した")
	}
	req.Header.Set("X-Goog-IAP-JWT-Assertion", "eyJhbGciOiJub25lIn0.eyJlbWFpbCI6ImR4QG5ody5qcCJ9.")
	req.Header.Set("X-Goog-Authenticated-User-Email", "accounts.google.com:dx@nhw.jp")
	if _, err := v.Email(req); err == nil {
		t.Fatal("偽の署名を通した")
	}
}

func TestClassify(t *testing.T) {
	q := QueueInfo{Names: map[string]bool{"FAX-W": true}}
	old := "2026-11-06T09:30:00+09:00"    // 30 分前
	recent := "2026-11-06T09:55:00+09:00" // 5 分前
	cases := []struct {
		r            Record
		queueOK      bool
		view, action string
	}{
		{Record{Status: "ok"}, true, "ok", "open"},
		{Record{Status: "done"}, true, "done", "none"},
		{Record{Status: "fail", LeftInHomis: "none"}, true, "fail", "rewrite"},
		{Record{Status: "fail", LeftInHomis: "editing"}, true, "fail", "cancel_then_rewrite"},
		{Record{Status: "fail", LeftInHomis: "saved"}, true, "fail", "check"},
		{Record{Status: "fail", LeftInHomis: "unknown"}, true, "fail", "check"},
		{Record{Status: "fail"}, true, "fail", "check"}, // 古い JSON（欄が無い）は安全側
		{Record{Status: "rejected", ErrorType: "skip:id_mismatch", LeftInHomis: "none"}, true, "fail", "check"},
		{Record{Status: "rejected", ErrorType: "error:TimeoutError", LeftInHomis: "none"}, true, "fail", "rewrite"},
		{Record{OrderID: "FAX-W", Status: "received", ReceivedAt: old}, true, "waiting", "none"}, // 列で待っているだけ（11/5 の 25 分待ち）
		{Record{OrderID: "FAX-X", Status: "received", ReceivedAt: old}, true, "stale", "check"},
		{Record{OrderID: "FAX-X", Status: "accepted", ReceivedAt: old, AcceptedAt: recent}, true, "running", "none"},
		{Record{OrderID: "FAX-X", Status: "received", ReceivedAt: recent}, true, "running", "none"},
		{Record{OrderID: "FAX-X", Status: "received", ReceivedAt: old}, false, "running", "none"}, // 列が読めないときは 60 分まで待つ
		{Record{OrderID: "FAX-X", Status: "received", ReceivedAt: "2026-11-06T08:30:00+09:00"}, false, "stale", "check"},
		// 0.3.0: 自動やり直し
		{Record{Status: "handed_over"}, true, "handed", "none"},
		{Record{Status: "fail", ErrorType: "skipped:new_karte_found", LeftInHomis: "none"}, true, "human", "none"},
		{Record{Status: "fail", ErrorType: "locked:busy", LeftInHomis: "none", Manual: true}, true, "fail", "manual"},
		{Record{OrderID: "FAX-W", Status: "scheduled", RetryAt: "2026-11-06T10:05:00+09:00"}, true, "scheduled", "none"},
		{Record{OrderID: "FAX-X-A1", Status: "scheduled", RetryAt: "2026-11-06T10:05:00+09:00"}, true, "scheduled", "none"},
		{Record{OrderID: "FAX-X-A1", Status: "scheduled", RetryAt: "2026-11-06T09:30:00+09:00"}, true, "stale", "check"},
		{Record{OrderID: "FAX-X-A1", Status: "scheduled", RetryAt: "2026-11-06T09:58:00+09:00"}, true, "running", "none"},
	}
	for i, c := range cases {
		v, a := classify(c.r, q, c.queueOK, fixedNow)
		if v != c.view || a != c.action {
			t.Errorf("%d: %+v → (%s,%s) want (%s,%s)", i, c.r, v, a, c.view, c.action)
		}
	}
}

func TestListHidesTestsAndPayload(t *testing.T) {
	h := newTestApp(sample()).routes()
	get := func(path, user string) map[string]any {
		w := call(t, h, path, user)
		if w.Code != 200 {
			t.Fatalf("%s %d", path, w.Code)
		}
		if strings.Contains(w.Body.String(), "本文ダミー") || strings.Contains(w.Body.String(), "sContent") {
			t.Fatal("一覧に送られた中身が出ている")
		}
		var m map[string]any
		json.Unmarshal(w.Body.Bytes(), &m)
		return m
	}
	n := func(m map[string]any) int { return len(m["rows"].([]any)) }
	if got := n(get("/kartelog/api/list", "a@nhw.jp")); got != 2 {
		t.Fatalf("職員は試験の行を見ない: %d", got)
	}
	if got := n(get("/kartelog/api/list?tests=1", "a@nhw.jp")); got != 2 {
		t.Fatalf("職員は tests=1 でも見えない: %d", got)
	}
	if got := n(get("/kartelog/api/list?tests=1", "DX@nhw.jp")); got != 3 {
		t.Fatalf("DX推進部（大文字でも）は試験も見える: %d", got)
	}
	m := get("/kartelog/api/list", "a@nhw.jp")
	first := m["rows"].([]any)[0].(map[string]any)
	if first["order_id"] != "BOT-G-2" || first["action"] != "rewrite" || first["view"] != "fail" {
		t.Fatalf("新しい順・判定: %v", first)
	}
}

func TestRecordAndBadInput(t *testing.T) {
	h := newTestApp(sample()).routes()
	if w := call(t, h, "/kartelog/api/record?day=2026-11-06&id=FAX-1", "a@nhw.jp"); w.Code != 200 || !strings.Contains(w.Body.String(), "本文ダミー") {
		t.Fatalf("1件の中身 %d", w.Code)
	}
	if w := call(t, h, "/kartelog/api/record?day=2026-11-06&id=FAX-MIRROR-1", "a@nhw.jp"); w.Code != 403 {
		t.Fatalf("試験の行は職員に出さない %d", w.Code)
	}
	if w := call(t, h, "/kartelog/api/record?day=2026-11-06&id=FAX-MIRROR-1", "dx@nhw.jp"); w.Code != 200 {
		t.Fatalf("DX推進部には出す %d", w.Code)
	}
	for _, p := range []string{"/kartelog/api/record?day=2026-11-06&id=../x", "/kartelog/api/record?day=x&id=FAX-1", "/kartelog/api/list?from=2026-13-40"} {
		if w := call(t, h, p, "a@nhw.jp"); w.Code != 400 {
			t.Fatalf("%s %d（400 のはず）", p, w.Code)
		}
	}
	if w := call(t, h, "/kartelog/api/record?day=2026-11-06&id=FAX-9", "a@nhw.jp"); w.Code != 404 {
		t.Fatalf("無いもの %d", w.Code)
	}
}

func TestDaysAndFailedDay(t *testing.T) {
	src := sample()
	h := newTestApp(src).routes()
	w := call(t, h, "/kartelog/api/list?from=2026-11-06&days=99", "a@nhw.jp")
	var m struct {
		Days       []string `json:"days"`
		FailedDays []string `json:"failed_days"`
	}
	json.Unmarshal(w.Body.Bytes(), &m)
	if len(m.Days) != 7 || m.Days[6] != "2026-10-31" {
		t.Fatalf("7日まで: %v", m.Days)
	}
	if len(m.FailedDays) != 1 || m.FailedDays[0] != "2026-11-01" {
		t.Fatalf("読めなかった日を知らせる: %v", m.FailedDays)
	}
	before := src.listCall
	call(t, h, "/kartelog/api/list?from=2026-11-06&days=1", "a@nhw.jp")
	if src.listCall != before {
		t.Fatal("写しを使わずに読み直した")
	}
}

func TestHeaders(t *testing.T) {
	h := newTestApp(sample()).routes()
	for _, p := range []string{"/kartelog/api/list", "/kartelog/api/record?day=2026-11-06&id=FAX-1", "/kartelog/"} {
		if got := call(t, h, p, "a@nhw.jp").Header().Get("Cache-Control"); got != "no-store" {
			t.Fatalf("%s にキャッシュしない印が無い: %q", p, got)
		}
	}
	w := call(t, h, "/kartelog/api/status", "a@nhw.jp")
	if w.Header().Get("Cache-Control") != "no-store" || !strings.Contains(w.Header().Get("Content-Security-Policy"), "default-src 'self'") {
		t.Fatal("キャッシュを残さない・よその部品を読まない印")
	}
	if !strings.Contains(w.Body.String(), `"homis-fax-writer":0`) {
		t.Fatalf("列の件数: %s", w.Body.String())
	}
}

// 本物の読み方（gcp）を偽の Cloud Storage・Cloud Tasks に向ける
func TestGCPSource(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := r.URL.EscapedPath()
		switch {
		case strings.HasPrefix(p, "/token"):
			w.Write([]byte(`{"access_token":"t","expires_in":3600}`))
		case p == "/storage/v1/b/bk/o" && r.URL.Query().Get("prefix") == "records/2026-11-06/":
			w.Write([]byte(`{"items":[{"name":"records/2026-11-06/FAX-1.json"},{"name":"records/2026-11-06/BOT-2.json"},{"name":"records/2026-11-06/x.txt"}]}`))
		case p == "/storage/v1/b/bk/o/records%2F2026-11-06%2FFAX-1.json":
			w.Write([]byte(`{"order_id":"FAX-1","status":"ok","patient":{"homis_id":"1"},"extra":{"a":1}}`))
		case p == "/storage/v1/b/bk/o/records%2F2026-11-06%2FBOT-2.json":
			w.Write([]byte(`{"status":"received"}`)) // 欄の足りない古い JSON
		case strings.HasSuffix(p, "/queues/homis-fax-writer/tasks"):
			w.Write([]byte(`{"tasks":[{"name":"projects/p/locations/l/queues/homis-fax-writer/tasks/FAX-9"}]}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	g := newGCP(Config{Bucket: "bk", StorageBase: srv.URL, TasksBase: srv.URL + "/v2/", TokenURL: srv.URL + "/token",
		Queues: []string{"projects/p/locations/l/queues/homis-fax-writer"}})
	recs, miss, err := g.ListDay(context.Background(), "2026-11-06")
	if err != nil || len(recs) != 2 || miss != 0 {
		t.Fatalf("2件読めるはず %v %d %d", err, len(recs), miss)
	}
	ids := recs[0].OrderID + "," + recs[1].OrderID
	if ids != "FAX-1,BOT-2" {
		t.Fatalf("名前から注文番号を補う: %s", ids)
	}
	if _, err := g.Get(context.Background(), "2026-11-06", "FAX-404"); err != errNotFound {
		t.Fatalf("無いものは errNotFound: %v", err)
	}
	if _, _, err := g.ListDay(context.Background(), "../x"); err == nil {
		t.Fatal("変な日付を通した")
	}
	q, err := g.Queues(context.Background())
	if err != nil || !q.Names["FAX-9"] || q.Counts["homis-fax-writer"] != 1 {
		t.Fatalf("列: %v %+v", err, q)
	}
}

// 読めなかった記録は 1 回読み直し、それでもだめなら件数を返す（黙って捨てない）
func TestMissingRecordsReported(t *testing.T) {
	hits := map[string]int{}
	var hmu sync.Mutex // 箱が並べて読むので、数える表に鍵（go test -race で見つけた）
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := r.URL.EscapedPath()
		hmu.Lock()
		hits[p]++
		n := hits[p]
		hmu.Unlock()
		switch {
		case strings.HasPrefix(p, "/token"):
			w.Write([]byte(`{"access_token":"t","expires_in":3600}`))
		case p == "/storage/v1/b/bk/o":
			w.Write([]byte(`{"items":[{"name":"records/2026-11-06/A.json"},{"name":"records/2026-11-06/B.json"},{"name":"records/2026-11-06/C.json"}]}`))
		case strings.HasSuffix(p, "A.json"):
			w.Write([]byte(`{"status":"ok"}`))
		case strings.HasSuffix(p, "B.json") && n == 1:
			http.Error(w, "busy", 503) // 1 回目だけ失敗
		case strings.HasSuffix(p, "B.json"):
			w.Write([]byte(`{"status":"ok"}`))
		default:
			http.Error(w, "down", 500) // C はずっと失敗
		}
	}))
	defer srv.Close()
	g := newGCP(Config{Bucket: "bk", StorageBase: srv.URL, TokenURL: srv.URL + "/token"})
	recs, miss, err := g.ListDay(context.Background(), "2026-11-06")
	if err != nil || len(recs) != 2 || miss != 1 {
		t.Fatalf("A・B は読める（B は読み直し）・C は欠け 1: %v %d %d", err, len(recs), miss)
	}

	src := sample()
	src.missing = map[string]int{"2026-11-06": 1}
	h := newTestApp(src).routes()
	w := call(t, h, "/kartelog/api/list", "a@nhw.jp")
	if !strings.Contains(w.Body.String(), `"missing":1`) {
		t.Fatalf("欠けの件数を画面に渡す: %s", w.Body.String())
	}
	before := src.listCall
	call(t, h, "/kartelog/api/list", "a@nhw.jp")
	if src.listCall == before {
		t.Fatal("欠けのある日は写しを持たず読み直す")
	}
}
