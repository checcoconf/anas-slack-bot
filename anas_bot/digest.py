"""Riepilogo delle ordinanze già in vigore, a chi sceglie (o cambia) le zone.

Chi si iscrive non deve ricevere solo le novità da quel momento in poi: la strada chiusa da
una settimana è ancora chiusa. Al primo giro dopo il salvataggio delle preferenze il bot manda
un riepilogo delle ordinanze utili ancora in vigore nelle zone scelte (le più recenti, fino a
MAX_ITEMS), e le segna come consegnate: da lì in poi arrivano solo le novità.

Si riconosce un cambio di zone confrontando le preferenze con quelle dell'ultimo riepilogo
(chiave digest:<utente> nel database): niente colonne nuove, niente modifiche al Worker.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from slack_sdk.errors import SlackApiError

from .db import Database, User
from .matching import matches
from .views import digest_messages

log = logging.getLogger(__name__)

MAX_ITEMS = 30


def _signature(u: User) -> str:
    return json.dumps([u.all_italy, u.regions, u.provinces, u.want_closures, u.want_speed])


class Digest:
    def __init__(self, db: Database, client, unknown_province_fallback: bool = True) -> None:
        self.db = db
        self.client = client
        self.fallback = unknown_province_fallback

    def run(self, today: date) -> int:
        """Manda il riepilogo a chi ha zone nuove. Restituisce il numero di utenti serviti."""
        due = [u for u in self.db.all_users() if u.receives and self.db.get(f"digest:{u.user_id}") != _signature(u)]
        if not due:
            return 0
        in_force = self.db.in_force_ordinanze(today)
        served = 0
        for u in due:
            done = self.db.delivered_ids(u.user_id)
            mine = [o for o in in_force if o.ord_id not in done and matches(u, o, self.fallback)]
            mine.sort(key=lambda o: (o.start_date, o.ord_id), reverse=True)  # le più recenti prima
            shown = mine[:MAX_ITEMS]
            try:
                channel = self.client.conversations_open(users=u.user_id)["channel"]["id"]
                for msg, ids in digest_messages(shown, total=len(mine)):
                    self.client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"],
                                                 unfurl_links=False, unfurl_media=False)
                    if ids:
                        self.db.record_deliveries(u.user_id, ids, "sent")
            except SlackApiError as exc:
                log.warning("Riepilogo non inviato: %s", exc.response.get("error") if exc.response else exc)
                continue  # si riprova al giro dopo (la chiave non viene aggiornata)
            except OSError as exc:
                log.warning("Riepilogo non inviato, Slack non raggiungibile: %s", exc)
                break
            # le non mostrate (oltre MAX_ITEMS) non arriveranno più: sono su Ordinanze Web
            rest = [o.ord_id for o in mine[MAX_ITEMS:]]
            if rest:
                self.db.record_deliveries(u.user_id, rest, "skipped")
            self.db.set(f"digest:{u.user_id}", _signature(u))
            served += 1
        return served
