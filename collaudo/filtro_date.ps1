# Prova dei filtri di data della ricerca (5 richieste oneste). Risultato: collaudo\risultati\filtro_date.log
. "$PSScriptRoot\_comune.ps1"
Installa-Librerie
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Write-Host "Provo i filtri di data della ricerca di Ordinanze Web..." -ForegroundColor Cyan
py -m collaudo.filtro_date 2>&1 | Tee-Object -FilePath (Join-Path $Out "filtro_date.log")
Write-Host "`nTrascina collaudo\risultati\filtro_date.log nella chat." -ForegroundColor Green
Read-Host "Premi Invio per chiudere"
