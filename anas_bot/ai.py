"""Secondo parere di un modello di linguaggio locale (gratis, su CPU) sulla classificazione.

Le regole in anas/listing.py restano l'autorità: il modello non cambia mai una classificazione da solo.
Serve a due cose:
- CHIUSURE: se il modello dice "la strada non chiude a tutti" (es. divieto solo per bici e ciclomotori,
  come la riclassificazione della SS 719 del 05/11/2026), il messaggio parte lo stesso ma segnato
  "⚠️ da verificare" con il motivo, e l'admin riceve l'avviso.
- PAROLE NUOVE nel vocabolario dei provvedimenti: se il modello giudica che la voce non può nascondere
  una chiusura, il bot la aggiunge da solo al vocabolario (nel database) e avvisa con una riga
  informativa invece di chiedere un controllo.

Il modello (Qwen2.5 7B Instruct, GGUF quantizzato Q4_K_M, ~4,7 GB: capisce bene l'italiano) gira con
llama.cpp sul runner di GitHub (4 CPU, 16 GB), 40-60 secondi per parere, usando tutte le CPU; il workflow
lo scarica una volta e lo tiene nella cache di Actions. Se manca il modello, la libreria o qualunque cosa
va storta, ogni funzione risponde None e il bot lavora come se il modello non esistesse.

AI_MODE: flag (default: i pareri segnano "da verificare" e ampliano il vocabolario), log (solo nel log),
off (non si carica nemmeno il modello).
"""

from __future__ import annotations

import logging
import os
import re
import time

log = logging.getLogger(__name__)

MAX_TEXT = 3000  # caratteri di riepilogo + PDF passati al modello (il contesto è 4k token)

SYSTEM = (
    "Sei un assistente che legge ordinanze stradali di ANAS per gli editor della mappa Waze. "
    "Rispondi solo nel formato richiesto, in italiano, senza aggiungere altro."
)

CLOSURE_PROMPT = """Ordinanza ANAS (riepilogo ed eventuale testo):
---
{text}
---
Per Waze conta solo se il tratto di strada (o una rampa/svincolo/area di servizio) diventa NON percorribile
da tutte le automobili, da un capo all'altro. Conta anche una sola carreggiata chiusa di una strada a
carreggiate separate (il traffico passa in doppio senso sull'altra): quella carreggiata è chiusa.
Non contano: divieti solo per alcune categorie (bici, ciclomotori, mezzi pesanti, veicoli a braccia, trazione
animale...), restringimenti, sensi unici alternati, chiusure di singole corsie o piazzole, limiti di velocità,
trasporti eccezionali.
Rispondi con una sola riga nel formato:
VERDETTO: chiusura_totale | accesso_chiuso | non_chiusura
MOTIVO: una frase breve"""

MEASURE_PROMPT = """Nel riepilogo di un'ordinanza ANAS compare questa voce tra i provvedimenti: «{measure}».
Contesto: {text}
Questa voce può indicare che un tratto di strada viene chiuso a tutte le automobili? Rispondi con una sola riga:
CHIUSURA: si | no
MOTIVO: una frase breve"""

_VERDICT = re.compile(r"verdetto\s*:\s*(chiusura_totale|accesso_chiuso|non_chiusura)", re.I)
_CLOSES = re.compile(r"chiusura\s*:\s*(si|sì|no)\b", re.I)
_REASON = re.compile(r"motivo\s*:\s*(.+)", re.I)


class LocalModel:
    """Modello locale via llama.cpp. `generate` è sostituibile nei test (prompt -> testo)."""

    def __init__(self, model_path: str, generate=None, n_threads: int | None = None) -> None:
        self.model_path = model_path
        self._generate = generate
        self._llm = None
        self.n_threads = n_threads or max(1, os.cpu_count() or 2)  # tutte le CPU del runner
        self.calls = 0
        self.seconds = 0.0

    @classmethod
    def from_env(cls, mode: str, model_path: str) -> "LocalModel | None":
        """None se spento, se manca il file del modello o se la libreria non c'è."""
        if mode == "off" or not model_path:
            return None
        model_path = os.path.expanduser(model_path)
        if not os.path.exists(model_path):
            log.info("Modello locale non presente (%s): secondo parere disattivato", model_path)
            return None
        try:
            import importlib
            importlib.import_module("llama_cpp")
        except Exception as exc:  # noqa: BLE001
            log.info("llama-cpp-python non disponibile (%s): secondo parere disattivato", exc)
            return None
        return cls(model_path)

    def _llama(self):
        if self._llm is None:
            from llama_cpp import Llama
            t0 = time.monotonic()
            self._llm = Llama(model_path=self.model_path, n_ctx=4096, n_threads=self.n_threads, verbose=False)
            log.info("Modello locale caricato in %.1f s (%s)", time.monotonic() - t0, os.path.basename(self.model_path))
        return self._llm

    def ask(self, prompt: str) -> str | None:
        """Risposta del modello, None se qualcosa va storto (mai un'eccezione verso il chiamante)."""
        t0 = time.monotonic()
        try:
            if self._generate is not None:
                out = self._generate(prompt)
            else:
                r = self._llama().create_chat_completion(
                    messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                    max_tokens=80, temperature=0.0)
                out = r["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - il modello è un aiuto, non un requisito
            log.warning("Modello locale: errore (%s): parere saltato", exc)
            return None
        finally:
            self.calls += 1
            self.seconds += time.monotonic() - t0
        return (out or "").strip()

    def closure_verdict(self, text: str) -> tuple[str, str] | None:
        """("chiusura_totale"|"accesso_chiuso"|"non_chiusura", motivo) oppure None se non risponde nel formato."""
        out = self.ask(CLOSURE_PROMPT.format(text=text[:MAX_TEXT]))
        if not out:
            return None
        m = _VERDICT.search(out)
        if not m:
            log.info("Modello locale: risposta fuori formato, ignorata: %r", out[:120])
            return None
        reason = _REASON.search(out)
        return m.group(1).lower(), (reason.group(1).strip() if reason else "")[:200]

    def measure_closes(self, measure: str, text: str) -> tuple[bool, str] | None:
        """(True se la voce può indicare una chiusura, motivo) oppure None se non risponde nel formato."""
        out = self.ask(MEASURE_PROMPT.format(measure=measure, text=text[:800]))
        if not out:
            return None
        m = _CLOSES.search(out)
        if not m:
            log.info("Modello locale: risposta fuori formato, ignorata: %r", out[:120])
            return None
        reason = _REASON.search(out)
        return m.group(1).lower() != "no", (reason.group(1).strip() if reason else "")[:200]
