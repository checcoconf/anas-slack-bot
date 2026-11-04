"""Dalle ordinanze salvate ai messaggi privati su Slack.

Due fasi separate, così un riavvio a metà non perde né duplica nulla:
1. plan():    per ogni ordinanza nuova calcola i destinatari e li mette in coda
              (tabella deliveries) nella stessa transazione in cui la segna come valutata;
2. deliver(): manda a ogni utente UN messaggio con tutte le sue ordinanze in coda,
              poi le segna come inviate. Se Slack fallisce, restano in coda.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from slack_sdk.errors import SlackApiError

from .db import Database, User
from .geo import MOTORWAYS, PROVINCE_BY_CODE, REGIONS
from .matching import matches
from .views import notification_messages

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
# Errori Slack per cui riprovare non serve: l'utente non esiste più o non è raggiungibile.
_PERMANENT_ERRORS = {"user_not_found", "account_inactive", "cannot_dm_bot", "user_disabled", "not_allowed"}


# Errori Slack che vogliono dire "il bot non è nel canale": si avvisa l'admin, non si insiste
_CHANNEL_ERRORS = {"not_in_channel", "channel_not_found", "is_archived"}


@dataclass
class NotifyResult:
    planned: int = 0
    skipped_expired: int = 0
    messages_sent: int = 0
    users_notified: int = 0
    errors: int = 0
    channel_errors: dict[str, str] = field(default_factory=dict)  # canale -> errore Slack


def channel_subscribers(spec: str) -> list[User]:
    """CHANNEL_SUBSCRIPTIONS ("C03EYL07SL9=autostrade;C0123=sicilia,PA") -> finti iscritti con l'ID del canale.

    Un canale riceve solo chiusure e riaperture (mai i limiti di velocità) e non si mette in pausa."""
    out: list[User] = []
    for item in (x.strip() for x in spec.split(";") if x.strip()):
        chan, _, zones = item.partition("=")
        chan = chan.strip()
        u = User(user_id=chan, configured=True, want_closures=True, want_speed=False)
        for z in (x.strip() for x in zones.split(",") if x.strip()):
            if z.lower() in ("italia", "tutta-italia", "*"):
                u.all_italy = True
            elif z.lower() == MOTORWAYS or z.lower() in REGIONS:
                u.regions.append(z.lower())
            elif z.upper() in PROVINCE_BY_CODE:
                u.provinces.append(z.upper())
            else:
                log.warning("CHANNEL_SUBSCRIPTIONS: zona sconosciuta %r per il canale %s, ignorata", z, chan)
        if chan and (u.all_italy or u.regions or u.provinces):
            out.append(u)
        elif chan:
            log.warning("CHANNEL_SUBSCRIPTIONS: nessuna zona valida per il canale %s, ignorato", chan)
    return out


class Notifier:
    def __init__(self, db: Database, client, unknown_province_fallback: bool = True,
                 channels: list[User] | None = None) -> None:
        self.db = db
        self.client = client  # slack_sdk.WebClient (o un finto client nei test)
        self.fallback = unknown_province_fallback
        self.channels = {u.user_id: u for u in channels or []}  # canali iscritti (channel_subscribers)

    def plan(self, today: date) -> NotifyResult:
        res = NotifyResult()
        users = [u for u in self.db.all_users() if u.receives] + list(self.channels.values())
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
        if user_id in self.channels:
            return user_id  # un canale: si scrive direttamente lì
        r = self.client.conversations_open(users=user_id)
        return r["channel"]["id"]

    def deliver(self, today: date, res: NotifyResult | None = None) -> NotifyResult:
        res = res or NotifyResult()
        for user_id, ord_ids in self.db.pending_deliveries().items():
            user = self.channels.get(user_id) or self.db.get_user(user_id)
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
                if user_id in self.channels and err in _CHANNEL_ERRORS:
                    res.channel_errors[user_id] = err  # il job avvisa l'admin: va invitato il bot nel canale
                if err in _PERMANENT_ERRORS:
                    self.db.mark_deliveries(user_id, remaining, "failed")
                else:
                    self.db.delivery_failed_attempt(user_id, remaining, MAX_ATTEMPTS)
            except OSError as exc:
                # Slack non raggiungibile (dopo i ritentativi dell'SDK): inutile provare gli altri utenti ora,
                # i messaggi restano in coda e partono alla prossima struttura letta o al giro dopo
                res.errors += 1
                log.warning("Slack non raggiungibile, consegne rimandate: %s", exc)
                self.db.delivery_failed_attempt(user_id, remaining, MAX_ATTEMPTS)
                break
        return res

    def run(self, today: date) -> NotifyResult:
        res = self.plan(today)
        return self.deliver(today, res)
