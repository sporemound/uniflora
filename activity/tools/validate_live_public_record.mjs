import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import { readFile } from "node:fs/promises";
import { build } from "esbuild";

const bundle = await build({ entryPoints: ["worker/preview.ts"], bundle: true,
  format: "esm", platform: "neutral", write: false });
const source = Buffer.from(bundle.outputFiles[0].contents).toString("base64");
const { default: previewWorker } = await import(`data:text/javascript;base64,${source}`);
const origin = "https://preview.example.com";
const secret = "preview-publication-test-secret-of-at-least-32-characters";
const archived = JSON.parse(await readFile("public/preview-live-state.json", "utf8"));
const tableNames = new Set([
  "current_public_state", "public_state_revisions", "hypha_request_nonces",
]);
const revisions = [];
const nonces = new Set();
let current = null;
const db = {
  prepare(sql) {
    const statement = { sql, args: [], bind(...args) { this.args = args; return this; },
      async all() {
        if (sql.includes("sqlite_master")) {
          return { results: this.args.filter((name) => tableNames.has(name)).map((name) => ({ name })) };
        }
        if (sql.includes("FROM public_state_revisions")) {
          const [, after, limit] = this.args;
          return { results: revisions.filter((row) => row.revision > after).slice(0, limit) };
        }
        throw new Error(`Unexpected all query: ${sql}`);
      },
      async first() {
        if (sql.includes("FROM current_public_state")) {
          return current ? { snapshot_json: current.snapshot_json } : null;
        }
        if (sql.includes("FROM public_state_revisions")) {
          const [, revision] = this.args;
          return revisions.find((row) => row.revision === revision) ?? null;
        }
        throw new Error(`Unexpected first query: ${sql}`);
      },
    };
    return statement;
  },
  async batch(statements) {
    assert.equal(statements.length, 3);
    const [nonce, revision, nextCurrent] = statements;
    assert.match(nonce.sql, /INSERT INTO hypha_request_nonces/u);
    assert.match(revision.sql, /INSERT INTO public_state_revisions/u);
    assert.match(nextCurrent.sql, /INSERT INTO current_public_state/u);
    if (nonces.has(nonce.args[0])) throw new Error("UNIQUE constraint failed: hypha_request_nonces.nonce");
    const [environment, number, hash, previousRevision, previousHash, snapshotJson, , publishedAt] = revision.args;
    assert.equal(environment, "live");
    if (number !== revisions.length + 1 ||
        (number === 1 ? previousRevision !== null || previousHash !== null
          : previousRevision !== number - 1 || previousHash !== revisions.at(-1).state_head_hash)) {
      throw new Error("FOREIGN KEY constraint failed");
    }
    nonces.add(nonce.args[0]);
    revisions.push({ revision: number, state_head_hash: hash,
      snapshot_json: snapshotJson, published_at: publishedAt });
    current = { snapshot_json: nextCurrent.args[4] };
    return [{ success: true }, { success: true }, { success: true }];
  },
};
const env = {
  ASSETS: { async fetch(request) {
    assert.equal(new URL(request.url).pathname, "/preview-live-state.json");
    return Response.json(archived);
  } },
  PUBLIC_DB: db,
  CHAT_DB: {},
  HYPHA_ACTIVITY_SECRET: secret,
};
function snapshot(revision, previousStateHeadHash = null) {
  return { ...archived, contentVersion: "2.1.0-static-roles", revision,
    previousStateHeadHash, stateHeadHash: revision.toString(16).padStart(64, "0"),
    updatedAt: `2026-10-08T23:35:0${revision}Z`, sequence: revision,
    positionId: "boundary_event", positionTitle: archived.positionTitle,
    recentObservations: [{ processId: archived.stochasticProcesses[0].id,
      actionId: "inspect_boundary_signal", channelId: "radio", outcomeId: `outcome-${revision}`,
      summary: `Observation ${revision}`, sequence: revision,
      observedState: null, measurements: [] }],
  };
}
let nextNonce = 1;
function signedRequest(value, nonce = (nextNonce++).toString(16).padStart(32, "0")) {
  const path = "/api/hypha/state";
  const body = JSON.stringify(value);
  const timestamp = String(Math.floor(Date.now() / 1000));
  const hash = createHash("sha256").update(body).digest("hex");
  const canonical = ["POST", path, timestamp, nonce, hash].join("\n");
  const signature = createHmac("sha256", secret).update(canonical).digest("hex");
  return new Request(`${origin}${path}`, { method: "POST", body,
    headers: { "Content-Type": "application/json", "X-Hypha-Timestamp": timestamp,
      "X-Hypha-Nonce": nonce, "X-Hypha-Content-SHA256": hash,
      "X-Hypha-Signature": `v1=${signature}` } });
}

