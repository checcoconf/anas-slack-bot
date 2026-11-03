"""Rispetto del robots.txt del sito ANAS.

Il bot si comporta da crawler educato: a ogni avvio legge /robots.txt e non interroga mai
un percorso vietato, rispettando anche un eventuale Crawl-delay dichiarato.

Nota (verificato il 02/11/2026): il robots.txt di ANAS NON vieta le pagine delle ordinanze
(/it/ordinanze-web, /anas_ordinanzeweb/searchordinanze, /it/anas_ordinanzeweb/getordinanzapdf).
Vieta solo /search/, /admin/, le aree utente, ecc. Controllare comunque a ogni avvio tiene il
bot a norma anche se un giorno quelle regole cambiano.

Se il robots.txt non è leggibile perché il sito risponde con un errore 5xx (è anche la forma
in cui arriva il blocco del firewall), per prudenza il bot NON interroga nulla in quel giro:
meglio fermarsi che insistere contro un sito che sta rifiutando.
"""

from __future__ import annotations

import logging
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)

ROBOTS_PATH = "/robots.txt"


class RobotsPolicy:
    """Decide se un URL è interrogabile secondo il robots.txt, per uno User-Agent dato."""

    def __init__(self, parser: RobotFileParser, user_agent: str, text: str | None = None) -> None:
        self._p = parser
        self.ua = user_agent
        self.text = text  # il robots.txt letto dal sito (None se la policy non viene dal sito)

    @classmethod
    def _build(cls, lines: list[str], user_agent: str, text: str | None = None) -> "RobotsPolicy":
        p = RobotFileParser()
        p.parse(lines)
        return cls(p, user_agent, text)

    @classmethod
    def from_text(cls, text: str, user_agent: str) -> "RobotsPolicy":
        return cls._build((text or "").splitlines(), user_agent, text or "")

    @classmethod
    def allow_all(cls, user_agent: str) -> "RobotsPolicy":
        return cls._build([], user_agent)

    @classmethod
    def disallow_all(cls, user_agent: str) -> "RobotsPolicy":
        return cls._build(["User-agent: *", "Disallow: /"], user_agent)

    def allowed(self, url: str) -> bool:
        return self._p.can_fetch(self.ua, url)

    def crawl_delay(self) -> float:
        d = self._p.crawl_delay(self.ua)
        try:
            return float(d) if d is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
