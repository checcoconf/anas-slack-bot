"""Riallineamento dei membri del canale (eseguito dal job di GitHub Actions).

Il Worker accoglie in tempo reale chi entra nel canale. Questo controllo
periodico fa da rete di sicurezza: recupera chi è entrato o uscito se un
evento di Slack è andato perso, e al primo avvio accoglie chi era già nel canale.
I log non contengono ID utente, perché su una repo pubblica sono visibili a tutti.
"""

from __future__ import annotations

import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import ConnectionErrorRetryHandler, RateLimitErrorRetryHandler

from . import views
from .config import Config
from .db import Database

log = logging.getLogger(__name__)


def build_web_client(token: str) -> WebClient:
    client = WebClient(token=token)
    # Gestori ufficiali dell'SDK: ritenta su limiti di frequenza (429) e cadute di rete.
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    client.retry_handlers.append(ConnectionErrorRetryHandler(max_retry_count=3))
    return client


class Membership:
    def __init__(self, db: Database, client: WebClient, cfg: Config) -> None:
        self.db = db
        self.client = client
        self.cfg = cfg
        self._human_cache: dict[str, bool] = {}

    def is_human(self, user_id: str) -> bool:
        if user_id in self._human_cache:
            return self._human_cache[user_id]
        try:
            u = self.client.users_info(user=user_id)["user"]
            human = not (u.get("is_bot") or u.get("deleted") or user_id == "USLACKBOT")
        except SlackApiError as exc:
            log.warning("users.info non riuscito: %s", exc.response.get("error") if exc.response else exc)
            return False  # nel dubbio non scriviamo
        self._human_cache[user_id] = human
        return human

    def welcome(self, user_id: str) -> None:
        user = self.db.ensure_user(user_id)
        if user.welcomed_at:
            return
        ch = self.client.conversations_open(users=user_id)["channel"]["id"]
        msg = views.welcome_message()
        self.client.chat_postMessage(channel=ch, text=msg["text"], blocks=msg["blocks"])
        self.db.mark_welcomed(user_id)

    def channel_members(self) -> set[str]:
        members: set[str] = set()
        for ch in self.cfg.channel_ids:
            cursor = None
            while True:
                r = self.client.conversations_members(channel=ch, limit=500, cursor=cursor)
                members.update(r["members"])
                cursor = (r.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break
        return members

    def _describe_token(self) -> None:
        """Diagnosi (mai il token): in quale workspace e con quale utente-bot sta lavorando il job.
        Se il bot "non trova" un canale in cui è stato invitato, qui si vede se il token è di un altro posto."""
        try:
            r = self.client.auth_test()
            log.warning("Il token Slack in uso appartiene al workspace «%s» (utente-bot %s): controlla che i canali "
                        "%s stiano lì e che quel bot ne sia membro", r.get("team"), r.get("user_id"),
                        ", ".join(self.cfg.channel_ids))
        except SlackApiError as exc:
            log.warning("auth.test non riuscito: %s", exc.response.get("error") if exc.response else exc)

    def reconcile(self, first_run: bool = False) -> tuple[int, int]:
        """Allinea il database ai membri reali dei canali. Restituisce (benvenuti, uscite)."""
        try:
            raw = self.channel_members()
        except SlackApiError as exc:
            log.warning("Riallineamento non riuscito: %s", exc.response.get("error") if exc.response else exc)
            self._describe_token()
            return 0, 0
        known = {u.user_id: u for u in self.db.all_users()}
        # users.info solo per chi non conosciamo ancora: meno chiamate a Slack
        members = {m for m in raw if m in known or self.is_human(m)}
        welcomed = left = 0
        for uid in members:
            u = known.get(uid)
            if u is None or not u.in_channel:
                self.db.set_in_channel(uid, True)
            if u is None or not u.welcomed_at:
                if first_run and not self.cfg.welcome_existing_members and u is None:
                    self.db.ensure_user(uid)
                    self.db.mark_welcomed(uid)  # già nel canale prima del bot: niente messaggio
                    continue
                try:
                    self.welcome(uid)
                    welcomed += 1
                except SlackApiError as exc:
                    log.warning("Benvenuto non inviato: %s", exc.response.get("error") if exc.response else exc)
        for uid, u in known.items():
            if u.in_channel and uid not in members:
                self.db.set_in_channel(uid, False)
                left += 1
        return welcomed, left
