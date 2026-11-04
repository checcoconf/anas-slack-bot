"""Il lavoro periodico, eseguito da GitHub Actions: `python -m anas_bot.job`.

Ogni esecuzione (una l'ora, dura quasi un'ora: una richiesta ad ANAS ogni ~2,5 minuti):
1. riallinea i membri del canale (rete di sicurezza: il benvenuto in tempo reale lo dà il Worker);
2. legge l'elenco ANAS struttura dopo struttura finché c'è tempo, mandando i messaggi man mano;
3. (di riserva) scarica le ordinanze nuove per numero a partire dal cursore salvato in D1;
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
from .anas.budget import RequestLedger
from .anas.client import AnasClient, BlockedError, TransientError
from .anas.listing import ListingClient
from .anas.pdftext import pdf_to_text
from .anas.relay import choose_route
from .anas.robots import RobotsPolicy
from .config import Config
from .db import D1Http, Database, LocalSqlite, schema_statements
from .membership import Membership, build_web_client
from .digest import Digest
from .notifier import Notifier, channel_subscribers
from .listing_poller import BLOCKED_UNTIL, ListingPoller
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


_admin_client = None


def admin(client, cfg: Config, text: str) -> None:
    """Avviso nel canale admin. Con ADMIN_SLACK_BOT_TOKEN il canale può stare in un altro workspace."""
    global _admin_client
    if not cfg.admin_channel_id:
        return
    if cfg.admin_slack_bot_token:
        if _admin_client is None:
            _admin_client = build_web_client(cfg.admin_slack_bot_token)
        client = _admin_client
    try:
        client.chat_postMessage(channel=cfg.admin_channel_id, text=text)
    except SlackApiError as exc:
        log.warning("Messaggio admin non inviato: %s", exc.response.get("error") if exc.response else exc)
    except OSError as exc:  # Slack non raggiungibile (dopo i ritentativi dell'SDK): un avviso perso non ferma il giro
        log.warning("Messaggio admin non inviato, Slack non raggiungibile: %s", exc)


def run(cfg: Config, db: Database, client, source, listing=None, started: float | None = None) -> int:
    """started: time.monotonic() dell'avvio del job (main): il tempo del giro conta da lì, anche se prima
    si è aspettata la fine di una pausa."""
    started = time.monotonic() if started is None else started
    budget = cfg.job_time_budget_minutes * 60
    local_now = datetime.now(ZoneInfo(cfg.timezone))
    today = local_now.date()

    first_ever = db.get("reconciled_once") is None
    try:
        welcomed, left = Membership(db, client, cfg).reconcile(first_run=first_ever)
    except OSError as exc:  # Slack non raggiungibile: il canale si riallinea al giro dopo, ANAS si legge lo stesso
        log.warning("Canale non riallineato, Slack non raggiungibile: %s", exc)
        welcomed = left = 0
    db.set("reconciled_once", "1")
    log.info("Canale: %d benvenuti, %d uscite", welcomed, left)

    channels = channel_subscribers(cfg.channel_subscriptions)
    notifier = Notifier(db, client, cfg.unknown_province_fallback, channels)
    fetched = relevant = sent = users = 0
    error = ""
    channel_errors: dict[str, str] = {}

    # Riepilogo delle ordinanze in vigore a chi ha appena scelto le zone (prima del giro: non aspetta un'ora)
    try:
        digests = Digest(db, client, cfg.unknown_province_fallback).run(today)
    except OSError as exc:
        log.warning("Riepiloghi rimandati, Slack non raggiungibile: %s", exc)
        digests = 0
    if digests:
        log.info("Riepilogo delle ordinanze in vigore mandato a %d iscritti", digests)

    # 1) Elenco ufficiale di Ordinanze Web: la fonte principale
    lres = None
    if listing is not None:
        def flush() -> None:  # i messaggi in coda partono subito, dopo ogni struttura letta
            nonlocal sent, users
            nres = notifier.run(today)
            sent += nres.messages_sent
            users += nres.users_notified
            channel_errors.update(nres.channel_errors)
        poller = ListingPoller(db, listing, source, cfg)
        poller.after_structure = flush
        lres = poller.run(today, deadline=started + budget, hour=local_now.hour)
        flush()
        fetched, relevant = lres.new, lres.relevant
        log.info("Elenco ufficiale: %d richieste all'elenco (%d in tutto ad ANAS), %d ordinanze viste, %d nuove "
                 "(%d utili, %d già in vigore prima del bot), %d corrette, %d rimandate, strutture: %s%s",
                 lres.requests, getattr(getattr(source, "client", None), "requests_made", 0), lres.seen, lres.new, lres.relevant,
                 lres.silent, lres.upgraded, lres.deferred, ",".join(lres.structures) or "-",
                 (f", saltate: {','.join(lres.skipped)}" if lres.skipped else "")
                 + (f", errore: {lres.error}" if lres.error else ""))
        _listing_alerts(db, client, cfg, lres)

    # 2) Canale a numeri: di riserva, solo se l'elenco ha cambiato formato (o se richiesto con WALK_ALWAYS).
    #    Mai per un errore di rete o durante la pausa dopo un blocco: prova numeri inesistenti (404) e il
    #    firewall conta anche quelli (03/11/2026: 4 PDF a vuoto hanno contribuito al blocco).
    blocked = bool(lres and lres.blocked)
    if not blocked and (listing is None or (lres and lres.broken) or cfg.walk_always):
        poller = Poller(db, source, cfg)
        while True:
            pres = poller.run_cycle()
            nres = notifier.run(today)
            fetched += pres.fetched
            relevant += pres.relevant
            sent += nres.messages_sent
            users += nres.users_notified
            channel_errors.update(nres.channel_errors)
            error = pres.error
            if not pres.more_pending or time.monotonic() - started > budget:
                break
            log.info("Arretrato ANAS: proseguo nello stesso job")

    log.info("Fine giro: %d ordinanze nuove (%d utili), %d messaggi a %d utenti, cursore %s%s",
             fetched, relevant, sent, users, db.cursor(), f", errore ANAS: {error}" if error else "")

    # Avvisi tecnici nel canale admin
    for chan, err in channel_errors.items():
        if db.get(f"channel_alerted:{chan}") != err:  # una volta per errore, non a ogni giro
            admin(client, cfg, f"⚠️ Non riesco a scrivere nel canale iscritto {chan} ({err}): "
                               "invita il bot nel canale (/invite @anas-bot) o togli il canale da CHANNEL_SUBSCRIPTIONS.")
            db.set(f"channel_alerted:{chan}", err)
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

    if lres.block_started:
        _block_alert(db, client, cfg, lres.error)

    if lres.unknown:
        already = set(json.loads(db.get("alerted_measures", "[]") or "[]"))
        fresh = sorted(set(lres.unknown) - already)
        if fresh:
            admin(client, cfg, "🆕 ANAS usa provvedimenti mai visti dal bot:\n"
                               + "\n".join(f"• `{m}` (<{lres.unknown[m]}|esempio PDF>)" for m in fresh)
                               + "\nControlla che vengano classificati bene: istruzioni in collaudo/LEGGIMI.md.")
            db.set("alerted_measures", json.dumps(sorted(already | set(fresh)), ensure_ascii=False))

    if lres.national_off:
        admin(client, cfg, "⚠️ Ricerca nazionale spenta per oggi (sfora i 1.000 risultati o ha cambiato forma):\n"
                           + "\n".join(f"• {m}" for m in lres.national_off)
                           + "\nLe stesse ordinanze arrivano comunque dalla rotazione per struttura, con più ritardo. "
                           "Se si ripete, togli quella voce da NATIONAL_SEARCHES.")

    if lres.uncertain:
        already = set(json.loads(db.get("alerted_uncertain", "[]") or "[]"))
        fresh = sorted(set(lres.uncertain) - already)
        if fresh:
            admin(client, cfg, "⚠️ Chiusure inviate come *da verificare* (dicitura che il bot non conosce):\n"
                               + "\n".join(f"• {m} (<{lres.uncertain[m]}|PDF>)" for m in fresh)
                               + "\nSe la strada era davvero chiusa, va bene così; se no, la dicitura va aggiunta "
                               "alle parti di strada da ignorare (LANES in anas_bot/anas/listing.py).")
            db.set("alerted_uncertain", json.dumps(sorted(already | set(fresh)), ensure_ascii=False))


def _block_alert(db: Database, client, cfg: Config, error: str) -> None:
    blocks = int(db.get("anas_blocks_total", "0") or 0) + 1
    db.set("anas_blocks_total", str(blocks))
    admin(client, cfg, f"🧱 Il firewall di ANAS ci ha bloccati (blocco n. {blocks}): {error}. "
                       f"Nessuna richiesta per {cfg.block_pause_minutes} minuti, poi si riprende da soli. "
                       f"Richieste ad ANAS nell'ultima ora: {RequestLedger(db, 0).in_last_hour()}, "
                       f"tetto MAX_REQUESTS_PER_HOUR={cfg.max_requests_per_hour}. Se si ripete, abbassa il tetto di una tacca.")


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    started = time.monotonic()
    cfg = Config.from_env()
    errors = cfg.validate()
    if errors:
        for e in errors:
            log.error(e)
        return 2
    db = open_database(cfg)
    if not fallback_run_is_needed(db, os.environ.get("RUN_TRIGGER", "")):
        return 0
    db.set("last_run_started_at", str(time.time()))
    client = build_web_client(cfg.slack_bot_token)
    anas = AnasClient(cfg.anas_pdf_url, cfg.anas_user_agent, cfg.request_delay_seconds)
    anas.ledger = RequestLedger(db, cfg.max_requests_per_hour)
    log.info("Budget ANAS: %d richieste nell'ultima ora, tetto %d", anas.ledger.in_last_hour(), cfg.max_requests_per_hour)
    if cfg.anas_bot_key:
        anas.session.headers["X-Waze-Bot-Key"] = cfg.anas_bot_key  # se ANAS ci riconosce da questo codice
    listing = ListingClient(anas)
    if not wait_for_pause(db, cfg):
        log.warning("In pausa dopo un blocco del firewall ANAS: nessuna richiesta in questo giro")
    else:
        try:
            route = choose_route(cfg.anas_route, db, anas, cfg.slack_bot_token, listing.prime, cfg.worker_url)
            log.info("Collegamento ad ANAS: %s", route)
            load_robots_cached(db, listing)  # da crawler educato: rispetta robots.txt e crawl-delay
        except BlockedError as exc:
            # Bloccati già alla prima pagina (o a robots.txt): stessa pausa di un blocco durante il giro,
            # così il giro non fa altre richieste (ognuna allungherebbe la quarantena)
            db.set(BLOCKED_UNTIL, str(time.time() + cfg.block_pause_minutes * 60))
            log.warning("Firewall ANAS: %s. Nessuna richiesta per %d minuti", exc, cfg.block_pause_minutes)
            _block_alert(db, client, cfg, str(exc))
        except TransientError as exc:
            log.warning("ANAS non raggiungibile né direttamente né dal ponte del Worker: %s", exc)
    source = PdfSource(anas, pdf_to_text)
    return run(cfg, db, client, source, listing, started)


def fallback_run_is_needed(db: Database, trigger: str, now=time.time, max_age_minutes: int = 100) -> bool:
    """La pianificazione di riserva del workflow (ogni 3 ore) serve solo se l'orologio del Worker non ha
    fatto partire giri di recente: altrimenti si accoderebbe un secondo giro nella stessa ora, che
    troverebbe il budget orario pieno e sposterebbe in avanti quello vero."""
    if trigger != "schedule":
        return True
    last = float(db.get("last_run_started_at", "0") or 0)
    if now() - last < max_age_minutes * 60:
        log.info("Giro di riserva non necessario: l'ultimo giro è partito %d minuti fa", int((now() - last) / 60))
        return False
    return True


def wait_for_pause(db: Database, cfg: Config, now=time.time, sleep=time.sleep) -> bool:
    """Pausa dopo un blocco del firewall: se finisce entro il giro, aspetta e poi si lavora (con meno tempo).
    Restituisce False solo se la pausa copre tutto il giro. (04/11/2026: un giro partito un minuto prima
    della fine della pausa aveva rinunciato a un'ora intera.)"""
    remaining = float(db.get(BLOCKED_UNTIL, "0") or 0) - now()
    if remaining <= 0:
        return True
    usable = cfg.job_time_budget_minutes * 60 - remaining
    if usable < 10 * 60:  # con meno di 10 minuti di giro non vale la pena: si riprova all'ora dopo
        return False
    log.warning("In pausa dopo un blocco del firewall ANAS: aspetto %d minuti, poi lavoro per i %d che restano",
                int(remaining / 60) + 1, int(usable / 60))
    sleep(remaining + 1)
    return True


def load_robots_cached(db: Database, listing: ListingClient) -> None:
    """robots.txt letto da ANAS una volta al giorno: ogni richiesta in meno conta per il firewall."""
    today = datetime.now(ZoneInfo("UTC")).date().isoformat()
    cached = db.get("robots_txt")
    if cached is not None and db.get("robots_day") == today:
        listing.anas.robots = RobotsPolicy.from_text(cached, listing.anas.user_agent)
        return
    policy = listing.load_robots()
    if policy.text is not None:  # letto davvero dal sito (non una policy di prudenza per un errore)
        db.set("robots_txt", policy.text)
        db.set("robots_day", today)


if __name__ == "__main__":
    sys.exit(main())
