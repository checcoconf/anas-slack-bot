"""Messaggi e schermate Slack (Block Kit).

Qui vivono i testi "fonte" in Python:
- le notifiche (le manda il job di GitHub Actions);
- il messaggio di benvenuto e il modulo con i menu a tendina, che vengono
  ESPORTATI in worker/src/generated.js (python -m anas_bot.export_worker)
  così il Cloudflare Worker usa esattamente gli stessi blocchi.
La scheda Home e la conferma di salvataggio stanno nel Worker (worker/src/views.js).

Regioni e province si scelgono da menu a tendina con ricerca, così nessuno
deve scriverle a mano. Le province sono raggruppate per regione.
Le emoji fanno da "segnaletica": si capisce il tipo di avviso prima di leggerlo.
Limiti Slack rispettati: max 100 opzioni per gruppo, max 100 gruppi,
testi delle opzioni sotto i 75 caratteri, max 50 blocchi per messaggio.
"""

from __future__ import annotations

from datetime import date

from .anas.parser import CLOSURE, REOPENING, SPEED, Ordinanza
from .db import User
from .geo import PROVINCE_BY_CODE, REGIONS, provinces_of_region

MODAL_CALLBACK = "prefs_modal"
ACTION_OPEN_PREFS = "open_prefs"
ACTION_PAUSE = "toggle_pause"
ACTION_OPEN_PDF_PREFIX = "open_pdf_"  # pulsante link: Slack lo notifica comunque, va solo confermato

B_SCOPE, A_SCOPE = "scope_block", "scope"
B_REGIONS, A_REGIONS = "regions_block", "regions"
B_PROVINCES, A_PROVINCES = "provinces_block", "provinces"
B_KINDS, A_KINDS = "kinds_block", "kinds"

KIND_CLOSURES = "closures"
KIND_SPEED = "speed"



