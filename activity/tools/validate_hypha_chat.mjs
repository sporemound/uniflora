import assert from "node:assert/strict";
import { createHash, createHmac, randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Miniflare } from "miniflare";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const channelId = "123456789012345678";
const liveChannelId = "987654321098765432";
const secret = "local-hypha-test-secret";
const mf = new Miniflare({
  modules: true,
  scriptPath: resolve(root, "dist/missing_interior_activity/index.js"),
  compatibilityDate: "2026-07-25",
  d1Databases: { PUBLIC_DB: "public-test", CHAT_DB: "shared-chat-test" },
  bindings: {
    V2_TEST_STREAM_ID: "stream-one",
    HYPHA_CHAT_ENABLED: "true",
    ACTIVITY_ALLOWED_TEST_CHANNEL_ID: channelId,
    ACTIVITY_ALLOWED_LIVE_CHANNEL_ID: liveChannelId,
    V2_LIVE_STREAM_ID: "stream-live",
    HYPHA_LIVE_CHAT_ENABLED: "true",
    HYPHA_ACTIVITY_SECRET: secret,
  },
});

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const tokens = ["a".repeat(64), "b".repeat(64), "c".repeat(64)];
const rawDiscordIds = ["111111111111111111", "222222222222222222", "444444444444444444"];

