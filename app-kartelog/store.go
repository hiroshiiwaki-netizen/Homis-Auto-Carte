// store.go — 記録の JSON（Cloud Storage）と列（Cloud Tasks）を読む。読むだけ（第1段）。
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Record は記録の JSON の中で、一覧に使う欄（無い欄は空のまま読める・仕様 5章「古い JSON」）。
type Record struct {
	OrderID     string   `json:"order_id"`
	Route       string   `json:"route"`
	Status      string   `json:"status"`
	ReceivedAt  string   `json:"received_at"`
	AcceptedAt  string   `json:"accepted_at,omitempty"`
	FinishedAt  string   `json:"finished_at,omitempty"`
	ErrorType   string   `json:"error_type,omitempty"`
	KarteID     string   `json:"karte_id,omitempty"`
	KarteURL    string   `json:"karte_url,omitempty"`
	LeftInHomis string   `json:"left_in_homis,omitempty"`
	Verify      string   `json:"verify,omitempty"` // 0.2.2: 書込後確認の結果（ライター 3.12.0 から記録・無ければ出さない）
	DocType     string   `json:"doc_type,omitempty"`
	Source      string   `json:"source,omitempty"`
	FaxRoute    string   `json:"fax_route,omitempty"`
	Sender      string   `json:"sender,omitempty"`
	Patient     Patient  `json:"patient"`
	TotalSec    *float64 `json:"total_sec,omitempty"`
	RetryOf     string   `json:"retry_of,omitempty"`
	RetriedAs   string   `json:"retried_as,omitempty"`
	RetryAt     string   `json:"retry_at,omitempty"` // 0.3.0: 自動やり直しの予約の時刻
	Attempt     int      `json:"attempt,omitempty"`  // 0.3.0: 何回目の自動やり直しか（1〜3）
	Manual      bool     `json:"manual,omitempty"`   // 0.3.0: 自動やり直しはここまで（手動でお願いします）
}

// Patient は患者さん（名前は第2段から）。
type Patient struct {
	HomisID string `json:"homis_id,omitempty"`
	Name    string `json:"name,omitempty"`
}

// Source は読む先（本物は GCP・テストは偽物）。
type Source interface {
	ListDay(ctx context.Context, day string) ([]Record, int, error) // 読めた記録・読めなかった件数
	Get(ctx context.Context, day, orderID string) (map[string]any, error)
	Queues(ctx context.Context) (QueueInfo, error)
}

// QueueInfo は列で待っている仕事。
type QueueInfo struct {
	Counts map[string]int  `json:"counts"` // 列の短い名前 → 件数
	Names  map[string]bool `json:"-"`      // 待っている注文番号
}

var (
	dayRe   = regexp.MustCompile(`^20[0-9]{2}-[01][0-9]-[0-3][0-9]$`)
	orderRe = regexp.MustCompile(`^[0-9A-Za-z\-]{1,80}$`)
)

type gcp struct {
	cfg    Config
	client *http.Client
	mu     sync.Mutex
	tok    string
	until  time.Time
}

func newGCP(cfg Config) *gcp {
	return &gcp{cfg: cfg, client: &http.Client{Timeout: 10 * time.Second}}
}

func (g *gcp) token(ctx context.Context) (string, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.tok != "" && time.Now().Before(g.until) {
		return g.tok, nil
	}
	req, _ := http.NewRequestWithContext(ctx, "GET", g.cfg.TokenURL, nil)
	req.Header.Set("Metadata-Flavor", "Google")
	res, err := g.client.Do(req)
	if err != nil {
		return "", err
	}
	defer res.Body.Close()
	var t struct {
		AccessToken string  `json:"access_token"`
		ExpiresIn   float64 `json:"expires_in"`
	}
	if err := json.NewDecoder(res.Body).Decode(&t); err != nil || t.AccessToken == "" {
		return "", errors.New("token")
	}
	g.tok = t.AccessToken
	g.until = time.Now().Add(time.Duration(t.ExpiresIn-120) * time.Second)
	return g.tok, nil
}

