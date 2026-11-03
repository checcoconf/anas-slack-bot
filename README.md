# ANAS Chiusure: bot Slack per Waze Italia

Il bot avvisa in privato gli editor quando ANAS pubblica un'ordinanza utile per la mappa:

- ⛔ **chiusure** di strade, carreggiate, rampe e svincoli, e le relative ✅ **riaperture**;
- 🚦 **limiti di velocità permanenti**.

Scarta il resto: corsie chiuse, restringimenti, sensi unici alternati, divieti per i soli mezzi pesanti, limiti nei cantieri.

Ogni utente sceglie le zone da menu a tendina: 🇮🇹 tutta Italia, 🗺️ regioni intere, 📍 singole province, o un mix. Le province sono aggiornate all'assetto 2026, con le 8 province sarde.

**Costo: zero.** Non serve nessun server: tutto gira su servizi gratuiti.

## Come è fatto

```
          Slack  ◄──────────────────────────────────────┐
            │ eventi, pulsanti, modulo                  │ messaggi privati
            ▼                                           │
 ┌─────────────────────────┐   ogni 15 min   ┌──────────┴──────────────┐
 │ Cloudflare Worker       │ ──────────────► │ GitHub Actions (Python) │
 │ (sempre acceso, gratis) │  avvia il job   │ scarica PDF ANAS,       │
 │ benvenuto, menu, Home   │                 │ classifica, invia       │
 └───────────┬─────────────┘                 └──────────┬──────────────┘
             │            Cloudflare D1 (SQLite)        │
             └──────────► iscritti, cursore, coda ◄─────┘
```

- **Cloudflare Worker** (cartella `worker/`, JavaScript). È la parte sempre accesa: risponde a Slack entro i 3 secondi richiesti.
  - Manda il benvenuto a chi entra nel canale.
  - Gestisce il modulo con i menu, la scheda Home e i comandi `/anas` (con sottocomandi: stato, pausa, riprendi, aiuto).
  - Ogni 15 minuti avvia il job su GitHub.
