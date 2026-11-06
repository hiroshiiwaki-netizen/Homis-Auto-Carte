// patient_test.go — おひさまシステムから患者さんの表示を引く部品のテスト（偽の FM・すべてダミーの値）
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// fakeFM は FileMaker Data API に似せた偽物。
type fakeFM struct {
	mu       sync.Mutex
	logins   int32
	finds    int32
	expireAt int32 // この回数目の _find でセッション切れ（952）を返す（0 は返さない）
	hang     time.Duration
	miss401  bool // 見つからないとき HTTP 401（＋code 401）で返す FM
	down     bool
	rows     map[string][]map[string]any // homisID → 当たる行
	tokens   map[string]bool
	queries  []string
}

func newFakeFM() (*fakeFM, *httptest.Server) {
	f := &fakeFM{rows: map[string][]map[string]any{}, tokens: map[string]bool{}}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if f.down {
			http.Error(w, "down", 503)
			return
		}
		if f.hang > 0 {
			time.Sleep(f.hang)
		}
		switch {
		case strings.HasSuffix(r.URL.Path, "/sessions") && r.Method == "POST":
			u, p, ok := r.BasicAuth()
			if !ok || u != "u" || p != "p" {
				w.WriteHeader(401)
				fmt.Fprint(w, `{"messages":[{"code":"212"}]}`)
				return
			}
			n := atomic.AddInt32(&f.logins, 1)
			tok := fmt.Sprintf("tok%d", n)
			f.mu.Lock()
			f.tokens = map[string]bool{tok: true} // 新しいトークンだけ有効
			f.mu.Unlock()
			fmt.Fprintf(w, `{"response":{"token":"%s"},"messages":[{"code":"0"}]}`, tok)
		case strings.HasSuffix(r.URL.Path, "/_find"):
			n := atomic.AddInt32(&f.finds, 1)
			tok := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			f.mu.Lock()
			valid := f.tokens[tok]
			if f.expireAt == n {
				delete(f.tokens, tok)
				valid = false
			}
			f.mu.Unlock()
			if !valid {
				w.WriteHeader(401)
				fmt.Fprint(w, `{"messages":[{"code":"952"}]}`)
				return
			}
			b, _ := io.ReadAll(r.Body)
			var q struct {
				Query []map[string]string `json:"query"`
			}
			json.Unmarshal(b, &q)
			v := q.Query[0]["homisID"]
			f.mu.Lock()
			f.queries = append(f.queries, v)
			f.mu.Unlock()
			id := strings.TrimPrefix(v, "==")
			data := f.rows[id]
			if !strings.HasPrefix(v, "==") || len(data) == 0 {
				if f.miss401 {
					w.WriteHeader(401)
				}
				fmt.Fprint(w, `{"messages":[{"code":"401"}],"response":{}}`)
				return
			}
			out := []map[string]any{}
			for _, fd := range data {
				out = append(out, map[string]any{"fieldData": fd})
			}
			j, _ := json.Marshal(map[string]any{"messages": []map[string]string{{"code": "0"}}, "response": map[string]any{"data": out}})
			w.Write(j)
		default:
			http.NotFound(w, r)
		}
	}))
	return f, srv
}

func row(id, clinic, orca, name string) map[string]any {
	return map[string]any{"homisID": id, "クリニック名": clinic, "ORCAID": orca, "patient_name": name, "seimei_kana": "かな"}
}

func src(srv *httptest.Server) *fmSource { return newFMSource(srv.URL, "db", "u", "p", "") }

func TestFMFindFoundMissingAmbiguous(t *testing.T) {
	f, srv := newFakeFM()
	defer srv.Close()
	f.rows["2277808"] = []map[string]any{row("2277808", "おひさまクリニック舞子", "0003", "テスト 舞子")}
	f.rows["1000002"] = []map[string]any{row("1000002", "A", "1", "見本 一"), row("1000002", "B", "2", "見本 二")}
	s := src(srv)
	got, err := s.Find(context.Background(), "2277808")
	if err != nil || !got.Found || got.Clinic != "おひさまクリニック舞子" || got.Orca != "0003" || got.Name != "テスト 舞子" {
		t.Fatalf("見つかる: %+v %v", got, err)
	}
	if got, err := s.Find(context.Background(), "1000001"); err != nil || got.Found {
		t.Fatalf("無い番号は名前なし: %+v %v", got, err)
	}
	if got, err := s.Find(context.Background(), "1000002"); err != nil || got.Found || got.Name != "" {
		t.Fatalf("2 件当たれば名前を出さない（取り違えを出さない）: %+v %v", got, err)
	}
	for _, q := range f.queries {
		if !strings.HasPrefix(q, "==") {
			t.Fatalf("完全一致で引いていない: %s", q)
		}
	}
	if got, _ := s.Find(context.Background(), "12a4"); got.Found || atomic.LoadInt32(&f.finds) != 3 {
		t.Fatal("番号の形でないものは引かない")
	}
}

