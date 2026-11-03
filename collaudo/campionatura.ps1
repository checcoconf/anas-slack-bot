# Verifica statistica della numerazione delle ordinanze (ord_id): e' progressiva? ha buchi?
# Risultato: collaudo\risultati\campionatura.zip
. "$PSScriptRoot\_comune.ps1"
Installa-Librerie
$dir = Join-Path $Out "campionatura"
$log = py -m collaudo.ultima_ordinanza find-latest --from 213695 2>&1
$match = ($log | Select-String -Pattern "Ultimo ord_id trovato: (\d+)").Matches
if (-not $match) {
    Write-Host "Non trovo l'ultima ordinanza: lancia prima ultima_ordinanza.bat" -ForegroundColor Red
    Read-Host "Premi Invio per chiudere"; exit 1
}
$last = [int]$match[0].Groups[1].Value
Write-Host "Ultimo numero: $last. Campionatura in corso (qualche minuto)..." -ForegroundColor Cyan
py -m collaudo.campionatura --latest $last --out $dir
Crea-Zip $dir (Join-Path $Out "campionatura.zip")
Write-Host "`nFatto: trascina collaudo\risultati\campionatura.zip nella chat." -ForegroundColor Green
Read-Host "Premi Invio per chiudere"
