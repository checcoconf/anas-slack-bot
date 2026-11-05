# Testi per la pagina dell'app su api.slack.com

Da incollare a mano il giorno del rilascio (non stanno nel manifest). Sezioni: *Basic Information → Display Information* (già nel manifest) e *Security & Compliance*.

## Display Information (già nel manifest, qui per riferimento)

- **Nome:** anas-bot
- **Descrizione breve:** Avvisi privati su chiusure, riaperture e limiti ANAS nelle zone che scegli tu
- **Descrizione lunga:** vedi `manifest.yaml` (`long_description`).

## Security & Compliance

**Privacy policy / Cosa conserva l'app**

anas-bot conserva soltanto l'ID Slack dell'utente e le preferenze che sceglie (zone, tipi di avviso, pausa), più la coda dei messaggi da inviare. Non legge messaggi, non accede a canali, non conserva nomi, email o altri dati del profilo. I dati stanno in un database Cloudflare D1 dell'autore e si cancellano su richiesta (basta scrivere all'autore) o mettendo in pausa l'app, che da quel momento non invia più nulla.

**Fonte dei dati**

Le informazioni provengono dalle ordinanze pubblicate da ANAS S.p.A. sul servizio pubblico "Ordinanze Web" (www.stradeanas.it). L'app le legge a ritmo ridotto (poche richieste l'ora, identificandosi con il nome `WazeItaliaAnasBot`), le riassume e le collega al PDF originale. L'app non è affiliata né autorizzata da ANAS: il testo che fa fede è sempre il PDF.

**Limiti noti**

La selezione delle ordinanze "utili per Waze" (chiusure, riaperture, limiti permanenti) è automatica e in beta: si basa su regole applicate al riepilogo pubblicato da ANAS. Può saltare qualche ordinanza o inviarne qualcuna non pertinente. Prima di modificare la mappa, verificare sempre il PDF.

**Contatto**

Francesco Conforti (checcoconf) — <inserire email o canale Slack di contatto>
Codice sorgente: https://github.com/checcoconf/anas-slack-bot

**Scope richiesti e perché**

- `chat:write`: inviare i messaggi privati e, se configurato, scrivere nel canale delle chiusure autostradali
- `im:write`: aprire la conversazione privata con chi attiva l'app
- evento `app_home_opened`: mostrare la scheda Home con le preferenze
