// Test del Worker: richieste Slack firmate, database D1 finto, chiamate esterne registrate.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import worker, { dispatchWorkflow } from "../src/index.js";
import { verifySlackRequest } from "../src/slack.js";
import { getUser } from "../src/db.js";
import G from "../src/generated.js";
import { D1Mock } from "./d1-mock.js";

const SECRET = "segreto-di-prova";
let env, calls, pending;

beforeEach(() => {
  env = {
    DB: new D1Mock(),
    SLACK_BOT_TOKEN: "xoxb-test",
    SLACK_SIGNING_SECRET: SECRET,
    SLACK_CHANNEL_IDS: "C1",
    GITHUB_REPO: "utente/repo",
    GITHUB_WORKFLOW: "anas.yml",
    GITHUB_TOKEN: "ghp_test",
  };
  calls = [];
  pending = [];
  globalThis.fetch = async (url, init) => {
    const body = init?.body ? JSON.parse(init.body) : null;
    calls.push({ url, body, headers: init?.headers });
    if (url.startsWith("https://api.github.com/")) return new Response(null, { status: 204 });
    const method = url.split("/api/")[1];
    const data = { ok: true };
    if (method === "users.info") data.user = { id: body.user, is_bot: body.user.startsWith("B") };
    if (method === "conversations.open") data.channel = { id: `D-${body.users}` };
    return Response.json(data);
  };
});

const ctx = { waitUntil: (p) => pending.push(p) };
const settle = () => Promise.all(pending.splice(0));
const slackCalls = (m) => calls.filter((c) => c.url === `https://slack.com/api/${m}`);

async function sign(body, ts = Math.floor(Date.now() / 1000)) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`v0:${ts}:${body}`));
  const hex = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return { "x-slack-request-timestamp": String(ts), "x-slack-signature": `v0=${hex}` };
}

async function post(path, body, { form = false, headers = {} } = {}) {
  const raw = form ? new URLSearchParams(body).toString() : JSON.stringify(body);
  const req = new Request(`https://bot.example.workers.dev${path}`, {
    method: "POST", body: raw, headers: { ...(await sign(raw)), ...headers },
  });
  const res = await worker.fetch(req, env, ctx);
  await settle();
  return res;
}

const event = (ev) => post("/slack/events", { type: "event_callback", event: ev });
const interact = (payload) => post("/slack/interactivity", { payload: JSON.stringify(payload) }, { form: true });
const sel = (...v) => ({ selected_options: v.map((value) => ({ value })) });

function submit(userId, { scope = [], regions = [], provinces = [], kinds = ["closures"], allRegions = [], allProvinces = [] }) {
  const [bS, aS] = G.ids.scope, [bR, aR] = G.ids.regions, [bP, aP] = G.ids.provinces, [bK, aK] = G.ids.kinds;
  const [bAR, aAR] = G.ids.allRegions, [bAP, aAP] = G.ids.allProvinces;
  return interact({
    type: "view_submission", user: { id: userId },
    view: { callback_id: G.ids.modalCallback, state: { values: {
      [bS]: { [aS]: sel(...scope) }, [bR]: { [aR]: sel(...regions) },
      [bP]: { [aP]: sel(...provinces) }, [bK]: { [aK]: sel(...kinds) },
      [bAR]: { [aAR]: sel(...allRegions) }, [bAP]: { [aAP]: sel(...allProvinces) },
    } } },
  });
}

