# "Sono bloccato da ANAS?" — fa 3 richieste oneste (robots, pagina, ricerca) e ti dice l'esito.
# Risultato: collaudo\risultati\diagnosi\diagnosi.log
. "$PSScriptRoot\_comune.ps1"
Installa-Librerie
$dir = Join-Path $Out "diagnosi"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

Write-Host "Controllo se il tuo indirizzo e' bloccato da ANAS..." -ForegroundColor Cyan
py -m collaudo.diagnosi 2>&1 | Tee-Object -FilePath (Join-Path $dir "diagnosi.log")

Write-Host "`nSe vuoi, trascina collaudo\risultati\diagnosi\diagnosi.log nella chat." -ForegroundColor Green
Read-Host "Premi Invio per chiudere"
