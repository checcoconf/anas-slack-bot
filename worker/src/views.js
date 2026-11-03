// Schermate Slack del Worker: modulo precompilato, lettura del modulo, scheda Home, conferma.
// Benvenuto e modulo "vuoto" arrivano da Python (generated.js): qui li adattiamo all'utente.

import G from "./generated.js";

const { ids } = G;
const [B_SCOPE, A_SCOPE] = ids.scope;
const [B_REGIONS, A_REGIONS] = ids.regions;
const [B_PROVINCES, A_PROVINCES] = ids.provinces;
const [B_KINDS, A_KINDS] = ids.kinds;

const txt = (s) => ({ type: "plain_text", text: s.slice(0, 75), emoji: true });

function element(modal, blockId) {
  return modal.blocks.find((b) => b.block_id === blockId).element;
}

function allOptions(el) {
  return el.options ?? el.option_groups.flatMap((g) => g.options);
}

function setInitial(el, values) {
  const chosen = allOptions(el).filter((o) => values.includes(o.value));
  if (chosen.length) el.initial_options = chosen;
  else delete el.initial_options;
}

/** Il modulo con le scelte attuali dell'utente già selezionate. */
export function preferencesModal(user) {
  const modal = structuredClone(G.modal);
  if (!user) return modal; // nuovo utente: il modulo esportato da Python ha già i default giusti
  setInitial(element(modal, B_SCOPE), user.allItaly ? ["all"] : []);
  setInitial(element(modal, B_REGIONS), user.regions);
  setInitial(element(modal, B_PROVINCES), user.provinces);
  const kinds = [];
  if (user.wantClosures) kinds.push(ids.kindClosures);
  if (user.wantSpeed) kinds.push(ids.kindSpeed);
  setInitial(element(modal, B_KINDS), kinds);
  return modal;
}

/** Legge il modulo inviato. Restituisce { prefs, errors } (errors vuoto se va tutto bene). */
export function parseModal(values) {
  const selected = (block, action) => (values?.[block]?.[action]?.selected_options ?? []).map((o) => o.value);
  const allItaly = selected(B_SCOPE, A_SCOPE).includes("all");
  const regions = selected(B_REGIONS, A_REGIONS).filter((r) => r in G.regions);
  const provinces = selected(B_PROVINCES, A_PROVINCES).filter((p) => p in G.provinces);
  const kinds = selected(B_KINDS, A_KINDS);
  const errors = {};
  if (!allItaly && !regions.length && !provinces.length) {
    errors[B_REGIONS] = "⚠️ Scegli almeno una regione o una provincia, oppure spunta Tutta Italia.";
  }
  if (!kinds.length) errors[B_KINDS] = "⚠️ Scegli almeno un tipo di avviso.";
  return {
    prefs: {
      allItaly,
      regions,
      provinces,
      wantClosures: kinds.includes(ids.kindClosures),
      wantSpeed: kinds.includes(ids.kindSpeed),
    },
    errors,
  };
}

export function describeZones(u) {
  if (u.allItaly) return "🇮🇹 Tutta Italia";
  const parts = [];
  if (u.regions.length) parts.push("🗺️ " + u.regions.map((r) => G.regions[r] ?? r).join(", "));
  if (u.provinces.length) {
    parts.push("📍 " + u.provinces.map((p) => `${G.provinces[p]?.name ?? p} (${p})`).join(", "));
  }
  return parts.join("\n") || "nessuna zona scelta";
}

export function describeKinds(u) {
  const k = [];
  if (u.wantClosures) k.push("⛔ chiusure e ✅ aperture");
  if (u.wantSpeed) k.push("🚦 limiti di velocità permanenti");
  return k.join(" · ") || "nessuno";
}

export function savedMessage(u) {
  return {
    text: "✅ Preferenze salvate.",
    blocks: [{ type: "section", text: { type: "mrkdwn", text: `✅ *Preferenze salvate!*\n\n${describeZones(u)}\n🔔 ${describeKinds(u)}` } }],
  };
}

export function homeView(u) {
  let status;
  if (!u || !u.configured) status = "⚪ Non hai ancora scelto le zone: per ora non ricevi avvisi.";
  else if (u.paused) status = "⏸️ *Avvisi in pausa.*";
  else if (!u.inChannel) status = "⚠️ Non sei più nel canale del bot: entra di nuovo per ricevere gli avvisi.";
  else status = "🟢 *Avvisi attivi.*";

  const blocks = [
    { type: "header", text: txt("🚧 Ordinanze ANAS per Waze") },
    { type: "section", text: { type: "mrkdwn", text: status } },
  ];
  if (u?.configured) {
    blocks.push({ type: "section", text: { type: "mrkdwn", text: `*Zone*\n${describeZones(u)}\n\n*Tipi di avviso*\n🔔 ${describeKinds(u)}` } });
  }
  const buttons = [{
    type: "button", style: "primary", action_id: ids.openPrefs,
    text: txt(u?.configured ? "✏️ Modifica zone" : "🗺️ Scegli le zone"),
  }];
  if (u?.configured) {
    buttons.push({
      type: "button", action_id: ids.pause, value: u.paused ? "resume" : "pause",
      text: txt(u.paused ? "▶️ Riattiva avvisi" : "⏸️ Metti in pausa"),
    });
  }
  blocks.push({ type: "actions", elements: buttons });
  blocks.push({ type: "context", elements: [{ type: "mrkdwn", text: "📄 Fonte: ordinanze pubblicate da ANAS S.p.A. Controlla sempre il PDF prima di modificare la mappa." }] });
  return { type: "home", blocks };
}

export const welcomeMessage = () => structuredClone(G.welcome);

// --- Comandi /anas ----------------------------------------------------------

const CMD = G.command;

/** Messaggio effimero (lo vede solo chi scrive il comando) con la lista dei comandi. */
export function helpMessage() {
  return {
    response_type: "ephemeral",
    blocks: [{
      type: "section",
      text: {
        type: "mrkdwn",
        text:
          "🚧 *Ordinanze ANAS per Waze* — comandi:\n" +
          `• \`${CMD}\` — scegli o modifica le tue zone e i tipi di avviso\n` +
          `• \`${CMD} stato\` — mostra le tue impostazioni\n` +
          `• \`${CMD} pausa\` — metti in pausa gli avvisi\n` +
          `• \`${CMD} riprendi\` — riattiva gli avvisi\n` +
          `• \`${CMD} aiuto\` — mostra questo messaggio\n\n` +
          "Puoi fare tutto anche dalla scheda *Home* dell'app.",
      },
    }],
  };
}

/** Messaggio effimero con le impostazioni attuali dell'utente. */
export function statusMessage(u) {
  let stato;
  if (!u || !u.configured) stato = `⚪ Non hai ancora scelto le zone — usa \`${CMD}\` per iniziare.`;
  else if (u.paused) stato = `⏸️ *Avvisi in pausa* — \`${CMD} riprendi\` per riattivarli.`;
  else if (!u.inChannel) stato = "⚠️ Non sei nel canale del bot: rientra per ricevere gli avvisi.";
  else stato = "🟢 *Avvisi attivi.*";
  const blocks = [{ type: "section", text: { type: "mrkdwn", text: stato } }];
  if (u && u.configured) {
    blocks.push({
      type: "section",
      text: { type: "mrkdwn", text: `*Zone*\n${describeZones(u)}\n\n*Tipi di avviso*\n🔔 ${describeKinds(u)}` },
    });
  }
  return { response_type: "ephemeral", blocks };
}

/** Breve messaggio effimero di testo. */
export const ephemeral = (text) => ({ response_type: "ephemeral", text });
