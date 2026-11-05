// Cloudflare Worker: la parte "sempre accesa" del bot.
//
//  POST /slack/events        eventi Slack: ingresso/uscita dal canale, apertura scheda Home
//  POST /slack/interactivity pulsanti e invio del modulo con i menu a tendina
//  POST /slack/commands      comando /anas (e sottocomandi: stato, pausa, riprendi, aiuto)
//  GET  /health              controllo veloce dopo il deploy
//  *    /anas-relay/...       ponte verso il sito ANAS per il job (vedi relay.js)
//  cron (una volta l'ora)    avvia il workflow di GitHub Actions che scarica le ordinanze
//
// Slack vuole una risposta entro 3 secondi: rispondiamo subito e il lavoro lento
// (chiamate a Slack) prosegue con ctx.waitUntil().

import G from "./generated.js";
import { getUser, markWelcomed, savePreferences, setInChannel, setKv, setPaused } from "./db.js";
import { isHuman, sendDm, slackApi, verifySlackRequest } from "./slack.js";
import { ephemeral, helpMessage, homeView, parseModal, preferencesModal, savedMessage, statusMessage, welcomeMessage } from "./views.js";
import { RELAY_PREFIX, handleRelay } from "./relay.js";

const ok = () => new Response(null, { status: 200 });
const channels = (env) => (env.SLACK_CHANNEL_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);

async function publishHome(env, userId) {
  await slackApi(env, "views.publish", { user_id: userId, view: homeView(await getUser(env.DB, userId)) });
}

async function openPreferences(env, triggerId, userId) {
  await slackApi(env, "views.open", { trigger_id: triggerId, view: preferencesModal(await getUser(env.DB, userId)) });
}

// --- Eventi -----------------------------------------------------------------

export async function onMemberJoined(env, userId, channel) {
  if (!channels(env).includes(channel)) return;
  if (!(await isHuman(env, userId))) return;
  await setInChannel(env.DB, userId, true);
  const user = await getUser(env.DB, userId);
  if (!user.welcomedAt && (await sendDm(env, userId, welcomeMessage()))) {
    await markWelcomed(env.DB, userId);
  }
}

async function welcomeIfNew(env, userId) {
  const user = await getUser(env.DB, userId);
  if (user?.welcomedAt || user?.configured) return;
  if (!(await isHuman(env, userId))) return;
  if (await sendDm(env, userId, welcomeMessage())) await markWelcomed(env.DB, userId);
}

async function handleEvent(env, event) {
  switch (event.type) {
    case "member_joined_channel":
      return onMemberJoined(env, event.user, event.channel);
    case "member_left_channel":
      // con più canali configurati, il controllo periodico del job ricorregge se serve
      if (channels(env).includes(event.channel)) await setInChannel(env.DB, event.user, false);
      return;
    case "app_home_opened":
      if (event.tab === "home") await publishHome(env, event.user);
      // Slack apre l'app sulla scheda Messaggi (vuota) per chi non ha mai ricevuto niente: il benvenuto
      // con il pulsante "Scegli le zone" arriva lì, una volta sola, senza bisogno di un canale
      else if (event.tab === "messages") await welcomeIfNew(env, event.user);
      return;
  }
}

// --- Pulsanti e modulo ------------------------------------------------------

async function handleBlockAction(env, payload) {
  const action = payload.actions?.[0];
  const userId = payload.user.id;
  if (!action) return;
  if (action.action_id === G.ids.openPrefs) {
    await openPreferences(env, payload.trigger_id, userId);
  } else if (action.action_id === G.ids.pause) {
    await setPaused(env.DB, userId, action.value === "pause");
    await publishHome(env, userId);
  }
  // open_pdf_*: il pulsante apre già il PDF nel browser, a Slack basta il 200
}

// Mini-job su GitHub che manda solo il riepilogo delle ordinanze in vigore (nessuna richiesta ad ANAS,
// fuori dalla coda del giro orario): parte appena l'utente salva le zone, arriva in 1-2 minuti.
export const DIGEST_WORKFLOW = "riepilogo.yml";

async function afterSave(env, userId) {
  await publishHome(env, userId);
  const user = await getUser(env.DB, userId);
  await sendDm(env, userId, savedMessage(user));
  if (!user.welcomedAt) await markWelcomed(env.DB, userId);
  await dispatchWorkflow(env, undefined, DIGEST_WORKFLOW);
}

// --- Comando /anas (con sottocomandi) ---------------------------------------

// sinonimi tolleranti: l'utente non deve ricordare la parola esatta
const SUB_PANEL = ["", "start", "inizia", "zone", "zona", "zones", "modifica", "cambia", "scegli"];
const SUB_STATUS = ["stato", "status", "info"];
const SUB_PAUSE = ["pausa", "pause", "stop", "ferma"];
const SUB_RESUME = ["riprendi", "riattiva", "resume", "on"];

