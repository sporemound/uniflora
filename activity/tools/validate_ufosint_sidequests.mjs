import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const migration = await readFile(
  path.join(root, "migrations/0004_ufosint_sidequests.sql"),
  "utf8",
);
const shared = await readFile(
  path.join(root, "src/shared/ufosint-sidequest.ts"),
  "utf8",
);
const repository = await readFile(
  path.join(root, "worker/lib/ufosint-sidequests.ts"),
  "utf8",
);
const api = await readFile(
  path.join(root, "worker/lib/ufosint-sidequest-api.ts"),
  "utf8",
);

for (const table of [
  "ufosint_sidequests",
  "ufosint_sidequest_events",
  "ufosint_sidequest_tasks",
  "ufosint_sidequest_finding_revisions",
  "ufosint_sidequest_reviews",
  "ufosint_sidequest_artifacts",
  "ufosint_sidequest_artifact_provenance",
]) {
  assert.match(migration, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}\\b`, "u"));
}

for (const lifecycle of ["open", "collecting", "review", "concluded", "archived"]) {
  assert.ok(shared.includes(`"${lifecycle}"`), `shared lifecycle includes ${lifecycle}`);
  assert.ok(migration.includes(`'${lifecycle}'`), `migration lifecycle includes ${lifecycle}`);
}
assert.ok(shared.includes('UFOSINT_SIDEQUEST_TEMPLATE_VERSION = "ufosint-sidequest-v1"'));
assert.ok(shared.includes("artifactContentBytes: 256_000"));
assert.ok(shared.includes("contentBase64: string"));
assert.ok(shared.includes("findingAggregateJsonBytes: 300_000"));
assert.ok(shared.includes("reviewAggregateJsonBytes: 150_000"));
assert.ok(shared.includes("artifactAggregateJsonBytes: 300_000"));
assert.ok(shared.includes("snapshotJsonBytes: 1_000_000"));
assert.ok(shared.includes("artifactAggregateContentBytes: 8_000_000"));
assert.ok(shared.includes('"unavailable"'));
assert.ok(shared.includes('"peer_review"'));
assert.match(migration, /template_version TEXT NOT NULL/u);
assert.match(migration, /'unavailable'/u);
assert.match(migration, /'peer_review'/u);

for (const exportedFunction of [
  "createUfosintSidequest",
  "getUfosintSidequest",
  "getUfosintSidequestArtifactContent",
  "listUfosintSidequests",
  "listUfosintSidequestEvents",
  "updateUfosintSidequestLifecycle",
  "updateUfosintSidequestTask",
  "addUfosintSidequestFinding",
  "addUfosintSidequestReview",
  "attachUfosintSidequestArtifact",
]) {
  assert.match(
    repository,
    new RegExp(`export async function ${exportedFunction}\\b`, "u"),
    `repository exports ${exportedFunction}`,
  );
}

assert.ok(shared.includes("UfosintDynamicalAnalysis"));
assert.ok(shared.includes("parentContentSha256"));
assert.ok(shared.includes("deriveUfosintFindingReviewState"));
assert.ok(repository.includes("stale_sidequest_revision"));
assert.ok(repository.includes("sidequest_operation_conflict"));
assert.ok(repository.includes("artifact_report_hash_mismatch"));
assert.ok(repository.includes("artifact_report_provenance_required"));
assert.ok(repository.includes("artifact_content_hash_mismatch"));
assert.ok(repository.includes("getUfosintSidequestArtifactContent"));
assert.ok(api.includes("/artifacts\\/([^/]+)\\/content"));
assert.ok(api.includes("private, max-age=31536000, immutable"));
assert.match(migration, /content_base64 TEXT NOT NULL/u);
assert.match(migration, /trg_ufosint_sidequest_task_definitions_no_update/u);
assert.match(migration, /trg_ufosint_sidequest_tasks_no_delete/u);
assert.match(migration, /UFOSINT finding revision limit exceeded/u);
assert.match(migration, /UFOSINT artifact content aggregate limit exceeded/u);

const db = new DatabaseSync(":memory:");
db.exec(migration);

const now = "2026-08-02T12:00:00.000Z";
const reportHash = "a".repeat(64);
const requestHash = "b".repeat(64);
const artifactContent = Buffer.from('{"evidence":"bounded and immutable"}', "utf8");
const artifactContentBase64 = artifactContent.toString("base64");
const artifactHash = createHash("sha256").update(artifactContent).digest("hex");

db.prepare(
  `INSERT INTO ufosint_sidequests (
    environment, sidequest_id, template_version, report_source_key, report_id,
    report_snapshot_json, report_snapshot_sha256, title, lifecycle,
    revision, opened_by_participant_id, opened_by_display_name,
    created_at, updated_at, concluded_at, archived_at
  ) VALUES ('test', 'sq-1', 'ufosint-sidequest-v1', 'ufosint', 'ufosint:618999', '{}', ?,
            'Investigate report', 'open', 0, 'participant-a', 'Alice',
            ?, ?, NULL, NULL)`,
).run(reportHash, now, now);

db.prepare(
  `INSERT INTO ufosint_sidequest_tasks (
    environment, sidequest_id, task_id, ordinal, task_kind, title,
    instructions, required, status, assigned_participant_id,
    assigned_display_name, completion_note, completed_at, updated_at
  ) VALUES ('test', 'sq-1', 'verify-provenance', 0, 'provenance',
            'Verify provenance', 'Trace the report source.', 1, 'pending',
            NULL, NULL, NULL, NULL, ?)`,
).run(now);

db.prepare(
  `INSERT INTO ufosint_sidequest_events (
    environment, sidequest_id, revision, operation_id, operation_type,
    request_sha256, actor_participant_id, actor_display_name,
    payload_json, created_at
  ) VALUES ('test', 'sq-1', 1, 'op-create', 'sidequest_created', ?,
            'participant-a', 'Alice', '{}', ?)`,
).run(requestHash, now);
db.prepare(
  `UPDATE ufosint_sidequests
   SET revision = 1, updated_at = ?
   WHERE environment = 'test' AND sidequest_id = 'sq-1' AND revision = 0`,
).run(now);

assert.equal(
  db.prepare(
    "SELECT revision FROM ufosint_sidequests WHERE environment = 'test' AND sidequest_id = 'sq-1'",
  ).get().revision,
  1,
);

assert.throws(
  () => db.prepare(
    `UPDATE ufosint_sidequest_tasks
     SET title = 'Changed plan'
     WHERE environment = 'test' AND sidequest_id = 'sq-1' AND task_id = 'verify-provenance'`,
  ).run(),
  /task definitions are immutable/u,
);

assert.throws(
  () => db.prepare(
    `DELETE FROM ufosint_sidequest_tasks
     WHERE environment = 'test' AND sidequest_id = 'sq-1' AND task_id = 'verify-provenance'`,
  ).run(),
  /task definitions are immutable/u,
);

assert.throws(
  () => db.prepare(
    `INSERT INTO ufosint_sidequest_tasks (
      environment, sidequest_id, task_id, ordinal, task_kind, title,
      instructions, required, status, assigned_participant_id,
      assigned_display_name, completion_note, completed_at, updated_at
    ) VALUES ('test', 'sq-1', 'late-task', 1, 'provenance',
              'Late task', 'Must not alter the frozen plan.', 1, 'pending',
              NULL, NULL, NULL, NULL, ?)`,
  ).run(now),
  /task definitions are immutable/u,
);

assert.throws(
  () => db.prepare(
    `UPDATE ufosint_sidequests SET report_snapshot_json = '{"changed":true}'
     WHERE environment = 'test' AND sidequest_id = 'sq-1'`,
  ).run(),
  /snapshot is immutable/u,
);

assert.throws(
  () => db.prepare(
    `UPDATE ufosint_sidequests SET template_version = 'ufosint-sidequest-v2'
     WHERE environment = 'test' AND sidequest_id = 'sq-1'`,
  ).run(),
  /snapshot is immutable/u,
);

assert.throws(
  () => db.prepare(
    `INSERT INTO ufosint_sidequest_events (
      environment, sidequest_id, revision, operation_id, operation_type,
      request_sha256, actor_participant_id, actor_display_name,
      payload_json, created_at
    ) VALUES ('test', 'sq-1', 3, 'op-skip', 'task_updated', ?,
              'participant-a', 'Alice', '{}', ?)`,
  ).run(requestHash, now),
  /revision conflict/u,
);

db.prepare(
  `INSERT INTO ufosint_sidequest_finding_revisions (
    environment, sidequest_id, finding_id, finding_revision,
    previous_revision, finding_kind, statement, confidence, finding_json,
    author_participant_id, author_display_name, created_at
  ) VALUES ('test', 'sq-1', 'finding-1', 1, NULL, 'observation',
            'The report records a bounded observation.', 'low', '{}',
            'participant-a', 'Alice', ?)`,
).run(now);

db.prepare(
  `INSERT INTO ufosint_sidequest_reviews (
    environment, sidequest_id, review_id, finding_id, finding_revision,
    reviewer_participant_id, reviewer_display_name, disposition,
    rationale, rubric_json, created_at
  ) VALUES ('test', 'sq-1', 'review-1', 'finding-1', 1,
            'participant-b', 'Bob', 'endorse',
            'The bounded statement follows the cited record.', '{}', ?)`,
).run(now);

assert.throws(
  () => db.prepare(
    `INSERT INTO ufosint_sidequest_reviews (
      environment, sidequest_id, review_id, finding_id, finding_revision,
      reviewer_participant_id, reviewer_display_name, disposition,
      rationale, rubric_json, created_at
    ) VALUES ('test', 'sq-1', 'review-missing', 'missing', 1,
              'participant-b', 'Bob', 'challenge', 'Missing finding.', '{}', ?)`,
  ).run(now),
  /FOREIGN KEY/u,
);

db.prepare(
  `INSERT INTO ufosint_sidequest_artifacts (
    environment, sidequest_id, artifact_id, artifact_kind, title, media_type,
    content_sha256, byte_length, content_base64, artifact_uri, artifact_json,
    created_by_participant_id, created_by_display_name, created_at
  ) VALUES ('test', 'sq-1', 'artifact-1', 'dynamical_analysis',
            'Trajectory envelope', 'application/json', ?, ?, ?, NULL, '{}',
            'participant-a', 'Alice', ?)`,
).run(artifactHash, artifactContent.byteLength, artifactContentBase64, now);

const storedContent = db.prepare(
  `SELECT content_base64, byte_length, content_sha256
   FROM ufosint_sidequest_artifacts
   WHERE environment = 'test' AND sidequest_id = 'sq-1' AND artifact_id = 'artifact-1'`,
).get();
assert.equal(storedContent.content_base64, artifactContentBase64);
assert.equal(storedContent.byte_length, artifactContent.byteLength);
assert.equal(
  createHash("sha256").update(Buffer.from(storedContent.content_base64, "base64")).digest("hex"),
  storedContent.content_sha256,
);

assert.throws(
  () => db.prepare(
    `INSERT INTO ufosint_sidequest_artifacts (
      environment, sidequest_id, artifact_id, artifact_kind, title, media_type,
      content_sha256, byte_length, content_base64, artifact_uri, artifact_json,
      created_by_participant_id, created_by_display_name, created_at
    ) VALUES ('test', 'sq-1', 'artifact-bad-length', 'source_capture',
              'Bad length', 'application/json', ?, 4, 'YQ==', NULL, '{}',
              'participant-a', 'Alice', ?)`,
  ).run(artifactHash, now),
  /CHECK constraint/u,
);

db.prepare(
  `INSERT INTO ufosint_sidequest_artifact_provenance (
    environment, sidequest_id, artifact_id, provenance_id, parent_type,
    parent_reference, parent_content_sha256, relation, description, retrieved_at
  ) VALUES ('test', 'sq-1', 'artifact-1', 'provenance-1',
            'report_snapshot', 'ufosint:618999', ?, 'derived_from',
            'Derived from the immutable report snapshot.', ?)`,
).run(reportHash, now);

assert.throws(
  () => db.prepare(
    `DELETE FROM ufosint_sidequest_artifacts
     WHERE environment = 'test' AND sidequest_id = 'sq-1' AND artifact_id = 'artifact-1'`,
  ).run(),
  /artifacts are immutable/u,
);

assert.throws(
  () => db.prepare(
    `UPDATE ufosint_sidequest_artifacts
     SET content_base64 = 'e30='
     WHERE environment = 'test' AND sidequest_id = 'sq-1' AND artifact_id = 'artifact-1'`,
  ).run(),
  /artifacts are immutable/u,
);

assert.equal(
  db.prepare(
    `SELECT COUNT(*) AS count
     FROM ufosint_sidequest_artifact_provenance
     WHERE environment = 'test' AND sidequest_id = 'sq-1'`,
  ).get().count,
  1,
);

const findingInsert = db.prepare(
  `INSERT INTO ufosint_sidequest_finding_revisions (
    environment, sidequest_id, finding_id, finding_revision,
    previous_revision, finding_kind, statement, confidence, finding_json,
    author_participant_id, author_display_name, created_at
  ) VALUES ('test', 'sq-1', ?, 1, NULL, 'observation',
            'Bounded finding.', 'low', '{}', 'participant-a', 'Alice', ?)`,
);
for (let index = 2; index <= 128; index += 1) {
  findingInsert.run(`finding-limit-${index}`, now);
}
assert.throws(
  () => findingInsert.run("finding-limit-129", now),
  /finding revision limit exceeded/u,
);

const reviewInsert = db.prepare(
  `INSERT INTO ufosint_sidequest_reviews (
    environment, sidequest_id, review_id, finding_id, finding_revision,
    reviewer_participant_id, reviewer_display_name, disposition,
    rationale, rubric_json, created_at
  ) VALUES ('test', 'sq-1', ?, 'finding-1', 1, ?, 'Reviewer', 'endorse',
            'Bounded review.', '{}', ?)`,
);
for (let index = 2; index <= 128; index += 1) {
  reviewInsert.run(`review-limit-${index}`, `participant-reviewer-${index}`, now);
}
assert.throws(
  () => reviewInsert.run("review-limit-129", "participant-reviewer-129", now),
  /review limit exceeded/u,
);

const oneByteHash = createHash("sha256").update("x").digest("hex");
const artifactInsert = db.prepare(
  `INSERT INTO ufosint_sidequest_artifacts (
    environment, sidequest_id, artifact_id, artifact_kind, title, media_type,
    content_sha256, byte_length, content_base64, artifact_uri, artifact_json,
    created_by_participant_id, created_by_display_name, created_at
  ) VALUES ('test', 'sq-1', ?, 'source_capture', 'Bounded artifact',
            'application/octet-stream', ?, 1, 'eA==', NULL, '{}',
            'participant-a', 'Alice', ?)`,
);
for (let index = 2; index <= 128; index += 1) {
  artifactInsert.run(`artifact-limit-${index}`, oneByteHash, now);
}
assert.throws(
  () => artifactInsert.run("artifact-limit-129", oneByteHash, now),
  /artifact limit exceeded/u,
);

db.prepare(
  `INSERT INTO ufosint_sidequests (
    environment, sidequest_id, template_version, report_source_key, report_id,
    report_snapshot_json, report_snapshot_sha256, title, lifecycle,
    revision, opened_by_participant_id, opened_by_display_name,
    created_at, updated_at, concluded_at, archived_at
  ) VALUES ('test', 'sq-aggregate', 'ufosint-sidequest-v1', 'ufosint', 'ufosint:619000',
            '{}', ?, 'Aggregate limit test', 'open', 0,
            'participant-a', 'Alice', ?, ?, NULL, NULL)`,
).run(reportHash, now, now);
const largeFindingJson = JSON.stringify({ padding: "x".repeat(249_900) });
const aggregateFindingInsert = db.prepare(
  `INSERT INTO ufosint_sidequest_finding_revisions (
    environment, sidequest_id, finding_id, finding_revision,
    previous_revision, finding_kind, statement, confidence, finding_json,
    author_participant_id, author_display_name, created_at
  ) VALUES ('test', 'sq-aggregate', ?, 1, NULL, 'observation',
            'Aggregate finding.', 'low', ?, 'participant-a', 'Alice', ?)`,
);
aggregateFindingInsert.run("aggregate-finding-1", largeFindingJson, now);
assert.throws(
  () => aggregateFindingInsert.run("aggregate-finding-2", largeFindingJson, now),
  /finding JSON aggregate limit exceeded/u,
);

console.log(JSON.stringify({
  ok: true,
  migration: "0004_ufosint_sidequests.sql",
  tables: 7,
  repositoryExports: 10,
  invariants: [
    "immutable_report_snapshot",
    "optimistic_revision_sequence",
    "immutable_task_plan",
    "bounded_aggregate_collections",
    "exact_finding_review_fk",
    "verified_immutable_artifact_content",
    "immutable_artifact_provenance",
  ],
}, null, 2));