def _shorten(text: str, limit: int) -> str:
    """Taglia su una parola intera, con i puntini se serve."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;.") + "…"

def _txt(s: str) -> dict:
    return {"type": "plain_text", "text": s[:75], "emoji": True}


def _region_option(code: str) -> dict:
    return {"text": _txt(REGIONS[code]), "value": code}


def _province_option(code: str) -> dict:
    p = PROVINCE_BY_CODE[code]
    return {"text": _txt(f"{p.name} ({p.code})"), "value": p.code}


def region_options() -> list[dict]:
    return [_region_option(c) for c in sorted(REGIONS, key=lambda c: REGIONS[c])]


def province_option_groups() -> list[dict]:
    groups = []
    for rcode in sorted(REGIONS, key=lambda c: REGIONS[c]):
        provs = sorted(provinces_of_region(rcode), key=lambda p: p.name)
        groups.append({"label": _txt(REGIONS[rcode]), "options": [_province_option(p.code) for p in provs]})
    return groups


_SCOPE_OPTION = {"text": _txt("🇮🇹 Tutta Italia"), "value": "all",
                 "description": _txt("Ricevi tutto, regioni e province vengono ignorate")}
_KIND_OPTIONS = {
    KIND_CLOSURES: {"text": _txt("⛔ Chiusure e ✅ aperture"), "value": KIND_CLOSURES,
                    "description": _txt("Strade, rampe e svincoli chiusi o aperti, nuove strade")},
    KIND_SPEED: {"text": _txt("🚦 Limiti di velocità permanenti"), "value": KIND_SPEED,
                 "description": _txt("Nuovi limiti definitivi sulle strade ANAS")},
}


def preferences_modal(user: User | None) -> dict:
    u = user or User(user_id="")
    regions_el: dict = {
        "type": "multi_static_select", "action_id": A_REGIONS,
        "placeholder": _txt("Scegli una o più regioni"), "options": region_options(),
    }
    if u.regions:
        regions_el["initial_options"] = [_region_option(r) for r in u.regions if r in REGIONS]
    provinces_el: dict = {
        "type": "multi_static_select", "action_id": A_PROVINCES,
        "placeholder": _txt("Scegli una o più province"), "option_groups": province_option_groups(),
    }
    if u.provinces:
        provinces_el["initial_options"] = [_province_option(p) for p in u.provinces if p in PROVINCE_BY_CODE]
    scope_el: dict = {"type": "checkboxes", "action_id": A_SCOPE, "options": [_SCOPE_OPTION]}
    if u.all_italy:
        scope_el["initial_options"] = [_SCOPE_OPTION]
    kinds_initial = [o for k, o in _KIND_OPTIONS.items()
                     if (k == KIND_CLOSURES and u.want_closures) or (k == KIND_SPEED and u.want_speed)]
    kinds_el: dict = {"type": "checkboxes", "action_id": A_KINDS, "options": list(_KIND_OPTIONS.values())}
    if kinds_initial:
        kinds_el["initial_options"] = kinds_initial

    return {
        "type": "modal",
        "callback_id": MODAL_CALLBACK,
        "title": _txt("🗺️ Zone da seguire"),
        "submit": _txt("💾 Salva"),
        "close": _txt("Annulla"),
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text":
                "Scegli dove vuoi ricevere le ordinanze ANAS.\n"
                "Puoi combinare *regioni intere* e *singole province*."}},
            {"type": "input", "block_id": B_SCOPE, "optional": True, "label": _txt("🌍 Copertura"),
             "element": scope_el},
            {"type": "input", "block_id": B_REGIONS, "optional": True, "label": _txt("🗺️ Regioni intere"),
             "element": regions_el},
            {"type": "input", "block_id": B_PROVINCES, "optional": True, "label": _txt("📍 Singole province"),
             "element": provinces_el, "hint": _txt("🔍 Scrivi nel menu per cercare, es. \"Cun\" per Cuneo")},
            {"type": "input", "block_id": B_KINDS, "label": _txt("🔔 Cosa vuoi ricevere"), "element": kinds_el},
        ],
    }


def welcome_message() -> dict:
    return {
        "text": "👋 Ciao! Scegli le zone per cui vuoi ricevere chiusure e limiti ANAS.",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text":
                "👋 *Benvenuto!* Ti scrivo qui quando ANAS pubblica un'ordinanza utile per la mappa:\n\n"
                "⛔ strade, carreggiate, rampe e svincoli *chiusi*\n"
                "✅ le *riaperture* e 🆕 le *nuove strade* aperte al traffico\n"
                "🚦 i *limiti di velocità permanenti*\n\n"
                "🚫 Niente cantieri con corsie ridotte o sensi unici alternati.\n\n"
                "👇 Per iniziare scegli le regioni o le province che ti interessano."}},
            {"type": "actions", "elements": [
                {"type": "button", "style": "primary", "action_id": ACTION_OPEN_PREFS,
                 "text": _txt("🗺️ Scegli le zone")}]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text":
                "⚙️ Puoi cambiarle quando vuoi dalla scheda *Home* di questa app o con `/anas`."}]},
        ],
    }


# --- Notifiche ---------------------------------------------------------------

def _fmt_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def _mrkdwn_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def title_line(o: Ordinanza) -> str:
    """Il "cartello" in cima a ogni avviso: cosa succede, in maiuscolo, con l'emoji giusta."""
    if o.category == CLOSURE:
        title = "↪️⛔ *RAMPA / SVINCOLO CHIUSO*" if o.ramp_only else "⛔ *STRADA CHIUSA*"
        return title + "  ⏩ _chiusura prorogata_" if o.extension else title
    if o.category == REOPENING:
        return "🆕 *NUOVA STRADA APERTA*" if o.new_road else "✅ *APERTA AL TRAFFICO*"
    if o.category == SPEED:
        speeds = o.speeds or ([o.speed_kmh] if o.speed_kmh else [])
        if len(speeds) > 1:
            return f"🚦 *NUOVI LIMITI: {' / '.join(map(str, speeds))} km/h*"
        return f"🚦 *NUOVO LIMITE: {speeds[0]} km/h*" if speeds else "🚦 *NUOVO LIMITE DI VELOCITÀ*"
    return f"ℹ️ *{o.category.upper()}*"