async function handleCommand(env, ctx, form) {
  const userId = form.get("user_id");
  const sub = (form.get("text") || "").trim().toLowerCase().split(/\s+/)[0];

  if (SUB_PANEL.includes(sub)) {
    // il modulo si apre con il trigger_id, che vive pochi secondi: niente attesa prima di rispondere
    ctx.waitUntil(openPreferences(env, form.get("trigger_id"), userId));
    return ok();
  }
  if (SUB_STATUS.includes(sub)) {
    return Response.json(statusMessage(await getUser(env.DB, userId)));
  }
  if (SUB_PAUSE.includes(sub) || SUB_RESUME.includes(sub)) {
    const user = await getUser(env.DB, userId);
    if (!user || !user.configured) {
      return Response.json(ephemeral(`⚪ Prima scegli le zone con \`${G.command}\`.`));
    }
    const pause = SUB_PAUSE.includes(sub);
    await setPaused(env.DB, userId, pause);
    ctx.waitUntil(publishHome(env, userId));
    return Response.json(ephemeral(pause
      ? `⏸️ Avvisi in pausa. Riattivali con \`${G.command} riprendi\`.`
      : "▶️ Avvisi riattivati."));
  }
  return Response.json(helpMessage()); // sottocomando sconosciuto: mostro l'aiuto
}

// --- Orologio: avvia GitHub Actions ------------------------------------------

// Un avvio mancato è un'ora senza letture: se GitHub non risponde (rete o 5xx) si riprova una volta
// dopo una breve attesa. Gli errori 4xx (token, repo, ref sbagliati) non si riprovano: non cambiano da soli.
export async function dispatchWorkflow(env, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), workflow = env.GITHUB_WORKFLOW) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${workflow}/dispatches`;
  let status = 0;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "anas-slack-bot-worker",
        },
        body: JSON.stringify({ ref: env.GITHUB_REF || "main" }),
      });
      status = res.status;
      if (status === 204) return status;
      console.error(`Avvio workflow non riuscito (tentativo ${attempt}): HTTP ${status} ${await res.text()}`);
      if (status < 500) return status;
    } catch (err) {
      status = 0;
      console.error(`Avvio workflow non riuscito (tentativo ${attempt}): ${err}`);
    }
    if (attempt === 1) await sleep(30_000);
  }
  return status;
}

// --- Ingresso ---------------------------------------------------------------

export default {
  async fetch(request, env, ctx) {
    const { pathname, origin } = new URL(request.url);
    if (request.method === "GET" && pathname === "/health") {
      ctx.waitUntil(setKv(env.DB, "worker_url", origin)); // il job lo legge per usare il ponte ANAS
      return Response.json({ ok: true, version: G.version, colo: request.cf?.colo });
    }
    if (pathname.startsWith(RELAY_PREFIX + "/")) {
      return handleRelay(request, env);
    }
    if (request.method !== "POST" || !pathname.startsWith("/slack/")) {
      return new Response("Not found", { status: 404 });
    }

    const raw = await request.text();
    if (!(await verifySlackRequest(request.headers, raw, env.SLACK_SIGNING_SECRET))) {
      return new Response("Firma non valida", { status: 401 });
    }
    ctx.waitUntil(setKv(env.DB, "worker_url", origin)); // il job lo legge per usare il ponte ANAS
    // Slack ripete gli eventi se non risponde entro 3 s: i duplicati li ignoriamo
    if (request.headers.get("x-slack-retry-num")) return ok();

    if (pathname === "/slack/events") {
      const body = JSON.parse(raw);
      if (body.type === "url_verification") return Response.json({ challenge: body.challenge });
      if (body.type === "event_callback") ctx.waitUntil(handleEvent(env, body.event));
      return ok();
    }

    if (pathname === "/slack/interactivity") {
      const payload = JSON.parse(new URLSearchParams(raw).get("payload") || "{}");
      if (payload.type === "block_actions") {
        ctx.waitUntil(handleBlockAction(env, payload));
        return ok();
      }
      if (payload.type === "view_submission" && payload.view?.callback_id === G.ids.modalCallback) {
        const { prefs, errors } = parseModal(payload.view.state.values);
        if (Object.keys(errors).length) return Response.json({ response_action: "errors", errors });
        await savePreferences(env.DB, payload.user.id, prefs); // salvato PRIMA di chiudere il modulo
        ctx.waitUntil(afterSave(env, payload.user.id));
        return ok();
      }
      return ok();
    }

    if (pathname === "/slack/commands") {
      const form = new URLSearchParams(raw);
      if (form.get("command") !== G.command) return ok();
      return handleCommand(env, ctx, form);
    }

    return new Response("Not found", { status: 404 });
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatchWorkflow(env));
  },
};