const initial = await previewWorker.fetch(new Request(`${origin}/api/public-state?environment=live`), env);
assert.equal(initial.status, 404);
assert.equal((await initial.json()).error, "state_unavailable");
const emptyDb = { prepare() { return { bind() { return this; },
  async all() { return { results: [] }; } }; } };
const noSchemaRead = await previewWorker.fetch(new Request(`${origin}/api/public-state?environment=live`),
  { ...env, PUBLIC_DB: emptyDb });
assert.equal(noSchemaRead.status, 404, "missing D1 schema must not reveal the archived revision chain");
const captured = await previewWorker.fetch(new Request(`${origin}/api/preview-capture?environment=live`), env);
assert.equal(captured.status, 200);
assert.equal(captured.headers.get("X-Preview-Source"), "captured-public-projection");
assert.equal(captured.headers.get("Cache-Control"), "no-store");
assert.equal((await captured.json()).revision, archived.revision);
const empty = await previewWorker.fetch(new Request(`${origin}/api/public-record?environment=live`), env);
assert.deepEqual(await empty.json(), { environment: "live", entries: [], hasMore: false });
const unsigned = await previewWorker.fetch(new Request(`${origin}/api/hypha/state`, {
  method: "POST", body: JSON.stringify(snapshot(1)),
}), env);
assert.equal(unsigned.status, 401);
const oldPack = await previewWorker.fetch(signedRequest(archived), env);
assert.equal(oldPack.status, 403, "captured legacy state must not seed the new live chain");
const missingSchema = await previewWorker.fetch(signedRequest(snapshot(1)), {
  ...env, PUBLIC_DB: emptyDb,
});
assert.equal(missingSchema.status, 503);
const firstSnapshot = snapshot(1);
const first = await previewWorker.fetch(signedRequest(firstSnapshot, "a".repeat(32)), env);
assert.equal(first.status, 201);
assert.deepEqual(await first.json(), { ok: true, environment: "live", revision: 1,
  stateHeadHash: firstSnapshot.stateHeadHash });
const live = await previewWorker.fetch(new Request(`${origin}/api/public-state?environment=live`), env);
assert.equal(live.status, 200);
assert.equal(live.headers.get("X-Public-Source"), "live-projection");
assert.equal(live.headers.get("Cache-Control"), "no-store");
assert.deepEqual(await live.json(), firstSnapshot);
const replay = await previewWorker.fetch(signedRequest(firstSnapshot, "a".repeat(32)), env);
assert.equal(replay.status, 409);
assert.equal((await replay.json()).error, "replayed_request");
const secondSnapshot = snapshot(2, firstSnapshot.stateHeadHash);
const second = await previewWorker.fetch(signedRequest(secondSnapshot), env);
assert.equal(second.status, 201);
const page = await previewWorker.fetch(new Request(`${origin}/api/public-record?environment=live&limit=1`), env);
assert.deepEqual(await page.json(), { environment: "live", entries: [{
  revision: 1, updatedAt: firstSnapshot.updatedAt, sequence: 1,
  positionId: "boundary_event", positionTitle: archived.positionTitle,
  stateHeadHash: firstSnapshot.stateHeadHash, observationSummary: "Observation 1",
}], hasMore: true });
const next = await previewWorker.fetch(new Request(`${origin}/api/public-record?environment=live&after=1&limit=1`), env);
assert.equal((await next.json()).entries[0].revision, 2);
const detail = await previewWorker.fetch(new Request(`${origin}/api/public-record/1`), env);
assert.equal(detail.status, 200, "public revision detail must not require a session");
assert.equal(detail.headers.get("Cache-Control"), "no-store");
assert.equal(detail.headers.get("X-Public-Source"), "live-projection");
assert.deepEqual(await detail.json(), firstSnapshot,
  "revision detail must return the full validated public snapshot");
