"""Esporta per il Cloudflare Worker i testi e i dati definiti in Python.

    python -m anas_bot.export_worker

Scrive worker/src/generated.js con: messaggio di benvenuto, modulo con i menu
a tendina, nomi di regioni e province, identificativi dei pulsanti.
Così benvenuto e menu hanno UNA sola fonte (Python) e il Worker non li ricopia
a mano. Un test controlla che il file sia aggiornato.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__, views
from .geo import MOTORWAYS, MOTORWAYS_LABEL, PROVINCES, REGIONS

COMMAND = "/anas"
OUT = Path(__file__).resolve().parents[1] / "worker" / "src" / "generated.js"


def build() -> dict:
    return {
        "_nota": "FILE GENERATO da python -m anas_bot.export_worker: non modificarlo a mano",
        "version": __version__,
        "command": COMMAND,
        "ids": {
            "modalCallback": views.MODAL_CALLBACK,
            "openPrefs": views.ACTION_OPEN_PREFS,
            "pause": views.ACTION_PAUSE,
            "openPdfPrefix": views.ACTION_OPEN_PDF_PREFIX,
            "scope": [views.B_SCOPE, views.A_SCOPE],
            "regions": [views.B_REGIONS, views.A_REGIONS],
            "provinces": [views.B_PROVINCES, views.A_PROVINCES],
            "kinds": [views.B_KINDS, views.A_KINDS],
            "allRegions": [views.B_ALL_REGIONS, views.A_ALL_REGIONS],
            "allProvinces": [views.B_ALL_PROVINCES, views.A_ALL_PROVINCES],
            "kindClosures": views.KIND_CLOSURES,
            "kindSpeed": views.KIND_SPEED,
            "kindAll": views.KIND_ALL,
        },
        "welcome": views.welcome_message(),
        "betaNotice": views.BETA_NOTICE,
        "modal": views.preferences_modal(None),
        "regions": {MOTORWAYS: MOTORWAYS_LABEL, **REGIONS},
        "provinces": {p.code: {"name": p.name, "region": p.region} for p in PROVINCES},
    }


def render() -> str:
    # Modulo JS (non .json): si importa uguale nel Worker e nei test di Node, senza opzioni speciali.
    return ("// FILE GENERATO da `python -m anas_bot.export_worker`: non modificarlo a mano.\n"
            "export default " + json.dumps(build(), ensure_ascii=False, indent=1) + ";\n")


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"Scritto {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