test("cantieri con zone proprie: salvate solo se la voce è accesa, mostrate nella conferma", async () => {
  await submit("U7", { scope: ["all"], kinds: ["closures", "all"], allProvinces: ["TA"], allRegions: ["marte"] });
  let row = await env.DB.prepare("SELECT * FROM users WHERE user_id='U7'").first();
  assert.equal(row.want_all, 1);
  assert.equal(row.all_provinces, '["TA"]');
  assert.equal(row.all_regions, "[]");                                   // regione inesistente scartata
  assert.match(slackCalls("chat.postMessage").at(-1).body.blocks[0].text.text, /tutte le altre ordinanze \(zone: .*Taranto/);
  const modal = (await import("../src/views.js")).preferencesModal(await getUser(env.DB, "U7"));
  const apBlock = modal.blocks.find((b) => b.block_id === G.ids.allProvinces[0]);
  assert.deepEqual(apBlock.element.initial_options.map((o) => o.value), ["TA"]);   // riaperto: la provincia è preselezionata
  await submit("U7", { scope: ["all"], kinds: ["closures"], allProvinces: ["TA"] });
  row = await env.DB.prepare("SELECT * FROM users WHERE user_id='U7'").first();
  assert.equal(row.want_all, 0);
  assert.equal(row.all_provinces, "[]");                                 // voce spenta: zone dei cantieri ignorate
});

test("firma: valida, sbagliata, scaduta", async () => {
  const h = new Headers(await sign("ciao", 1000));
  assert.equal(await verifySlackRequest(h, "ciao", SECRET, 1000), true);
  assert.equal(await verifySlackRequest(h, "ciao!", SECRET, 1000), false);
  assert.equal(await verifySlackRequest(h, "ciao", SECRET, 1000 + 301), false);
  const res = await worker.fetch(new Request("https://x/slack/events", { method: "POST", body: "{}" }), env, ctx);
  assert.equal(res.status, 401);
});

test("verifica dell'URL da parte di Slack", async () => {
  const res = await post("/slack/events", { type: "url_verification", challenge: "abc" });
  assert.deepEqual(await res.json(), { challenge: "abc" });
});

test("ingresso nel canale: un solo benvenuto, niente ai bot e agli altri canali", async () => {
  await event({ type: "member_joined_channel", user: "U1", channel: "C1" });
  await event({ type: "member_joined_channel", user: "U1", channel: "C1" });
  await event({ type: "member_joined_channel", user: "BOT1", channel: "C1" });
  await event({ type: "member_joined_channel", user: "U2", channel: "C_ALTRO" });
  const posts = slackCalls("chat.postMessage");
  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.channel, "D-U1");
  assert.equal(posts[0].body.blocks[1].elements[0].action_id, G.ids.openPrefs);
  const row = await env.DB.prepare("SELECT in_channel, welcomed_at FROM users WHERE user_id='U1'").first();
  assert.equal(row.in_channel, 1);
  assert.ok(row.welcomed_at);
});

test("i tentativi ripetuti di Slack vengono ignorati", async () => {
  const res = await post("/slack/events", { type: "event_callback", event: { type: "member_joined_channel", user: "U1", channel: "C1" } },
    { headers: { "x-slack-retry-num": "1" } });
  assert.equal(res.status, 200);
  assert.equal(slackCalls("chat.postMessage").length, 0);
});

test("uscita dal canale", async () => {
  await event({ type: "member_joined_channel", user: "U1", channel: "C1" });
  await event({ type: "member_left_channel", user: "U1", channel: "C1" });
  const row = await env.DB.prepare("SELECT in_channel FROM users WHERE user_id='U1'").first();
  assert.equal(row.in_channel, 0);
});

test("modulo: errore se non si sceglie nessuna zona", async () => {
  const res = await submit("U1", {});
  const body = await res.json();
  assert.equal(body.response_action, "errors");
  assert.ok(body.errors[G.ids.regions[0]]);
});

test("modulo: salvataggio, scheda Home e conferma", async () => {
  const res = await submit("U1", { regions: ["abruzzo"], provinces: ["TO", "CN"], kinds: ["closures", "speed"] });
  assert.equal(res.status, 200);
  const row = await env.DB.prepare("SELECT * FROM users WHERE user_id='U1'").first();
  assert.equal(row.configured, 1);
  assert.equal(row.regions, '["abruzzo"]');
  assert.equal(row.provinces, '["CN","TO"]');
  assert.equal(row.want_speed, 1);
  const home = slackCalls("views.publish")[0].body.view;
  assert.match(JSON.stringify(home), /Avvisi attivi/);
  assert.match(JSON.stringify(home), /checcoconf/);  // la firma dell'autore resta in fondo alla Home
  assert.match(slackCalls("chat.postMessage")[0].body.blocks[0].text.text, /Cuneo \(CN\)/);
  await settle();
  const dispatched = calls.filter((c) => c.url.includes("/actions/workflows/"));
  assert.equal(dispatched.length, 1);                                    // parte il mini-job del riepilogo
  assert.match(dispatched[0].url, /riepilogo\.yml\/dispatches$/);
});

