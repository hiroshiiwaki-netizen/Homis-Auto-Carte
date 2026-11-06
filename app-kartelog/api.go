// api.go — 画面に渡す一覧・1件・状態（読むだけ・第1段）
package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"
)

var jst = time.FixedZone("JST", 9*3600)

const (
	staleAfter        = 15 * time.Minute // 列にも無くて、これより古い途中のものは「止まっているかも」（仕様 6章）
	staleAfterNoQueue = 60 * time.Minute // 列が読めないときは長めに見る
	todayTTL          = 30 * time.Second
	pastTTL           = 10 * time.Minute
)

// Row は一覧の 1 行（記録＋箱が決めた見え方）。送られた中身（S・O）は入れない。
type Row struct {
	Record
	Day    string `json:"day"`
	View   string `json:"view"`   // ok／fail／done／waiting（列で待つ）／running／stale（止まっているかも）
	Action string `json:"action"` // open／rewrite（第3段）／cancel_then_rewrite（第3段）／check／none
	Test   bool   `json:"test"`   // 試験の行（FAX-MIRROR・BOT-TEST）
}

func isTestRoute(route string) bool { return route == "fax_mirror" || route == "bot_test" }

// classify は 1 件の見え方と、次にできることを決める（仕様 6章・7章）。
func classify(r Record, q QueueInfo, queueOK bool, now time.Time) (view, action string) {
	switch r.Status {
	case "ok":
		return "ok", "open"
	case "done":
		return "done", "none"
	case "fail", "rejected":
		return "fail", nextAction(r)
	}
	// received・accepted・running（途中）
	if queueOK && q.Names[r.OrderID] {
		return "waiting", "none"
	}
	t, err := time.Parse(time.RFC3339, r.AcceptedAt)
	if err != nil {
		t, err = time.Parse(time.RFC3339, r.ReceivedAt)
	}
	limit := staleAfter
	if !queueOK {
		limit = staleAfterNoQueue
	}
	if err == nil && now.Sub(t) > limit {
		return "stale", "check" // 分からない（unknown）扱い。再書き込みは出さない
	}
	return "running", "none"
}

// nextAction は書けなかったときの次の一手。判定は left_in_homis（仕様 7章）。無い・分からないは安全側（check）。
func nextAction(r Record) string {
	if r.Status == "rejected" {
		if strings.HasPrefix(r.ErrorType, "error:") {
			return "rewrite" // 列に入れられなかっただけ（中身は正しい）
		}
		return "check" // 患者さんの食い違い・本文が空など。元の書類を見て手で
	}
	switch r.LeftInHomis {
	case "none":
		return "rewrite"
	case "editing":
		return "cancel_then_rewrite"
	default:
		return "check"
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func (a *App) handleMe(w http.ResponseWriter, r *http.Request, u User) {
	writeJSON(w, 200, map[string]any{"email": u.Email, "admin": u.Admin, "version": version})
}

// days は、from（既定は今日）から前へ n 日（1〜7）。
func (a *App) days(r *http.Request) ([]string, bool) {
	now := a.now().In(jst)
	from := r.URL.Query().Get("from")
	if from == "" {
		from = now.Format("2006-01-02")
	}
	t, err := time.ParseInLocation("2006-01-02", from, jst)
	if err != nil || !dayRe.MatchString(from) {
		return nil, false
	}
	n, _ := strconv.Atoi(r.URL.Query().Get("days"))
	if n < 1 {
		n = 1
	}
	if n > 7 {
		n = 7
	}
	out := []string{}
	for i := 0; i < n; i++ {
		out = append(out, t.AddDate(0, 0, -i).Format("2006-01-02"))
	}
	return out, true
}

// loadDay は日ごとの記録。欠け（読めなかった記録）がある日は写しを持たない（次に読み直す）。
func (a *App) loadDay(ctx context.Context, day string) ([]Record, int, error) {
	now := a.now()
	ttl := pastTTL
	if day == now.In(jst).Format("2006-01-02") {
		ttl = todayTTL
	}
	if recs, ok := a.cache.get(day, ttl, now); ok {
		return recs, 0, nil
	}
	recs, missing, err := a.src.ListDay(ctx, day)
	if err != nil {
		return nil, 0, err
	}
	if missing == 0 {
		a.cache.put(day, recs, now)
	}
	return recs, missing, nil
}

func (a *App) handleList(w http.ResponseWriter, r *http.Request, u User) {
	days, ok := a.days(r)
	if !ok {
		writeJSON(w, 400, map[string]any{"error": "bad_day"})
		return
	}
	showTests := u.Admin && r.URL.Query().Get("tests") == "1" // 試験の行は DX推進部だけ（仕様 8章）
	ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
	defer cancel()
	q, qerr := a.src.Queues(ctx)
	rows := []Row{}
	failedDays := []string{}
	missing := 0
	now := a.now()
	for _, d := range days {
		recs, miss, err := a.loadDay(ctx, d)
		missing += miss
		if err != nil {
			log.Printf("LIST day=%s err=%s", d, err.Error())
			failedDays = append(failedDays, d)
			continue
		}
		for _, rec := range recs {
			test := isTestRoute(rec.Route)
			if test && !showTests {
				continue
			}
			view, act := classify(rec, q, qerr == nil, now)
			rows = append(rows, Row{Record: rec, Day: d, View: view, Action: act, Test: test})
		}
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].ReceivedAt > rows[j].ReceivedAt })
	writeJSON(w, 200, map[string]any{"rows": rows, "days": days, "failed_days": failedDays, "missing": missing, "queue_ok": qerr == nil,
		"queues": q.Counts, "now": now.In(jst).Format(time.RFC3339)})
}

// handleRecord は 1 件まるごと（送られた中身つき）。試験の行は DX推進部だけ。
func (a *App) handleRecord(w http.ResponseWriter, r *http.Request, u User) {
	day, id := r.URL.Query().Get("day"), r.URL.Query().Get("id")
	if !dayRe.MatchString(day) || !orderRe.MatchString(id) {
		writeJSON(w, 400, map[string]any{"error": "bad_request"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()
	m, err := a.src.Get(ctx, day, id)
	if err == errNotFound {
		writeJSON(w, 404, map[string]any{"error": "not_found"})
		return
	}
	if err != nil {
		log.Printf("RECORD err=%s", err.Error())
		writeJSON(w, 502, map[string]any{"error": "storage"})
		return
	}
	route, _ := m["route"].(string)
	if isTestRoute(route) && !u.Admin {
		writeJSON(w, 403, map[string]any{"error": "forbidden"})
		return
	}
	writeJSON(w, 200, m)
}

// handleStatus はライターが動いているかの印（列の件数・今日の最後の書き終わり）。
func (a *App) handleStatus(w http.ResponseWriter, r *http.Request, u User) {
	ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
	defer cancel()
	q, qerr := a.src.Queues(ctx)
	today := a.now().In(jst).Format("2006-01-02")
	last := ""
	if recs, _, err := a.loadDay(ctx, today); err == nil {
		for _, rec := range recs {
			if rec.FinishedAt > last && !isTestRoute(rec.Route) {
				last = rec.FinishedAt
			}
		}
	}
	writeJSON(w, 200, map[string]any{"queue_ok": qerr == nil, "queues": q.Counts, "last_finished_at": last,
		"now": a.now().In(jst).Format(time.RFC3339)})
}
