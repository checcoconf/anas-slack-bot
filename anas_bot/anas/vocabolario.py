"""Vocabolario dei provvedimenti ANAS: tutte le voci viste nell'elenco ufficiale.

Rilevato il 02/11/2026 dal collaudo completo (collaudo/elenco.bat): 3.718 ordinanze in vigore,
77 voci diverse (più quelle aggiunte dopo, una per riga con la data). I numeri sono sostituiti da N ("limite di velocita 40Km/h" -> "limite di velocita Nkm/h").

Se in un'ordinanza nuova compare una voce che non è qui, il bot avvisa nel canale admin:
vuol dire che ANAS ha introdotto un provvedimento nuovo e le regole in listing.py vanno controllate.
Per aggiornare: rilancia collaudo/elenco.bat e copia qui la prima colonna di provvedimenti.csv.
"""

import re

KNOWN_MEASURES: frozenset[str] = frozenset({
    'limite di velocita Nkm/h',
    'divieto di sorpasso autoveicoli',
    'chiusura al traffico',
    'restringimento carreggiata destra',
    'senso unico alternato mediante impianto semaforico o movieri',
    'restringimento carreggiata sinistra',
    'distanza minima obbligatoria Nm',
    'divieto di transito',
    'apertura al traffico',
    'limite massimo di velocita Nkm/h',
    'senso unico alternato mediante impianto semaforico',
    'restringimento carreggiata simmetrica',
    'divieto di sosta',
    'divieto di sorpasso',
    'messa in opera segnaletica',
    'restringimento carreggiata',
    'senso unico alternato tramite movieri',
    'divieto di sorpasso per gli autocarri con massa maggiore di Nt',
    'doppio senso di circolazione',
    'fermarsi e dare precedenza',
    'tutti veicoli aventi massa superiore a Nt',
    'autorizzazione a passaggio trasporto eccezionale',
    'deviazione del traffico su carreggiata opposta',
    'passaggio obbligatorio',
    'tutti gli autoveicoli veicoli aventi massa superiore a Nt',
    'divieto di sorpasso tra autotreni',
    'apertura varco',
    'dare precedenza',
    'obbligo catene a bordo o di pneumatici invernali',
    'pedoni',
    'velocipedi',
    'senso unico di marcia',
    'direzione obbligatoria diritto',
    'direzione obbligatoria destra',
    'senso unico alternato',
    'tutti',
    'diritto di precedenza',
    'autobus',
    'tutti veicoli aventi massa superiore a Nt tranne mezzi di soccorso',
    'autoarticolati',
    'autocarri',
    'autotreni',
    'limite di velocita',
    'direzione obbligatoria destra e diritto',
    'tutti veicoli aventi massa superiore a Nt tranne autobus',
    'tutti tranne tutti veicoli che trasportano merci con massa complessiva superiore a Nt',
    'tutti veicoli aventi altezza superiore a Nm',
    'motocarrozzette',
    'motocicli',
    'veicoli a trazione animale',
    'ciclomotori e motocicli',
    'tutti gli autoveicoli',
    'tutti veicoli che trasportano merci con massa autorizzata a pieno carico superiore a Nt',
    'trattori stradali',
    'tutti tranne mezzi di soccorso',
    'tutti veicoli eccezionali e trasporti in condizioni di eccezionalita aventi massa superiore a Nt',
    'tutti veicoli che trasportano merci con massa complessiva superiore a Nt',
    'tutti tranne autobus',
    'tutti gli autoveicoli veicoli aventi altezza superiore a Nm',
    'ciclomotori',
    'tutti gli autoveicoli veicoli aventi massa superiore a Nt tranne autobus',
    'tutti veicoli od ai complessi di veicoli di larghezza superiore a Nm',
    'tutti tranne tutti veicoli aventi massa superiore a Nt',
    'tutti gli autoveicoli veicoli eccezionali e trasporti in condizioni di eccezionalita aventi massa superiore a Nt',
    'tutti gli autoveicoli veicoli ed ai complessi di veicoli di larghezza superiore a Nm',
    'tutti gli autoveicoli veicoli ed ai complessi di veicoli di lunghezza superiore a Nm',
    'tutti veicoli eccezionali e trasporti in condizioni di eccezionalita',
    'distanza minima obbligatoria',
    'spostamento su carreggiata opposta',
    'tutti veicoli che trasportano merci con massa complessiva superiore a Nt tranne autobus',
    'autovetture',
    'autobus veicoli aventi massa superiore a Nt',
    'tutti gli autoveicoli veicoli aventi massa superiore a Nt tranne mezzi di soccorso',
    'restringimento carreggiata autoveicoli',
    'veicoli che trasportano esplosivo o prodotti facilmente infiammabili',
    'direzione obbligatoria sinistra',
    'direzione obbligatoria sinistra e destra',  # 04/11/2026, ord. 462/2026/CT: deviazione a lato di una chiusura
    'veicoli a braccia',  # 05/11/2026: categoria in un divieto di transito (carretti a mano), non una chiusura
    'macchine agricole',
})


def measure_key(m: str) -> str:
    """Voce senza numeri, per confrontarla col vocabolario."""
    return re.sub(r"\d+([.,]\d+)?", "N", m).strip(" .;,")


def unknown_measures(measures: list[str], extra: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Voci non nel vocabolario (né tra quelle aggiunte a runtime, `extra`: vedi listing_poller)."""
    return sorted({measure_key(m) for m in measures} - KNOWN_MEASURES - set(extra))