const command = (text, user = "U1") =>
  post("/slack/commands", { command: G.command, text, trigger_id: "T123", user_id: user }, { form: true });

test("/anas senza argomenti apre il modulo con le scelte già selezionate", async () => {
  await submit("U1", { regions: ["lazio"], provinces: ["OT"], kinds: ["speed"] });
  const res = await command("");
  assert.equal(res.status, 200);
  const view = slackCalls("views.open")[0].body.view;
  const el = (b) => view.blocks.find((x) => x.block_id === b).element;
  assert.deepEqual(el(G.ids.regions[0]).initial_options.map((o) => o.value), ["lazio"]);
  assert.deepEqual(el(G.ids.provinces[0]).initial_options.map((o) => o.value), ["OT"]);
  assert.deepEqual(el(G.ids.kinds[0]).initial_options.map((o) => o.value), ["speed"]);
  assert.equal(el(G.ids.scope[0]).initial_options, undefined);
});

test("/anas stato mostra zone e stato in un messaggio effimero", async () => {
  await submit("U1", { regions: ["lazio"] });
  const res = await command("stato");
  const body = await res.json();
  assert.equal(body.response_type, "ephemeral");
  assert.match(JSON.stringify(body.blocks), /Lazio/);
});

test("/anas pausa e /anas riprendi cambiano lo stato dell'utente", async () => {
  await submit("U1", { scope: ["all"] });
  const p = await (await command("pausa")).json();
  assert.match(p.text, /pausa/i);
  assert.equal((await getUser(env.DB, "U1")).paused, true);
  await command("riprendi");
  assert.equal((await getUser(env.DB, "U1")).paused, false);
});

test("/anas aiuto elenca i comandi; un sottocomando sconosciuto mostra l'aiuto", async () => {
  for (const text of ["aiuto", "booh"]) {
    const body = await (await command(text)).json();
    assert.equal(body.response_type, "ephemeral");
    assert.match(JSON.stringify(body.blocks), /stato.*pausa.*riprendi/s);
  }
});

test("pausa senza aver scelto le zone invita a configurare", async () => {
  const body = await (await command("pausa", "Unew")).json();
  assert.match(body.text, /scegli le zone/i);
});

test("pulsante pausa e pulsante PDF", async () => {
  await submit("U1", { scope: ["all"] });
  await interact({ type: "block_actions", user: { id: "U1" }, trigger_id: "t", actions: [{ action_id: G.ids.pause, value: "pause" }] });
  const row = await env.DB.prepare("SELECT paused FROM users WHERE user_id='U1'").first();
  assert.equal(row.paused, 1);
  assert.match(JSON.stringify(slackCalls("views.publish").at(-1).body.view), /Riattiva avvisi/);
  const res = await interact({ type: "block_actions", user: { id: "U1" }, actions: [{ action_id: "open_pdf_42" }] });
  assert.equal(res.status, 200);
});

test("scheda Messaggi aperta da un nuovo utente: benvenuto una volta sola, mai dopo la configurazione", async () => {
  await event({ type: "app_home_opened", user: "U9", tab: "messages" });
  await settle();
  assert.equal(slackCalls("chat.postMessage").length, 1);
  assert.match(slackCalls("chat.postMessage")[0].body.text, /Benvenuto|Scegli le zone/);
  await event({ type: "app_home_opened", user: "U9", tab: "messages" });
  await settle();
  assert.equal(slackCalls("chat.postMessage").length, 1);          // già salutato
  await event({ type: "app_home_opened", user: "B1", tab: "messages" });
  await settle();
  assert.equal(slackCalls("chat.postMessage").length, 1);          // un bot non si saluta
});

test("terza voce: tutte le altre ordinanze (want_all)", async () => {
  await submit("U7", { regions: ["sicilia"], kinds: ["closures", "all"] });
  const row = await env.DB.prepare("SELECT want_closures, want_speed, want_all FROM users WHERE user_id='U7'").first();
  assert.deepEqual([row.want_closures, row.want_speed, row.want_all], [1, 0, 1]);
  assert.match(slackCalls("chat.postMessage").at(-1).body.blocks[0].text.text, /tutte le altre ordinanze/);
  await submit("U7", { regions: ["sicilia"], kinds: ["closures"] });
  const row2 = await env.DB.prepare("SELECT want_all FROM users WHERE user_id='U7'").first();
  assert.equal(row2.want_all, 0);
});

