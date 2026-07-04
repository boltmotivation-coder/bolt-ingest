# bolt installer (Windows). Run in PowerShell:
#   irm https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.ps1 | iex

$Repo = "boltmotivation-coder/bolt-ingest"

Write-Host "== Installing bolt =="

# Ensure Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Installing Python via winget..."
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Write-Host "Python installed. CLOSE this window, open a NEW PowerShell, and run the install command again."
    exit
}

python -m pip install --user -q pipx
python -m pipx ensurepath | Out-Null
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

python -m pipx install --force "git+https://github.com/$Repo.git"

Write-Host ""
Write-Host "Done. Close this window, open a new PowerShell, and type: bolt"
