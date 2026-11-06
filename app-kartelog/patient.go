// patient.go — 患者さんの表示（所属クリニック・ORCA番号・患者名）をおひさまシステム（FileMaker）から引く
//
// 仕様 docs/SPEC_実行リスト_v0.md v0.8 13章（黒ヤギ 仕様2回目【進めてよい】）。
//   - 一覧は FM を待たない。覚えている分だけ付けてすぐ返し、まだの番号は裏の係に頼む（次の読み直しで出る）
//   - 同じ番号の頼みは 1 回にまとめる。頼みの列は 100 件まで・あふれたら古い頼みを捨て、新しい頼みを先に引く
//   - 覚えは 24 時間（見つからない番号は 1 時間）。FM に続けて失敗したら 60 秒は引かない（頼みも受けない）
//   - FM のセッションは 1 つを使い回し、切れたら鍵をかけて 1 回だけ取り直す
//   - 1 件に決まらない（0 件・2 件以上）ときは名前を出さない（取り違えを出さない）
//   - 患者名・ORCA番号はログに出さない。読むだけ（FM に書かない）
//
// 将来 Solcore に替えるときは、PatientSource を差し替える。
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"
)

// PatientInfo は一覧に出す患者さんの情報。Found=false なら名前は出さない（ふつうの患者番号で出す）。
type PatientInfo struct {
	Found  bool   `json:"found"`
	Clinic string `json:"clinic,omitempty"`
	Orca   string `json:"orca,omitempty"`
	Name   string `json:"name,omitempty"`
	Kana   string `json:"kana,omitempty"`
}

// PatientSource は 1 件を引く先（今は FM・将来 Solcore）。found=false・err=nil は「1 件に決まらない」。
type PatientSource interface {
	Find(ctx context.Context, homisID string) (PatientInfo, error)
}

const (
	pinfoTTL      = 24 * time.Hour
	pinfoMissTTL  = 1 * time.Hour
	pinfoQueueMax = 100
	pinfoWorkers  = 2
	pinfoTimeout  = 5 * time.Second
	pinfoPause    = 60 * time.Second
	pinfoFailMax  = 3 // 続けてこの回数失敗したら休む
)

var homisIDRe = regexp.MustCompile(`^[1-9][0-9]{0,9}$`)

type pinfoEntry struct {
	info PatientInfo
	at   time.Time
}

// Resolver は覚え・頼みの列・裏の係。
type Resolver struct {
	src     PatientSource
	now     func() time.Time
	mu      sync.RWMutex
	cache   map[string]pinfoEntry
	qmu     sync.Mutex
	queue   []string        // 頼みの列（後ろほど新しい）
	pending map[string]bool // 列にある・引いている番号（同じ番号は 1 回）
	wake    chan struct{}
	fails   int
	pauseTo time.Time
	stop    chan struct{}
}

func NewResolver(src PatientSource) *Resolver {
	r := &Resolver{src: src, now: time.Now, cache: map[string]pinfoEntry{}, pending: map[string]bool{},
		wake: make(chan struct{}, 1), stop: make(chan struct{})}
	for i := 0; i < pinfoWorkers; i++ {
		go r.worker()
	}
	return r
}

func (r *Resolver) Close() { close(r.stop) }

// Lookup は覚えている分だけ返す（FM は待たない）。覚えていない・古い番号は頼みの列に入れる。
func (r *Resolver) Lookup(ids []string) map[string]PatientInfo {
	out := map[string]PatientInfo{}
	var miss []string
	now := r.now()
	r.mu.RLock()
	for _, id := range ids {
		id = strings.TrimSpace(id)
		if !homisIDRe.MatchString(id) {
			continue
		}
		e, ok := r.cache[id]
		ttl := pinfoTTL
		if ok && !e.info.Found {
			ttl = pinfoMissTTL
		}
		if ok && now.Sub(e.at) <= ttl {
			out[id] = e.info
			continue
		}
		miss = append(miss, id)
	}
	r.mu.RUnlock()
	r.request(miss)
	return out
}

// request は頼みの列に入れる。休んでいる間は受けない。あふれたら古い頼みを捨てる。
func (r *Resolver) request(ids []string) {
	if len(ids) == 0 {
		return
	}
	r.qmu.Lock()
	defer r.qmu.Unlock()
	if r.now().Before(r.pauseTo) {
		return
	}
	for _, id := range ids {
		if r.pending[id] {
			continue
		}
		if len(r.queue) >= pinfoQueueMax {
			old := r.queue[0]
			r.queue = r.queue[1:]
			delete(r.pending, old)
		}
		r.queue = append(r.queue, id)
		r.pending[id] = true
	}
	select {
	case r.wake <- struct{}{}:
	default:
	}
}

// next は一番新しい頼みを取り出す（新しく書かれたカルテを先に）。
func (r *Resolver) next() (string, bool) {
	r.qmu.Lock()
	defer r.qmu.Unlock()
	if len(r.queue) == 0 || r.now().Before(r.pauseTo) {
		return "", false
	}
	id := r.queue[len(r.queue)-1]
	r.queue = r.queue[:len(r.queue)-1]
	return id, true // pending は引き終わるまで残す（引いている間の同じ頼みを 1 回にまとめる）
}

