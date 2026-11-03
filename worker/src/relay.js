// Ponte verso il sito ANAS per il job su GitHub Actions.
//
// Il sito ANAS non accetta collegamenti dai server di GitHub (negli Stati Uniti): la connessione
// scade senza risposta. Il Worker invece gira vicino all'Italia (vedi "placement" in wrangler.jsonc),
// quindi il job chiede a lui di leggere le pagine ANAS:
//
//   job (GitHub)  --POST /anas-relay/it/...-->  Worker (Milano)  --->  www.stradeanas.it/it/...
//
// Solo il job può usarlo: ogni richiesta è firmata con il token Slack del bot, che conoscono solo
// il job e il Worker. Il ponte inoltra soltanto verso www.stradeanas.it, nient'altro.

export const RELAY_PREFIX = "/anas-relay";
const TARGET = "https://www.stradeanas.it";
const FORWARDED = ["user-agent", "accept", "accept-language", "cookie", "content-type",
  "x-requested-with", "origin", "referer", "x-waze-bot-key"];
const enc = new TextEncoder();

async function hmacHex(key, message) {
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", k, enc.encode(message));
  return [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Firma usata dal job: HMAC-SHA256(token, "timestamp:METODO:/percorso?query"). */
export async function relaySignature(key, ts, method, pathAndQuery) {
  return hmacHex(key, `${ts}:${method}:${pathAndQuery}`);
}

export async function handleRelay(request, env, nowSeconds = Date.now() / 1000) {
  const url = new URL(request.url);
  const target = url.pathname.slice(RELAY_PREFIX.length) + url.search;
  if (!target.startsWith("/") || !["GET", "POST"].includes(request.method)) {
    return new Response("Richiesta non valida", { status: 400 });
  }
  const ts = request.headers.get("x-relay-ts") || "";
  const sig = request.headers.get("x-relay-sig") || "";
  const key = env.SLACK_BOT_TOKEN || "";
  if (!key || !ts || Math.abs(nowSeconds - Number(ts)) > 300
      || sig !== (await relaySignature(key, ts, request.method, target))) {
    return new Response("Firma non valida", { status: 401 });
  }

  const headers = new Headers();
  for (const name of FORWARDED) {
    const v = request.headers.get(name);
    if (v) headers.set(name, v);
  }
  let upstream;
  try {
    upstream = await fetch(TARGET + target, {
      method: request.method,
      headers,
      body: request.method === "POST" ? await request.arrayBuffer() : undefined,
      redirect: "follow",
    });
  } catch (err) {
    // 502: il job lo tratta come errore temporaneo e riprova al giro dopo
    return new Response(`ANAS non raggiungibile dal Worker: ${err}`, { status: 502 });
  }
  const out = new Response(upstream.body, { status: upstream.status, headers: upstream.headers });
  out.headers.set("x-relay-colo", request.cf?.colo || "?");
  return out;
}