- **GitHub Actions** (cartella `anas_bot/`, Python con l'SDK ufficiale `slack_sdk`). Fa il lavoro pesante:
  - legge l'elenco ufficiale di [Ordinanze Web](https://www.stradeanas.it/it/ordinanze-web) e trova le ordinanze nuove;
  - le classifica (scarica il PDF solo quando serve) e manda un messaggio riassuntivo per utente;
  - ricontrolla i membri del canale.
- **Cloudflare D1.** È il database condiviso tra le due parti. Contiene le ordinanze già viste, gli iscritti e la coda dei messaggi, quindi niente si perde e niente si ripete tra un giro e l'altro.

> Sui Worker gli SDK ufficiali di Slack non girano. Lì il codice chiama direttamente la Web API ufficiale di Slack (5 metodi) e verifica la firma di ogni richiesta, senza librerie di terzi.

## Installazione (una volta sola, circa 40 minuti, tutto dal browser)

Non serve installare niente sul PC. Ti servono un account **GitHub** e un account **Cloudflare** (gratuiti), e un workspace **Slack** dove puoi installare app. Conviene iniziare con un **canale di test**.

**L'ordine conta:** prima si raccolgono tutte le chiavi, poi si inseriscono su GitHub e **solo alla fine** si carica il codice. Così il primo caricamento pubblica subito il Worker, senza errori. Tieni aperto un Blocco note per annotare i valori.

### 1. Prepara i file sul PC
1. Scompatta lo zip. In Esplora file attiva *Visualizza → Elementi nascosti* (serve per vedere la cartella `.github`).
2. Apri `manifest.yaml` con il Blocco note: lo modifichi al passo 3.

### 2. Cloudflare (<https://dash.cloudflare.com>)
1. *Workers & Pages*: se è la prima volta, scegli il **sottodominio** `workers.dev` (senza, la pubblicazione fallisce). Annota il sottodominio e l'**Account ID** (colonna di destra). → `CF_ACCOUNT_ID`
2. *Storage & Databases → D1 SQL Database → Create*, nome esattamente `anas-bot`. Annota il **Database ID**. → `CF_D1_DATABASE_ID`
3. *Profilo → API Tokens → Create Token*, modello **Edit Cloudflare Workers** → *Use template*:
   - in *Permissions* aggiungi una riga **Account · D1 · Edit**;
   - in *Account Resources* scegli il tuo account; in *Zone Resources* lascia **All zones**;
   - *Continue to summary → Create Token*. Annota il token (si vede una volta sola). → `CF_API_TOKEN`

### 3. App Slack
1. Nel `manifest.yaml` aperto sul PC sostituisci `TUO-SOTTODOMINIO` con il tuo sottodominio (3 punti) e salva.
2. <https://api.slack.com/apps> → **Create New App → From a manifest** → workspace di test → incolla il manifest → *Create*. Un avviso sull'URL non verificato è normale: il Worker non esiste ancora.
3. **Install to Workspace** e autorizza.
4. Annota il **Bot User OAuth Token** (*OAuth & Permissions*, inizia con `xoxb-`). → `SLACK_BOT_TOKEN`
5. Annota il **Signing Secret** (*Basic Information → App Credentials*). → `SLACK_SIGNING_SECRET`
6. Nel canale di test scrivi `/invite @anas-chiusure` e annota l'**ID del canale** (dettagli del canale, in fondo, tipo `C0123ABCD`). → `SLACK_CHANNEL_IDS`
7. Consigliato: un canale per gli avvisi tecnici, con il bot invitato. → `ADMIN_CHANNEL_ID`

### 4. Repository GitHub vuota
1. <https://github.com/new>: nome `anas-slack-bot`, **Public** (i minuti di Actions sono gratuiti senza limiti solo sulle pubbliche). **Non** aggiungere README, .gitignore o licenza. *Create repository*.
2. Lasciala vuota per ora: il codice si carica al passo 7.

### 5. Chiave GitHub per il Worker
*Foto profilo → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token*:
- **Repository access:** *Only select repositories* → `anas-slack-bot`;
- **Permissions → Repository permissions → Actions:** *Read and write*;
- scadenza: la più lunga disponibile (segnati la data: quando scade, il bot si ferma).

Annota il token. → `WORKER_GITHUB_TOKEN`

### 6. Inserisci tutto su GitHub (prima del codice)
Nella repo: *Settings → Secrets and variables → Actions*. Nomi esattamente così, maiuscoli.

Scheda **Secrets** (*New repository secret*):

| Nome | Valore |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-…` |
| `SLACK_SIGNING_SECRET` | Signing Secret di Slack |
| `CF_API_TOKEN` | chiave API di Cloudflare |
| `CF_ACCOUNT_ID` | Account ID di Cloudflare |
| `CF_D1_DATABASE_ID` | Database ID di D1 |
| `WORKER_GITHUB_TOKEN` | chiave GitHub del passo 5 |

Scheda **Variables** (*New repository variable*):

| Nome | Valore |
|---|---|
| `SLACK_CHANNEL_IDS` | ID del canale (di test, per ora) |
| `ADMIN_CHANNEL_ID` | ID del canale tecnico (facoltativo) |
| `ANAS_USER_AGENT` | es. `WazeItaliaAnasBot/1.0 (+mailto:tuo@email.it)` |
| `WELCOME_EXISTING_MEMBERS` | `true` per accogliere anche chi è già nel canale |

### 7. Carica il codice
1. Nella repo vuota clicca **uploading an existing file**.
2. Apri la cartella del progetto, seleziona **tutto il contenuto** (compresa `.github`, non la cartella esterna) e trascinalo nella pagina. *Commit changes*.
3. Controlla che nella repo ci siano `.github`, `anas_bot`, `worker`, `tests`, `collaudo`.
4. *Actions*: partono da soli **Test** e **Pubblica Worker**, ed entrambi devono diventare verdi ✅ (2-3 minuti). Se *Pubblica Worker* non parte da solo: *Actions → Pubblica Worker → Run workflow*.
   Se diventa rosso, il passaggio *Controllo dei Secrets e delle Variables* dice quale valore manca.

### 8. Collega Slack
1. Apri `https://anas-slack-bot.SOTTODOMINIO.workers.dev/health`: deve rispondere `{"ok":true,...}`.
2. Su api.slack.com, nella tua app: *Event Subscriptions* → accanto all'URL premi **Retry** → ✅ *Verified* → *Save Changes*.
3. Su Slack scrivi `/anas` e scegli le zone (per la prima prova: 🇮🇹 Tutta Italia).

### 9. Primo giro
1. *Actions → ANAS ordinanze → Run workflow* (oppure aspetta: il Worker lo avvia da solo ogni 15 minuti).
2. Nel log devono comparire `Elenco ufficiale: 23 strutture, …` e `Fine giro: …`. Nel canale tecnico arriva 🤖 *Bot attivo*.
3. Esci e rientra nel canale: deve arrivarti il benvenuto 👋.

**Le prime 5-6 ore sono di "presa visione".** Il bot legge per intero una struttura ANAS per giro (23 strutture, quindi 23 giri) e segna come già viste le circa 4.000 ordinanze in vigore, **senza mandarle**. Fanno eccezione quelle che iniziano dal giorno dell'installazione in poi: quelle sono novità per la mappa e arrivano subito. Le ordinanze pubblicate dopo l'installazione arrivano sempre, fin dal primo giro.

### Dal canale di test a quello vero

- **Stesso workspace:** cambia la variable `SLACK_CHANNEL_IDS` con l'ID del canale vero, invita il bot nel canale e rilancia *Actions → Pubblica Worker*.
- **Workspace diverso** (per esempio il tuo di prova → Waze Italia): crea l'app anche lì dallo stesso manifest, poi aggiorna `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` e `SLACK_CHANNEL_IDS` e rilancia *Pubblica Worker*. Gli iscritti del canale di test non vengono trasferiti.

## Per gli utenti

Gli utenti non installano nulla:
1. entrano nel canale e ricevono il benvenuto con il pulsante 🗺️ **Scegli le zone**;
2. scelgono le zone e i tipi di avviso dai menu;
3. da quel momento ricevono gli avvisi in privato.

Possono cambiare le zone o mettere in pausa dalla scheda **Home** dell'app o con i comandi `/anas` (`/anas stato`, `/anas pausa`, `/anas riprendi`, `/anas aiuto`). Se escono dal canale gli avvisi si fermano, ma le preferenze restano salvate.

## Buono a sapersi

- **I log di Actions sono pubblici** su una repo pubblica: il codice non scrive mai ID utente, e i token stanno nei Secrets.
- **La pianificazione di riserva** nel workflow (ogni 3 ore) viene sospesa da GitHub dopo 60 giorni senza commit. Non è un problema: il giro normale lo avvia il Worker.
- **Dopo un'interruzione si riparte da dove ci si era fermati**, sia per ANAS sia per Slack: il cursore e la coda stanno in D1. Se l'arretrato è grande, il job prosegue nello stesso giro finché ha tempo.
- **Come trova tutte le ordinanze nuove.** La fonte è l'elenco ufficiale di Ordinanze Web, che mostra le ordinanze dalla più recente (verificato su tutte le 3.718 ordinanze in vigore il 02/11/2026). A ogni giro, cioè ogni 15 minuti:
  - **lettura veloce:** per ognuna delle 23 strutture ANAS legge la prima pagina (fino a 6 se ci sono molte novità) e si ferma quando non trova più niente di nuovo. Un'ordinanza nuova arriva quindi entro 15-20 minuti, qualunque numero abbia;
  - **lettura completa a rotazione:** rilegge per intero una struttura ogni ora (una per giro durante l'installazione), come rete di sicurezza per le ordinanze che il sito non mettesse in cima.
  In tutto circa 30 richieste per giro, a ritmo lento (3 secondi l'una): il firewall di ANAS blocca chi ne fa troppe.
- **Come classifica.** Usa il riepilogo strutturato dell'elenco (tratta, corsie, provvedimenti, destinatari, date). Le regole sono state scritte sul vocabolario reale di ANAS: 77 tipi di provvedimento, raccolti in `anas_bot/anas/vocabolario.py`.
  - ⛔ è chiusura: *chiusura al traffico*, *divieto di transito*, *interdizione*, *sospensione della circolazione*, se valgono **per tutti** e su tutta la carreggiata (o su una rampa/svincolo);
  - ✅ è apertura: *apertura al traffico* e *riapertura*; 🆕 se è una strada nuova;
  - 🚦 è limite permanente: limite di velocità senza data di fine, per le cause *regolamentazione della circolazione*, *apertura nuova strada* e *tratto pericoloso*;
  - scartati: corsie, restringimenti, sensi unici alternati, divieti per i soli mezzi pesanti, trasporti eccezionali, limiti dei cantieri.
- **Proroghe e revoche.** Nell'elenco non hanno il riepilogo: il bot legge il PDF e, se cita un'ordinanza che conosce già, ne eredita strada, km e tipo. La proroga di una chiusura resta una chiusura (⏩ *prorogata*), la revoca di una chiusura diventa un'apertura. Verificato su una proroga reale (621/2026/UC, che cita la 459/2026/UC).
- **Niente ordinanze vecchie.** Finché una struttura non è stata letta per intero la prima volta, le ordinanze trovate vengono solo segnate come viste (e il PDF non viene neanche scaricato). Fanno eccezione quelle che iniziano dal giorno di installazione in poi.
- **Canale di riserva a numeri.** Se l'elenco ufficiale non si legge, il bot prova i numeri di ordinanza dopo l'ultimo visto nell'elenco. È solo un ripiego: i numeri ANAS non sono in ordine di emissione e hanno buchi.
- **Avvisi nel canale admin:**
  - 🆕 se ANAS usa un tipo di provvedimento mai visto (va controllato se è una chiusura);
  - se l'elenco ufficiale non si legge più per 3 ore, o subito se ha cambiato formato;
  - se una struttura supera i 1.000 risultati (il sito ne mostra al massimo 1.000, quindi l'elenco sarebbe incompleto);
  - se non arrivano ordinanze nuove da 3 giorni.
- **Impostazioni facoltative** (Variables di GitHub): `LISTING_FAST_PAGES_MIN` / `LISTING_FAST_PAGES_MAX` (pagine della lettura veloce, default 1 e 6), `LISTING_FULL_PER_RUN` (strutture lette per intero a ogni turno, default 1), `LISTING_FULL_EVERY_RUNS` (un turno di lettura completa ogni N giri, default 4), `REQUEST_DELAY_SECONDS` (pausa tra le richieste, default 3), secret `ANAS_BOT_KEY` (codice concordato con ANAS, mandato nell'intestazione `X-Waze-Bot-Key`), `WALK_ALWAYS=true` (usa sempre anche il canale a numeri), `ANAS_START_ID` (numero da cui parte il canale a numeri se l'elenco non è mai stato letto).
- **Il sito ANAS non accetta collegamenti dai server di GitHub** (negli Stati Uniti): la connessione scade senza risposta. Per questo il Worker fa da **ponte**: gira vicino a Milano (`placement` in `worker/wrangler.jsonc`) e legge le pagine ANAS per conto del job (`worker/src/relay.js`). Il bot prova prima il collegamento diretto e, se non va, passa da solo al ponte e se lo ricorda (`ANAS_ROUTE=auto`; si può forzare con `direct` o `worker`). Il ponte accetta solo richieste firmate dal job e inoltra solo verso www.stradeanas.it. L'indirizzo del Worker il job lo trova da solo nel database: il Worker lo salva ogni volta che Slack lo chiama o che apri `/health`.
- **Se ANAS non risponde** né direttamente né dal ponte, arriva un avviso ⚠️ nel canale admin dopo circa 3 ore.
- **Se modifichi il benvenuto o il modulo** in `anas_bot/views.py`, lancia `python -m anas_bot.export_worker` e carica anche `worker/src/generated.js`: il Worker si ripubblica da solo. Un test ti avvisa se te ne dimentichi.

## Prova del job sul PC, senza Cloudflare

```bash
cp .env.example .env     # compila: con LOCAL_DB_PATH il database è un file locale
set -a; . ./.env; set +a
python -m anas_bot.job
```

## Sviluppo e test

```bash
pip install -r requirements.txt pytest && python -m pytest     # parte Python
cd worker && npm test                                           # parte Worker
```

I test girano anche su GitHub a ogni modifica (workflow *Test*). Simulano ANAS, Slack, D1 e GitHub, quindi non serve la rete.

### Struttura del progetto

```
anas-slack-bot/
├── anas_bot/                 IL BOT (gira su GitHub Actions)
│   ├── job.py                il giro completo: canale, ordinanze, messaggi
│   ├── listing_poller.py     elenco ufficiale di Ordinanze Web: lettura veloce + rotazione
│   ├── poller.py             canale di riserva a numeri
│   ├── notifier.py           coda e invio dei messaggi privati
│   ├── matching.py           chi deve ricevere cosa
│   ├── membership.py         ingressi/uscite dal canale, benvenuti
│   ├── views.py              testi dei messaggi Slack, benvenuto, modulo con i menu
│   ├── geo.py                20 regioni e 110 province
│   ├── db.py, schema.sql     database (Cloudflare D1, o SQLite sul PC)
│   ├── config.py             impostazioni da variabili d'ambiente
│   ├── export_worker.py      copia benvenuto e menu nel Worker (generated.js)
│   └── anas/
│       ├── listing.py        lettura e classificazione dell'elenco: LE REGOLE STANNO QUI
│       ├── vocabolario.py    i 77 provvedimenti ANAS conosciuti (avviso se ne compare uno nuovo)
│       ├── parser.py         lettura e classificazione dei PDF
│       ├── client.py         download dal sito ANAS
│       ├── relay.py          collegamento ad ANAS: diretto o dal ponte del Worker
│       └── pdftext.py        testo dai PDF
├── worker/                   IL WORKER (Cloudflare, sempre acceso)
│   ├── src/                  index.js, slack.js, views.js, db.js, relay.js (ponte ANAS), generated.js
│   ├── wrangler.jsonc        configurazione (l'ID del database lo inserisce il workflow)
│   └── test/                 test del Worker (npm test)
├── tests/                    test del bot (python -m pytest)
│   └── fixtures/             risposte e ordinanze vere di ANAS usate nei test
├── collaudo/                 STRUMENTI DI VERIFICA da lanciare dal PC (vedi collaudo/LEGGIMI.md)
├── .github/workflows/        anas.yml (il giro), deploy-worker.yml (pubblica il Worker), test.yml
├── manifest.yaml             configurazione dell'app Slack
└── requirements.txt          librerie Python
```

> Le ordinanze sono atti di ANAS S.p.A. Il bot segnala e linka il PDF originale: prima di modificare la mappa, verifica sempre l'atto.
