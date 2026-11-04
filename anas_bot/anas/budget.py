"""Budget di richieste ad ANAS per ora scorrevole, condiviso tra i giri.

Il firewall di ANAS conta le richieste in una finestra di circa un'ora, e non gli importa se
vengono da un giro solo o da due giri accodati (03/11/2026: 19 richieste in 55 minuti sono passate;
la 21ª in 65 minuti è stata chiusa). Il ritmo "una ogni 4 minuti dentro il giro" non basta quando
GitHub fa partire un giro in ritardo e quello dopo gli si accoda: nella stessa ora si somma tutto.

Il registro tiene in D1 gli istanti delle ultime richieste (chiave anas_request_times). Prima di
ogni richiesta: se nell'ultima ora ce ne sono già MAX, aspetta che la più vecchia esca dalla finestra;
se l'attesa supererebbe il tempo del giro, il giro finisce lì e riprende all'ora dopo.
"""

from __future__ import annotations

import json
import logging
import time

from .client import TransientError

log = logging.getLogger(__name__)

KEY = "anas_request_times"
WINDOW = 3600.0


class BudgetExhausted(TransientError):
    """Budget orario finito e attesa troppo lunga per questo giro: si riprende al giro dopo."""


class RequestLedger:
    def __init__(self, db, max_per_hour: int, max_wait: float = 900.0, now=time.time, sleep=time.sleep) -> None:
        self.db = db
        self.max_per_hour = max_per_hour
        self.max_wait = max_wait
        self.now = now
        self.sleep = sleep

    def _load(self, now: float) -> list[float]:
        try:
            times = json.loads(self.db.get(KEY, "[]") or "[]")
        except ValueError:
            times = []
        return sorted(t for t in times if isinstance(t, (int, float)) and now - t < WINDOW)

    def in_last_hour(self) -> int:
        return len(self._load(self.now()))

    def before_request(self) -> None:
        """Aspetta finché c'è posto nell'ora, poi registra la richiesta. BudgetExhausted se l'attesa è troppa."""
        now = self.now()
        times = self._load(now)
        if len(times) >= self.max_per_hour:
            wait = times[-self.max_per_hour] + WINDOW - now
            if wait > self.max_wait:
                raise BudgetExhausted(f"budget orario esaurito ({len(times)} richieste nell'ultima ora): "
                                      f"riprendo al giro dopo (servirebbero {int(wait / 60)} min di attesa)")
            log.info("Budget orario: %d richieste nell'ultima ora, aspetto %d s", len(times), int(wait))
            self.sleep(wait + 1)
            now = self.now()
            times = self._load(now)
        times.append(now)
        self.db.set(KEY, json.dumps([round(t, 1) for t in times]))