async function assertDisabledGate() {
  const disabled = new Miniflare({
    modules: true,
    scriptPath: resolve(root, "dist/missing_interior_activity/index.js"),
    compatibilityDate: "2026-07-25",
    d1Databases: { PUBLIC_DB: "public-disabled", CHAT_DB: "chat-disabled" },
    bindings: {
      V2_TEST_STREAM_ID: "stream-one",
      HYPHA_CHAT_ENABLED: "false",
      ACTIVITY_ALLOWED_TEST_CHANNEL_ID: channelId,
      HYPHA_ACTIVITY_SECRET: secret,
    },
  });
  try {
    const publicDb = await disabled.getD1Database("PUBLIC_DB");
    for (const filename of [
      "0001_phase2_public_sync.sql",
      "0002_phase4_room_tickets.sql",
      "0003_activity_instance_sessions.sql",
      "0005_activity_difficulty.sql",
    ]) {
      const migration = await readFile(resolve(root, "migrations", filename), "utf8");
      for (const statement of migration.split(";").map((part) => part.trim()).filter(Boolean)) {
        await publicDb.prepare(statement).run();
      }
    }
    const now = Math.floor(Date.now() / 1000);
    await publicDb.prepare(
      `INSERT INTO activity_sessions (session_hash, participant_id, display_name,
        discord_user_id, instance_id, guild_id, channel_id,
        issued_at, expires_at, last_seen_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(sha256(tokens[0]), "safe_participant", "Private Name",
      rawDiscordIds[0], "instance-test", "333333333333333333",
      channelId, now, now + 900, now).run();
    const response = await disabled.dispatchFetch("https://activity.example/api/hypha-chat", {
      headers: { Authorization: `Bearer ${tokens[0]}` },
    });
    assert.equal(response.status, 503);
  } finally {
    await disabled.dispose();
  }
}

async function request(path, { method = "GET", token, body, headers = {} } = {}) {
  return mf.dispatchFetch(`https://activity.example${path}`, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
}

function signedHeaders(path, body, nonce = randomBytes(16).toString("hex")) {
  const timestamp = String(Math.floor(Date.now() / 1000));
  const contentHash = sha256(body);
  const canonical = ["POST", path, timestamp, nonce, contentHash].join("\n");
  return {
    "Content-Type": "application/json",
    "X-Hypha-Timestamp": timestamp,
    "X-Hypha-Nonce": nonce,
    "X-Hypha-Content-SHA256": contentHash,
    "X-Hypha-Signature": `v1=${createHmac("sha256", secret).update(canonical).digest("hex")}`,
  };
}

async function signedPost(path, value, headers) {
  const body = JSON.stringify(value);
  return mf.dispatchFetch(`https://activity.example${path}`, {
    method: "POST",
    headers: headers ?? signedHeaders(path, body),
    body,
  });
}

try {
  const publicDb = await mf.getD1Database("PUBLIC_DB");
  const chatDb = await mf.getD1Database("CHAT_DB");
  for (const filename of [
    "0001_phase2_public_sync.sql",
    "0002_phase4_room_tickets.sql",
    "0003_activity_instance_sessions.sql",
    "0005_activity_difficulty.sql",
  ]) {
    const migration = await readFile(resolve(root, "migrations", filename), "utf8");
    for (const statement of migration.split(";").map((part) => part.trim()).filter(Boolean)) {
      await publicDb.prepare(statement).run();
    }
  }
  for (const filename of [
    "0001_hypha_chat_relay.sql",
    "0002_albuquerque_mode.sql",
  ]) {
    const chatMigration = await readFile(resolve(root,
      "chat-migrations", filename), "utf8");
    for (const statement of chatMigration.split(";").map((part) => part.trim()).filter(Boolean)) {
      await chatDb.prepare(statement).run();
    }
  }
  const now = Math.floor(Date.now() / 1000);
  for (let index = 0; index < 2; index += 1) {
    await publicDb.prepare(
      `INSERT INTO activity_sessions (session_hash, participant_id, display_name,
        discord_user_id, instance_id, guild_id, channel_id,
        issued_at, expires_at, last_seen_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(sha256(tokens[index]), `participant_safe_${index}`,
      `Private Name ${index}`, rawDiscordIds[index], "instance-test",
      "333333333333333333", channelId, now, now + 900, now).run();
  }
  await publicDb.prepare(
    `INSERT INTO activity_sessions (session_hash, participant_id, display_name,
      discord_user_id, instance_id, guild_id, channel_id,
      issued_at, expires_at, last_seen_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(sha256(tokens[2]), "participant_live", "Live Private Name",
    rawDiscordIds[2], "instance-live", "333333333333333333",
    liveChannelId, now, now + 900, now).run();

  assert.equal((await request("/api/my-difficulty")).status, 401);
  assert.deepEqual(await (await request("/api/my-difficulty", { token: tokens[2] })).json(),
    { environment: "live", level: "standard", revision: 0 });
  const syncPath = "/api/hypha/difficulty";
  assert.equal((await signedPost(syncPath, {
    environment: "live", choices: [{ discordUserId: rawDiscordIds[2], level: "guided", revision: 2 }],
  })).status, 200);
  assert.deepEqual(await (await request("/api/my-difficulty", { token: tokens[2] })).json(),
    { environment: "live", level: "guided", revision: 2 });
  assert.deepEqual(await (await request("/api/my-difficulty", { token: tokens[0] })).json(),
    { environment: "test", level: "standard", revision: 0 });
  assert.equal((await signedPost(syncPath, {
    environment: "live", choices: [{ discordUserId: rawDiscordIds[2], level: "expert", revision: 1 }],
  })).status, 200);
  assert.equal((await (await request("/api/my-difficulty", { token: tokens[2] })).json()).level,
    "guided");

  assert.equal((await request("/api/hypha-chat")).status, 401);
  await publicDb.prepare("UPDATE activity_sessions SET channel_id = ? WHERE session_hash = ?")
    .bind("999999999999999999", sha256(tokens[1])).run();
  assert.equal((await request("/api/hypha-chat", { token: tokens[1] })).status, 403);
  await publicDb.prepare("UPDATE activity_sessions SET channel_id = ? WHERE session_hash = ?")
    .bind(channelId, sha256(tokens[1])).run();
  assert.equal((await request("/api/hypha-chat", {
    method: "POST", token: tokens[0],
    body: { environment: "live", message: "Unsafe scope" },
  })).status, 403);
  assert.equal((await request("/api/hypha-chat", {
    method: "POST", token: tokens[2],
    body: { environment: "test", message: "Unsafe reverse scope" },
  })).status, 403);
  const liveCreated = await request("/api/hypha-chat", {
    method: "POST", token: tokens[2],
    body: { environment: "live", streamId: "stream-live", message: "Live question" },
  });
  assert.equal(liveCreated.status, 202);
  const liveFirst = await liveCreated.json();
  assert.equal((await (await request("/api/hypha-chat", { token: tokens[0] })).json()).messages.length, 0);
  const liveClaim = await signedPost("/api/hypha/chat/claim", {
    environment: "live", streamId: "stream-live",
  });
  assert.equal(liveClaim.status, 200);
  const liveWork = await liveClaim.json();
  assert.equal(liveWork.requestId, liveFirst.requestId);
  assert.equal(liveWork.albuquerqueMode, false);
  const liveCompletion = await signedPost(
    `/api/hypha/chat/${liveFirst.requestId}/complete`,
    { environment: "live", streamId: "stream-live", failed: true,
      transcriptText: "Live sealed-stone response unavailable." },
  );
  assert.equal(liveCompletion.status, 200);
  assert.equal((await (await request("/api/hypha-chat", { token: tokens[2] })).json()).messages.length, 2);
  const created = await request("/api/hypha-chat", {
    method: "POST", token: tokens[0],
    body: { environment: "test", streamId: "stream-one", message: "What is known?",
      workingName: "berrypunch" },
  });
  assert.equal(created.status, 202);
  const first = await created.json();
  assert.equal(first.messages.length, 2);
  assert.deepEqual(first.messages.map((item) => item.senderType), ["participant", "hypha"]);
  assert.equal(first.messages[1].status, "pending");
  assert.equal(first.messages[0].workingName, "berrypunch");

  const peer = await request("/api/hypha-chat", { token: tokens[1] });
  assert.equal(peer.status, 200);
  const peerBody = await peer.json();
  assert.equal(peerBody.messages.length, 2);
  assert.equal(peerBody.messages[0].text, "What is known?");
  assert.equal(peerBody.messages[1].status, "pending");
  const publicJson = JSON.stringify(peerBody);
  for (const raw of [...rawDiscordIds, "Private Name 0", "Private Name 1"]) {
    assert.equal(publicJson.includes(raw), false, `shared API leaked ${raw}`);
  }

  const wrongClaim = await signedPost("/api/hypha/chat/claim", {
    environment: "test", streamId: "another-stream",
  });
  assert.equal(wrongClaim.status, 403);
  const claimPath = "/api/hypha/chat/claim";
  const claimBody = { environment: "test", streamId: "stream-one" };
  const claimHeaders = signedHeaders(claimPath, JSON.stringify(claimBody));
  const claimed = await signedPost(claimPath, claimBody, claimHeaders);
  assert.equal(claimed.status, 200);
  const work = await claimed.json();
  assert.equal(work.requestId, first.requestId);
  assert.equal(work.discordUserId, rawDiscordIds[0]);
  assert.equal(work.albuquerqueMode, false);
  assert.equal((await signedPost(claimPath, claimBody, claimHeaders)).status, 409);
  const processing = await (await request("/api/hypha-chat", { token: tokens[1] })).json();
  assert.equal(processing.messages[1].status, "processing");

  const ogg = Buffer.from("OggSlocal-test-audio");
  const completePath = `/api/hypha/chat/${first.requestId}/complete`;
  const completion = {
    environment: "test", streamId: "stream-one", failed: false,
    transcriptText: "The common record remains open.",
    audioBase64: ogg.toString("base64"),
  };
  const completeHeaders = signedHeaders(completePath, JSON.stringify(completion));
  const completed = await signedPost(completePath, completion, completeHeaders);
  assert.equal(completed.status, 200);
  assert.equal((await signedPost(completePath, completion, completeHeaders)).status, 409);
  const history = await (await request("/api/hypha-chat", { token: tokens[1] })).json();
  assert.equal(history.messages[1].status, "complete");
  assert.equal(history.messages[1].text, completion.transcriptText);
  assert.equal(history.messages[1].audioUrl, `/api/hypha-chat/${first.hyphaMessageId}/audio`);
  const audio = await request(history.messages[1].audioUrl, { token: tokens[1] });
  assert.equal(audio.status, 200);
  assert.deepEqual(Buffer.from(await audio.arrayBuffer()), ogg);
  assert.equal((await request(history.messages[1].audioUrl)).status, 401);

  const second = await request("/api/hypha-chat", {
    method: "POST", token: tokens[1],
    body: { environment: "test", streamId: "stream-one",
      message: `And then, <@${rawDiscordIds[0]}>?` },
  });
  assert.equal(second.status, 202);
  const secondBody = await second.json();
  assert.equal(secondBody.messages[0].text, "And then, [participant]?");
  assert.equal(JSON.stringify(secondBody).includes(rawDiscordIds[0]), false);
  const secondClaim = await signedPost(claimPath, claimBody);
  assert.equal(secondClaim.status, 200);
  const secondWork = await secondClaim.json();
  assert.equal(secondWork.requestId, secondBody.requestId);
  assert.deepEqual(secondWork.history, [
    { senderType: "participant", text: "What is known?" },
    { senderType: "hypha", text: "The common record remains open." },
  ]);
  const secondCompletion = await signedPost(
    `/api/hypha/chat/${secondBody.requestId}/complete`,
    { environment: "test", streamId: "stream-one", failed: true,
      transcriptText: "Hypha could not render sealed-stone audio." },
  );
  assert.equal(secondCompletion.status, 200);
  const latest = await (await request("/api/hypha-chat?limit=2", { token: tokens[0] })).json();
  assert.equal(latest.messages.length, 2);
  assert.equal(latest.hasMore, true);
  assert.equal(latest.messages[1].status, "failed");
  assert.equal(latest.messages[1].audioUrl, null);
  const earlier = await (await request(
    `/api/hypha-chat?limit=2&before=${latest.messages[0].messageId}`,
    { token: tokens[0] },
  )).json();
  assert.deepEqual(earlier.messages.map((item) => item.messageId),
    history.messages.map((item) => item.messageId));
  assert.equal(earlier.hasMore, false);
  const later = await (await request(
    `/api/hypha-chat?limit=2&after=${history.messages[1].messageId}`,
    { token: tokens[0] },
  )).json();
  assert.deepEqual(later.messages.map((item) => item.messageId),
    latest.messages.map((item) => item.messageId));
  assert.equal((await request("/api/hypha-chat?limit=51", { token: tokens[0] })).status, 400);

  await chatDb.prepare(
    `INSERT INTO hypha_chat_messages (message_id, request_id, environment,
      stream_id, sender_type, content_text, delivery_status, created_at)
     VALUES ('foreign-message', 'foreign-request', 'test', 'stream-two',
      'hypha', 'Private to another stream', 'complete', ?)`,
  ).bind(now).run();
  assert.equal((await request(
    "/api/hypha-chat?before=foreign-message", { token: tokens[0] },
  )).status, 400);
  const isolated = await (await request("/api/hypha-chat", { token: tokens[0] })).text();
  assert.equal(isolated.includes("Private to another stream"), false);
  assert.equal((await request("/api/hypha-chat/foreign-message/audio", {
    token: tokens[0],
  })).status, 404);

  assert.equal((await request("/api/hypha-chat", {
    method: "POST", token: tokens[0],
    body: { message: "Hello", albuquerqueMode: "true" },
  })).status, 400);
  for (const [message, button, expected] of [
    ["What does this clock show?", true, true],
    ["Tell me about Albuquerque.", false, false],
    ["Please transform this reply in Albuquerque mode.", false, true],
    ["Turn off Albuquerque mode for this reply.", true, false],
  ]) {
    const created = await request("/api/hypha-chat", {
      method: "POST", token: tokens[0],
      body: { environment: "test", streamId: "stream-one", message,
        albuquerqueMode: button },
    });
    assert.equal(created.status, 202);
    const pending = await created.json();
    const claimed = await signedPost(claimPath, claimBody);
    assert.equal(claimed.status, 200);
    const job = await claimed.json();
    assert.equal(job.requestId, pending.requestId);
    assert.equal(job.albuquerqueMode, expected);
  }

  await assertDisabledGate();

  console.log("Shared Hypha chat Worker integration checks passed.");
} finally {
  await mf.dispose();
}
