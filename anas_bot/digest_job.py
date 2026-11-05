"""Mini-job: solo il riepilogo delle ordinanze in vigore a chi ha appena scelto le zone.

Lo fa partire il Worker (workflow riepilogo.yml) subito dopo il salvataggio delle preferenze, così
l'utente non aspetta il giro orario. Nessuna richiesta ad ANAS: legge solo il database e scrive su Slack.
Il giro orario (job.py) fa lo stesso controllo all'inizio, come rete di sicurezza se questo non parte.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Config
from .digest import Digest
from .job import open_database
from .membership import build_web_client

log = logging.getLogger("anas_bot.riepilogo")


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
    today = datetime.now(ZoneInfo(cfg.timezone)).date()
    served = Digest(db, client, cfg.unknown_province_fallback).run(today)
    log.info("Riepilogo delle ordinanze in vigore mandato a %d iscritti", served)
    return 0


if __name__ == "__main__":
    sys.exit(main())
