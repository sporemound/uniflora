import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { transformWithOxc } from "vite";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const readJson = async (path) => JSON.parse(await readFile(resolve(root, path), "utf8"));

const wrangler = await readJson("wrangler.jsonc");
const data = await readJson("examples/activity-data.json");
const spec = await readJson("examples/activity-visualization.json");
const roomSource = await readFile(
  resolve(root, "worker/lib/investigation-room.ts"),
  "utf8",
);
const clientSourcePath = resolve(root, "src/lib/investigation-room.ts");
const clientSource = await readFile(clientSourcePath, "utf8");
const hookSource = await readFile(
  resolve(root, "src/hooks/useInvestigationRoom.ts"),
  "utf8",
);
const workspaceSource = await readFile(
  resolve(root, "src/components/ScientificWorkspace.tsx"),
  "utf8",
);
const appSource = await readFile(resolve(root, "src/App.tsx"), "utf8");
const discordSource = await readFile(resolve(root, "src/lib/discord.ts"), "utf8");
const workerSource = await readFile(resolve(root, "worker/index.ts"), "utf8");
const authSource = await readFile(resolve(root, "worker/lib/auth.ts"), "utf8");
const bundledScienceSource = await readFile(
  resolve(root, "worker/lib/bundled-science.ts"),
  "utf8",
);
const clientScienceSource = await readFile(
  resolve(root, "src/lib/science.ts"),
  "utf8",
);
const migrationSource = await readFile(
  resolve(root, "migrations/0002_phase4_room_tickets.sql"),
  "utf8",
);
const instanceMigrationSource = await readFile(
  resolve(root, "migrations/0003_activity_instance_sessions.sql"),
  "utf8",
);
const bundledData = await readFile(
  resolve(root, "public/science/artifact-phase3-sr03/activity-data.json"),
);
const bundledVisualization = await readFile(
  resolve(root, "public/science/artifact-phase3-sr03/activity-visualization.json"),
);
const bundledPlate = await readFile(
  resolve(root, "public/science/artifact-phase3-sr03/scientific-plate.png"),
);
const bundledManifest = await readJson(
  "public/science/artifact-phase3-sr03/manifest-phase3b.json",
);

