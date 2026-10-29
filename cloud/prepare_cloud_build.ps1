# ビルド用に C:\HomisKarteCloud へ必要なファイルを揃える（Drive上で docker しない）
# cloud/ だけをコンテキストにすると COPY が失敗する（src に本体があるため）
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path (Split-Path -Parent $here) "src"
$dst = "C:\HomisKarteCloud"

if (-not (Test-Path -LiteralPath $src)) { throw "src not found: $src" }
New-Item -ItemType Directory -Force -Path $dst | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dst "templates") | Out-Null

$files = @(
  @{ From = (Join-Path $here "Dockerfile"); To = (Join-Path $dst "Dockerfile") }
  @{ From = (Join-Path $here "requirements-cloud.txt"); To = (Join-Path $dst "requirements-cloud.txt") }
  @{ From = (Join-Path $here ".dockerignore"); To = (Join-Path $dst ".dockerignore") }
  @{ From = (Join-Path $here "server.py"); To = (Join-Path $dst "server.py") }
  @{ From = (Join-Path $here "write_once.py"); To = (Join-Path $dst "write_once.py") }
  @{ From = (Join-Path $here "result_sheet.py"); To = (Join-Path $dst "result_sheet.py") }
  @{ From = (Join-Path $here "navi_callback.py"); To = (Join-Path $dst "navi_callback.py") }
  @{ From = (Join-Path $here "verify_karte.py"); To = (Join-Path $dst "verify_karte.py") }
  @{ From = (Join-Path $src "template_engine.py"); To = (Join-Path $dst "template_engine.py") }
  @{ From = (Join-Path $src "browser_actions.py"); To = (Join-Path $dst "browser_actions.py") }
  @{ From = (Join-Path $src "clipboard_utils.py"); To = (Join-Path $dst "clipboard_utils.py") }
  @{ From = (Join-Path $src "paths.py"); To = (Join-Path $dst "paths.py") }
  @{ From = (Join-Path $src "shared_log.py"); To = (Join-Path $dst "shared_log.py") }
  @{ From = (Join-Path $src "templates\xray_karte.yaml"); To = (Join-Path $dst "templates\xray_karte.yaml") }
  @{ From = (Join-Path $src "templates\fax_so.yaml"); To = (Join-Path $dst "templates\fax_so.yaml") }
  @{ From = (Join-Path $src "templates\bot_s_interrupt.yaml"); To = (Join-Path $dst "templates\bot_s_interrupt.yaml") }
)
foreach ($f in $files) {
  if (-not (Test-Path -LiteralPath $f.From)) { throw "missing: $($f.From)" }
  Copy-Item -LiteralPath $f.From -Destination $f.To -Force
  Write-Output "OK $($f.To)"
}
Write-Output "READY $dst"
Write-Output "Next: cd /d C:\HomisKarteCloud"
Write-Output "      gcloud builds submit --tag asia-northeast1-docker.pkg.dev/gen-lang-client-0979357970/homis-karte-writer/homis-karte-writer:v1"