func TestFMSessionRefreshOnce(t *testing.T) {
	f, srv := newFakeFM()
	defer srv.Close()
	f.rows["2277808"] = []map[string]any{row("2277808", "C", "3", "テスト 舞子")}
	s := src(srv)
	s.Find(context.Background(), "2277808")
	f.expireAt = 2 // 2 回目の _find でセッション切れ
	got, err := s.Find(context.Background(), "2277808")
	if err != nil || !got.Found || atomic.LoadInt32(&f.logins) != 2 {
		t.Fatalf("切れたら 1 回だけ取り直す: %+v %v logins=%d", got, err, f.logins)
	}
	// 同時に 10 件が切れたトークンを持っていても、取り直しは 1 回
	f.mu.Lock()
	f.tokens = map[string]bool{}
	f.mu.Unlock()
	before := atomic.LoadInt32(&f.logins)
	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); s.Find(context.Background(), "2277808") }()
	}
	wg.Wait()
	if n := atomic.LoadInt32(&f.logins) - before; n != 1 {
		t.Fatalf("同時に切れても取り直しは 1 回のはず: %d", n)
	}
}

// countSource は Find の回数を数える偽物（Resolver のテスト用）。
type countSource struct {
	mu    sync.Mutex
	calls map[string]int
	order []string
	delay time.Duration
	fail  bool
}