assert.equal(wrangler.durable_objects.bindings[0].name, "LIVE_ROOMS");
assert.equal(wrangler.durable_objects.bindings[0].class_name, "InvestigationRoom");
assert.equal(wrangler.exports.InvestigationRoom.type, "durable-object");
assert.equal(wrangler.exports.InvestigationRoom.storage, "sqlite");
assert.equal(wrangler.preview_urls, false);
assert.equal(wrangler.observability.enabled, false);
assert.equal(wrangler.r2_buckets, undefined);
assert.equal(wrangler.vars.SESSION_TTL_SECONDS, "900");
assert.equal(spec.visualizationId, data.visualizationId);
assert.equal(spec.artifactId, data.artifactId);
assert.ok(data.waveform.startSeconds < data.waveform.endSeconds);
assert.match(roomSource, /this\.state\.acceptWebSocket\(server/);
assert.match(roomSource, /setWebSocketAutoResponse/);
assert.match(roomSource, /server\.serializeAttachment\(attachment\)/);
assert.match(roomSource, /deserializeAttachment\(\)/);
assert.match(roomSource, /this\.state\.getWebSockets\(\)/);
assert.match(roomSource, /async webSocketMessage\(/);
assert.match(roomSource, /async webSocketClose\(/);
assert.match(roomSource, /MAX_WEBSOCKET_MESSAGE_BYTES = 64 \* 1024/);
assert.match(roomSource, /MAX_ROOM_STATE_BYTES = 512 \* 1024/);
assert.match(roomSource, /MAX_USED_TICKETS = 256/);
assert.match(roomSource, /MAX_SOCKET_AGE_MS = 15 \* 60 \* 1_000/);
assert.match(roomSource, /presenter_already_claimed/);
assert.match(roomSource, /private messageQueue: Promise<void>/);
assert.match(clientSource, /new WebSocket/);
assert.match(hookSource, /expectedRevision/);
assert.match(discordSource, /sdk\.instanceId/);
assert.match(discordSource, /JSON\.stringify\(\{ code, instanceId \}\)/);
assert.match(appSource, /discordInstanceId=\{discord\.instanceId\}/);
assert.match(workspaceSource, /discordInstanceId,/);
assert.match(hookSource, /currentRoomId\(options\.discordInstanceId\)/);
assert.match(workerSource, /ALLOW_TEST_GUESTS\?: string/);
assert.match(workerSource, /env\.ALLOW_TEST_GUESTS !== "true"/);
assert.match(workerSource, /!isLoopbackRequest\(request\)/);
assert.match(workerSource, /ACTIVITY_ALLOWED_TEST_CHANNEL_ID/);
assert.match(workerSource, /discord-instance:\$\{session\.instanceId\}/);
assert.match(workerSource, /enforceEdgeRate\(request, "session", 30\)/);
assert.match(workerSource, /enforceEdgeRate\(request, "logout", 10\)/);
assert.doesNotMatch(workerSource, /RATE_BUCKETS\.clear\(\)/);
assert.match(authSource, /activity-instances/);
assert.match(authSource, /input\.allowedChannelIds\.has\(value\.location\.channel_id\)/);
assert.match(authSource, /allowedUsers\.has\(user\.id\)/);
assert.match(instanceMigrationSource, /instance_id/);
assert.match(instanceMigrationSource, /guild_id/);
assert.match(instanceMigrationSource, /channel_id/);
assert.match(bundledScienceSource, /artifact-phase3-sr03/);
assert.equal(
  createHash("sha256").update(bundledData).digest("hex"),
  bundledManifest.files["activity-data.json"],
);
assert.equal(
  createHash("sha256").update(bundledVisualization).digest("hex"),
  bundledManifest.files["activity-visualization.json"],
);
const bundledPlateHash = createHash("sha256").update(bundledPlate).digest("hex");
assert.equal(bundledPlateHash, bundledManifest.files["scientific-plate.png"]);
assert.match(clientScienceSource, new RegExp(bundledPlateHash));
assert.match(migrationSource, /room_ticket_nonces/);

const roomHandlerStart = workerSource.indexOf("async function handleRoomTicket");
const roomHandlerEnd = workerSource.indexOf("\nfunction roomConnectRoute", roomHandlerStart);
const roomHandlerSource = workerSource.slice(roomHandlerStart, roomHandlerEnd);
assert.ok(roomHandlerStart >= 0 && roomHandlerEnd > roomHandlerStart);
assert.ok(
  roomHandlerSource.indexOf('env.ALLOW_TEST_GUESTS !== "true"') <
    roomHandlerSource.indexOf("validateActiveVisualization"),
  "unauthenticated guest access must be rejected before artifact reads",
);

const executableClientSource = clientSource.replace(
  'import { ROOM_ID_MAX_LENGTH } from "../shared/investigation-room";',
  "const ROOM_ID_MAX_LENGTH = 96;",
);
const clientJavaScript = (
  await transformWithOxc(executableClientSource, clientSourcePath)
).code;
const { currentRoomId, discordInstanceRoomId } = await import(
  `data:text/javascript;base64,${Buffer.from(clientJavaScript).toString("base64")}`
);
const originalWindow = globalThis.window;
try {
  globalThis.window = {
    location: { href: "http://127.0.0.1:5173/?room=explicit_lab" },
  };
  assert.equal(currentRoomId(null), "explicit_lab");
  assert.equal(
    currentRoomId("instance:unsafe/path"),
    "discord-instance-unsafe-path",
  );
  globalThis.window = {
    location: { href: "https://activity.example/" },
  };
  assert.equal(
    currentRoomId(" instance:unsafe/path "),
    "discord-instance-unsafe-path",
  );
  globalThis.window = {
    location: { href: "https://activity.example/?room=public_override" },
  };
  assert.equal(currentRoomId(null), null);
  assert.equal(discordInstanceRoomId("☃"), null);
  const boundedRoomId = discordInstanceRoomId("x".repeat(200));
  assert.equal(boundedRoomId.length, 96);
  assert.match(boundedRoomId, /^[A-Za-z0-9][A-Za-z0-9_-]*$/);
} finally {
  if (originalWindow === undefined) {
    delete globalThis.window;
  } else {
    globalThis.window = originalWindow;
  }
}

const initial = {
  startSeconds: data.waveform.startSeconds,
  endSeconds: data.waveform.endSeconds,
  revision: 0,
  presenterParticipantId: null,
};
const selected = {
  ...initial,
  startSeconds: -3.5,
  endSeconds: 3.5,
  revision: initial.revision + 1,
};
assert.ok(selected.startSeconds >= initial.startSeconds);
assert.ok(selected.endSeconds <= initial.endSeconds);
assert.ok(selected.endSeconds > selected.startSeconds);
assert.equal(selected.revision, 1);

console.log(
  JSON.stringify(
    {
      ok: true,
      phase: "4A",
      durableObjectClass: "InvestigationRoom",
      storage: "sqlite",
      hibernationWebSockets: true,
      discordInstanceRooms: true,
      discordInstanceAttestation: true,
      oneUseTickets: true,
      strictFreeStorage: true,
      artifactId: data.artifactId,
      visualizationId: data.visualizationId,
      simulatedSharedWindow: [selected.startSeconds, selected.endSeconds],
    },
    null,
    2,
  ),
);
