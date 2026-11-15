"""Impostazioni comuni dei test."""

import pytest


@pytest.fixture(autouse=True)
def _no_network_for_external_sources(monkeypatch):
    """I test del giro completo non scaricano davvero Bolzano e l'A22: le fonti hanno test propri su dati salvati
    (tests/test_fonti.py). Qui ogni richiesta fallisce subito, come una fonte irraggiungibile."""
    def offline(url, user_agent):
        raise OSError("rete disattivata nei test")
    monkeypatch.setattr("anas_bot.fonti.poller._http_get", offline)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    """Il giro e il riepilogo usano la data di oggi: i test ruotano attorno a ordinanze reali di novembre 2026
    (es. SS614 dal 10 al 14/11/2026), che con l'orologio vero prima o poi scadono. Qui "adesso" è sempre
    giovedì 12/11/2026 alle 10:03 (ora italiana): fuori dalla lettura profonda, bollettino di Bolzano aperto."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 11, 12, 10, 3, tzinfo=ZoneInfo("Europe/Rome"))
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr("anas_bot.job.datetime", FixedDatetime)
    monkeypatch.setattr("anas_bot.digest_job.datetime", FixedDatetime)
