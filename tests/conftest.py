"""Impostazioni comuni dei test."""

import pytest


@pytest.fixture(autouse=True)
def _no_network_for_external_sources(monkeypatch):
    """I test del giro completo non scaricano davvero Bolzano e l'A22: le fonti hanno test propri su dati salvati
    (tests/test_fonti.py). Qui ogni richiesta fallisce subito, come una fonte irraggiungibile."""
    def offline(url, user_agent):
        raise OSError("rete disattivata nei test")
    monkeypatch.setattr("anas_bot.fonti.poller._http_get", offline)