func (c *countSource) Find(ctx context.Context, id string) (PatientInfo, error) {
	time.Sleep(c.delay)
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.calls == nil {
		c.calls = map[string]int{}
	}
	c.calls[id]++
	c.order = append(c.order, id)
	if c.fail {
		return PatientInfo{}, errors.New("down")
	}
	return PatientInfo{Found: true, Name: "見本 " + id}, nil
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	for i := 0; i < 200; i++ {
		if cond() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("待っても終わらない")
}

func TestResolverAsyncAndDedup(t *testing.T) {
	cs := &countSource{delay: 50 * time.Millisecond}
	r := NewResolver(cs)
	defer r.Close()
	t0 := time.Now()
	if got := r.Lookup([]string{"1000001", "1000001", " 1000002 ", "x"}); len(got) != 0 {
		t.Fatal("初めは覚えていない（FM を待たずに空で返す）")
	}
	if time.Since(t0) > 20*time.Millisecond {
		t.Fatal("一覧は FM を待たない")
	}
	for i := 0; i < 10; i++ { // 10 人が同時に開いた
		go r.Lookup([]string{"1000001"})
	}
	waitFor(t, func() bool { return len(r.Lookup([]string{"1000001", "1000002"})) == 2 })
	cs.mu.Lock()
	defer cs.mu.Unlock()
	if cs.calls["1000001"] != 1 || cs.calls["1000002"] != 1 {
		t.Fatalf("同じ番号は 1 回だけ引く: %v", cs.calls)
	}
}

func TestResolverQueueCapNewestFirst(t *testing.T) {
	cs := &countSource{}
	r := &Resolver{src: cs, now: time.Now, cache: map[string]pinfoEntry{}, pending: map[string]bool{}, wake: make(chan struct{}, 1), stop: make(chan struct{})}
	ids := []string{}
	for i := 1; i <= 150; i++ {
		ids = append(ids, fmt.Sprintf("%d", 3000000+i))
	}
	r.request(ids) // 係はまだ動かしていない
	if len(r.queue) != pinfoQueueMax || r.queue[0] != "3000051" {
		t.Fatalf("100 件まで・古い頼みを捨てる: %d %s", len(r.queue), r.queue[0])
	}
	go r.worker()
	defer close(r.stop)
	r.wake <- struct{}{}
	waitFor(t, func() bool { cs.mu.Lock(); defer cs.mu.Unlock(); return len(cs.order) >= 1 })
	cs.mu.Lock()
	first := cs.order[0]
	cs.mu.Unlock()
	if first != "3000150" {
		t.Fatalf("新しい頼みを先に引く: %s", first)
	}
}

func TestResolverPauseAndMissTTL(t *testing.T) {
	cs := &countSource{fail: true}
	r := NewResolver(cs)
	defer r.Close()
	r.Lookup([]string{"1", "2", "3"})
	waitFor(t, func() bool { r.qmu.Lock(); defer r.qmu.Unlock(); return !r.pauseTo.IsZero() })
	r.Lookup([]string{"4"})
	r.qmu.Lock()
	n := len(r.queue)
	r.qmu.Unlock()
	if n != 0 {
		t.Fatal("休んでいる間は頼みを受けない")
	}
	// 見つからなかった番号は 1 時間で忘れる・見つかった番号は 24 時間
	now := time.Now()
	r.mu.Lock()
	r.cache["7"] = pinfoEntry{info: PatientInfo{Found: false}, at: now.Add(-61 * time.Minute)}
	r.cache["8"] = pinfoEntry{info: PatientInfo{Found: true, Name: "見本"}, at: now.Add(-23 * time.Hour)}
	r.mu.Unlock()
	got := r.Lookup([]string{"7", "8"})
	if _, ok := got["7"]; ok {
		t.Fatal("見つからない番号は 1 時間で忘れる")
	}
	if got["8"].Name != "見本" {
		t.Fatal("見つかった番号は 24 時間覚える")
	}
}

func TestListDoesNotWaitForFM(t *testing.T) {
	f, srv := newFakeFM()
	defer srv.Close()
	f.hang = 3 * time.Second // FM が遅い
	a := newTestApp(sample())
	a.pinfo = NewResolver(src(srv))
	defer a.pinfo.Close()
	h := a.routes()
	t0 := time.Now()
	w := call(t, h, "/kartelog/api/list", "a@nhw.jp")
	if w.Code != 200 || time.Since(t0) > 500*time.Millisecond {
		t.Fatalf("一覧は FM を待たない: %d %v", w.Code, time.Since(t0))
	}
}

func TestListShowsPatientAfterResolve(t *testing.T) {
	f, srv := newFakeFM()
	defer srv.Close()
	f.rows["1000009"] = []map[string]any{row("1000009", "おひさまクリニック舞子", "0009", "見本 花子")}
	s := sample()
	s.days["2026-11-06"][0].Patient.HomisID = "1000009"
	a := newTestApp(s)
	a.pinfo = NewResolver(src(srv))
	defer a.pinfo.Close()
	h := a.routes()
	call(t, h, "/kartelog/api/list", "a@nhw.jp") // 1 回目で頼む
	var body string
	waitFor(t, func() bool {
		body = call(t, h, "/kartelog/api/list", "a@nhw.jp").Body.String()
		return strings.Contains(body, "見本 花子")
	})
	if !strings.Contains(body, `"clinic":"おひさまクリニック舞子"`) || !strings.Contains(body, `"orca":"0009"`) {
		t.Fatalf("所属クリニック・ORCA が出る: %s", body)
	}
}

func TestFMCloseLogsOut(t *testing.T) {
	f, srv := newFakeFM()
	defer srv.Close()
	f.rows["2277808"] = []map[string]any{row("2277808", "C", "3", "テスト 舞子")}
	s := src(srv)
	s.Find(context.Background(), "2277808")
	s.Close(context.Background())
	if s.token != "" {
		t.Fatal("閉じたらトークンを忘れる")
	}
	s.Close(context.Background()) // 2 回目は何もしない
}

func TestFMMissWithHTTP401IsNotExpiry(t *testing.T) {
	f, srv := newFakeFM()
	defer srv.Close()
	f.miss401 = true
	s := src(srv)
	for i := 0; i < 5; i++ {
		got, err := s.Find(context.Background(), "1000001")
		if err != nil || got.Found {
			t.Fatalf("HTTP 401 の「見つからない」は見つからないのまま（エラーにしない）: %+v %v", got, err)
		}
	}
	if n := atomic.LoadInt32(&f.logins); n != 1 {
		t.Fatalf("見つからないだけで取り直さない: logins=%d", n)
	}
}
