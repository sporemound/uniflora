import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { RoomModel, LIMITS } from "./phase4b_reference_model.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const requiredSources = {
  "src/shared/investigation-room.ts": ["finding:create", "finding:update", "finding:delete", "finding:open"],
  "worker/lib/investigation-room.ts": ["DurableObjectState", "processedOperations", "finding_forbidden", "stale_revision"],
  "worker/lib/room-ticket.ts": ["signRoomTicket", "verifyRoomTicket", "constantTimeEqual"],
  "src/components/SharedFindingsPanel.tsx": ["Create finding", "Edit shared finding", "Delete"],
  "src/hooks/useInvestigationRoom.ts": ["requestRoomTicket", "reconnecting", "room:snapshot"],
};

const sourceChecks = [];
for (const [relative, needles] of Object.entries(requiredSources)) {
  const content = await readFile(path.join(root, relative), "utf8");
  for (const needle of needles) {
    assert.ok(content.includes(needle), `${relative} contains ${needle}`);
  }
  sourceChecks.push(relative);
}

const alice = { id: "participant_alice" };
const bob = { id: "participant_bob" };
const roomA = new RoomModel({
  roomId: "phase4-lab",
  artifactId: "artifact-phase3-sr03",
  visualizationId: "viz_9c555925e5bc6da2fb0def5b",
  bounds: [-2, 8],
});
const roomB = new RoomModel({
  roomId: "phase4-second-room",
  artifactId: "artifact-phase3-sr03",
  visualizationId: "viz_9c555925e5bc6da2fb0def5b",
  bounds: [-2, 8],
});

const create = {
  type: "finding:create",
  operationId: "op-create-0001",
  expectedRevision: 0,
  title: "Candidate discontinuity",
  observation: "A narrow timing break appears in the retained voltage record.",
  selection: {
    startSeconds: 1.25,
    endSeconds: 1.75,
    timeBasis: "Zulu",
    sourceView: "waveform",
  },
};
const created = roomA.mutate(alice, create);
assert.equal(created.type, "created");
assert.equal(created.finding.artifactId, "artifact-phase3-sr03");
assert.equal(created.finding.visualizationId, "viz_9c555925e5bc6da2fb0def5b");
assert.equal(roomA.findings.size, 1, "same-room client receives finding");
assert.equal(roomB.findings.size, 0, "different room remains isolated");

const replay = roomA.mutate(alice, create);
assert.deepEqual(replay, created, "operation replay returns canonical response");
assert.equal(roomA.findings.size, 1, "operation replay does not duplicate finding");
assert.equal(roomA.revision, 1, "operation replay does not increment revision");

assert.throws(
  () => roomA.mutate(bob, {
    type: "finding:update",
    operationId: "op-update-bob",
    expectedRevision: 1,
    findingId: created.finding.id,
    title: "Unauthorized edit",
    observation: "Should fail",
  }),
  /edit authorization/,
);

roomA.mutate(bob, {
  type: "presenter:claim",
  operationId: "op-presenter-bob",
  expectedRevision: 1,
});
const updated = roomA.mutate(bob, {
  type: "finding:update",
  operationId: "op-update-presenter",
  expectedRevision: 2,
  findingId: created.finding.id,
  title: "Presenter-confirmed discontinuity",
  observation: "The same interval remains visible after synchronized restoration.",
});
assert.equal(updated.type, "updated");
assert.equal(roomA.reconnectSnapshot().findings.length, 1, "reconnect restores finding");

assert.throws(
  () => new RoomModel({ roomId: "invalid", artifactId: "a", visualizationId: "v", bounds: [0, 1] }).mutate(alice, {
    ...create,
    operationId: "op-invalid-range",
    selection: { ...create.selection, startSeconds: -1, endSeconds: 2 },
  }),
  /range lower bound|range upper bound/,
);
assert.throws(
  () => new RoomModel({ roomId: "oversize", artifactId: "a", visualizationId: "v" }).mutate(alice, {
    ...create,
    operationId: "op-oversize",
    title: "x".repeat(LIMITS.title + 1),
  }),
  /title limit/,
);

const deleted = roomA.mutate(bob, {
  type: "finding:delete",
  operationId: "op-delete-presenter",
  expectedRevision: 3,
  findingId: created.finding.id,
});
assert.equal(deleted.type, "deleted");
assert.equal(roomA.findings.size, 0);
assert.equal(roomA.revision, 4, "room revision increments deterministically");

console.log(JSON.stringify({
  ok: true,
  phase: "4B",
  sourceChecks,
  scenarios: {
    sameRoomSynchronization: true,
    roomIsolation: true,
    operationReplayProtection: true,
    ownershipEnforcement: true,
    presenterOverride: true,
    reconnectPersistence: true,
    invalidRangeRejection: true,
    oversizedTextRejection: true,
    deterministicRevision: roomA.revision,
  },
}, null, 2));
