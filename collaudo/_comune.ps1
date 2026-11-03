# Impostazioni comuni ai collaudi: cartella del progetto, caratteri accentati, librerie.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot          # cartella del progetto (sopra collaudo\)
Set-Location -Path $Root
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$Out = Join-Path $PSScriptRoot "risultati"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Installa-Librerie {
    Write-Host "Installo le librerie Python..." -ForegroundColor Cyan
    py -m pip install --quiet --disable-pip-version-check -r requirements.txt
}

function Crea-Zip($cartella, $zip) {
    if (Test-Path $zip) { Remove-Item $zip }
    Compress-Archive -Path (Join-Path $cartella "*") -DestinationPath $zip -Force
}
