# xbloom-mcp setup for Windows. Installs uv and cloudflared if needed, then runs the
# interactive setup. Also: .\setup.ps1 check | rotate-key | uninstall [--all]
#
# If PowerShell refuses to run scripts, start it with:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                "$env:USERPROFILE\.local\bin;${env:ProgramFiles(x86)}\cloudflared"
}

$command = if ($args.Count -gt 0) { $args } else { @("setup") }
Refresh-Path

if ($command[0] -eq "setup") {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "winget is missing. Install 'App Installer' from the Microsoft Store, then re-run."
        exit 1
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "Installing uv (Python tool runner)..."
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        Write-Host "Installing cloudflared (Cloudflare Tunnel)..."
        winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }
}

uv sync --frozen -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --frozen xbloom-mcp @command
exit $LASTEXITCODE
