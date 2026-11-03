# Collaudo del bot ANAS

Strumenti da lanciare **dal tuo PC** (Windows: doppio clic sul `.bat`) per verificare che il bot sia ancora allineato al sito ANAS. Non servono per far funzionare il bot: servono a te per controllarlo e aggiornarlo.

I risultati finiscono in `collaudo/risultati/` (cartella esclusa da git). Ogni strumento crea uno `.zip` pronto da mandare a chi mantiene il bot.

Requisiti: Python 3.12 o superiore, con il comando `py` di Windows.

| Strumento | Quando usarlo | Durata | Cosa produce |
|---|---|---|---|
| `diagnosi.bat` | Per sapere **se il tuo indirizzo è bloccato da ANAS** adesso, prima di rimettere in piedi il bot. | pochi secondi | Esito "bloccato / accesso ok", con 3 sole richieste oneste |
| `ultima_ordinanza.bat` | Quando ANAS cambia l'indirizzo dei PDF, o per controllare a che numero sono arrivate le ordinanze. | 2-5 min | Ultimo numero di ordinanza, le ultime 40 classificate, diagnosi se il sito non risponde |
| `elenco.bat` | **Il più importante.** Dopo ogni modifica al sito ANAS, quando il bot sbaglia una classificazione, o una volta ogni qualche mese. | 40-60 min, riprendibile | Tutte le ordinanze in vigore in Italia, il vocabolario completo dei provvedimenti, le chiusure trovate |
| `campionatura.bat` | Se nasce un dubbio sulla numerazione delle ordinanze. | ~5 min | Statistiche su buchi e ordine dei numeri |

## Come leggere i risultati di `elenco.bat`

- `riepilogo.txt`: numeri principali, controllo di completezza (somma delle strutture = totale Italia?) ed elenco delle chiusure trovate.
- `provvedimenti.csv`: **il vocabolario**. Ogni voce di provvedimento che ANAS usa ("chiusura al traffico", "senso unico alternato…"), quante volte compare e come la classifica il bot. La colonna NUOVA segna le voci che il bot non conosce ancora.
- `corsie.csv`: le diciture su corsie, rampe e carreggiate.
- `ordinanze.csv`: tutte le ordinanze con la classificazione del bot, da aprire con Excel.
- `strutture.csv`: le strutture territoriali ANAS (sigla e nome).

## Cosa fare se il bot sbaglia

1. Lancia `elenco.bat` e cerca l'ordinanza sbagliata in `ordinanze.csv`, per numero.
2. Le regole di classificazione stanno in `anas_bot/anas/listing.py`, nella parte "Classificazione dal RIEPILOGO". Per i PDF stanno in `anas_bot/anas/parser.py`.
3. Aggiungi l'ordinanza reale a `tests/fixtures/ordinanze_reali.json` con la classificazione giusta (il record si copia da `grezzi/*.jsonl`) e lancia `python -m pytest`.

## Se arriva l'avviso 🆕 "ANAS usa provvedimenti mai visti"

1. Apri il PDF citato nell'avviso e decidi se quel provvedimento è una chiusura, un'apertura, un limite o niente di utile.
2. Se serve, aggiorna le regole in `anas_bot/anas/listing.py` (le liste `CLOSING_MEASURES`, `OPENING_MEASURES`…).
3. Aggiungi la voce a `KNOWN_MEASURES` in `anas_bot/anas/vocabolario.py`, così l'avviso non si ripete.

## Uso da riga di comando (anche su Linux/Mac)

Dalla cartella del progetto:

```bash
python -m collaudo.diagnosi                               # sono bloccato da ANAS adesso?
python -m collaudo.ultima_ordinanza find-latest --from 213695
python -m collaudo.ultima_ordinanza around <NUMERO> --before 40 --after 0 --out collaudo/risultati/pdf
python -m collaudo.ultima_ordinanza check <NUMERO>        # diagnosi: cosa risponde il sito
python -m collaudo.elenco --out collaudo/risultati/elenco  # aggiungi --restart per ricominciare da zero
python -m collaudo.elenco --only BA,MI                     # prova veloce su due strutture
python -m collaudo.campionatura --latest <NUMERO>
```
