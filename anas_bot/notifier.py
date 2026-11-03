"""Dalle ordinanze salvate ai messaggi privati su Slack.

Due fasi separate, così un riavvio a metà non perde né duplica nulla:
1. plan():    per ogni ordinanza nuova calcola i destinatari e li mette in coda
              (tabella deliveries) nella stessa transazione in cui la segna come valutata;
2. deliver(): manda a ogni utente UN messaggio con tutte le sue ordinanze in coda,
              poi le segna come inviate. Se Slack fallisce, restano in coda.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from slack_sdk.errors import SlackApiError

from .db import Database
from .matching import matches
from .views import notification_messages

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
# Errori Slack per cui riprovare non serve: l'utente non esiste più o non è raggiungibile.
_PERMANENT_ERRORS = {"user_not_found", "account_inactive", "cannot_dm_bot", "user_disabled", "not_allowed"}


@dataclass
class NotifyResult:
    planned: int = 0
    skipped_expired: int = 0
    messages_sent: int = 0
    users_notified: int = 0
    errors: int = 0


class Notifier:
    def __init__(self, db: Database, client, unknown_province_fallback: bool = True) -> None:
        self.db = db
        self.client = client  # slack_sdk.WebClient (o un finto client nei test)
        self.fallback = unknown_province_fallback

    def plan(self, today: date) -> NotifyResult:
        res = NotifyResult()
        users = [u for u in self.db.all_users() if u.receives]
        for o in self.db.pending_ordinanze():
            if o.is_expired(today):
                self.db.enqueue(o.ord_id, [], skip=True)
                res.skipped_expired += 1
                continue
            targets = [u.user_id for u in users if matches(u, o, self.fallback)]
            self.db.enqueue(o.ord_id, targets, skip=False)
            res.planned += len(targets)
        return res

    def _dm_channel(self, user_id: str) -> str:
        r = self.client.conversations_open(users=user_id)
        return r["channel"]["id"]

    def deliver(self, today: date, res: NotifyResult | None = None) -> NotifyResult:
        res = res or NotifyResult()
        for user_id, ord_ids in self.db.pending_deliveries().items():
            user = self.db.get_user(user_id)
            ords = self.db.get_ordinanze(ord_ids)
            # Nel frattempo l'utente può essere uscito, in pausa, o l'ordinanza scaduta.
            if user is None or not user.receives:
                self.db.mark_deliveries(user_id, ord_ids, "skipped")
                continue
            expired = [o.ord_id for o in ords if o.is_expired(today)]
            if expired:
                self.db.mark_deliveries(user_id, expired, "skipped")
            ords = [o for o in ords if not o.is_expired(today)]
            if not ords:
                continue
            remaining = [o.ord_id for o in ords]
            try:
                channel = self._dm_channel(user_id)
                for msg, ids in notification_messages(ords):
                    self.client.chat_postMessage(channel=channel, text=msg["text"], blocks=msg["blocks"],
                                                 unfurl_links=False, unfurl_media=False)
                    self.db.mark_deliveries(user_id, ids, "sent")  # segnato subito: niente doppioni
                    remaining = [i for i in remaining if i not in ids]
                    res.messages_sent += 1
                res.users_notified += 1
            except SlackApiError as exc:
                err = exc.response.get("error", "") if exc.response is not None else ""
                res.errors += 1
                # niente ID utente nei log: su una repo pubblica i log di Actions li vede chiunque
                log.warning("Invio di un messaggio privato fallito: %s", err or exc)
                if err in _PERMANENT_ERRORS:
                    self.db.mark_deliveries(user_id, remaining, "failed")
                else:
                    self.db.delivery_failed_attempt(user_id, remaining, MAX_ATTEMPTS)
        return res

    def run(self, today: date) -> NotifyResult:
        res = self.plan(today)
        return self.deliver(today, res)