func (r *Resolver) worker() {
	for {
		id, ok := r.next()
		if !ok {
			select {
			case <-r.wake:
				continue
			case <-r.stop:
				return
			case <-time.After(2 * time.Second):
				continue
			}
		}
		ctx, cancel := context.WithTimeout(context.Background(), pinfoTimeout)
		info, err := r.src.Find(ctx, id)
		cancel()
		r.qmu.Lock()
		delete(r.pending, id)
		if err != nil {
			r.fails++
			if r.fails >= pinfoFailMax {
				r.pauseTo = r.now().Add(pinfoPause)
				r.fails = 0
				log.Printf("PINFO pause %ds reason=%s", int(pinfoPause.Seconds()), errWord(err))
			}
			r.qmu.Unlock()
			continue
		}
		r.fails = 0
		r.qmu.Unlock()
		r.mu.Lock()
		r.cache[id] = pinfoEntry{info: info, at: r.now()}
		if len(r.cache) > 20000 {
			r.cache = map[string]pinfoEntry{}
		}
		r.mu.Unlock()
	}
}

// errWord はログ用の短い言葉（患者の情報・ログイン情報は入れない）。
func errWord(err error) string {
	s := err.Error()
	if len(s) > 40 {
		s = s[:40]
	}
	return regexp.MustCompile(`[^A-Za-z0-9 _:.-]`).ReplaceAllString(s, "")
}

// ---------- おひさまシステム（FileMaker Data API） ----------

type fmSource struct {
	base, user, pass, layout string
	client                   *http.Client
	mu                       sync.Mutex
	token                    string
}

func newFMSource(host, db, user, pass, layout string) *fmSource {
	if layout == "" {
		layout = "API_M_PATIENT_LINKINFO"
	}
	return &fmSource{base: strings.TrimRight(host, "/") + "/fmi/data/v1/databases/" + db, user: user, pass: pass,
		layout: layout, client: &http.Client{Timeout: pinfoTimeout}}
}

// session は使い回しのトークン。old と同じなら取り直す（鍵の中で 1 回だけ）。
func (f *fmSource) session(ctx context.Context, old string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.token != "" && f.token != old {
		return f.token, nil
	}
	req, _ := http.NewRequestWithContext(ctx, "POST", f.base+"/sessions", bytes.NewReader([]byte("{}")))
	req.SetBasicAuth(f.user, f.pass)
	req.Header.Set("Content-Type", "application/json")
	res, err := f.client.Do(req)
	if err != nil {
		return "", err
	}
	defer res.Body.Close()
	var j struct {
		Response struct {
			Token string `json:"token"`
		} `json:"response"`
	}
	if res.StatusCode != 200 || json.NewDecoder(res.Body).Decode(&j) != nil || j.Response.Token == "" {
		return "", fmt.Errorf("fm login http %d", res.StatusCode)
	}
	f.token = j.Response.Token
	return f.token, nil
}

// Close は使っているセッションを閉じる（箱を止めるとき）。失敗しても気にしない（15 分で切れる）。
func (f *fmSource) Close(ctx context.Context) {
	f.mu.Lock()
	tok := f.token
	f.token = ""
	f.mu.Unlock()
	if tok == "" {
		return
	}
	req, _ := http.NewRequestWithContext(ctx, "DELETE", f.base+"/sessions/"+tok, nil)
	if res, err := f.client.Do(req); err == nil {
		res.Body.Close()
	}
}

func (f *fmSource) Find(ctx context.Context, homisID string) (PatientInfo, error) {
	if !homisIDRe.MatchString(homisID) {
		return PatientInfo{}, nil
	}
	tok, err := f.session(ctx, "")
	if err != nil {
		return PatientInfo{}, err
	}
	info, expired, err := f.find(ctx, tok, homisID)
	if expired {
		if tok, err = f.session(ctx, tok); err != nil {
			return PatientInfo{}, err
		}
		info, _, err = f.find(ctx, tok, homisID)
	}
	return info, err
}

func (f *fmSource) find(ctx context.Context, tok, homisID string) (PatientInfo, bool, error) {
	body, _ := json.Marshal(map[string]any{"query": []map[string]string{{"homisID": "==" + homisID}}, "limit": 3})
	req, _ := http.NewRequestWithContext(ctx, "POST", f.base+"/layouts/"+f.layout+"/_find", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+tok)
	req.Header.Set("Content-Type", "application/json")
	res, err := f.client.Do(req)
	if err != nil {
		return PatientInfo{}, false, err
	}
	defer res.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(res.Body, 1<<20))
	var j struct {
		Messages []struct {
			Code string `json:"code"`
		} `json:"messages"`
		Response struct {
			Data []struct {
				FieldData map[string]any `json:"fieldData"`
			} `json:"data"`
		} `json:"response"`
	}
	_ = json.Unmarshal(raw, &j)
	code := ""
	if len(j.Messages) > 0 {
		code = j.Messages[0].Code
	}
	switch {
	case code == "401": // 見つからない（FM は HTTP 200・401・500 のどれでも返しうる。先に見る・黒ヤギ実装1回目 指摘1）
		return PatientInfo{Found: false}, false, nil
	case code == "952" || res.StatusCode == 401: // セッション切れ
		return PatientInfo{}, true, errors.New("fm session expired")
	case code != "0":
		return PatientInfo{}, false, fmt.Errorf("fm find http %d code %s", res.StatusCode, code)
	}
	if len(j.Response.Data) != 1 { // 2 件以上は出さない（取り違えを出さない）
		return PatientInfo{Found: false}, false, nil
	}
	fd := j.Response.Data[0].FieldData
	str := func(k string) string { v, _ := fd[k].(string); return strings.TrimSpace(v) }
	if str("homisID") != homisID { // 念のため（完全一致のはず）
		return PatientInfo{Found: false}, false, nil
	}
	return PatientInfo{Found: true, Clinic: str("クリニック名"), Orca: str("ORCAID"), Name: str("patient_name"), Kana: str("seimei_kana")}, false, nil
}
