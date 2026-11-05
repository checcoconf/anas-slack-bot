// FILE GENERATO da `python -m anas_bot.export_worker`: non modificarlo a mano.
export default {
 "_nota": "FILE GENERATO da python -m anas_bot.export_worker: non modificarlo a mano",
 "version": "1.1.0",
 "command": "/anas",
 "ids": {
  "modalCallback": "prefs_modal",
  "openPrefs": "open_prefs",
  "pause": "toggle_pause",
  "openPdfPrefix": "open_pdf_",
  "scope": [
   "scope_block",
   "scope"
  ],
  "regions": [
   "regions_block",
   "regions"
  ],
  "provinces": [
   "provinces_block",
   "provinces"
  ],
  "kinds": [
   "kinds_block",
   "kinds"
  ],
  "allRegions": [
   "all_regions_block",
   "all_regions"
  ],
  "allProvinces": [
   "all_provinces_block",
   "all_provinces"
  ],
  "kindClosures": "closures",
  "kindSpeed": "speed",
  "kindAll": "all"
 },
 "welcome": {
  "text": "👋 Ciao! Scegli le zone per cui vuoi ricevere chiusure e limiti ANAS.",
  "blocks": [
   {
    "type": "section",
    "text": {
     "type": "mrkdwn",
     "text": "👋 *Benvenuto!* Ti scrivo qui quando ANAS pubblica un'ordinanza utile per la mappa:\n\n⛔ strade, carreggiate, rampe e svincoli *chiusi*\n✅ le *riaperture* e 🆕 le *nuove strade* aperte al traffico\n🚦 i *limiti di velocità permanenti*\n\n🚧 Cantieri, corsie ridotte e sensi unici alternati solo se li chiedi.\n\n👇 Per iniziare scegli le regioni o le province che ti interessano."
    }
   },
   {
    "type": "actions",
    "elements": [
     {
      "type": "button",
      "style": "primary",
      "action_id": "open_prefs",
      "text": {
       "type": "plain_text",
       "text": "🗺️ Scegli le zone",
       "emoji": true
      }
     }
    ]
   },
   {
    "type": "context",
    "elements": [
     {
      "type": "mrkdwn",
      "text": "⚙️ Puoi cambiarle quando vuoi dalla scheda *Home* di questa app.\n🧪 Il filtro \"utili per Waze\" è in beta: legge il riepilogo di ANAS con regole, non è perfetto. Può perdere qualche ordinanza o mandarne qualcuna che non c'entra. Se noti un errore, segnalalo."
     }
    ]
   }
  ]
 },
 "betaNotice": "🧪 Il filtro \"utili per Waze\" è in beta: legge il riepilogo di ANAS con regole, non è perfetto. Può perdere qualche ordinanza o mandarne qualcuna che non c'entra. Se noti un errore, segnalalo.",
 "modal": {
  "type": "modal",
  "callback_id": "prefs_modal",
  "title": {
   "type": "plain_text",
   "text": "🗺️ Zone da seguire",
   "emoji": true
  },
  "submit": {
   "type": "plain_text",
   "text": "💾 Salva",
   "emoji": true
  },
  "close": {
   "type": "plain_text",
   "text": "Annulla",
   "emoji": true
  },
  "blocks": [
   {
    "type": "section",
    "text": {
     "type": "mrkdwn",
     "text": "Scegli dove vuoi ricevere le ordinanze ANAS.\nPuoi combinare *regioni intere* e *singole province*."
    }
   },
   {
    "type": "input",
    "block_id": "scope_block",
    "optional": true,
    "label": {
     "type": "plain_text",
     "text": "🌍 Copertura",
     "emoji": true
    },
    "element": {
     "type": "checkboxes",
     "action_id": "scope",
     "options": [
      {
       "text": {
        "type": "plain_text",
        "text": "🇮🇹 Tutta Italia",
        "emoji": true
       },
       "value": "all",
       "description": {
        "type": "plain_text",
        "text": "Ricevi tutto, regioni e province vengono ignorate",
        "emoji": true
       }
      }
     ]
    }
   },
   {
    "type": "input",
    "block_id": "regions_block",
    "optional": true,
    "label": {
     "type": "plain_text",
     "text": "🗺️ Regioni intere (o tutte le autostrade)",
     "emoji": true
    },
    "element": {
     "type": "multi_static_select",
     "action_id": "regions",
     "placeholder": {
      "type": "plain_text",
      "text": "Scegli una o più regioni",
      "emoji": true
     },
     "options": [
      {
       "text": {
        "type": "plain_text",
        "text": "🛣️ Autostrade (tutta Italia)",
        "emoji": true
       },
       "value": "autostrade"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Abruzzo",
        "emoji": true
       },
       "value": "abruzzo"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Basilicata",
        "emoji": true
       },
       "value": "basilicata"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Calabria",
        "emoji": true
       },
       "value": "calabria"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Campania",
        "emoji": true
       },
       "value": "campania"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Emilia-Romagna",
        "emoji": true
       },
       "value": "emilia-romagna"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Friuli-Venezia Giulia",
        "emoji": true
       },
       "value": "friuli-venezia-giulia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Lazio",
        "emoji": true
       },
       "value": "lazio"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Liguria",
        "emoji": true
       },
       "value": "liguria"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Lombardia",
        "emoji": true
       },
       "value": "lombardia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Marche",
        "emoji": true
       },
       "value": "marche"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Molise",
        "emoji": true
       },
       "value": "molise"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Piemonte",
        "emoji": true
       },
       "value": "piemonte"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Puglia",
        "emoji": true
       },
       "value": "puglia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Sardegna",
        "emoji": true
       },
       "value": "sardegna"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Sicilia",
        "emoji": true
       },
       "value": "sicilia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Toscana",
        "emoji": true
       },
       "value": "toscana"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Trentino-Alto Adige",
        "emoji": true
       },
       "value": "trentino-alto-adige"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Umbria",
        "emoji": true
       },
       "value": "umbria"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Valle d'Aosta",
        "emoji": true
       },
       "value": "valle-d-aosta"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Veneto",
        "emoji": true
       },
       "value": "veneto"
      }
     ]
    }
   },
   {
    "type": "input",
    "block_id": "provinces_block",
    "optional": true,
    "label": {
     "type": "plain_text",
     "text": "📍 Singole province",
     "emoji": true
    },
    "element": {
     "type": "multi_static_select",
     "action_id": "provinces",
     "placeholder": {
      "type": "plain_text",
      "text": "Scegli una o più province",
      "emoji": true
     },
     "option_groups": [
      {
       "label": {
        "type": "plain_text",
        "text": "Abruzzo",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Chieti (CH)",
          "emoji": true
         },
         "value": "CH"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "L'Aquila (AQ)",
          "emoji": true
         },
         "value": "AQ"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pescara (PE)",
          "emoji": true
         },
         "value": "PE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Teramo (TE)",
          "emoji": true
         },
         "value": "TE"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Basilicata",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Matera (MT)",
          "emoji": true
         },
         "value": "MT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Potenza (PZ)",
          "emoji": true
         },
         "value": "PZ"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Calabria",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Catanzaro (CZ)",
          "emoji": true
         },
         "value": "CZ"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Cosenza (CS)",
          "emoji": true
         },
         "value": "CS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Crotone (KR)",
          "emoji": true
         },
         "value": "KR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Reggio Calabria (RC)",
          "emoji": true
         },
         "value": "RC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Vibo Valentia (VV)",
          "emoji": true
         },
         "value": "VV"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Campania",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Avellino (AV)",
          "emoji": true
         },
         "value": "AV"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Benevento (BN)",
          "emoji": true
         },
         "value": "BN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Caserta (CE)",
          "emoji": true
         },
         "value": "CE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Napoli (NA)",
          "emoji": true
         },
         "value": "NA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Salerno (SA)",
          "emoji": true
         },
         "value": "SA"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Emilia-Romagna",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bologna (BO)",
          "emoji": true
         },
         "value": "BO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ferrara (FE)",
          "emoji": true
         },
         "value": "FE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Forlì-Cesena (FC)",
          "emoji": true
         },
         "value": "FC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Modena (MO)",
          "emoji": true
         },
         "value": "MO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Parma (PR)",
          "emoji": true
         },
         "value": "PR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Piacenza (PC)",
          "emoji": true
         },
         "value": "PC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ravenna (RA)",
          "emoji": true
         },
         "value": "RA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Reggio Emilia (RE)",
          "emoji": true
         },
         "value": "RE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Rimini (RN)",
          "emoji": true
         },
         "value": "RN"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Friuli-Venezia Giulia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Gorizia (GO)",
          "emoji": true
         },
         "value": "GO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pordenone (PN)",
          "emoji": true
         },
         "value": "PN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Trieste (TS)",
          "emoji": true
         },
         "value": "TS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Udine (UD)",
          "emoji": true
         },
         "value": "UD"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Lazio",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Frosinone (FR)",
          "emoji": true
         },
         "value": "FR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Latina (LT)",
          "emoji": true
         },
         "value": "LT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Rieti (RI)",
          "emoji": true
         },
         "value": "RI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Roma (RM)",
          "emoji": true
         },
         "value": "RM"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Viterbo (VT)",
          "emoji": true
         },
         "value": "VT"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Liguria",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Genova (GE)",
          "emoji": true
         },
         "value": "GE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Imperia (IM)",
          "emoji": true
         },
         "value": "IM"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "La Spezia (SP)",
          "emoji": true
         },
         "value": "SP"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Savona (SV)",
          "emoji": true
         },
         "value": "SV"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Lombardia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bergamo (BG)",
          "emoji": true
         },
         "value": "BG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Brescia (BS)",
          "emoji": true
         },
         "value": "BS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Como (CO)",
          "emoji": true
         },
         "value": "CO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Cremona (CR)",
          "emoji": true
         },
         "value": "CR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lecco (LC)",
          "emoji": true
         },
         "value": "LC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lodi (LO)",
          "emoji": true
         },
         "value": "LO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Mantova (MN)",
          "emoji": true
         },
         "value": "MN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Milano (MI)",
          "emoji": true
         },
         "value": "MI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Monza e della Brianza (MB)",
          "emoji": true
         },
         "value": "MB"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pavia (PV)",
          "emoji": true
         },
         "value": "PV"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Sondrio (SO)",
          "emoji": true
         },
         "value": "SO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Varese (VA)",
          "emoji": true
         },
         "value": "VA"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Marche",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Ancona (AN)",
          "emoji": true
         },
         "value": "AN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ascoli Piceno (AP)",
          "emoji": true
         },
         "value": "AP"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Fermo (FM)",
          "emoji": true
         },
         "value": "FM"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Macerata (MC)",
          "emoji": true
         },
         "value": "MC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pesaro e Urbino (PU)",
          "emoji": true
         },
         "value": "PU"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Molise",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Campobasso (CB)",
          "emoji": true
         },
         "value": "CB"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Isernia (IS)",
          "emoji": true
         },
         "value": "IS"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Piemonte",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Alessandria (AL)",
          "emoji": true
         },
         "value": "AL"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Asti (AT)",
          "emoji": true
         },
         "value": "AT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Biella (BI)",
          "emoji": true
         },
         "value": "BI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Cuneo (CN)",
          "emoji": true
         },
         "value": "CN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Novara (NO)",
          "emoji": true
         },
         "value": "NO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Torino (TO)",
          "emoji": true
         },
         "value": "TO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Verbano-Cusio-Ossola (VB)",
          "emoji": true
         },
         "value": "VB"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Vercelli (VC)",
          "emoji": true
         },
         "value": "VC"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Puglia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bari (BA)",
          "emoji": true
         },
         "value": "BA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Barletta-Andria-Trani (BT)",
          "emoji": true
         },
         "value": "BT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Brindisi (BR)",
          "emoji": true
         },
         "value": "BR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Foggia (FG)",
          "emoji": true
         },
         "value": "FG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lecce (LE)",
          "emoji": true
         },
         "value": "LE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Taranto (TA)",
          "emoji": true
         },
         "value": "TA"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Sardegna",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Cagliari (CA)",
          "emoji": true
         },
         "value": "CA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Gallura Nord-Est Sardegna (OT)",
          "emoji": true
         },
         "value": "OT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Medio Campidano (VS)",
          "emoji": true
         },
         "value": "VS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Nuoro (NU)",
          "emoji": true
         },
         "value": "NU"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ogliastra (OG)",
          "emoji": true
         },
         "value": "OG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Oristano (OR)",
          "emoji": true
         },
         "value": "OR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Sassari (SS)",
          "emoji": true
         },
         "value": "SS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Sulcis Iglesiente (SU)",
          "emoji": true
         },
         "value": "SU"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Sicilia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Agrigento (AG)",
          "emoji": true
         },
         "value": "AG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Caltanissetta (CL)",
          "emoji": true
         },
         "value": "CL"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Catania (CT)",
          "emoji": true
         },
         "value": "CT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Enna (EN)",
          "emoji": true
         },
         "value": "EN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Messina (ME)",
          "emoji": true
         },
         "value": "ME"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Palermo (PA)",
          "emoji": true
         },
         "value": "PA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ragusa (RG)",
          "emoji": true
         },
         "value": "RG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Siracusa (SR)",
          "emoji": true
         },
         "value": "SR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Trapani (TP)",
          "emoji": true
         },
         "value": "TP"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Toscana",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Arezzo (AR)",
          "emoji": true
         },
         "value": "AR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Firenze (FI)",
          "emoji": true
         },
         "value": "FI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Grosseto (GR)",
          "emoji": true
         },
         "value": "GR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Livorno (LI)",
          "emoji": true
         },
         "value": "LI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lucca (LU)",
          "emoji": true
         },
         "value": "LU"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Massa-Carrara (MS)",
          "emoji": true
         },
         "value": "MS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pisa (PI)",
          "emoji": true
         },
         "value": "PI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pistoia (PT)",
          "emoji": true
         },
         "value": "PT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Prato (PO)",
          "emoji": true
         },
         "value": "PO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Siena (SI)",
          "emoji": true
         },
         "value": "SI"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Trentino-Alto Adige",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bolzano (BZ)",
          "emoji": true
         },
         "value": "BZ"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Trento (TN)",
          "emoji": true
         },
         "value": "TN"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Umbria",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Perugia (PG)",
          "emoji": true
         },
         "value": "PG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Terni (TR)",
          "emoji": true
         },
         "value": "TR"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Valle d'Aosta",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Aosta (AO)",
          "emoji": true
         },
         "value": "AO"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Veneto",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Belluno (BL)",
          "emoji": true
         },
         "value": "BL"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Padova (PD)",
          "emoji": true
         },
         "value": "PD"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Rovigo (RO)",
          "emoji": true
         },
         "value": "RO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Treviso (TV)",
          "emoji": true
         },
         "value": "TV"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Venezia (VE)",
          "emoji": true
         },
         "value": "VE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Verona (VR)",
          "emoji": true
         },
         "value": "VR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Vicenza (VI)",
          "emoji": true
         },
         "value": "VI"
        }
       ]
      }
     ]
    },
    "hint": {
     "type": "plain_text",
     "text": "🔍 Scrivi nel menu per cercare, es. \"Cun\" per Cuneo",
     "emoji": true
    }
   },
   {
    "type": "input",
    "block_id": "kinds_block",
    "label": {
     "type": "plain_text",
     "text": "🔔 Cosa vuoi ricevere",
     "emoji": true
    },
    "element": {
     "type": "checkboxes",
     "action_id": "kinds",
     "options": [
      {
       "text": {
        "type": "plain_text",
        "text": "⛔ Chiusure e ✅ aperture",
        "emoji": true
       },
       "value": "closures",
       "description": {
        "type": "plain_text",
        "text": "Strade, rampe e svincoli chiusi o aperti, nuove strade",
        "emoji": true
       }
      },
      {
       "text": {
        "type": "plain_text",
        "text": "🚦 Limiti di velocità permanenti",
        "emoji": true
       },
       "value": "speed",
       "description": {
        "type": "plain_text",
        "text": "Nuovi limiti definitivi sulle strade ANAS",
        "emoji": true
       }
      },
      {
       "text": {
        "type": "plain_text",
        "text": "🚧 Anche cantieri e restringimenti",
        "emoji": true
       },
       "value": "all",
       "description": {
        "type": "plain_text",
        "text": "Tutte le altre ordinanze delle tue zone: corsie ridotte, sensi unici, limit",
        "emoji": true
       }
      }
     ],
     "initial_options": [
      {
       "text": {
        "type": "plain_text",
        "text": "⛔ Chiusure e ✅ aperture",
        "emoji": true
       },
       "value": "closures",
       "description": {
        "type": "plain_text",
        "text": "Strade, rampe e svincoli chiusi o aperti, nuove strade",
        "emoji": true
       }
      },
      {
       "text": {
        "type": "plain_text",
        "text": "🚦 Limiti di velocità permanenti",
        "emoji": true
       },
       "value": "speed",
       "description": {
        "type": "plain_text",
        "text": "Nuovi limiti definitivi sulle strade ANAS",
        "emoji": true
       }
      }
     ]
    },
    "hint": {
     "type": "plain_text",
     "text": "🧪 Il filtro \"utili per Waze\" è in beta: può sbagliare.",
     "emoji": true
    }
   },
   {
    "type": "context",
    "elements": [
     {
      "type": "mrkdwn",
      "text": "🧪 Il filtro \"utili per Waze\" è in beta: legge il riepilogo di ANAS con regole, non è perfetto. Può perdere qualche ordinanza o mandarne qualcuna che non c'entra. Se noti un errore, segnalalo."
     }
    ]
   },
   {
    "type": "input",
    "block_id": "all_regions_block",
    "optional": true,
    "label": {
     "type": "plain_text",
     "text": "🚧 Zone per cantieri e restringimenti (se diverse da quelle sopra)",
     "emoji": true
    },
    "element": {
     "type": "multi_static_select",
     "action_id": "all_regions",
     "placeholder": {
      "type": "plain_text",
      "text": "Regioni per i cantieri (vuoto = le stesse di sopra)",
      "emoji": true
     },
     "options": [
      {
       "text": {
        "type": "plain_text",
        "text": "🛣️ Autostrade (tutta Italia)",
        "emoji": true
       },
       "value": "autostrade"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Abruzzo",
        "emoji": true
       },
       "value": "abruzzo"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Basilicata",
        "emoji": true
       },
       "value": "basilicata"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Calabria",
        "emoji": true
       },
       "value": "calabria"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Campania",
        "emoji": true
       },
       "value": "campania"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Emilia-Romagna",
        "emoji": true
       },
       "value": "emilia-romagna"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Friuli-Venezia Giulia",
        "emoji": true
       },
       "value": "friuli-venezia-giulia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Lazio",
        "emoji": true
       },
       "value": "lazio"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Liguria",
        "emoji": true
       },
       "value": "liguria"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Lombardia",
        "emoji": true
       },
       "value": "lombardia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Marche",
        "emoji": true
       },
       "value": "marche"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Molise",
        "emoji": true
       },
       "value": "molise"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Piemonte",
        "emoji": true
       },
       "value": "piemonte"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Puglia",
        "emoji": true
       },
       "value": "puglia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Sardegna",
        "emoji": true
       },
       "value": "sardegna"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Sicilia",
        "emoji": true
       },
       "value": "sicilia"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Toscana",
        "emoji": true
       },
       "value": "toscana"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Trentino-Alto Adige",
        "emoji": true
       },
       "value": "trentino-alto-adige"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Umbria",
        "emoji": true
       },
       "value": "umbria"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Valle d'Aosta",
        "emoji": true
       },
       "value": "valle-d-aosta"
      },
      {
       "text": {
        "type": "plain_text",
        "text": "Veneto",
        "emoji": true
       },
       "value": "veneto"
      }
     ]
    }
   },
   {
    "type": "input",
    "block_id": "all_provinces_block",
    "optional": true,
    "label": {
     "type": "plain_text",
     "text": "🚧 ...e province",
     "emoji": true
    },
    "element": {
     "type": "multi_static_select",
     "action_id": "all_provinces",
     "placeholder": {
      "type": "plain_text",
      "text": "Province per i cantieri (vuoto = le stesse di sopra)",
      "emoji": true
     },
     "option_groups": [
      {
       "label": {
        "type": "plain_text",
        "text": "Abruzzo",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Chieti (CH)",
          "emoji": true
         },
         "value": "CH"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "L'Aquila (AQ)",
          "emoji": true
         },
         "value": "AQ"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pescara (PE)",
          "emoji": true
         },
         "value": "PE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Teramo (TE)",
          "emoji": true
         },
         "value": "TE"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Basilicata",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Matera (MT)",
          "emoji": true
         },
         "value": "MT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Potenza (PZ)",
          "emoji": true
         },
         "value": "PZ"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Calabria",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Catanzaro (CZ)",
          "emoji": true
         },
         "value": "CZ"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Cosenza (CS)",
          "emoji": true
         },
         "value": "CS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Crotone (KR)",
          "emoji": true
         },
         "value": "KR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Reggio Calabria (RC)",
          "emoji": true
         },
         "value": "RC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Vibo Valentia (VV)",
          "emoji": true
         },
         "value": "VV"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Campania",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Avellino (AV)",
          "emoji": true
         },
         "value": "AV"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Benevento (BN)",
          "emoji": true
         },
         "value": "BN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Caserta (CE)",
          "emoji": true
         },
         "value": "CE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Napoli (NA)",
          "emoji": true
         },
         "value": "NA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Salerno (SA)",
          "emoji": true
         },
         "value": "SA"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Emilia-Romagna",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bologna (BO)",
          "emoji": true
         },
         "value": "BO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ferrara (FE)",
          "emoji": true
         },
         "value": "FE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Forlì-Cesena (FC)",
          "emoji": true
         },
         "value": "FC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Modena (MO)",
          "emoji": true
         },
         "value": "MO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Parma (PR)",
          "emoji": true
         },
         "value": "PR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Piacenza (PC)",
          "emoji": true
         },
         "value": "PC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ravenna (RA)",
          "emoji": true
         },
         "value": "RA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Reggio Emilia (RE)",
          "emoji": true
         },
         "value": "RE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Rimini (RN)",
          "emoji": true
         },
         "value": "RN"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Friuli-Venezia Giulia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Gorizia (GO)",
          "emoji": true
         },
         "value": "GO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pordenone (PN)",
          "emoji": true
         },
         "value": "PN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Trieste (TS)",
          "emoji": true
         },
         "value": "TS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Udine (UD)",
          "emoji": true
         },
         "value": "UD"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Lazio",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Frosinone (FR)",
          "emoji": true
         },
         "value": "FR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Latina (LT)",
          "emoji": true
         },
         "value": "LT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Rieti (RI)",
          "emoji": true
         },
         "value": "RI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Roma (RM)",
          "emoji": true
         },
         "value": "RM"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Viterbo (VT)",
          "emoji": true
         },
         "value": "VT"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Liguria",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Genova (GE)",
          "emoji": true
         },
         "value": "GE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Imperia (IM)",
          "emoji": true
         },
         "value": "IM"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "La Spezia (SP)",
          "emoji": true
         },
         "value": "SP"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Savona (SV)",
          "emoji": true
         },
         "value": "SV"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Lombardia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bergamo (BG)",
          "emoji": true
         },
         "value": "BG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Brescia (BS)",
          "emoji": true
         },
         "value": "BS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Como (CO)",
          "emoji": true
         },
         "value": "CO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Cremona (CR)",
          "emoji": true
         },
         "value": "CR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lecco (LC)",
          "emoji": true
         },
         "value": "LC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lodi (LO)",
          "emoji": true
         },
         "value": "LO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Mantova (MN)",
          "emoji": true
         },
         "value": "MN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Milano (MI)",
          "emoji": true
         },
         "value": "MI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Monza e della Brianza (MB)",
          "emoji": true
         },
         "value": "MB"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pavia (PV)",
          "emoji": true
         },
         "value": "PV"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Sondrio (SO)",
          "emoji": true
         },
         "value": "SO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Varese (VA)",
          "emoji": true
         },
         "value": "VA"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Marche",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Ancona (AN)",
          "emoji": true
         },
         "value": "AN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ascoli Piceno (AP)",
          "emoji": true
         },
         "value": "AP"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Fermo (FM)",
          "emoji": true
         },
         "value": "FM"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Macerata (MC)",
          "emoji": true
         },
         "value": "MC"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pesaro e Urbino (PU)",
          "emoji": true
         },
         "value": "PU"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Molise",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Campobasso (CB)",
          "emoji": true
         },
         "value": "CB"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Isernia (IS)",
          "emoji": true
         },
         "value": "IS"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Piemonte",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Alessandria (AL)",
          "emoji": true
         },
         "value": "AL"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Asti (AT)",
          "emoji": true
         },
         "value": "AT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Biella (BI)",
          "emoji": true
         },
         "value": "BI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Cuneo (CN)",
          "emoji": true
         },
         "value": "CN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Novara (NO)",
          "emoji": true
         },
         "value": "NO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Torino (TO)",
          "emoji": true
         },
         "value": "TO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Verbano-Cusio-Ossola (VB)",
          "emoji": true
         },
         "value": "VB"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Vercelli (VC)",
          "emoji": true
         },
         "value": "VC"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Puglia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bari (BA)",
          "emoji": true
         },
         "value": "BA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Barletta-Andria-Trani (BT)",
          "emoji": true
         },
         "value": "BT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Brindisi (BR)",
          "emoji": true
         },
         "value": "BR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Foggia (FG)",
          "emoji": true
         },
         "value": "FG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lecce (LE)",
          "emoji": true
         },
         "value": "LE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Taranto (TA)",
          "emoji": true
         },
         "value": "TA"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Sardegna",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Cagliari (CA)",
          "emoji": true
         },
         "value": "CA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Gallura Nord-Est Sardegna (OT)",
          "emoji": true
         },
         "value": "OT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Medio Campidano (VS)",
          "emoji": true
         },
         "value": "VS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Nuoro (NU)",
          "emoji": true
         },
         "value": "NU"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ogliastra (OG)",
          "emoji": true
         },
         "value": "OG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Oristano (OR)",
          "emoji": true
         },
         "value": "OR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Sassari (SS)",
          "emoji": true
         },
         "value": "SS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Sulcis Iglesiente (SU)",
          "emoji": true
         },
         "value": "SU"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Sicilia",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Agrigento (AG)",
          "emoji": true
         },
         "value": "AG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Caltanissetta (CL)",
          "emoji": true
         },
         "value": "CL"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Catania (CT)",
          "emoji": true
         },
         "value": "CT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Enna (EN)",
          "emoji": true
         },
         "value": "EN"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Messina (ME)",
          "emoji": true
         },
         "value": "ME"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Palermo (PA)",
          "emoji": true
         },
         "value": "PA"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Ragusa (RG)",
          "emoji": true
         },
         "value": "RG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Siracusa (SR)",
          "emoji": true
         },
         "value": "SR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Trapani (TP)",
          "emoji": true
         },
         "value": "TP"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Toscana",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Arezzo (AR)",
          "emoji": true
         },
         "value": "AR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Firenze (FI)",
          "emoji": true
         },
         "value": "FI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Grosseto (GR)",
          "emoji": true
         },
         "value": "GR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Livorno (LI)",
          "emoji": true
         },
         "value": "LI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Lucca (LU)",
          "emoji": true
         },
         "value": "LU"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Massa-Carrara (MS)",
          "emoji": true
         },
         "value": "MS"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pisa (PI)",
          "emoji": true
         },
         "value": "PI"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Pistoia (PT)",
          "emoji": true
         },
         "value": "PT"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Prato (PO)",
          "emoji": true
         },
         "value": "PO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Siena (SI)",
          "emoji": true
         },
         "value": "SI"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Trentino-Alto Adige",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Bolzano (BZ)",
          "emoji": true
         },
         "value": "BZ"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Trento (TN)",
          "emoji": true
         },
         "value": "TN"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Umbria",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Perugia (PG)",
          "emoji": true
         },
         "value": "PG"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Terni (TR)",
          "emoji": true
         },
         "value": "TR"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Valle d'Aosta",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Aosta (AO)",
          "emoji": true
         },
         "value": "AO"
        }
       ]
      },
      {
       "label": {
        "type": "plain_text",
        "text": "Veneto",
        "emoji": true
       },
       "options": [
        {
         "text": {
          "type": "plain_text",
          "text": "Belluno (BL)",
          "emoji": true
         },
         "value": "BL"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Padova (PD)",
          "emoji": true
         },
         "value": "PD"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Rovigo (RO)",
          "emoji": true
         },
         "value": "RO"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Treviso (TV)",
          "emoji": true
         },
         "value": "TV"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Venezia (VE)",
          "emoji": true
         },
         "value": "VE"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Verona (VR)",
          "emoji": true
         },
         "value": "VR"
        },
        {
         "text": {
          "type": "plain_text",
          "text": "Vicenza (VI)",
          "emoji": true
         },
         "value": "VI"
        }
       ]
      }
     ]
    },
    "hint": {
     "type": "plain_text",
     "text": "Es. chiusure di tutta Italia, ma cantieri solo della tua provincia. Vuoto =",
     "emoji": true
    }
   }
  ]
 },
 "regions": {
  "autostrade": "🛣️ Autostrade (tutta Italia)",
  "abruzzo": "Abruzzo",
  "basilicata": "Basilicata",
  "calabria": "Calabria",
  "campania": "Campania",
  "emilia-romagna": "Emilia-Romagna",
  "friuli-venezia-giulia": "Friuli-Venezia Giulia",
  "lazio": "Lazio",
  "liguria": "Liguria",
  "lombardia": "Lombardia",
  "marche": "Marche",
  "molise": "Molise",
  "piemonte": "Piemonte",
  "puglia": "Puglia",
  "sardegna": "Sardegna",
  "sicilia": "Sicilia",
  "toscana": "Toscana",
  "trentino-alto-adige": "Trentino-Alto Adige",
  "umbria": "Umbria",
  "valle-d-aosta": "Valle d'Aosta",
  "veneto": "Veneto"
 },
 "provinces": {
  "TO": {
   "name": "Torino",
   "region": "piemonte"
  },
  "VC": {
   "name": "Vercelli",
   "region": "piemonte"
  },
  "NO": {
   "name": "Novara",
   "region": "piemonte"
  },
  "CN": {
   "name": "Cuneo",
   "region": "piemonte"
  },
  "AT": {
   "name": "Asti",
   "region": "piemonte"
  },
  "AL": {
   "name": "Alessandria",
   "region": "piemonte"
  },
  "BI": {
   "name": "Biella",
   "region": "piemonte"
  },
  "VB": {
   "name": "Verbano-Cusio-Ossola",
   "region": "piemonte"
  },
  "AO": {
   "name": "Aosta",
   "region": "valle-d-aosta"
  },
  "VA": {
   "name": "Varese",
   "region": "lombardia"
  },
  "CO": {
   "name": "Como",
   "region": "lombardia"
  },
  "SO": {
   "name": "Sondrio",
   "region": "lombardia"
  },
  "MI": {
   "name": "Milano",
   "region": "lombardia"
  },
  "BG": {
   "name": "Bergamo",
   "region": "lombardia"
  },
  "BS": {
   "name": "Brescia",
   "region": "lombardia"
  },
  "PV": {
   "name": "Pavia",
   "region": "lombardia"
  },
  "CR": {
   "name": "Cremona",
   "region": "lombardia"
  },
  "MN": {
   "name": "Mantova",
   "region": "lombardia"
  },
  "LC": {
   "name": "Lecco",
   "region": "lombardia"
  },
  "LO": {
   "name": "Lodi",
   "region": "lombardia"
  },
  "MB": {
   "name": "Monza e della Brianza",
   "region": "lombardia"
  },
  "BZ": {
   "name": "Bolzano",
   "region": "trentino-alto-adige"
  },
  "TN": {
   "name": "Trento",
   "region": "trentino-alto-adige"
  },
  "VR": {
   "name": "Verona",
   "region": "veneto"
  },
  "VI": {
   "name": "Vicenza",
   "region": "veneto"
  },
  "BL": {
   "name": "Belluno",
   "region": "veneto"
  },
  "TV": {
   "name": "Treviso",
   "region": "veneto"
  },
  "VE": {
   "name": "Venezia",
   "region": "veneto"
  },
  "PD": {
   "name": "Padova",
   "region": "veneto"
  },
  "RO": {
   "name": "Rovigo",
   "region": "veneto"
  },
  "UD": {
   "name": "Udine",
   "region": "friuli-venezia-giulia"
  },
  "GO": {
   "name": "Gorizia",
   "region": "friuli-venezia-giulia"
  },
  "TS": {
   "name": "Trieste",
   "region": "friuli-venezia-giulia"
  },
  "PN": {
   "name": "Pordenone",
   "region": "friuli-venezia-giulia"
  },
  "IM": {
   "name": "Imperia",
   "region": "liguria"
  },
  "SV": {
   "name": "Savona",
   "region": "liguria"
  },
  "GE": {
   "name": "Genova",
   "region": "liguria"
  },
  "SP": {
   "name": "La Spezia",
   "region": "liguria"
  },
  "PC": {
   "name": "Piacenza",
   "region": "emilia-romagna"
  },
  "PR": {
   "name": "Parma",
   "region": "emilia-romagna"
  },
  "RE": {
   "name": "Reggio Emilia",
   "region": "emilia-romagna"
  },
  "MO": {
   "name": "Modena",
   "region": "emilia-romagna"
  },
  "BO": {
   "name": "Bologna",
   "region": "emilia-romagna"
  },
  "FE": {
   "name": "Ferrara",
   "region": "emilia-romagna"
  },
  "RA": {
   "name": "Ravenna",
   "region": "emilia-romagna"
  },
  "FC": {
   "name": "Forlì-Cesena",
   "region": "emilia-romagna"
  },
  "RN": {
   "name": "Rimini",
   "region": "emilia-romagna"
  },
  "MS": {
   "name": "Massa-Carrara",
   "region": "toscana"
  },
  "LU": {
   "name": "Lucca",
   "region": "toscana"
  },
  "PT": {
   "name": "Pistoia",
   "region": "toscana"
  },
  "FI": {
   "name": "Firenze",
   "region": "toscana"
  },
  "LI": {
   "name": "Livorno",
   "region": "toscana"
  },
  "PI": {
   "name": "Pisa",
   "region": "toscana"
  },
  "AR": {
   "name": "Arezzo",
   "region": "toscana"
  },
  "SI": {
   "name": "Siena",
   "region": "toscana"
  },
  "GR": {
   "name": "Grosseto",
   "region": "toscana"
  },
  "PO": {
   "name": "Prato",
   "region": "toscana"
  },
  "PG": {
   "name": "Perugia",
   "region": "umbria"
  },
  "TR": {
   "name": "Terni",
   "region": "umbria"
  },
  "PU": {
   "name": "Pesaro e Urbino",
   "region": "marche"
  },
  "AN": {
   "name": "Ancona",
   "region": "marche"
  },
  "MC": {
   "name": "Macerata",
   "region": "marche"
  },
  "AP": {
   "name": "Ascoli Piceno",
   "region": "marche"
  },
  "FM": {
   "name": "Fermo",
   "region": "marche"
  },
  "VT": {
   "name": "Viterbo",
   "region": "lazio"
  },
  "RI": {
   "name": "Rieti",
   "region": "lazio"
  },
  "RM": {
   "name": "Roma",
   "region": "lazio"
  },
  "LT": {
   "name": "Latina",
   "region": "lazio"
  },
  "FR": {
   "name": "Frosinone",
   "region": "lazio"
  },
  "AQ": {
   "name": "L'Aquila",
   "region": "abruzzo"
  },
  "TE": {
   "name": "Teramo",
   "region": "abruzzo"
  },
  "PE": {
   "name": "Pescara",
   "region": "abruzzo"
  },
  "CH": {
   "name": "Chieti",
   "region": "abruzzo"
  },
  "CB": {
   "name": "Campobasso",
   "region": "molise"
  },
  "IS": {
   "name": "Isernia",
   "region": "molise"
  },
  "CE": {
   "name": "Caserta",
   "region": "campania"
  },
  "BN": {
   "name": "Benevento",
   "region": "campania"
  },
  "NA": {
   "name": "Napoli",
   "region": "campania"
  },
  "AV": {
   "name": "Avellino",
   "region": "campania"
  },
  "SA": {
   "name": "Salerno",
   "region": "campania"
  },
  "FG": {
   "name": "Foggia",
   "region": "puglia"
  },
  "BA": {
   "name": "Bari",
   "region": "puglia"
  },
  "TA": {
   "name": "Taranto",
   "region": "puglia"
  },
  "BR": {
   "name": "Brindisi",
   "region": "puglia"
  },
  "LE": {
   "name": "Lecce",
   "region": "puglia"
  },
  "BT": {
   "name": "Barletta-Andria-Trani",
   "region": "puglia"
  },
  "PZ": {
   "name": "Potenza",
   "region": "basilicata"
  },
  "MT": {
   "name": "Matera",
   "region": "basilicata"
  },
  "CS": {
   "name": "Cosenza",
   "region": "calabria"
  },
  "CZ": {
   "name": "Catanzaro",
   "region": "calabria"
  },
  "RC": {
   "name": "Reggio Calabria",
   "region": "calabria"
  },
  "KR": {
   "name": "Crotone",
   "region": "calabria"
  },
  "VV": {
   "name": "Vibo Valentia",
   "region": "calabria"
  },
  "TP": {
   "name": "Trapani",
   "region": "sicilia"
  },
  "PA": {
   "name": "Palermo",
   "region": "sicilia"
  },
  "ME": {
   "name": "Messina",
   "region": "sicilia"
  },
  "AG": {
   "name": "Agrigento",
   "region": "sicilia"
  },
  "CL": {
   "name": "Caltanissetta",
   "region": "sicilia"
  },
  "EN": {
   "name": "Enna",
   "region": "sicilia"
  },
  "CT": {
   "name": "Catania",
   "region": "sicilia"
  },
  "RG": {
   "name": "Ragusa",
   "region": "sicilia"
  },
  "SR": {
   "name": "Siracusa",
   "region": "sicilia"
  },
  "SS": {
   "name": "Sassari",
   "region": "sardegna"
  },
  "NU": {
   "name": "Nuoro",
   "region": "sardegna"
  },
  "CA": {
   "name": "Cagliari",
   "region": "sardegna"
  },
  "OR": {
   "name": "Oristano",
   "region": "sardegna"
  },
  "OT": {
   "name": "Gallura Nord-Est Sardegna",
   "region": "sardegna"
  },
  "OG": {
   "name": "Ogliastra",
   "region": "sardegna"
  },
  "VS": {
   "name": "Medio Campidano",
   "region": "sardegna"
  },
  "SU": {
   "name": "Sulcis Iglesiente",
   "region": "sardegna"
  }
 }
};
