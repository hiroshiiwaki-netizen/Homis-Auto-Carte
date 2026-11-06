// main.go — カルテライターの実行リスト（app.nhw.jp/kartelog/・PWA）
//
// 版: 0.3.3
// 最終更新: 2026-11-06
// 改定履歴:
//
//	0.3.3 (2026-11-06) 院を選んでいるとき、院の分からない行の件数を出し、その中の書込失敗は赤い知らせで知らせる。ロボットはクリックを素通りさせ、960px 以下では走らせない（黒ヤギ 11/6）
//	0.3.2 (2026-11-06) クリニックを選ぶと、タブの件数・上の数字・棒グラフ・赤い知らせもその院だけで数える（岩城さん「絞った結果の数字がいい」）
//	0.3.1 (2026-11-06) ロボットが上の帯の中を左右に走る（岩城さん「ロボットはしらせて 上の部分で」）。動きを減らす設定では止める
//	0.3.0 (2026-11-06) 自動やり直しの表示（↻ 自動で再書込へ・⏳ 自動で再書込（時刻まで・あと何回）・✋ 手動でお願いします・☑ 人が書いた見込み）と
//	                   書込後確認（○／未確認（カルテは保存済み）／×）。件数は最後の結果だけ（仕様 v1.2 14章）。
//	                   ロボットの印の名前を robot-busy・robot-alert に（"alert" が赤い知らせの枠の display:none とぶつかり、失敗の行があるとロボットが消えていた・岩城さん 11/6）
//	0.2.2 (2026-11-06) 言い方: 「カルテ書込 ○・書込後確認 ○」・番号の名前（OhiScanGo 札番号＝起動時刻＋何枚目の札・問い合わせ番号・疑義照会の送信時刻）・時刻の流れ（GCP 受付・カルテライター受付）（岩城さん 11/6）
//	0.2.1 (2026-11-06) タブの名前を「OhiScanGo（FAX/SCAN）」「問い合わせ（コール受付分）」「疑義照会（Tukusiフォームから）」に（岩城さん「OhiscanGO って誰もわからない」）
//	0.2.0 (2026-11-06) 所属クリニック・ORCA番号・患者名をおひさまシステム（FM の API_M_PATIENT_LINKINFO を homisID 完全一致）から引いて出す（patient.go・仕様 v0.8 13章）。
//	                   一覧は FM を待たず、裏の係が引いて覚える。FM_HOST 等が無ければ今まで通り患者番号だけ
//	0.1.3 (2026-11-06) ロボットを Antigravity が描いた絵（robot.png・アイコン icon-192/512.png）に替え、大きく（岩城さん「もう少し大きく」「Antigravity に」）
//	0.1.2 (2026-11-06) ヘッダーとアイコンのロボットを、法人のロボット（写真・岩城さん 11/6「このロボットを入れて」）に似せた絵に（robot.svg）
//	0.1.1 (2026-11-06) 状態の言い方を「書込成功・書込失敗・書込待機中・書込中・停止の疑い」に（岩城さん 11/6「列で待っていますという表現はない」）
//	0.1.0 (2026-11-06) 第1段（読むだけ）。記録の JSON（Cloud Storage・RECORD_BUCKET）を日付ごとに読み、
//	                   タブ（全記録・OhiScanGo・問い合わせ・疑義照会）・しぼり込み・詳しい窓を出す。
//	                   再書き込み・手で書いた・削除は第3段（仕様 docs/SPEC_実行リスト_v0.md v0.4）
//
// 作りは OhiSnap（app-ohisnap）と同じ Go の箱。ログインの関所は Cloud Run の IAP（@nhw.jp・全職員）。
// 箱でも IAP の署名（X-Goog-IAP-JWT-Assertion）を確かめ、署名の無い呼び出しは断る（仕様 8章）。
// 患者さんの名前・本文はログに出さない。
package main

