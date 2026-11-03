"""Finti Slack e ANAS per i test: registrano le chiamate invece di farle davvero."""

from __future__ import annotations

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse


def _resp(data: dict) -> SlackResponse:
    return SlackResponse(client=None, http_verb="POST", api_url="", req_args={}, data={"ok": True, **data},
                         headers={}, status_code=200)


class FakeSlack(WebClient):
    """Sottoclasse del WebClient ufficiale (Bolt lo richiede); le chiamate usate sono simulate,
    qualsiasi altra chiamata punta a un indirizzo inesistente e fallisce subito."""

    def __init__(self, members: dict[str, list[str]] | None = None, bots: set[str] | None = None) -> None:
        super().__init__(token="xoxb-test", base_url="http://127.0.0.1:9/", timeout=1)
        self.members = members or {}
        self.bots = bots or set()
        self.posts: list[dict] = []
        self.views_opened: list[dict] = []
        self.homes: dict[str, dict] = {}
        self.fail_users: dict[str, str] = {}  # user_id -> errore Slack da simulare

    def auth_test(self, **_):
        return _resp({"user_id": "UBOT", "bot_id": "BBOT", "team_id": "T1", "url": "https://x.slack.com/"})

    def conversations_open(self, users: str, **_):
        if users in self.fail_users:
            raise SlackApiError("errore", _resp({"ok": False, "error": self.fail_users[users]}))
        return _resp({"channel": {"id": f"D-{users}"}})

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return _resp({"ts": str(len(self.posts))})

    def users_info(self, user: str):
        return _resp({"user": {"id": user, "is_bot": user in self.bots, "deleted": False}})

    def conversations_members(self, channel: str, limit: int = 500, cursor=None):
        return _resp({"members": self.members.get(channel, []), "response_metadata": {"next_cursor": ""}})

    def views_open(self, trigger_id: str, view: dict):
        self.views_opened.append(view)
        return _resp({})

    def views_publish(self, user_id: str, view: dict):
        self.homes[user_id] = view
        return _resp({})

    def posts_to(self, user_id: str) -> list[dict]:
        return [p for p in self.posts if p["channel"] == f"D-{user_id}"]


class FakeSource:
    """Ordinanze 'pubblicate' su un finto sito: dict ord_id -> testo."""

    def __init__(self, docs: dict[int, str]) -> None:
        self.docs = docs
        self.requests: list[int] = []
        self.fail_from: int | None = None

    def url_for(self, ord_id: int) -> str:
        return f"https://example.test/ord?ord_id={ord_id}"

    def fetch_text(self, ord_id: int) -> str | None:
        from anas_bot.anas.client import TransientError
        self.requests.append(ord_id)
        if self.fail_from is not None and ord_id >= self.fail_from:
            raise TransientError("sito giù")
        return self.docs.get(ord_id)