test("l'orologio avvia il workflow di GitHub", async () => {
  assert.equal(await dispatchWorkflow(env), 204);
  const c = calls.at(-1);
  assert.equal(c.url, "https://api.github.com/repos/utente/repo/actions/workflows/anas.yml/dispatches");
  assert.deepEqual(c.body, { ref: "main" });
  assert.equal(c.headers.Authorization, "Bearer ghp_test");
});

test("l'orologio riprova una volta se GitHub non risponde, non per un errore nostro", async () => {
  const real = globalThis.fetch;
  let n = 0;
  globalThis.fetch = async (url, init) => {
    n++;
    if (n === 1) throw new TypeError("rete giù");
    return real(url, init);
  };
  const waits = [];
  assert.equal(await dispatchWorkflow(env, async (ms) => waits.push(ms)), 204);
  assert.equal(n, 2);
  assert.deepEqual(waits, [30_000]);
  n = 0;
  globalThis.fetch = async () => { n++; return new Response("Bad credentials", { status: 401 }); };
  assert.equal(await dispatchWorkflow(env, async () => {}), 401);
  assert.equal(n, 1);                                   // 4xx: riprovare non serve
});

test("health", async () => {
  const res = await worker.fetch(new Request("https://x/health"), env, ctx);
  assert.equal((await res.json()).ok, true);
});

// --- Ponte verso ANAS ---------------------------------------------------------

import { relaySignature } from "../src/relay.js";

async function relay(path, { method = "GET", key = "xoxb-test", body, ts = Math.floor(Date.now() / 1000) } = {}) {
  const sig = await relaySignature(key, String(ts), method, path);
  const req = new Request(`https://bot.example.workers.dev/anas-relay${path}`, {
    method, body, headers: { "x-relay-ts": String(ts), "x-relay-sig": sig, cookie: "cookiesession1=abc",
      "user-agent": "WazeItaliaAnasBot/1.0", "x-slack-signature": "da-non-inoltrare" },
  });
  return worker.fetch(req, env, ctx);
}

test("il ponte inoltra ad ANAS le richieste firmate dal job, con cookie e risposta", async () => {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response("%PDF-1.7", { status: 200, headers: { "set-cookie": "cookiesession1=xyz; Path=/" } });
  };
  const res = await relay("/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213628");
  assert.equal(res.status, 200);
  assert.equal(await res.text(), "%PDF-1.7");
  assert.match(res.headers.get("set-cookie"), /cookiesession1=xyz/);
  assert.equal(calls[0].url, "https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213628");
  assert.equal(calls[0].init.headers.get("cookie"), "cookiesession1=abc");
  assert.equal(calls[0].init.headers.get("x-slack-signature"), null);
});

test("il ponte inoltra anche la ricerca (POST con modulo)", async () => {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return Response.json({ esito: "ok", results: [] });
  };
  const res = await relay("/anas_ordinanzeweb/searchordinanze", { method: "POST", body: "action=search_ordinanze&page=1" });
  assert.equal(res.status, 200);
  assert.equal(new TextDecoder().decode(calls[0].init.body), "action=search_ordinanze&page=1");
});

test("il ponte rifiuta richieste non firmate, scadute o firmate con un'altra chiave", async () => {
  globalThis.fetch = async () => assert.fail("non deve contattare ANAS");
  assert.equal((await relay("/it/ordinanze-web", { key: "altra-chiave" })).status, 401);
  assert.equal((await relay("/it/ordinanze-web", { ts: Math.floor(Date.now() / 1000) - 3600 })).status, 401);
  const plain = new Request("https://bot.example.workers.dev/anas-relay/it/ordinanze-web");
  assert.equal((await worker.fetch(plain, env, ctx)).status, 401);
});

test("/health salva l'indirizzo del Worker per il job", async () => {
  const res = await worker.fetch(new Request("https://bot.example.workers.dev/health"), env, ctx);
  await settle();
  assert.equal(res.status, 200);
  const row = await env.DB.prepare("SELECT value FROM kv WHERE key='worker_url'").first();
  assert.equal(row.value, "https://bot.example.workers.dev");
});
