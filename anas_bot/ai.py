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

Ogni parere gira in un processo figlio (anas_bot/ai_worker.py): llama.cpp è codice nativo e, se crolla
(è successo il 05/11/2026: ruota compilata per una CPU e riusata dalla cache su un runner con CPU diversa,
"illegal instruction", job morto a metà giro), muore solo il figlio e il giro continua con le sole regole.
Il workflow la compila senza ottimizzazioni per la CPU del momento (GGML_NATIVE=OFF), così la cache pip
vale per tutti i runner.

AI_MODE: flag (default: i pareri segnano "da verificare" e ampliano il vocabolario), log (solo nel log),
off (non si carica nemmeno il modello).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

log = logging.getLogger(__name__)

MAX_TEXT = 3000  # caratteri di riepilogo + PDF passati al modello (il contesto è 4k token)
MAX_CALLS_PER_RUN = 15  # oltre, il giro va avanti con le sole regole: il modello non deve rallentare la lettura
MAX_SECONDS_PER_RUN = 600  # idem se i pareri hanno già preso 10 minuti del giro
SUBPROCESS_TIMEOUT = 180  # secondi per un parere (caricamento del modello compreso): oltre, il figlio viene ucciso


class ModelCrashed(Exception):
    """Il processo del modello è uscito male (crollo del codice nativo, libreria mancante...)."""


_SIGNAL_HINTS = {4: "istruzione non supportata dalla CPU: ruota di llama.cpp non portabile",
                 9: "ucciso, probabilmente memoria finita", 11: "accesso a memoria non valido"}


def _signal_hint(returncode: int) -> str:
    """-4 -> " (SIGILL, istruzione non supportata...)": un codice negativo è il segnale che ha ucciso il processo."""
    if returncode >= 0:
        return ""
    import signal
    try:
        name = signal.Signals(-returncode).name
    except ValueError:
        name = f"segnale {-returncode}"
    hint = _SIGNAL_HINTS.get(-returncode)
    return f" ({name}, {hint})" if hint else f" ({name})"

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

PROVINCE_PROMPT = """Tratto di strada statale italiana gestita da ANAS:
- strada: {road}
- chilometri: {km}
- regione: {region}
- direzione indicata: {direction}
In quale provincia (o province) italiana si trova questo tratto? Usa la tua conoscenza della geografia
stradale italiana. Se non sei sicuro, dichiaralo: una provincia sbagliata è peggio di nessuna.
Rispondi con tre righe nel formato:
PROVINCE: sigle separate da virgola (es. NA oppure NA, SA)
CERTEZZA: alta | media | bassa
MOTIVO: una frase breve"""

_PROVS = re.compile(r"province\s*:\s*([A-Za-z ,]+)", re.I)
_CERT = re.compile(r"certezza\s*:\s*(alta|media|bassa)", re.I)

_VERDICT = re.compile(r"verdetto\s*:\s*(chiusura_totale|accesso_chiuso|non_chiusura)", re.I)
_CLOSES = re.compile(r"chiusura\s*:\s*(si|sì|no)\b", re.I)
_REASON = re.compile(r"motivo\s*:\s*(.+)", re.I)


class LocalModel:
    """Modello locale via llama.cpp. `generate` è sostituibile nei test (prompt -> testo)."""

    def __init__(self, model_path: str, generate=None, n_threads: int | None = None) -> None:
        self.model_path = model_path
        self._generate = generate
        self.n_threads = n_threads or max(1, os.cpu_count() or 2)  # tutte le CPU del runner
        self.calls = 0
        self.seconds = 0.0
        self.disabled = False  # True dopo un crollo del processo del modello: da lì solo regole, per tutto il giro

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

    def _in_subprocess(self, prompt: str) -> str:
        """Carica il modello e risponde in un processo figlio (anas_bot/ai_worker.py): se il codice nativo
        crolla (SIGILL su una CPU diversa, memoria finita) o si impianta, muore o viene fermato solo il figlio."""
        import subprocess
        import sys
        req = json.dumps({"model_path": self.model_path, "system": SYSTEM, "prompt": prompt, "n_threads": self.n_threads})
        p = subprocess.run([sys.executable, "-m", "anas_bot.ai_worker"], input=req, capture_output=True, text=True,
                           timeout=SUBPROCESS_TIMEOUT)
        if p.returncode != 0:
            tail = (p.stderr or "").strip().splitlines()[-1:] or ["nessun dettaglio"]
            raise ModelCrashed(f"uscita {p.returncode}{_signal_hint(p.returncode)}: {tail[0][:200]}")
        return p.stdout

    def ask(self, prompt: str) -> str | None:
        """Risposta del modello, None se qualcosa va storto (mai un'eccezione verso il chiamante)."""
        if self.disabled:
            return None
        if self.calls >= MAX_CALLS_PER_RUN or self.seconds >= MAX_SECONDS_PER_RUN:
            if self.calls == MAX_CALLS_PER_RUN or self.seconds >= MAX_SECONDS_PER_RUN:
                log.info("Modello locale: tetto del giro raggiunto (%d pareri, %.0f s): da qui solo regole", self.calls, self.seconds)
            self.calls += 1
            return None
        t0 = time.monotonic()
        try:
            if self._generate is not None:
                out = self._generate(prompt)
            else:
                out = self._in_subprocess(prompt)
        except ModelCrashed as exc:
            self.disabled = True
            log.warning("Modello locale: il processo del modello è crollato (%s): per questo giro solo regole", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - il modello è un aiuto, non un requisito
            if exc.__class__.__name__ == "TimeoutExpired":
                self.disabled = True
                log.warning("Modello locale: nessuna risposta entro %d s: per questo giro solo regole", SUBPROCESS_TIMEOUT)
            else:
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

    def province_guess(self, road: str, km: str, region: str, direction: str) -> tuple[list[str], str, str] | None:
        """([sigle], certezza, motivo) oppure None se non risponde nel formato. Chi chiama decide se fidarsi
        (solo con certezza "alta" e province dentro la regione)."""
        out = self.ask(PROVINCE_PROMPT.format(road=road or "?", km=km or "non indicati", region=region or "?",
                                              direction=direction or "non indicata"))
        if not out:
            return None
        provs, cert = _PROVS.search(out), _CERT.search(out)
        if not provs or not cert:
            log.info("Modello locale: risposta fuori formato, ignorata: %r", out[:120])
            return None
        codes = sorted({c.strip().upper() for c in provs.group(1).split(",") if 1 < len(c.strip()) <= 2})
        reason = _REASON.search(out)
        return codes, cert.group(1).lower(), (reason.group(1).strip() if reason else "")[:200]

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
