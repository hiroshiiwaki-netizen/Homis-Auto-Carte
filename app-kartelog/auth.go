// auth.go — だれが見ているかを決める（IAP の署名を確かめる）
//
// tools/murakami_apps/app-register/auth.go と同じ確かめ方。画面から送られたメールやヘッダーの名前は信じない。
package main

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"regexp"
	"strings"

	"google.golang.org/api/idtoken"
)

const iapIssuer = "https://cloud.google.com/iap"

// Verifier は、要求を出した本人のメールを決める。
type Verifier interface {
	Email(r *http.Request) (string, error)
}

type iapVerifier struct {
	audience string
}

func (v iapVerifier) Email(r *http.Request) (string, error) {
	tok := r.Header.Get("X-Goog-IAP-JWT-Assertion")
	if tok == "" {
		return "", errors.New("no_token")
	}
	p, err := idtoken.Validate(r.Context(), tok, v.audience)
	if err != nil {
		if aud := unverifiedAudience(tok); aud != v.audience {
			log.Printf("AUTH aud_mismatch actual=%s", aud)
		}
		return "", errors.New("invalid_token")
	}
	if p.Issuer != iapIssuer {
		return "", errors.New("issuer")
	}
	mail, _ := p.Claims["email"].(string)
	mail = strings.ToLower(strings.TrimSpace(mail))
	if mail == "" {
		return "", errors.New("no_email")
	}
	return mail, nil
}

var unsafeLogChars = regexp.MustCompile(`[^A-Za-z0-9/._:-]`)

// unverifiedAudience は、証明の宛先（aud）だけを、署名を確かめずに読む（記録用・決まった文字だけ）。
func unverifiedAudience(tok string) string {
	parts := strings.Split(tok, ".")
	if len(parts) != 3 {
		return "?"
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return "?"
	}
	var c struct {
		Aud any `json:"aud"`
	}
	if json.Unmarshal(raw, &c) != nil {
		return "?"
	}
	s, _ := c.Aud.(string)
	s = unsafeLogChars.ReplaceAllString(s, "")
	if len(s) > 120 {
		s = s[:120]
	}
	if s == "" {
		return "?"
	}
	return s
}

// devVerifier は、パソコンで動かすときだけ使う（main.go で Cloud Run では起動させない）。
type devVerifier struct{ email string }

func (v devVerifier) Email(*http.Request) (string, error) { return v.email, nil }

// allowList は DX推進部のメールの一覧（DX_ADMINS・カンマ区切り）。
type allowList map[string]bool

func parseAllowList(s string) allowList {
	a := allowList{}
	for _, m := range strings.Split(s, ",") {
		m = strings.ToLower(strings.TrimSpace(m))
		if m != "" {
			a[m] = true
		}
	}
	return a
}

// User は見ている人。
type User struct {
	Email string `json:"email"`
	Admin bool   `json:"admin"` // DX推進部（試験の行・第3段の管理の操作）
}

// withUser は、署名を確かめてから中へ通す。確かめられなければ 403（中身は出さない）。
func (a *App) withUser(next func(http.ResponseWriter, *http.Request, User)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		mail, err := a.auth.Email(r)
		if err != nil {
			log.Printf("AUTH deny reason=%s path=%s", err.Error(), unsafeLogChars.ReplaceAllString(r.URL.Path, ""))
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		mail = strings.ToLower(strings.TrimSpace(mail))
		next(w, r, User{Email: mail, Admin: a.cfg.Admins[mail]})
	}
}
