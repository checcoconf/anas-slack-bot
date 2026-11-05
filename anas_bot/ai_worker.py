"""Processo separato che carica il modello locale e risponde a UNA domanda (usato da anas_bot/ai.py).

Perché a parte: llama.cpp è codice nativo. Se la libreria crolla (es. istruzione non supportata dalla CPU
del runner, memoria finita), il processo che la ospita muore senza eccezione Python. Tenendola in un
processo figlio, muore solo il figlio: il giro ANAS prosegue senza secondo parere.

Protocollo: su stdin un JSON {"model_path", "system", "prompt", "n_threads"}; su stdout la risposta
del modello (testo). Uscita 0 = ok. Il resto (log, errori) va su stderr.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    req = json.loads(sys.stdin.read())
    from llama_cpp import Llama  # import qui: se manca, l'errore resta nel figlio

    llm = Llama(model_path=req["model_path"], n_ctx=4096, n_threads=int(req.get("n_threads") or 2), verbose=False)
    r = llm.create_chat_completion(
        messages=[{"role": "system", "content": req["system"]}, {"role": "user", "content": req["prompt"]}],
        max_tokens=80, temperature=0.0)
    sys.stdout.write(r["choices"][0]["message"]["content"] or "")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