def time_line(window: str) -> str:
    """🌙 se l'orario attraversa la notte, ☀️ se è di giorno."""
    if not window:
        return ""
    start_h = int(window[:2])
    end_h = int(window[6:8])
    night = start_h > end_h or start_h >= 20 or end_h <= 6
    return f"🌙 solo di notte, {window.replace('-', '–')}" if night else f"☀️ solo di giorno, {window.replace('-', '–')}"


def ordinanza_blocks(o: Ordinanza) -> list[dict]:
    roads = ", ".join(f"{r} {o.road_names[r]}" if r in o.road_names else r for r in o.roads[:4]) or "strada n.d."
    lines = [title_line(o), f"🛣️ *{_mrkdwn_escape(roads)}*"]

    if o.km_from:
        lines.append(f"📏 km {o.km_from}" + (f" → {o.km_to}" if o.km_to else ""))
    if o.direction:
        icon = "🔁" if o.direction.startswith("entrambe") else "➡️"
        lines.append(f"{icon} {o.direction}")

    if o.provinces:
        lines.append("📍 " + ", ".join(
            f"{PROVINCE_BY_CODE[p].name} ({p})" for p in o.provinces if p in PROVINCE_BY_CODE))
    elif o.regions:
        lines.append("📍 " + ", ".join(REGIONS.get(r, r) for r in o.regions) + "  ❓ _provincia non determinata_")
    else:
        lines.append("📍 ❓ _zona non determinata_")

    if o.start_date:
        when = f"📅 dal {_fmt_date(o.start_date)}"
        when += f" al {_fmt_date(o.end_date)}" if o.end_date else "  ♾️ fino a nuova disposizione"
        lines.append(when)
    elif o.open_ended:
        lines.append("📅 ♾️ fino a nuova disposizione")
    if o.time_window:
        lines.append(time_line(o.time_window))

    if o.excerpt:
        lines.append(f"> 💬 _{_mrkdwn_escape(_shorten(o.excerpt, 280))}_")

    num = f"n. {o.number}" if o.number else f"id {o.ord_id}"
    section: dict = {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]}}
    if o.pdf_url:
        section["accessory"] = {"type": "button", "action_id": f"{ACTION_OPEN_PDF_PREFIX}{o.ord_id}",
                                "text": _txt("📄 Apri PDF"), "url": o.pdf_url}
    return [
        section,
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            f"🏛️ Ordinanza {num}" + (f" · {o.structure}" if o.structure else "")}]},
        {"type": "divider"},
    ]


_SHORT = {CLOSURE: "⛔ chiusura", REOPENING: "✅ apertura", SPEED: "🚦 limite"}


def notification_messages(ords: list[Ordinanza], per_message: int = 15) -> list[tuple[dict, list[int]]]:
    """Uno o più messaggi (max ~47 blocchi ciascuno) con le ordinanze raggruppate.

    Restituisce coppie (messaggio, ord_id contenuti), così chi invia può segnare
    come consegnato ogni pezzo appena parte.
    """
    msgs: list[tuple[dict, list[int]]] = []
    n = len(ords)
    for i in range(0, n, per_message):
        chunk = ords[i:i + per_message]
        title = "🚧 1 nuova ordinanza ANAS" if n == 1 else f"🚧 {n} nuove ordinanze ANAS"
        if n > per_message:
            title += f" ({i // per_message + 1}/{(n - 1) // per_message + 1})"
        counts = {c: sum(o.category == c for o in chunk) for c in _SHORT}
        recap = " · ".join(f"{_SHORT[c]} ×{k}" for c, k in counts.items() if k)
        blocks: list[dict] = [
            {"type": "header", "text": _txt(f"{title} per le tue zone")},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": recap or " "}]},
            {"type": "divider"},
        ]
        for o in chunk:
            blocks.extend(ordinanza_blocks(o))
        summary = "; ".join(f"{_SHORT.get(o.category, o.category)} {' '.join(o.roads[:2])}" for o in chunk)
        msgs.append(({"text": f"{title}: {summary}"[:3000], "blocks": blocks}, [o.ord_id for o in chunk]))
    return msgs
