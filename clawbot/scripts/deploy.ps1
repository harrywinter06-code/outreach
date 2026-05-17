# One-shot deploy from Windows host → clawbot VPS.
# Idempotent: safe to re-run for updates.
#
# Prerequisites:
#   - SSH config entry `Host clawbot` pointing at the VPS
#   - .env populated locally with credentials
#   - Docker Desktop NOT required on the host (we only ship the source)
#
# Usage from project root:
#   .\scripts\deploy.ps1

$ErrorActionPreference = "Stop"

$Project = Split-Path -Leaf (Get-Location)
if ($Project -ne "clawbot") {
    Write-Error "Run this from the clawbot project root (cwd is '$Project')."
}

Write-Host "[1/5] Packaging project (excluding .venv, caches)..." -ForegroundColor Cyan
$tarball = "$env:TEMP\clawbot-deploy.tar.gz"
if (Test-Path $tarball) { Remove-Item $tarball }
tar --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' `
    --exclude='.ruff_cache' --exclude='*.pyc' `
    --exclude='/metrics' --exclude='kill' `
    -czf $tarball -C .. clawbot
if ($LASTEXITCODE -ne 0) { Write-Error "tar failed" }

Write-Host "[2/5] Uploading tarball to VPS..." -ForegroundColor Cyan
scp $tarball clawbot:/tmp/clawbot-deploy.tar.gz
if ($LASTEXITCODE -ne 0) { Write-Error "scp failed" }

Write-Host "[3/5] Installing Docker + extracting project on VPS..." -ForegroundColor Cyan
ssh clawbot @"
set -e
if ! command -v docker >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq docker.io docker-compose-v2
    systemctl enable --now docker
fi
mkdir -p /opt/clawbot
tar -xzf /tmp/clawbot-deploy.tar.gz -C /opt --overwrite
mkdir -p /opt/clawbot/kill
echo "Project size: \$(du -sh /opt/clawbot | cut -f1)"
"@
if ($LASTEXITCODE -ne 0) { Write-Error "Remote setup failed" }

Write-Host "[4/5] Building and starting containers..." -ForegroundColor Cyan
ssh clawbot "cd /opt/clawbot && docker compose up -d --build"
if ($LASTEXITCODE -ne 0) { Write-Error "docker compose up failed" }

Write-Host "[5/5] Verifying boot..." -ForegroundColor Cyan
Start-Sleep -Seconds 5
ssh clawbot "cd /opt/clawbot && docker compose ps && echo '--- last 30 log lines ---' && docker compose logs --tail=30 clawbot"

Write-Host "`nDeploy complete. To stream logs: " -NoNewline -ForegroundColor Green
Write-Host "ssh clawbot 'cd /opt/clawbot && docker compose logs -f clawbot'" -ForegroundColor Yellow
Write-Host "To halt: " -NoNewline -ForegroundColor Green
Write-Host "ssh clawbot 'touch /opt/clawbot/kill/clawbot.KILL'" -ForegroundColor Yellow