const detailHead = await previewWorker.fetch(new Request(`${origin}/api/public-record/2`,
  { method: "HEAD" }), env);
assert.equal(detailHead.status, 200);
assert.equal(detailHead.headers.get("X-Public-Source"), "live-projection");
assert.equal(await detailHead.text(), "");
const missingDetail = await previewWorker.fetch(new Request(`${origin}/api/public-record/3`), env);
assert.equal(missingDetail.status, 404);
assert.equal((await missingDetail.json()).error, "record_revision_unavailable");
assert.equal((await previewWorker.fetch(new Request(`${origin}/api/public-record/0`), env)).status, 400);
assert.equal((await previewWorker.fetch(new Request(`${origin}/api/public-record/1?environment=test`), env)).status, 400);
const missingDetailSchema = await previewWorker.fetch(new Request(`${origin}/api/public-record/1`),
  { ...env, PUBLIC_DB: emptyDb });
assert.equal(missingDetailSchema.status, 503);
const storedFirst = revisions[0].snapshot_json;
revisions[0].snapshot_json = JSON.stringify({ ...firstSnapshot, privatePlayerId: "not-public" });
const unsafeDetail = await previewWorker.fetch(new Request(`${origin}/api/public-record/1`), env);
assert.equal(unsafeDetail.status, 500, "stored snapshots with extra private fields must never be returned");
revisions[0].snapshot_json = storedFirst;
assert.equal((await previewWorker.fetch(new Request(`${origin}/api/public-record?environment=live&after=1e3`), env)).status, 400);
assert.equal((await previewWorker.fetch(new Request(`${origin}/api/public-record?environment=live&limit=101`), env)).status, 400);
assert.equal((await previewWorker.fetch(new Request(`${origin}/api/game/status`, { method: "POST" }), env)).status, 401);
assert.equal((await previewWorker.fetch(new Request(`${origin}/api/game/command`, { method: "POST",
  headers: { Authorization: "Bearer discord" } }), env)).status, 403);
assert.equal((await previewWorker.fetch(new Request(`${origin}/api/publications/latest?environment=live`), env)).status, 200);

for (const name of ["activity_sessions", "web_magic_links", "web_magic_link_cooldowns",
  "preview_magic_link_quota"]) tableNames.add(name);
const gameDb = { ...db, prepare(sql) {
  if (sql.includes("FROM activity_sessions")) return { bind() { return this; },
    async first() { return { participant_id: `participant_${"a".repeat(24)}`,
      display_name: "Investigator", expires_at: Math.floor(Date.now() / 1000) + 600 }; } };
  return db.prepare(sql);
} };
const gameEnv = { ...env, PUBLIC_DB: gameDb, APP_ORIGIN: origin,
  RESEND_API_KEY: "test-mail-key", MAGIC_LINK_FROM_EMAIL: "signin@example.com",
  ACTIVITY_IDENTITY_SECRET: "test-identity-secret-of-at-least-32-characters",
  GAME_API_ORIGIN: "https://game.example.com", GAME_API_SECRET: "game-api-test-secret-of-at-least-32-characters" };
const health = await previewWorker.fetch(new Request(`${origin}/api/health`), gameEnv);
assert.equal((await health.json()).gameActionsReady, true);
const originalFetch = globalThis.fetch;
let upstreamCalls = 0;
globalThis.fetch = async (url, options) => {
  upstreamCalls += 1;
  assert.equal(String(url), "https://game.example.com/internal/game/status");
  const body = JSON.parse(options.body);
  assert.deepEqual(body, { playerId: `web:participant_${"a".repeat(24)}`, environment: "live" });
  assert.match(options.headers["X-Game-Signature"], /^v1=[a-f0-9]{64}$/u);
  return Response.json({ accepted: true, projectionCurrent: true });
};
try {
  const signedIn = await previewWorker.fetch(new Request(`${origin}/api/game/status`, {
    method: "POST", headers: { Origin: origin, Cookie: `__Host-mi_session=${"b".repeat(64)}` },
  }), gameEnv);
  assert.equal(signedIn.status, 200);
  assert.deepEqual(await signedIn.json(), { accepted: true, projectionCurrent: true });
  assert.equal(upstreamCalls, 1);
} finally {
  globalThis.fetch = originalFetch;
}

console.log("Live public projection, signed publication, replay isolation, and revision feed checks passed.");
