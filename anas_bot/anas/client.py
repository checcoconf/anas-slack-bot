"""Scaricamento delle ordinanze dal sito ANAS.

Strategia: ogni ordinanza ha un identificativo numerico (ord_id) e un PDF
raggiungibile a un indirizzo fisso, per esempio
    https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213467
Il bot ricorda l'ultimo ord_id trovato e prova i successivi. Niente da
interpretare nelle pagine HTML del sito: se ANAS cambia la grafica, il bot
continua a funzionare.

Comportamento "educato":
- User-Agent che dichiara chi siamo (WazeItaliaAnasBot);
- una richiesta alla volta, con pausa configurabile tra l'una e l'altra;
- se il sito risponde 429/503 rispettiamo Retry-After e ci fermiamo.

Il firewall di ANAS (FortiWeb) mette in quarantena per un po' chi fa troppe richieste in poco
tempo (collaudo del 03/11/2026: bloccato alla 9ª richiesta in 27 secondi). Insistere durante il
blocco lo allunga: alla prima pagina di blocco solleviamo BlockedError e il giro si ferma.
"""

from __future__ import annotations

import html
import logging
import random
import re
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .robots import RobotsPolicy

log = logging.getLogger(__name__)

# Frasi della pagina "Web Page Blocked!" del firewall FortiWeb di ANAS.
BLOCK_MARKERS = ("web page blocked", "the url you requested has been blocked", "attack id")


def is_block_page(text: str) -> bool:
    """True se è la pagina di blocco del firewall. Il testo viene normalizzato (via i tag HTML, le
    entità, gli accapo e gli spazi doppi): nella pagina vera le frasi sono spezzate su più righe."""
    plain = re.sub(r"<[^>]+>", " ", text or "")
    plain = " ".join(html.unescape(plain).split()).lower()
    return any(m in plain for m in BLOCK_MARKERS)


class TransientError(Exception):
    """Errore temporaneo (rete giù, sito in errore): non avanzare il cursore, riprovare dopo."""


class BlockedError(TransientError):
    """Il firewall di ANAS ci ha messo in quarantena: niente altre richieste per un po'."""


# Ritentativi automatici di urllib3, per tutti i collegamenti ad ANAS (diretti o dal ponte del Worker):
# solo se la connessione non si apre (TCP). Mai rimandare una richiesta già partita (connessione chiusa,
# timeout in lettura): per il firewall sarebbe una richiesta in più, fatta senza pausa e fuori budget.
RETRY_POLICY = Retry(total=1, connect=1, read=0, status=0, backoff_factor=2, allowed_methods=frozenset({"GET"}))


class AnasClient:
    def __init__(self, url_template: str, user_agent: str, delay_seconds: float = 2.0,
                 timeout: tuple[float, float] = (10, 60)) -> None:
        if "{id}" not in url_template:
            raise ValueError("ANAS_PDF_URL deve contenere {id}")
        self.url_template = url_template
        self.user_agent = user_agent
        self.delay = delay_seconds
        self.timeout = timeout
        self._last_request: float | None = None  # None = nessuna richiesta ancora: la prima parte subito
        self.requests_made = 0  # richieste fatte in questo giro (per i log: il budget è piccolo)
        self.ledger = None  # RequestLedger (anas/budget.py): budget per ora scorrevole, condiviso tra i giri
        self.via = "diretto"  # oppure "ponte del Worker" (vedi relay.py)
        self.robots = RobotsPolicy.allow_all(user_agent)  # sostituito all'avvio leggendo /robots.txt
        self.session = requests.Session()
        # Ci presentiamo con il nostro nome (collaudo del 03/11/2026: dal nostro indirizzo passa uguale
        # a un browser; e nei log di ANAS si vede chi siamo). Gli altri header sono quelli di un client normale.
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate",  # niente "br": richiederebbe il pacchetto brotli
            # Una connessione nuova per ogni richiesta: tra una richiesta e l'altra passano 4-5 minuti e la
            # rete di GitHub (Azure) chiude in silenzio le connessioni inattive da 4 minuti; riusarle dava
            # "connection reset" che sembravano blocchi del firewall (04/11/2026).
            "Connection": "close",
        })
        self.session.mount("https://", HTTPAdapter(max_retries=RETRY_POLICY))
        self.session.mount("http://", HTTPAdapter(max_retries=RETRY_POLICY))

    def url_for(self, ord_id: int) -> str:
        return self.url_template.format(id=ord_id)

    def _throttle(self, what: str = "") -> None:
        """Pausa prima di una richiesta; `what` descrive la richiesta nel log (es. "ricerca BA pagina 1")."""
        # rispetta sia la nostra pausa sia l'eventuale Crawl-delay dichiarato nel robots.txt;
        # la pausa varia un po' a caso: un intervallo sempre identico al millisecondo è un'altra firma da bot
        delay = max(self.delay, self.robots.crawl_delay()) * random.uniform(1.0, 1.4)
        wait = 0.0 if self._last_request is None else delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        if self.ledger is not None:
            self.ledger.before_request()  # può aspettare ancora, o fermare il giro (BudgetExhausted)
        self._last_request = time.monotonic()
        self.requests_made += 1
        log.info("Richiesta ad ANAS n. %d del giro: %s", self.requests_made, what or "?")

    def fetch_pdf(self, ord_id: int) -> bytes | None:
        """Bytes del PDF, None se l'ordinanza non esiste. TransientError se il sito non risponde bene."""
        url = self.url_for(ord_id)
        if not self.robots.allowed(url):
            log.warning("robots.txt vieta %s: non lo scarico", url)
            return None
        self._throttle(f"PDF {ord_id}")
        try:
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            raise TransientError(f"rete: {exc}") from exc

        body = r.content
        if body[:5] == b"%PDF-":
            return body
        # La pagina di blocco del firewall può arrivare con qualunque codice (403, 503...): si riconosce dal testo
        if is_block_page(r.text):
            raise BlockedError(f"firewall ANAS: PDF {ord_id} bloccato (HTTP {r.status_code})")
        if r.status_code in (429, 503):
            retry_after = r.headers.get("Retry-After", "")
            raise TransientError(f"HTTP {r.status_code}, Retry-After={retry_after or '?'}")
        if r.status_code >= 500:
            raise TransientError(f"HTTP {r.status_code}")
        if r.status_code == 401 and "Firma non valida" in (r.text or ""):
            # risposta del NOSTRO Worker, non di ANAS: job e Worker hanno token Slack diversi
            raise TransientError("HTTP 401: il ponte del Worker ha rifiutato la firma del job (token diversi: "
                                 "ripubblica il Worker); ANAS non è stata contattata")
        if r.status_code in (401, 403):
            raise TransientError(f"HTTP {r.status_code}: accesso negato (blocco anti-bot?)")
        if r.status_code == 404:
            return None
        # Il sito a volte risponde 200 con una pagina HTML quando l'id non esiste.
        log.debug("ord_id=%s: risposta non PDF (%s, %d byte)", ord_id,
                  r.headers.get("Content-Type"), len(body))
        return None