import (
	"context"
	"embed"
	"io/fs"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const version = "0.3.3"

//go:embed public/*
var staticFS embed.FS

// Config は箱の設定（環境変数）。
type Config struct {
	Bucket      string   // RECORD_BUCKET（記録の置き場）
	Queues      []string // QUEUES（列の名前・カンマ区切り）。待ちの件数と「止まっているかも」に使う
	Audience    string   // IAP_AUDIENCE（/projects/番号/locations/…/services/app-kartelog）
	Admins      allowList
	StorageBase string // テスト用（既定 https://storage.googleapis.com）
	TasksBase   string // テスト用（既定 https://cloudtasks.googleapis.com/v2/）
	TokenURL    string // テスト用（既定 metadata）
	FMHost      string // FM_HOST（おひさまシステム）
	FMDB        string // FM_DB
	FMUser      string // FM_USER（Secret）
	FMPass      string // FM_PASSWORD（Secret）
	FMLayout    string // FM_LAYOUT（既定 API_M_PATIENT_LINKINFO）
}

func loadConfig() Config {
	c := Config{
		Bucket:      strings.TrimSpace(os.Getenv("RECORD_BUCKET")),
		Audience:    strings.TrimSpace(os.Getenv("IAP_AUDIENCE")),
		Admins:      parseAllowList(os.Getenv("DX_ADMINS")),
		StorageBase: envOr("GCS_BASE", "https://storage.googleapis.com"),
		TasksBase:   envOr("CLOUD_TASKS_BASE", "https://cloudtasks.googleapis.com/v2/"),
		TokenURL:    envOr("METADATA_TOKEN_URL", "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"),
		FMHost:      strings.TrimSpace(os.Getenv("FM_HOST")),
		FMDB:        strings.TrimSpace(os.Getenv("FM_DB")),
		FMUser:      strings.TrimSpace(os.Getenv("FM_USER")),
		FMPass:      strings.TrimSpace(os.Getenv("FM_PASSWORD")),
		FMLayout:    strings.TrimSpace(os.Getenv("FM_LAYOUT")),
	}
	for _, q := range strings.Split(os.Getenv("QUEUES"), ",") {
		if q = strings.Trim(strings.TrimSpace(q), "/"); q != "" {
			c.Queues = append(c.Queues, q)
		}
	}
	return c
}

func envOr(k, d string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return d
}

func main() {
	cfg := loadConfig()
	var v Verifier
	switch {
	case cfg.Audience != "":
		v = iapVerifier{audience: cfg.Audience}
	case os.Getenv("K_SERVICE") == "" && os.Getenv("DEV_EMAIL") != "":
		// パソコンで試すときだけ（Cloud Run では K_SERVICE があるので通らない）
		v = devVerifier{email: strings.ToLower(os.Getenv("DEV_EMAIL"))}
	default:
		log.Fatal("IAP_AUDIENCE が無いので起動しない（署名を確かめられないため）")
	}
	port := envOr("PORT", "8080")
	app := newApp(cfg, v, newGCP(cfg))
	var fm *fmSource
	if cfg.FMHost != "" && cfg.FMDB != "" && cfg.FMUser != "" && cfg.FMPass != "" {
		fm = newFMSource(cfg.FMHost, cfg.FMDB, cfg.FMUser, cfg.FMPass, cfg.FMLayout)
		app.pinfo = NewResolver(fm)
	}
	log.Printf("kartelog %s listening on :%s bucket_set=%t queues=%d admins=%d fm=%t", version, port, cfg.Bucket != "", len(cfg.Queues), len(cfg.Admins), app.pinfo != nil)
	srv := &http.Server{Addr: ":" + port, Handler: app.routes(), ReadHeaderTimeout: 10 * time.Second}
	go func() { // 箱を止めるとき（Cloud Run の SIGTERM）に FM のセッションを閉じる（仕様 13.2）
		ch := make(chan os.Signal, 1)
		signal.Notify(ch, syscall.SIGTERM, os.Interrupt)
		<-ch
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		srv.Shutdown(ctx)
		if fm != nil {
			fm.Close(ctx)
		}
	}()
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

// App は箱の中身。
type App struct {
	cfg   Config
	auth  Verifier
	src   Source
	cache *dayCache
	now   func() time.Time
	pinfo *Resolver // おひさまシステムの患者さんの表示（nil なら出さない）
}

func newApp(cfg Config, v Verifier, src Source) *App {
	return &App{cfg: cfg, auth: v, src: src, cache: newDayCache(), now: time.Now}
}

// routes は道を決める。決めた道以外は 404。
func (a *App) routes() http.Handler {
	sub, err := fs.Sub(staticFS, "public")
	if err != nil {
		log.Fatal(err)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/kartelog", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/kartelog/", http.StatusMovedPermanently)
	})
	static := map[string]string{
		"/kartelog/":                     "index.html",
		"/kartelog/index.html":           "index.html",
		"/kartelog/app.js":               "app.js",
		"/kartelog/style.css":            "style.css",
		"/kartelog/manifest.webmanifest": "manifest.webmanifest",
		"/kartelog/sw.js":                "sw.js",
		"/kartelog/icon.svg":             "icon.svg",
		"/kartelog/robot.svg":            "robot.svg",
		"/kartelog/robot.png":            "robot.png",
		"/kartelog/icon-192.png":         "icon-192.png",
		"/kartelog/icon-512.png":         "icon-512.png",
	}
	for path, file := range static {
		mux.HandleFunc(path, a.serveStatic(sub, file))
	}
	mux.HandleFunc("/kartelog/api/me", a.withUser(a.handleMe))
	mux.HandleFunc("/kartelog/api/list", a.withUser(a.handleList))
	mux.HandleFunc("/kartelog/api/record", a.withUser(a.handleRecord))
	mux.HandleFunc("/kartelog/api/status", a.withUser(a.handleStatus))
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("/", http.NotFound)
	return withHeaders(mux)
}

var contentTypes = map[string]string{
	".html":        "text/html; charset=utf-8",
	".js":          "application/javascript; charset=utf-8",
	".css":         "text/css; charset=utf-8",
	".webmanifest": "application/manifest+json",
	".svg":         "image/svg+xml",
	".png":         "image/png",
}

// serveStatic は画面の部品を返す。画面も IAP の内側（署名が無ければ 403）。
func (a *App) serveStatic(sub fs.FS, file string) http.HandlerFunc {
	return a.withUser(func(w http.ResponseWriter, r *http.Request, u User) {
		b, err := fs.ReadFile(sub, file)
		if err != nil {
			http.NotFound(w, r)
			return
		}
		ct := "application/octet-stream"
		for ext, t := range contentTypes {
			if strings.HasSuffix(file, ext) {
				ct = t
			}
		}
		w.Header().Set("Content-Type", ct)
		if file == "sw.js" {
			w.Header().Set("Service-Worker-Allowed", "/kartelog/")
		}
		w.Write(b)
	})
}

// withHeaders は、検索に載せない・キャッシュを残さない・よその部品を読まない印を付ける。
func withHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("X-Robots-Tag", "noindex, nofollow")
		h.Set("Cache-Control", "no-store")
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("Referrer-Policy", "no-referrer")
		h.Set("Content-Security-Policy", "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "+
			"font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
		next.ServeHTTP(w, r)
	})
}
