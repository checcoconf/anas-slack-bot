# Trova l'ultima ordinanza pubblicata (valore per ANAS_START_ID) e classifica le ultime 40.
# Risultato: collaudo\risultati\ultima_ordinanza.zip
. "$PSScriptRoot\_comune.ps1"
Installa-Librerie
$dir = Join-Path $Out "ultima_ordinanza"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

Write-Host "Cerco l'ordinanza ANAS piu' recente..." -ForegroundColor Cyan
$log = py -m collaudo.ultima_ordinanza find-latest --from 213695 2>&1 | Tee-Object -FilePath (Join-Path $dir "ultima.log")
$match = ($log | Select-String -Pattern "Ultimo ord_id trovato: (\d+)").Matches
if (-not $match) {
    Write-Host "Non trovo ordinanze: faccio una diagnosi della risposta del sito..." -ForegroundColor Yellow
    py -m collaudo.ultima_ordinanza check 213695 2>&1 | Tee-Object -FilePath (Join-Path $dir "diagnosi.log")
} else {
    $last = [int]$match[0].Groups[1].Value
    Write-Host "Ultimo numero: $last  (valore per ANAS_START_ID)" -ForegroundColor Green
    Write-Host "Scarico e classifico le ultime 40 ordinanze..." -ForegroundColor Cyan
    py -m collaudo.ultima_ordinanza around $last --before 40 --after 0 --out (Join-Path $dir "pdf") 2>&1 |
        Tee-Object -FilePath (Join-Path $dir "classificazione.log")
    Get-ChildItem (Join-Path $dir "pdf") -Filter *.pdf -ErrorAction SilentlyContinue | Remove-Item
}
Crea-Zip $dir (Join-Path $Out "ultima_ordinanza.zip")
Write-Host "`nFatto: trascina collaudo\risultati\ultima_ordinanza.zip nella chat." -ForegroundColor Green
Read-Host "Premi Invio per chiudere"
