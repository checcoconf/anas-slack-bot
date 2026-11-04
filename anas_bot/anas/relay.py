"""Collegamento al sito ANAS: diretto, oppure attraverso il "ponte" del Worker Cloudflare.

Il sito ANAS non accetta collegamenti dai server di GitHub Actions (negli Stati Uniti): la
connessione scade senza risposta. Il Worker gira vicino a Milano e fa da ponte (worker/src/relay.js).

Con ANAS_ROUTE=auto (il default) il bot prova prima il collegamento diretto; se non va e il ponte
risponde, usa il ponte e se lo ricorda per i giri successivi. Il resto del codice non se ne accorge:
il ponte è montato nella sessione HTTP come un "adattatore" per www.stradeanas.it, e i cookie del
sito restano legati a www.stradeanas.it come in un collegamento diretto.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Callable
from urllib.parse import urlsplit

from requests.adapters import HTTPAdapter

from .client import RETRY_POLICY, AnasClient, TransientError

log = logging.getLogger(__name__)

ANAS_ORIGIN = "https://www.stradeanas.it"
RELAY_PREFIX = "/anas-relay"


def relay_signature(key: str, ts: str, method: str, path_and_query: str) -> str:
    """Stessa firma di worker/src/relay.js: HMAC-SHA256(chiave, "ts:METODO:/percorso?query")."""
    return hmac.new(key.encode(), f"{ts}:{method}:{path_and_query}".encode(), hashlib.sha256).hexdigest()


class RelayAdapter(HTTPAdapter):
    """Manda al Worker le richieste per www.stradeanas.it, firmate con la chiave condivisa."""

    def __init__(self, worker_url: str, key: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.worker_url = worker_url.rstrip("/")
        self.key = key

    def send(self, request, **kwargs):
        u = urlsplit(request.url)
        target = u.path + (f"?{u.query}" if u.query else "")
        ts = str(int(time.time()))
        relayed = request.copy()  # la richiesta originale resta intatta: i cookie restano di stradeanas.it
        relayed.url = f"{self.worker_url}{RELAY_PREFIX}{target}"
        relayed.headers["X-Relay-Ts"] = ts
        relayed.headers["X-Relay-Sig"] = relay_signature(self.key, ts, request.method, target)
        return super().send(relayed, **kwargs)


def use_relay(anas: AnasClient, worker_url: str, key: str) -> None:
    anas.session.mount(ANAS_ORIGIN, RelayAdapter(worker_url, key, max_retries=RETRY_POLICY))
    anas.via = "ponte del Worker"


def use_direct(anas: AnasClient) -> None:
    anas.session.adapters.pop(ANAS_ORIGIN, None)
    anas.via = "diretto"


def choose_route(mode: str, db, anas: AnasClient, key: str, probe: Callable[[], object],
                 worker_url: str = "") -> str:
    """Sceglie come raggiungere ANAS e restituisce "diretto" o "worker".

    probe() fa una richiesta di prova (la pagina di Ordinanze Web) e solleva TransientError se non va.
    """
    worker_url = worker_url or (db.get("worker_url") or "")
    mode = (mode or "auto").lower()
    if mode == "direct":
        use_direct(anas)
        return "diretto"
    if mode == "worker" or (mode == "auto" and db.get("anas_route") == "worker"):
        if worker_url:
            use_relay(anas, worker_url, key)
            return "worker"
        log.warning("Ponte del Worker richiesto ma indirizzo del Worker sconosciuto: apri /health del Worker")

    use_direct(anas)
    try:
        probe()
        db.set("anas_route", "direct")
        return "diretto"
    except TransientError as exc:
        if not worker_url:
            log.warning("ANAS non raggiungibile direttamente (%s) e indirizzo del Worker sconosciuto: "
                        "apri https://anas-slack-bot.TUO-SOTTODOMINIO.workers.dev/health una volta", exc)
            raise
        log.warning("ANAS non raggiungibile direttamente (%s): provo il ponte del Worker", exc)
    use_relay(anas, worker_url, key)
    probe()  # se non va neanche così, TransientError: riprova al prossimo giro
    db.set("anas_route", "worker")
    log.info("ANAS raggiungibile attraverso il ponte del Worker: lo userò anche nei prossimi giri")
    return "worker"
