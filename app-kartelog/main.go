// main.go — カルテライターの実行リスト（app.nhw.jp/kartelog/・PWA）
//
// 版: 0.1.3
// 最終更新: 2026-11-06
// 改定履歴:
//
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
	"embed"
	"io/fs"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

const version = "0.1.3"

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
}

func loadConfig() Config {
	c := Config{
		Bucket:      strings.TrimSpace(os.Getenv("RECORD_BUCKET")),
		Audience:    strings.TrimSpace(os.Getenv("IAP_AUDIENCE")),
		Admins:      parseAllowList(os.Getenv("DX_ADMINS")),
		StorageBase: envOr("GCS_BASE", "https://storage.googleapis.com"),
		TasksBase:   envOr("CLOUD_TASKS_BASE", "https://cloudtasks.googleapis.com/v2/"),
		TokenURL:    envOr("METADATA_TOKEN_URL", "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"),
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
	log.Printf("kartelog %s listening on :%s bucket_set=%t queues=%d admins=%d", version, port, cfg.Bucket != "", len(cfg.Queues), len(cfg.Admins))
	srv := &http.Server{Addr: ":" + port, Handler: app.routes(), ReadHeaderTimeout: 10 * time.Second}
	if err := srv.ListenAndServe(); err != nil {
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
