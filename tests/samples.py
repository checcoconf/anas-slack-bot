"""Testi di prova che imitano la struttura delle ordinanze ANAS (contenuto inventato)."""

HEADER_ABRUZZO = """Struttura Territoriale Abruzzo e Molise
Via dei Piccolomini, 5 - 67100 L'Aquila - T [+39] 0862305001
Pec anas.abruzzo@postacert.stradeanas.it - www.stradeanas.it
Anas S.p.A. - Gruppo Ferrovie dello Stato Italiane
ALLA PREFETTURA DI CHIETI
ALLA PREFETTURA DI PESCARA
ALLA QUESTURA DI CHIETI
AL COMUNE DI SCAFA
"""

CLOSURE_SS614 = HEADER_ABRUZZO + """
ORDINANZA n. 266/2026
Oggetto: Strada Statale 614 "della Maielletta" - lavori di ripristino del piano viabile.
IL RESPONSABILE DELLA STRUTTURA TERRITORIALE
VISTO il Codice della Strada; CONSIDERATO che occorre eseguire i lavori;
ORDINA
* la chiusura al traffico della Strada Statale 614 "della Maielletta" dal km 12+300 al km 14+050,
in entrambe le direzioni, a partire dal 10/11/2026 fino al 14/11/2026 dalle ore 08:00 alle ore 17:00,
con deviazione del traffico sulla viabilità locale; interesserà tutti gli utenti.
DISPONE
che la presente ordinanza sia resa nota mediante la prescritta segnaletica.
Il Responsabile Struttura Territoriale
"""

RAMP_A2 = """Coordinamento Territoriale Calabria
Area Compartimentale Autostrada del Mediterraneo
Contrada Ligiuri - 87100 Cosenza
ALLA PREFETTURA DI COSENZA
ALLA QUESTURA DI COSENZA
ORDINANZA n. 238/2026
ORDINA
* chiusura al traffico su A2 AUTOSTRADA DEL MEDITERRANEO al km 187+748, chiusura della rampa di
ingresso in carreggiata Nord dello svincolo di Morano Calabro/Castrovillari, Corsie: rampa di ingresso
Provvedimenti: chiusura al traffico, a partire dal 12/11/2026 fino al 15/11/2026 nella fascia oraria dalle
22:00 alle 07:00 del giorno successivo; interesserà tutti gli utenti.
AVVERTE
che i trasgressori saranno puniti.
"""

LANE_ONLY = HEADER_ABRUZZO + """
ORDINANZA n. 300/2026
ORDINA
* la chiusura della corsia di sorpasso della SS 16 "Adriatica" dal km 450+000 al km 452+000 in direzione
Pescara, dal 05/11/2026 al 20/11/2026, con restringimento della carreggiata.
* l'istituzione del senso unico alternato regolato da impianto semaforico al km 455+100.
Il Responsabile
"""

MIXED_LANE_AND_CLOSURE = HEADER_ABRUZZO + """
ORDINANZA n. 301/2026
ORDINA
* la chiusura della corsia di marcia della SS 16 dal km 450+000 al km 451+000 dal 05/11/2026 al 06/11/2036;
* la chiusura al traffico dello svincolo di Francavilla al Mare sulla SS 16 al km 452+300, rampa di uscita,
dal 05/11/2026 al 06/11/2036 dalle ore 21:00 alle ore 06:00.
Il Responsabile
"""

TRUCKS_ONLY = HEADER_ABRUZZO + """
ORDINANZA n. 302/2026
ORDINA
* il divieto di transito ai veicoli di massa complessiva superiore a 7,5 t, chiusura al traffico per
tali veicoli sulla SS 5 "Tiburtina Valeria" dal km 180+000 al km 182+000 dal 01/12/2026 al 31/03/2027.
Il Responsabile
"""

SPEED_PERMANENT = """Struttura Territoriale Puglia
Viale Einaudi 15 - Bari
ALLA PREFETTURA DI FOGGIA
ORDINANZA n. 410/2026
ORDINA
* l'istituzione in via permanente del limite di velocità di 70 km/h sulla SS 16 "Adriatica" dal km
680+500 al km 683+200 in entrambe le direzioni, a decorrere dal 15/11/2026.
Il Responsabile
"""

SPEED_WORKSITE = """Struttura Territoriale Puglia
Viale Einaudi 15 - Bari
ALLA PREFETTURA DI BARI
ORDINANZA n. 411/2026
ORDINA
* il limite di velocità di 40 km/h in corrispondenza del cantiere sulla SS 96 dal km 100+000 al km 101+000
dal 03/11/2026 al 30/11/2026 per tutta la durata dei lavori.
Il Responsabile
"""

REOPENING_SS36 = """Struttura Territoriale Lombardia
Via Corradino D'Ascanio 3 - Milano
ALLA PREFETTURA DI LECCO
ALLA QUESTURA DI LECCO
ORDINANZA n. 512/2026
ORDINA
* la revoca dell'ordinanza n. 480/2026 di chiusura al traffico e la conseguente riapertura al traffico della
SS 36 "del Lago di Como e dello Spluga" tra gli svincoli di Bellano e Abbadia Lariana dal 08/11/2026.
Il Responsabile
"""

NO_PROVINCE = """Struttura Territoriale Sardegna
Via Biasi 27 - Cagliari
ORDINANZA n. 77/2026
ORDINA
* la chiusura al traffico della SS 131 "Carlo Felice" dal km 30+000 al km 31+000 dal 20/11/2026 al 21/11/2026
dalle ore 22:00 alle ore 06:00.
Il Responsabile
"""

EXPIRED = HEADER_ABRUZZO + """
ORDINANZA n. 12/2026
ORDINA
* la chiusura al traffico della SS 17 dal km 100+000 al km 101+000 dal 10/01/2026 al 12/01/2026.
Il Responsabile
"""

# Formato 2026: numero con sigla della struttura, struttura indicata con la città, proroga
EXTENSION_BARI = """Anas S.p.A. - Struttura Territoriale Bari
Viale Einaudi 15 - Bari
ORDINANZA N°723/2026/BA
Protocollo: CDG-1010738-U
ORDINA
* la proroga fino al 20/11/2026 della chiusura al traffico della SS 172 "dei Trulli" dal km 20+000 al km 22+500,
in entrambe le direzioni, gia' disposta con ordinanza n. 650/2026/BA a partire dal 01/10/2026.
Il Responsabile
"""
