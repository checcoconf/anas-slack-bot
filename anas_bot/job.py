"""Il lavoro periodico, eseguito da GitHub Actions: `python -m anas_bot.job`.

Ogni esecuzione:
1. riallinea i membri del canale (rete di sicurezza: il benvenuto in tempo reale lo dà il Worker);
2. scarica le ordinanze ANAS nuove a partire dal cursore salvato in D1;
3. mette in coda e invia i messaggi privati;
4. se c'è ancora arretrato (es. dopo giorni di ANAS irraggiungibile) ripete
   finché resta tempo nel budget del job.
Poi termina: tutto lo stato vive in D1, quindi il giro successivo riparte da lì.

I log non contengono ID utente: su una repo pubblica i log di Actions li vede chiunque.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from slack_sdk.errors import SlackApiError

from . import __version__
from .anas.client import AnasClient, TransientError
from .anas.listing import ListingClient
from .anas.pdftext import pdf_to_text
from .anas.relay import choose_route
from .config import Config
from .db import D1Http, Database, LocalSqlite, schema_statements
from .membership import Membership, build_web_client
from .notifier import Notifier
from .listing_poller import ListingPoller
from .poller import PdfSource, Poller

log = logging.getLogger("anas_bot")

ALERT_AFTER_FAILED_RUNS = 12  # con un giro ogni 15 minuti: ~3 ore di ANAS irraggiungibile


def open_database(cfg: Config) -> Database:
    if cfg.uses_d1:
        backend = D1Http(cfg.cf_account_id, cfg.cf_d1_database_id, cfg.cf_api_token)
        # crea le tabelle se mancano: il job funziona anche se parte prima del workflow "Pubblica Worker"
        backend.batch([(st, ()) for st in schema_statements()])
        return Database(backend)
    return Database(LocalSqlite(cfg.local_db_path))


def admin(client, cfg: Config, text: str) -> None:
    if not cfg.admin_channel_id:
        return
    try:
        client.chat_postMessage(channel=cfg.admin_channel_id, text=text)
    except SlackApiError as exc:
        log.warning("Messaggio admin non inviato: %s", exc.response.get("error") if exc.response else exc)


def run(cfg: Config, db: Database, client, source, listing=None) -> int:
    started = time.monotonic()
    budget = cfg.job_time_budget_minutes * 60
    today = datetime.now(ZoneInfo(cfg.timezone)).date()

    first_ever = db.get("reconciled_once") is None
    welcomed, left = Membership(db, client, cfg).reconcile(first_run=first_ever)
    db.set("reconciled_once", "1")
    log.info("Canale: %d benvenuti, %d uscite", welcomed, left)

    notifier = Notifier(db, client, cfg.unknown_province_fallback)
    fetched = relevant = sent = users = 0
    error = ""

    # 1) Elenco ufficiale di Ordinanze Web: la fonte principale
    lres = None
    if listing is not None:
        lres = ListingPoller(db, listing, source, cfg).run(today, deadline=started + budget)
        nres = notifier.run(today)
        fetched, relevant = lres.new, lres.relevant
        sent, users = nres.messages_sent, nres.users_notified
        log.info("Elenco ufficiale: %d strutture, %d richieste, %d ordinanze viste, %d nuove (%d utili, "
                 "%d già in vigore prima del bot), %d corrette, lettura completa: %s%s%s",
                 len(lres.structures), lres.requests, lres.seen, lres.new, lres.relevant, lres.silent,
                 lres.upgraded, ",".join(lres.full) or "-",
                 f", saltate: {','.join(lres.skipped)}" if lres.skipped else "",
                 f", errore: {lres.error}" if lres.error else "")
        _listing_alerts(db, client, cfg, lres)

    # 2) Canale a numeri: di riserva, se l'elenco non è disponibile (o se richiesto con WALK_ALWAYS)
    if listing is None or (lres and lres.error) or cfg.walk_always:
        poller = Poller(db, source, cfg)
        while True:
            pres = poller.run_cycle()
            nres = notifier.run(today)
            fetched += pres.fetched
            relevant += pres.relevant
            sent += nres.messages_sent
            users += nres.users_notified
            error = pres.error
            if not pres.more_pending or time.monotonic() - started > budget:
                break
            log.info("Arretrato ANAS: proseguo nello stesso job")

    log.info("Fine giro: %d ordinanze nuove (%d utili), %d messaggi a %d utenti, cursore %s%s",
             fetched, relevant, sent, users, db.cursor(), f", errore ANAS: {error}" if error else "")

    # Avvisi tecnici nel canale admin
    failed = int(db.get("anas_failed_runs", "0") or 0)
    if error:
        failed += 1
        if failed == ALERT_AFTER_FAILED_RUNS:
            admin(client, cfg, f"⚠️ ANAS non raggiungibile da {failed} giri: {error}")
    else:
        if failed >= ALERT_AFTER_FAILED_RUNS:
            admin(client, cfg, "✅ ANAS di nuovo raggiungibile.")
        failed = 0
    db.set("anas_failed_runs", str(failed))

    # Nessuna ordinanza nuova da giorni: possibile cambio di numerazione o di indirizzo
    last_found = float(db.get("anas_last_found_at", "0") or 0)
    if last_found:
        idle_h = (time.time() - last_found) / 3600
        if idle_h > cfg.stall_alert_hours and db.get("stall_alerted") != "1":
            admin(client, cfg, f"⚠️ Nessuna nuova ordinanza ANAS da {int(idle_h)} ore. Controlla su Ordinanze Web "
                               "se il sito è cambiato (lancia collaudo/elenco.bat per una verifica completa).")
            db.set("stall_alerted", "1")
        elif idle_h <= cfg.stall_alert_hours and db.get("stall_alerted") == "1":
            db.set("stall_alerted", "0")
    if first_ever:
        admin(client, cfg, f"🤖 Bot v{__version__} attivo. Primo giro: {fetched} ordinanze ({relevant} utili), "
                           f"{welcomed} benvenuti inviati." + (f"\n⚠️ {error}" if error else ""))
    return 0


def _listing_alerts(db: Database, client, cfg: Config, lres) -> None:
    """Avvisi nel canale admin: elenco illeggibile, voci di provvedimento mai viste."""
    lfailed = int(db.get("listing_failed_runs", "0") or 0)
    if lres.error:
        lfailed += 1
        if lfailed == ALERT_AFTER_FAILED_RUNS or (lres.broken and lfailed == 1):
            admin(client, cfg, f"⚠️ Elenco ufficiale di Ordinanze Web non leggibile: {lres.error}. "
                               "Intanto il bot usa il canale di riserva a numeri.")
    else:
        if lfailed >= ALERT_AFTER_FAILED_RUNS:
            admin(client, cfg, "✅ Elenco ufficiale di nuovo leggibile.")
        lfailed = 0
    db.set("listing_failed_runs", str(lfailed))

    if lres.stuck:
        admin(client, cfg, "⚠️ Ordinanze Web: da 3 ore il sito risponde con un errore per "
                           + ", ".join(lres.stuck) + ". Le ordinanze di quelle zone arriveranno quando "
                           "il sito tornerà a rispondere; se continua, controlla con collaudo/elenco.bat.")

    if lres.unknown:
        already = set(json.loads(db.get("alerted_measures", "[]") or "[]"))
        fresh = sorted(set(lres.unknown) - already)
        if fresh:
            admin(client, cfg, "🆕 ANAS usa provvedimenti mai visti dal bot:\n"
                               + "\n".join(f"• `{m}` (<{lres.unknown[m]}|esempio PDF>)" for m in fresh)
                               + "\nControlla che vengano classificati bene: istruzioni in collaudo/LEGGIMI.md.")
            db.set("alerted_measures", json.dumps(sorted(already | set(fresh)), ensure_ascii=False))


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    errors = cfg.validate()
    if errors:
        for e in errors:
            log.error(e)
        return 2
    db = open_database(cfg)
    client = build_web_client(cfg.slack_bot_token)
    anas = AnasClient(cfg.anas_pdf_url, cfg.anas_user_agent, cfg.request_delay_seconds)
    if cfg.anas_bot_key:
        anas.session.headers["X-Waze-Bot-Key"] = cfg.anas_bot_key  # se ANAS ci riconosce da questo codice
    listing = ListingClient(anas)
    try:
        route = choose_route(cfg.anas_route, db, anas, cfg.slack_bot_token, listing.prime, cfg.worker_url)
        log.info("Collegamento ad ANAS: %s", route)
        listing.load_robots()  # da crawler educato: rispetta robots.txt e crawl-delay
    except TransientError as exc:
        log.warning("ANAS non raggiungibile né direttamente né dal ponte del Worker: %s", exc)
    source = PdfSource(anas, pdf_to_text)
    return run(cfg, db, client, source, listing)


if __name__ == "__main__":
    sys.exit(main())
