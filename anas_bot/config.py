"""Configurazione del job, letta dalle variabili d'ambiente.

Su GitHub Actions arrivano da *Secrets* (token) e *Variables* (il resto),
vedi .github/workflows/anas.yml. Sul PC si possono mettere in un file .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "si", "sì", "on")


def _int(name: str, default: int | None) -> int | None:
    v = os.environ.get(name, "").strip()
    return int(v) if v else default


def _str(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v or default


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


@dataclass
class Config:
    slack_bot_token: str = ""
    channel_ids: list[str] = field(default_factory=list)
    admin_channel_id: str = ""

    # Database: Cloudflare D1 (produzione) oppure file SQLite locale (prove sul PC)
    cf_account_id: str = ""
    cf_d1_database_id: str = ""
    cf_api_token: str = ""
    local_db_path: str = ""

    timezone: str = "Europe/Rome"

    anas_pdf_url: str = "https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id={id}"
    anas_start_id: int | None = None
    anas_user_agent: str = "WazeItaliaAnasBot"  # ci presentiamo per quello che siamo (ANAS_USER_AGENT per cambiarlo)
    anas_route: str = "auto"  # auto | direct | worker (vedi anas/relay.py)
    worker_url: str = ""      # di solito non serve: il Worker lo salva da solo nel database
    # Il firewall di ANAS tollera circa 20 richieste per ora "scorrevole" (03/11/2026: 19 in 55 minuti dopo
    # due ore di silenzio sono passate; la 21ª in 65 minuti è stata chiusa con un "connection reset"; le
    # raffiche e i giri accodati senza pausa sono stati bloccati prima). Il giro è lungo (circa un'ora) e
    # "respira": una richiesta ogni 4-5 minuti, qualunque sia (pagina, ricerca, PDF), cioè 13-15 all'ora,
    # e al primo blocco (o a due connessioni chiuse di fila) si ferma per un'ora.
    request_delay_seconds: float = 240.0  # pausa tra due richieste ad ANAS (~13 richieste all'ora)
    max_pdf_per_run: int = 3  # PDF scaricati al massimo per giro (gli altri slittano al giro dopo)
    block_pause_minutes: int = 60  # dopo una pagina di blocco del firewall: niente richieste per un'ora
    max_requests_per_cycle: int = 4  # canale a numeri (di riserva): PDF provati per giro, pochi per il firewall
    max_gap: int = 25
    missing_retry_hours: int = 168  # i numeri saltati si ricontrollano per 7 giorni
    missing_recheck_per_cycle: int = 20
    lookahead_after_hours: int = 6  # senza novità da 6 ore: assaggi più avanti nella numerazione
    stall_alert_hours: int = 72  # senza novità da 3 giorni: avviso nel canale admin
    job_time_budget_minutes: int = 50  # il giro dura quasi un'ora: parte una volta l'ora
    # Lettura veloce: poche strutture per giro, a rotazione (la ricerca "tutta Italia" non elenca: il sito
    # si rifiuta oltre 1.000 risultati), 1-2 pagine da 5 per struttura, dalla più recente.
    listing_structures_per_run: int = 23  # strutture lette per giro: tutte, è il tempo (budget) a fermare il giro
    listing_fast_pages_min: int = 1  # pagine lette sempre
    listing_fast_pages_max: int = 2  # ...e massime, se continuano a comparire ordinanze nuove
    # Lettura profonda di notte (ANAS non pubblica, il ritmo resta lo stesso): più pagine per struttura,
    # per le ordinanze che il sito non mette in prima pagina (ordina per inizio validità, non per pubblicazione).
    listing_deep_pages: int = 4  # pagine lette sempre, per struttura, nelle ore "profonde"
    listing_deep_hours: str = "0-6"  # ore locali (da-a, estremo finale escluso); vuoto = mai
    # Lettura completa a rotazione (una struttura per intero): spenta, costa decine di richieste.
    listing_full_per_run: int = 0  # strutture rilette per intero a ogni turno (0 = mai)
    listing_full_every_runs: int = 4  # un turno di lettura completa ogni N giri
    anas_bot_key: str = ""  # codice concordato con ANAS, mandato nell'intestazione X-Waze-Bot-Key
    walk_always: bool = False  # canale a numeri anche quando l'elenco funziona (di norma solo di riserva)

    welcome_existing_members: bool = True
    unknown_province_fallback: bool = True

    def is_deep_hour(self, hour: int) -> bool:
        """True se l'ora locale (0-23) cade nella fascia della lettura profonda, es. "0-6" oppure "22-6"."""
        try:
            a, b = (int(x) for x in self.listing_deep_hours.split("-"))
        except ValueError:
            return False
        return a <= hour < b if a <= b else (hour >= a or hour < b)

    @property
    def uses_d1(self) -> bool:
        return bool(self.cf_account_id and self.cf_d1_database_id and self.cf_api_token)

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.slack_bot_token = _str("SLACK_BOT_TOKEN", "")
        c.channel_ids = _list("SLACK_CHANNEL_IDS")
        c.admin_channel_id = _str("ADMIN_CHANNEL_ID", "")
        c.cf_account_id = _str("CF_ACCOUNT_ID", "")
        c.cf_d1_database_id = _str("CF_D1_DATABASE_ID", "")
        c.cf_api_token = _str("CF_API_TOKEN", "")
        c.local_db_path = _str("LOCAL_DB_PATH", "")
        c.timezone = _str("BOT_TIMEZONE", c.timezone)
        c.anas_pdf_url = _str("ANAS_PDF_URL", c.anas_pdf_url)
        c.anas_start_id = _int("ANAS_START_ID", None)
        c.anas_user_agent = _str("ANAS_USER_AGENT", c.anas_user_agent)
        c.anas_route = _str("ANAS_ROUTE", c.anas_route)
        c.worker_url = _str("WORKER_URL", c.worker_url)
        c.request_delay_seconds = float(_str("REQUEST_DELAY_SECONDS", str(c.request_delay_seconds)))
        c.max_pdf_per_run = _int("MAX_PDF_PER_RUN", c.max_pdf_per_run)
        c.block_pause_minutes = _int("BLOCK_PAUSE_MINUTES", c.block_pause_minutes)
        c.max_requests_per_cycle = _int("MAX_REQUESTS_PER_CYCLE", c.max_requests_per_cycle)
        c.max_gap = _int("MAX_GAP", c.max_gap)
        c.missing_retry_hours = _int("MISSING_RETRY_HOURS", c.missing_retry_hours)
        c.lookahead_after_hours = _int("LOOKAHEAD_AFTER_HOURS", c.lookahead_after_hours)
        c.stall_alert_hours = _int("STALL_ALERT_HOURS", c.stall_alert_hours)
        c.listing_full_per_run = _int("LISTING_FULL_PER_RUN", c.listing_full_per_run)
        c.listing_full_every_runs = max(1, _int("LISTING_FULL_EVERY_RUNS", c.listing_full_every_runs))
        c.anas_bot_key = _str("ANAS_BOT_KEY", c.anas_bot_key)
        c.listing_structures_per_run = max(1, _int("LISTING_STRUCTURES_PER_RUN", c.listing_structures_per_run))
        c.listing_fast_pages_min = _int("LISTING_FAST_PAGES_MIN", c.listing_fast_pages_min)
        c.listing_fast_pages_max = _int("LISTING_FAST_PAGES_MAX", c.listing_fast_pages_max)
        c.listing_deep_pages = _int("LISTING_DEEP_PAGES", c.listing_deep_pages)
        c.listing_deep_hours = os.environ.get("LISTING_DEEP_HOURS", c.listing_deep_hours).strip()
        c.walk_always = _bool("WALK_ALWAYS", c.walk_always)
        c.job_time_budget_minutes = _int("JOB_TIME_BUDGET_MINUTES", c.job_time_budget_minutes)
        c.welcome_existing_members = _bool("WELCOME_EXISTING_MEMBERS", c.welcome_existing_members)
        c.unknown_province_fallback = _bool("UNKNOWN_PROVINCE_FALLBACK", c.unknown_province_fallback)
        return c

    def validate(self) -> list[str]:
        errors = []
        if not self.slack_bot_token.startswith("xoxb-"):
            errors.append("SLACK_BOT_TOKEN mancante o non valido (deve iniziare con xoxb-)")
        if not self.channel_ids:
            errors.append("SLACK_CHANNEL_IDS mancante (ID del canale, es. C0123ABCD)")
        if not self.uses_d1 and not self.local_db_path:
            errors.append("Database mancante: imposta CF_ACCOUNT_ID, CF_D1_DATABASE_ID e CF_API_TOKEN "
                          "(oppure LOCAL_DB_PATH per una prova sul PC)")
        if "{id}" not in self.anas_pdf_url:
            errors.append("ANAS_PDF_URL deve contenere {id}")
        return errors
