# カルテライターの実行リスト（app.nhw.jp/kartelog/）。Go の箱。ログインの関所は Cloud Run の IAP。
# ビルドは Cloud Build（gcloud builds submit）で行う。G: で直接 go build しない（C: に写してから）
FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/kartelog .

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /
COPY --from=build /out/kartelog /kartelog
ENV PORT=8080
EXPOSE 8080
USER nonroot
ENTRYPOINT ["/kartelog"]
