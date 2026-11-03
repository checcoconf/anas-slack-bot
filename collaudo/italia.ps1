. "$PSScriptRoot\\_comune.ps1"
Installa-Librerie
Write-Host "Provo la ricerca 'tutta Italia' (2 richieste)..." -ForegroundColor Cyan
py -m collaudo.italia --pagine 2 2>&1 | Tee-Object -FilePath (Join-Path $Out "italia.log")
Write-Host ""
Read-Host "Premi Invio per chiudere"
