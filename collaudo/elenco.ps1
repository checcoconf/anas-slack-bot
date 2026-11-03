# Collaudo completo sull'elenco ufficiale: tutte le ordinanze in vigore in Italia e il vocabolario
# dei provvedimenti. Dura 40-60 minuti; ogni riga con l'orario mostra che sta andando avanti.
# Si puo' chiudere quando si vuole: rilanciando riprende da dove era rimasto.
# Risultato: collaudo\risultati\elenco.zip
. "$PSScriptRoot\_comune.ps1"
Installa-Librerie
$dir = Join-Path $Out "elenco"
Write-Host "Leggo l'elenco ufficiale di tutte le strutture..." -ForegroundColor Cyan
Write-Host "(righe con l'orario = sta andando; BLOCCATO = il sito non risponde)" -ForegroundColor DarkGray
py -m collaudo.elenco --out $dir 2>&1 | Tee-Object -FilePath (Join-Path $Out "elenco.log") -Append
$code = $LASTEXITCODE
Copy-Item (Join-Path $Out "elenco.log") $dir -Force -ErrorAction SilentlyContinue
Crea-Zip $dir (Join-Path $Out "elenco.zip")
if ($code -eq 0) {
    Write-Host "`nFatto: trascina collaudo\risultati\elenco.zip nella chat." -ForegroundColor Green
} else {
    Write-Host "`nQualche struttura non scaricata: rilancia elenco.bat per completare." -ForegroundColor Yellow
}
Read-Host "Premi Invio per chiudere"
