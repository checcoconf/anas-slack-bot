// Accesso al database D1 (stesse tabelle usate dal job Python: anas_bot/schema.sql).

const now = () => Date.now() / 1000;

function toUser(row) {
  if (!row) return null;
  return {
    userId: row.user_id,
    inChannel: Boolean(row.in_channel),
    paused: Boolean(row.paused),
    configured: Boolean(row.configured),
    allItaly: Boolean(row.all_italy),
    regions: JSON.parse(row.regions || "[]"),
    provinces: JSON.parse(row.provinces || "[]"),
    wantClosures: Boolean(row.want_closures),
    wantSpeed: Boolean(row.want_speed),
    welcomedAt: row.welcomed_at,
  };
}

const UPSERT = "INSERT OR IGNORE INTO users(user_id, updated_at) VALUES(?, ?)";

export async function getUser(db, userId) {
  return toUser(await db.prepare("SELECT * FROM users WHERE user_id = ?").bind(userId).first());
}

export async function setInChannel(db, userId, value) {
  // db.batch() su D1 è una transazione: o entrambe le istruzioni o nessuna
  await db.batch([
    db.prepare(UPSERT).bind(userId, now()),
    db.prepare("UPDATE users SET in_channel = ?, updated_at = ? WHERE user_id = ?").bind(value ? 1 : 0, now(), userId),
  ]);
}

export async function markWelcomed(db, userId) {
  await db.prepare("UPDATE users SET welcomed_at = ? WHERE user_id = ?").bind(now(), userId).run();
}

export async function setPaused(db, userId, value) {
  await db.prepare("UPDATE users SET paused = ?, updated_at = ? WHERE user_id = ?").bind(value ? 1 : 0, now(), userId).run();
}

export async function savePreferences(db, userId, p) {
  await db.batch([
    db.prepare(UPSERT).bind(userId, now()),
    db.prepare(
      "UPDATE users SET configured = 1, paused = 0, all_italy = ?, regions = ?, provinces = ?, " +
        "want_closures = ?, want_speed = ?, updated_at = ? WHERE user_id = ?",
    ).bind(
      p.allItaly ? 1 : 0,
      JSON.stringify([...p.regions].sort()),
      JSON.stringify([...p.provinces].sort()),
      p.wantClosures ? 1 : 0,
      p.wantSpeed ? 1 : 0,
      now(),
      userId,
    ),
  ]);
}

export async function setKv(db, key, value) {
  await db.prepare("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    .bind(key, value).run();
}