func (g *gcp) getJSON(ctx context.Context, u string, out any) (int, error) {
	tok, err := g.token(ctx)
	if err != nil {
		return 0, err
	}
	req, _ := http.NewRequestWithContext(ctx, "GET", u, nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	res, err := g.client.Do(req)
	if err != nil {
		return 0, err
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		io.Copy(io.Discard, res.Body)
		return res.StatusCode, fmt.Errorf("http %d", res.StatusCode)
	}
	return 200, json.NewDecoder(res.Body).Decode(out)
}

func (g *gcp) objURL(name string) string {
	return strings.TrimRight(g.cfg.StorageBase, "/") + "/storage/v1/b/" + url.PathEscape(g.cfg.Bucket) + "/o/" + url.PathEscape(name) + "?alt=media"
}

// ListDay は、その日のフォルダの記録を全部読む（並べて 8 件ずつ）。読めなかったものは 1 回だけ読み直し、
// それでも読めなければ件数を返す（黙って捨てない）。
func (g *gcp) ListDay(ctx context.Context, day string) ([]Record, int, error) {
	if !dayRe.MatchString(day) {
		return nil, 0, errors.New("bad_day")
	}
	if g.cfg.Bucket == "" {
		return nil, 0, errors.New("no_bucket")
	}
	var names []string
	page := ""
	for i := 0; i < 50; i++ {
		q := url.Values{"prefix": {"records/" + day + "/"}, "fields": {"items(name),nextPageToken"}, "maxResults": {"1000"}}
		if page != "" {
			q.Set("pageToken", page)
		}
		var lst struct {
			Items []struct {
				Name string `json:"name"`
			} `json:"items"`
			NextPageToken string `json:"nextPageToken"`
		}
		u := strings.TrimRight(g.cfg.StorageBase, "/") + "/storage/v1/b/" + url.PathEscape(g.cfg.Bucket) + "/o?" + q.Encode()
		if _, err := g.getJSON(ctx, u, &lst); err != nil {
			return nil, 0, err
		}
		for _, it := range lst.Items {
			if strings.HasSuffix(it.Name, ".json") {
				names = append(names, it.Name)
			}
		}
		if page = lst.NextPageToken; page == "" {
			break
		}
	}
	out := make([]Record, len(names))
	ok := make([]bool, len(names))
	sem := make(chan struct{}, 8)
	var wg sync.WaitGroup
	for i, n := range names {
		wg.Add(1)
		go func(i int, n string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			for try := 0; try < 2 && !ok[i]; try++ {
				var r Record
				if _, err := g.getJSON(ctx, g.objURL(n), &r); err == nil {
					if r.OrderID == "" {
						r.OrderID = strings.TrimSuffix(n[strings.LastIndex(n, "/")+1:], ".json")
					}
					out[i], ok[i] = r, true
				}
			}
		}(i, n)
	}
	wg.Wait()
	recs := make([]Record, 0, len(out))
	missing := 0
	for i := range out {
		if ok[i] {
			recs = append(recs, out[i])
		} else {
			missing++
		}
	}
	return recs, missing, nil
}

// Get は 1 件をまるごと読む（詳しい窓・送られた中身）。
func (g *gcp) Get(ctx context.Context, day, orderID string) (map[string]any, error) {
	if !dayRe.MatchString(day) || !orderRe.MatchString(orderID) {
		return nil, errors.New("bad_request")
	}
	var m map[string]any
	code, err := g.getJSON(ctx, g.objURL("records/"+day+"/"+orderID+".json"), &m)
	if code == 404 {
		return nil, errNotFound
	}
	return m, err
}

var errNotFound = errors.New("not_found")

// Queues は列で待っている仕事の名前（＝注文番号）と件数。
func (g *gcp) Queues(ctx context.Context) (QueueInfo, error) {
	qi := QueueInfo{Counts: map[string]int{}, Names: map[string]bool{}}
	for _, q := range g.cfg.Queues {
		short := q[strings.LastIndex(q, "/")+1:]
		page := ""
		for i := 0; i < 20; i++ {
			v := url.Values{"pageSize": {"1000"}, "responseView": {"BASIC"}}
			if page != "" {
				v.Set("pageToken", page)
			}
			var lst struct {
				Tasks []struct {
					Name string `json:"name"`
				} `json:"tasks"`
				NextPageToken string `json:"nextPageToken"`
			}
			if _, err := g.getJSON(ctx, strings.TrimRight(g.cfg.TasksBase, "/")+"/"+q+"/tasks?"+v.Encode(), &lst); err != nil {
				return qi, err
			}
			for _, t := range lst.Tasks {
				qi.Counts[short]++
				qi.Names[t.Name[strings.LastIndex(t.Name, "/")+1:]] = true
			}
			if page = lst.NextPageToken; page == "" {
				break
			}
		}
	}
	return qi, nil
}

// dayCache は日ごとの写し（今日は 30 秒・前の日は 10 分）。
type dayCache struct {
	mu   sync.Mutex
	days map[string]cached
}

type cached struct {
	at   time.Time
	recs []Record
}

func newDayCache() *dayCache { return &dayCache{days: map[string]cached{}} }

func (c *dayCache) get(day string, ttl time.Duration, now time.Time) ([]Record, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	v, ok := c.days[day]
	if !ok || now.Sub(v.at) > ttl {
		return nil, false
	}
	return v.recs, true
}

func (c *dayCache) put(day string, recs []Record, now time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.days) > 120 {
		c.days = map[string]cached{}
	}
	c.days[day] = cached{at: now, recs: recs}
}
