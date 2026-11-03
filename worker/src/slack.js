// Comunicazione con Slack: verifica della firma e chiamate alla Web API ufficiale.
// Nessuna libreria: sui Worker gli SDK ufficiali di Slack non girano, ma l'API è la stessa.

const enc = new TextEncoder();

function toHex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a, b) {
  // confronto a tempo costante: non rivela dopo quanti caratteri la firma è sbagliata
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/**
 * Controlla che la richiesta arrivi davvero da Slack.
 * Slack firma ogni richiesta con il "Signing Secret" dell'app (HMAC-SHA256 di "v0:timestamp:corpo").
 * Rifiuta anche richieste più vecchie di 5 minuti (protezione contro il riutilizzo).
 */
export async function verifySlackRequest(headers, rawBody, signingSecret, nowSeconds = Date.now() / 1000) {
  const ts = headers.get("x-slack-request-timestamp");
  const sig = headers.get("x-slack-signature");
  if (!ts || !sig || !signingSecret) return false;
  if (Math.abs(nowSeconds - Number(ts)) > 300) return false;
  const key = await crypto.subtle.importKey("raw", enc.encode(signingSecret), { name: "HMAC", hash: "SHA-256" },
    false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`v0:${ts}:${rawBody}`));
  return safeEqual(`v0=${toHex(mac)}`, sig);
}

/** Chiama un metodo della Web API di Slack (https://api.slack.com/methods). */
export async function slackApi(env, method, body) {
  const res = await fetch(`https://slack.com/api/${method}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.SLACK_BOT_TOKEN}`,
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ ok: false, error: `http_${res.status}` }));
  if (!data.ok) console.warn(`Slack ${method}: ${data.error}`); // niente ID utente nei log
  return data;
}

export async function isHuman(env, userId) {
  if (userId === "USLACKBOT") return false;
  const r = await slackApi(env, "users.info", { user: userId });
  return Boolean(r.ok && !r.user?.is_bot && !r.user?.deleted);
}

export async function sendDm(env, userId, message) {
  const open = await slackApi(env, "conversations.open", { users: userId });
  if (!open.ok) return false;
  const r = await slackApi(env, "chat.postMessage", { channel: open.channel.id, ...message });
  return Boolean(r.ok);
}
