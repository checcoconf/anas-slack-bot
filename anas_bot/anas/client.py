"""Scaricamento delle ordinanze dal sito ANAS.

Strategia: ogni ordinanza ha un identificativo numerico (ord_id) e un PDF
raggiungibile a un indirizzo fisso, per esempio
    https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213467
Il bot ricorda l'ultimo ord_id trovato e prova i successivi. Niente da
interpretare nelle pagine HTML del sito: se ANAS cambia la grafica, il bot
continua a funzionare.

Comportamento "educato":
- User-Agent che dichiara chi siamo e come contattarci;
- una richiesta alla volta, con pausa configurabile tra l'una e l'altra;
- se il sito risponde 429/503 rispettiamo Retry-After e ci fermiamo.
"""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .robots import RobotsPolicy

log = logging.getLogger(__name__)


class TransientError(Exception):
    """Errore temporaneo (rete giù, sito in errore): non avanzare il cursore, riprovare dopo."""


class AnasClient:
    def __init__(self, url_template: str, user_agent: str, delay_seconds: float = 2.0,
                 timeout: tuple[float, float] = (10, 60)) -> None:
        if "{id}" not in url_template:
            raise ValueError("ANAS_PDF_URL deve contenere {id}")
        self.url_template = url_template
        self.user_agent = user_agent
        self.delay = delay_seconds
        self.timeout = timeout
        self._last_request = 0.0
        self.via = "diretto"  # oppure "ponte del Worker" (vedi relay.py)
        self.robots = RobotsPolicy.allow_all(user_agent)  # sostituito all'avvio leggendo /robots.txt
        self.session = requests.Session()
        # Header coerenti con lo User-Agent (un Firefox italiano): un UA da browser con header
        # "da script" e' una contraddizione che i filtri anti-bot riconoscono.
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate",  # niente "br": richiederebbe il pacchetto brotli
        })
        retry = Retry(total=2, connect=2, read=2, status=0, backoff_factor=2,
                      allowed_methods=frozenset({"GET"}))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def url_for(self, ord_id: int) -> str:
        return self.url_template.format(id=ord_id)

    def _throttle(self) -> None:
        # rispetta sia la nostra pausa sia l'eventuale Crawl-delay dichiarato nel robots.txt
        delay = max(self.delay, self.robots.crawl_delay())
        wait = delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def fetch_pdf(self, ord_id: int) -> bytes | None:
        """Bytes del PDF, None se l'ordinanza non esiste. TransientError se il sito non risponde bene."""
        url = self.url_for(ord_id)
        if not self.robots.allowed(url):
            log.warning("robots.txt vieta %s: non lo scarico", url)
            return None
        self._throttle()
        try:
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            raise TransientError(f"rete: {exc}") from exc

        if r.status_code in (429, 503):
            retry_after = r.headers.get("Retry-After", "")
            raise TransientError(f"HTTP {r.status_code}, Retry-After={retry_after or '?'}")
        if r.status_code >= 500:
            raise TransientError(f"HTTP {r.status_code}")
        if r.status_code in (401, 403):
            raise TransientError(f"HTTP {r.status_code}: accesso negato (blocco anti-bot?)")
        if r.status_code == 404:
            return None
        body = r.content
        if body[:5] == b"%PDF-":
            return body
        # Il sito a volte risponde 200 con una pagina HTML quando l'id non esiste.
        log.debug("ord_id=%s: risposta non PDF (%s, %d byte)", ord_id,
                  r.headers.get("Content-Type"), len(body))
        return None