import {
  UFOSINT_ARTIFACT_KINDS,
  UFOSINT_FINDING_CONFIDENCE,
  UFOSINT_FINDING_KINDS,
  UFOSINT_SIDEQUEST_LIFECYCLES,
  UFOSINT_SIDEQUEST_LIMITS,
  UFOSINT_SIDEQUEST_SCHEMA_VERSION,
  UFOSINT_SIDEQUEST_TASK_KINDS,
  assertBoundedJson,
  assertUfosintActor,
  assertUfosintIdentifier,
  assertUfosintTimestamp,
  canTransitionUfosintSidequest,
  canTransitionUfosintTask,
  isUfosintSidequestLifecycle,
  isUfosintSidequestTaskStatus,
  parseUfosintFindingRevision,
  parseUfosintReportSnapshot,
  parseUfosintSidequestArtifact,
  parseUfosintSidequestReview,
  parseUfosintTaskDefinitions,
  type AddUfosintSidequestFindingInput,
  type AddUfosintSidequestReviewInput,
  type AttachUfosintSidequestArtifactInput,
  type CreateUfosintSidequestInput,
  type UfosintActor,
  type UfosintArtifactKind,
  type UfosintSidequestArtifact,
  type UfosintSidequestEnvironment,
  type UfosintSidequestEvent,
  type UfosintSidequestFindingRevision,
  type UfosintSidequestLifecycle,
  type UfosintSidequestReview,
  type UfosintSidequestSnapshot,
  type UfosintSidequestSummary,
  type UfosintSidequestTask,
  type UfosintSidequestTaskKind,
  type UfosintSidequestTaskStatus,
  type UpdateUfosintSidequestLifecycleInput,
  type UpdateUfosintSidequestTaskInput,
} from "../../src/shared/ufosint-sidequest";
import type { D1Database, D1PreparedStatement } from "./cloudflare";
import { HttpError } from "./errors";

interface SidequestRow {
  environment: string;
  sidequest_id: string;
  template_version: string;
  report_id: string;
  report_snapshot_json: string;
  report_snapshot_sha256: string;
  title: string;
  lifecycle: string;
  revision: number;
  opened_by_participant_id: string;
  opened_by_display_name: string;
  created_at: string;
  updated_at: string;
  concluded_at: string | null;
  archived_at: string | null;
}

interface TaskRow {
  task_id: string;
  ordinal: number;
  task_kind: string;
  title: string;
  instructions: string;
  required: number;
  status: string;
  assigned_participant_id: string | null;
  assigned_display_name: string | null;
  completion_note: string | null;
  completed_at: string | null;
  updated_at: string;
}

interface FindingRow {
  finding_id: string;
  finding_revision: number;
  finding_json: string;
}

interface ReviewRow {
  review_id: string;
  review_json: string;
}

interface ArtifactRow {
  artifact_id: string;
  artifact_json: string;
}

interface EventRow {
  revision: number;
  operation_id: string;
  operation_type: UfosintSidequestEvent["operationType"];
  request_sha256: string;
  actor_participant_id: string;
  actor_display_name: string;
  created_at: string;
}

interface OperationRow {
  request_sha256: string;
  revision: number;
}

interface FindingAuthorRow {
  finding_json: string;
  latest_revision: number;
}

interface ArtifactHashRow {
  artifact_id: string;
  content_sha256: string;
}

interface ArtifactContentRow {
  artifact_id: string;
  media_type: string;
  content_sha256: string;
  byte_length: number;
  content_base64: string;
  created_at: string;
}

export interface UfosintSidequestArtifactContent {
  artifactId: string;
  mediaType: string;
  contentSha256: string;
  byteLength: number;
  bytes: Uint8Array;
  createdAt: string;
}

export interface ListUfosintSidequestsInput {
  environment: UfosintSidequestEnvironment;
  lifecycle?: UfosintSidequestLifecycle;
  reportId?: string;
  beforeUpdatedAt?: string;
  limit?: number;
}

export interface ListUfosintSidequestEventsInput {
  environment: UfosintSidequestEnvironment;
  sidequestId: string;
  afterRevision?: number;
  limit?: number;
}

const HEX = "0123456789abcdef";

function boundedText(value: unknown, maximum: number, label: string): string {
  if (typeof value !== "string") {
    throw new HttpError(400, "invalid_sidequest_input", `${label} must be text.`);
  }
  const normalized = value.replaceAll("\u0000", " ").trim().replace(/\s+/gu, " ");
  if (!normalized || normalized.length > maximum) {
    throw new HttpError(
      400,
      "invalid_sidequest_input",
      `${label} must contain between 1 and ${maximum} characters.`,
    );
  }
  return normalized;
}

function nullableText(value: unknown, maximum: number, label: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  return boundedText(value, maximum, label);
}

function environment(value: unknown): UfosintSidequestEnvironment {
  if (value !== "live" && value !== "test") {
    throw new HttpError(400, "invalid_environment", "Environment must be live or test.");
  }
  return value;
}

function expectedRevision(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new HttpError(
      400,
      "invalid_expected_revision",
      "Expected revision must be a nonnegative safe integer.",
    );
  }
  return Number(value);
}

function timestamp(value: unknown, label: string): string {
  try {
    return assertUfosintTimestamp(value, label);
  } catch (error) {
    throw new HttpError(
      400,
      "invalid_timestamp",
      error instanceof Error ? error.message : `${label} is invalid.`,
    );
  }
}

function operationTime(value: unknown): string {
  return timestamp(value ?? new Date().toISOString(), "operation time");
}

function parseStoredJson(value: string, label: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    throw new HttpError(500, "invalid_sidequest_storage", `${label} is not valid JSON.`);
  }
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (typeof value !== "object" || value === null) return value;
  const record = value as Record<string, unknown>;
  return Object.fromEntries(
    Object.keys(record)
      .filter((key) => record[key] !== undefined)
      .sort()
      .map((key) => [key, stableValue(record[key])]),
  );
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

async function sha256Hex(value: string | Uint8Array): Promise<string> {
  const source = typeof value === "string" ? new TextEncoder().encode(value) : value;
  const bytes = new Uint8Array(source.byteLength);
  bytes.set(source);
  const digest = await crypto.subtle.digest("SHA-256", bytes.buffer);
  return [...new Uint8Array(digest)]
    .map((byte) => `${HEX[byte >>> 4]}${HEX[byte & 15]}`)
    .join("");
}

const CANONICAL_BASE64 =
  /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u;

function encodeBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 32_768;
  for (let offset = 0; offset < bytes.byteLength; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function decodeCanonicalArtifactContent(value: unknown): Uint8Array {
  if (typeof value !== "string") {
    throw new HttpError(
      400,
      "invalid_artifact_content",
      "Artifact contentBase64 must be canonical Base64 text.",
    );
  }
  if (value.length > UFOSINT_SIDEQUEST_LIMITS.artifactContentBase64Length) {
    throw new HttpError(
      413,
      "artifact_content_too_large",
      `Artifact content exceeds ${UFOSINT_SIDEQUEST_LIMITS.artifactContentBytes} bytes.`,
    );
  }
  if (!CANONICAL_BASE64.test(value)) {
    throw new HttpError(
      400,
      "invalid_artifact_content",
      "Artifact contentBase64 must use padded standard Base64 without whitespace.",
    );
  }
  let binary: string;
  try {
    binary = atob(value);
  } catch {
    throw new HttpError(
      400,
      "invalid_artifact_content",
      "Artifact contentBase64 could not be decoded.",
    );
  }
  if (binary.length > UFOSINT_SIDEQUEST_LIMITS.artifactContentBytes) {
    throw new HttpError(
      413,
      "artifact_content_too_large",
      `Artifact content exceeds ${UFOSINT_SIDEQUEST_LIMITS.artifactContentBytes} bytes.`,
    );
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  if (encodeBase64(bytes) !== value) {
    throw new HttpError(
      400,
      "invalid_artifact_content",
      "Artifact contentBase64 is not in canonical form.",
    );
  }
  return bytes;
}

async function requestDigest(operationType: string, payload: unknown): Promise<string> {
  return sha256Hex(canonicalJson({ operationType, payload }));
}

function validateActor(value: unknown): UfosintActor {
  try {
    return assertUfosintActor(value);
  } catch (error) {
    throw new HttpError(
      400,
      "invalid_actor",
      error instanceof Error ? error.message : "Actor is invalid.",
    );
  }
}

function validateIdentifier(value: unknown, label: string): string {
  try {
    return assertUfosintIdentifier(value, label);
  } catch (error) {
    throw new HttpError(
      400,
      "invalid_identifier",
      error instanceof Error ? error.message : `${label} is invalid.`,
    );
  }
}

function validateJson(value: unknown, maximum: number, label: string): string {
  try {
    return assertBoundedJson(value, maximum, label);
  } catch (error) {
    throw new HttpError(
      413,
      "sidequest_payload_too_large",
      error instanceof Error ? error.message : `${label} is too large.`,
    );
  }
}

function operationStatement(
  db: D1Database,
  input: {
    environment: UfosintSidequestEnvironment;
    sidequestId: string;
    revision: number;
    operationId: string;
    operationType: UfosintSidequestEvent["operationType"];
    requestSha256: string;
    actor: UfosintActor;
    payloadJson: string;
    createdAt: string;
  },
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT INTO ufosint_sidequest_events (
        environment, sidequest_id, revision, operation_id, operation_type,
        request_sha256, actor_participant_id, actor_display_name,
        payload_json, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      input.environment,
      input.sidequestId,
      input.revision,
      input.operationId,
      input.operationType,
      input.requestSha256,
      input.actor.participantId,
      input.actor.displayName,
      input.payloadJson,
      input.createdAt,
    );
}

function advanceStatement(
  db: D1Database,
  input: {
    environment: UfosintSidequestEnvironment;
    sidequestId: string;
    expectedRevision: number;
    updatedAt: string;
  },
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE ufosint_sidequests
       SET revision = revision + 1, updated_at = ?
       WHERE environment = ? AND sidequest_id = ? AND revision = ?`,
    )
    .bind(
      input.updatedAt,
      input.environment,
      input.sidequestId,
      input.expectedRevision,
    );
}

async function operationRow(
  db: D1Database,
  environmentName: UfosintSidequestEnvironment,
  sidequestId: string,
  operationId: string,
): Promise<OperationRow | null> {
  return db
    .prepare(
      `SELECT request_sha256, revision
       FROM ufosint_sidequest_events
       WHERE environment = ? AND sidequest_id = ? AND operation_id = ?`,
    )
    .bind(environmentName, sidequestId, operationId)
    .first<OperationRow>();
}

async function idempotentResult(
  db: D1Database,
  environmentName: UfosintSidequestEnvironment,
  sidequestId: string,
  operationId: string,
  digest: string,
): Promise<UfosintSidequestSnapshot | null> {
  const existing = await operationRow(db, environmentName, sidequestId, operationId);
  if (!existing) return null;
  if (existing.request_sha256 !== digest) {
    throw new HttpError(
      409,
      "sidequest_operation_conflict",
      "That operation ID was already used with a different request.",
    );
  }
  const snapshot = await getUfosintSidequest(db, environmentName, sidequestId);
  if (!snapshot) {
    throw new HttpError(
      500,
      "invalid_sidequest_storage",
      "An idempotency record references a missing sidequest.",
    );
  }
  return snapshot;
}

async function recoverConcurrentOperation(
  db: D1Database,
  environmentName: UfosintSidequestEnvironment,
  sidequestId: string,
  operationId: string,
  digest: string,
  error: unknown,
): Promise<UfosintSidequestSnapshot> {
  const replay = await idempotentResult(
    db,
    environmentName,
    sidequestId,
    operationId,
    digest,
  );
  if (replay) return replay;
  const detail = error instanceof Error ? error.message : String(error);
  if (
    detail.includes("UFOSINT sidequest task limit exceeded") ||
    detail.includes("UFOSINT finding revision limit exceeded") ||
    detail.includes("UFOSINT review limit exceeded") ||
    detail.includes("UFOSINT artifact limit exceeded")
  ) {
    throw new HttpError(
      409,
      "sidequest_collection_limit",
      "This sidequest has reached an immutable collection limit.",
    );
  }
  if (detail.includes("aggregate limit exceeded")) {
    throw new HttpError(
      409,
      "sidequest_aggregate_limit",
      "This sidequest has reached an immutable aggregate storage limit.",
    );
  }
  if (
    detail.includes("UFOSINT sidequest revision conflict") ||
    detail.includes("ufosint_sidequest_events.environment") ||
    detail.includes("UFOSINT sidequest revision must increase")
  ) {
    throw new HttpError(
      409,
      "stale_sidequest_revision",
      "The sidequest changed after the caller read it.",
    );
  }
  if (detail.includes("UNIQUE constraint failed")) {
    throw new HttpError(
      409,
      "sidequest_record_conflict",
      "The sidequest mutation conflicts with an existing immutable record.",
    );
  }
  if (
    detail.includes("CHECK constraint failed") ||
    detail.includes("FOREIGN KEY constraint failed")
  ) {
    throw new HttpError(
      409,
      "sidequest_integrity_conflict",
      "The sidequest mutation does not satisfy the durable integrity contract.",
    );
  }
  throw error;
}

async function rootRow(
  db: D1Database,
  environmentName: UfosintSidequestEnvironment,
  sidequestId: string,
): Promise<SidequestRow | null> {
  return db
    .prepare(
      `SELECT environment, sidequest_id, template_version, report_id, report_snapshot_json,
              report_snapshot_sha256, title, lifecycle, revision,
              opened_by_participant_id, opened_by_display_name,
              created_at, updated_at, concluded_at, archived_at
       FROM ufosint_sidequests
       WHERE environment = ? AND sidequest_id = ?`,
    )
    .bind(environmentName, sidequestId)
    .first<SidequestRow>();
}

function requireRootLifecycle(value: string): UfosintSidequestLifecycle {
  if (!isUfosintSidequestLifecycle(value)) {
    throw new HttpError(
      500,
      "invalid_sidequest_storage",
      "Stored sidequest lifecycle is invalid.",
    );
  }
  return value;
}

async function requireRoot(
  db: D1Database,
  environmentName: UfosintSidequestEnvironment,
  sidequestId: string,
  wantedRevision?: number,
): Promise<SidequestRow> {
  const row = await rootRow(db, environmentName, sidequestId);
  if (!row) {
    throw new HttpError(404, "sidequest_not_found", "UFOSINT sidequest was not found.");
  }
  requireRootLifecycle(row.lifecycle);
  if (wantedRevision !== undefined && row.revision !== wantedRevision) {
    throw new HttpError(
      409,
      "stale_sidequest_revision",
      `Expected revision ${wantedRevision}, but current revision is ${row.revision}.`,
    );
  }
  return row;
}

function taskKind(value: string): UfosintSidequestTaskKind {
  if (!(UFOSINT_SIDEQUEST_TASK_KINDS as readonly string[]).includes(value)) {
    throw new HttpError(500, "invalid_sidequest_storage", "Stored task kind is invalid.");
  }
  return value as UfosintSidequestTaskKind;
}

function taskStatus(value: string): UfosintSidequestTaskStatus {
  if (!isUfosintSidequestTaskStatus(value)) {
    throw new HttpError(500, "invalid_sidequest_storage", "Stored task status is invalid.");
  }
  return value;
}

function taskFromRow(row: TaskRow): UfosintSidequestTask {
  return {
    taskId: row.task_id,
    ordinal: row.ordinal,
    kind: taskKind(row.task_kind),
    title: row.title,
    instructions: row.instructions,
    required: row.required === 1,
    status: taskStatus(row.status),
    assignee: row.assigned_participant_id === null
      ? null
      : {
          participantId: row.assigned_participant_id,
          displayName: row.assigned_display_name ?? "Investigator",
        },
    completionNote: row.completion_note,
    completedAt: row.completed_at,
    updatedAt: row.updated_at,
  };
}

function taskCounts(
  tasks: readonly UfosintSidequestTask[],
): Record<UfosintSidequestTaskStatus, number> {
  const result: Record<UfosintSidequestTaskStatus, number> = {
    pending: 0,
    in_progress: 0,
    completed: 0,
    waived: 0,
    unavailable: 0,
  };
  for (const task of tasks) result[task.status] += 1;
  return result;
}

export async function getUfosintSidequest(
  db: D1Database,
  environmentValue: UfosintSidequestEnvironment,
  sidequestValue: string,
): Promise<UfosintSidequestSnapshot | null> {
  const environmentName = environment(environmentValue);
  const sidequestId = validateIdentifier(sidequestValue, "sidequest ID");
  const root = await rootRow(db, environmentName, sidequestId);
  if (!root) return null;
  const lifecycle = requireRootLifecycle(root.lifecycle);
  const [taskResult, findingResult, reviewResult, artifactResult] = await Promise.all([
    db
      .prepare(
        `SELECT task_id, ordinal, task_kind, title, instructions, required,
                status, assigned_participant_id, assigned_display_name,
                completion_note, completed_at, updated_at
         FROM ufosint_sidequest_tasks
         WHERE environment = ? AND sidequest_id = ?
         ORDER BY ordinal, task_id`,
      )
      .bind(environmentName, sidequestId)
      .all<TaskRow>(),
    db
      .prepare(
        `SELECT finding_id, finding_revision, finding_json
         FROM ufosint_sidequest_finding_revisions
         WHERE environment = ? AND sidequest_id = ?
         ORDER BY finding_id, finding_revision`,
      )
      .bind(environmentName, sidequestId)
      .all<FindingRow>(),
    db
      .prepare(
        `SELECT review_id, json_object(
                  'reviewId', review_id,
                  'findingId', finding_id,
                  'findingRevision', finding_revision,
                  'reviewer', json_object(
                    'participantId', reviewer_participant_id,
                    'displayName', reviewer_display_name
                  ),
                  'disposition', disposition,
                  'rationale', rationale,
                  'rubric', CASE WHEN rubric_json IS NULL THEN NULL ELSE json(rubric_json) END,
                  'createdAt', created_at
                ) AS review_json
         FROM ufosint_sidequest_reviews
         WHERE environment = ? AND sidequest_id = ?
         ORDER BY created_at, review_id`,
      )
      .bind(environmentName, sidequestId)
      .all<ReviewRow>(),
    db
      .prepare(
        `SELECT artifact_id, artifact_json
         FROM ufosint_sidequest_artifacts
         WHERE environment = ? AND sidequest_id = ?
         ORDER BY created_at, artifact_id`,
      )
      .bind(environmentName, sidequestId)
      .all<ArtifactRow>(),
  ]);

  const reportSnapshot = parseUfosintReportSnapshot(
    parseStoredJson(root.report_snapshot_json, "Stored report snapshot"),
  );
  const calculatedSnapshotHash = await sha256Hex(canonicalJson(reportSnapshot));
  if (calculatedSnapshotHash !== root.report_snapshot_sha256) {
    throw new HttpError(
      500,
      "sidequest_snapshot_hash_mismatch",
      "Stored UFOSINT report snapshot failed its integrity check.",
    );
  }
  const tasks = (taskResult.results ?? []).map(taskFromRow);
  const findings = (findingResult.results ?? []).map((row) =>
    parseUfosintFindingRevision(parseStoredJson(row.finding_json, "Stored finding revision")),
  );
  const reviews = (reviewResult.results ?? []).map((row) =>
    parseUfosintSidequestReview(parseStoredJson(row.review_json, "Stored sidequest review")),
  );
  const artifacts = (artifactResult.results ?? []).map((row) =>
    parseUfosintSidequestArtifact(parseStoredJson(row.artifact_json, "Stored sidequest artifact")),
  );
  return {
    schemaVersion: UFOSINT_SIDEQUEST_SCHEMA_VERSION,
    templateVersion: root.template_version,
    environment: environmentName,
    sidequestId,
    reportId: root.report_id,
    reportTitle: reportSnapshot.title,
    title: root.title,
    lifecycle,
    revision: root.revision,
    taskCounts: taskCounts(tasks),
    createdAt: root.created_at,
    updatedAt: root.updated_at,
    reportSnapshot,
    reportSnapshotSha256: root.report_snapshot_sha256,
    openedBy: {
      participantId: root.opened_by_participant_id,
      displayName: root.opened_by_display_name,
    },
    concludedAt: root.concluded_at,
    archivedAt: root.archived_at,
    tasks,
    findings,
    reviews,
    artifacts,
  };
}

export async function listUfosintSidequests(
  db: D1Database,
  input: ListUfosintSidequestsInput,
): Promise<UfosintSidequestSummary[]> {
  const environmentName = environment(input.environment);
  const values: unknown[] = [environmentName];
  const clauses = ["s.environment = ?"];
  if (input.lifecycle !== undefined) {
    if (!isUfosintSidequestLifecycle(input.lifecycle)) {
      throw new HttpError(400, "invalid_lifecycle", "Sidequest lifecycle is invalid.");
    }
    clauses.push("s.lifecycle = ?");
    values.push(input.lifecycle);
  }
  if (input.reportId !== undefined) {
    clauses.push("s.report_id = ?");
    values.push(boundedText(input.reportId, UFOSINT_SIDEQUEST_LIMITS.reportId, "report ID"));
  }
  if (input.beforeUpdatedAt !== undefined) {
    clauses.push("s.updated_at < ?");
    values.push(timestamp(input.beforeUpdatedAt, "pagination timestamp"));
  }
  const limit = input.limit === undefined ? 50 : expectedRevision(input.limit);
  if (limit < 1 || limit > 100) {
    throw new HttpError(400, "invalid_limit", "List limit must be from 1 through 100.");
  }
  values.push(limit);
  const result = await db
    .prepare(
      `SELECT s.environment, s.sidequest_id, s.template_version, s.report_id, s.report_snapshot_json,
              s.report_snapshot_sha256, s.title, s.lifecycle, s.revision,
              s.opened_by_participant_id, s.opened_by_display_name,
              s.created_at, s.updated_at, s.concluded_at, s.archived_at
       FROM ufosint_sidequests AS s
       WHERE ${clauses.join(" AND ")}
       ORDER BY s.updated_at DESC, s.sidequest_id
       LIMIT ?`,
    )
    .bind(...values)
    .all<SidequestRow>();
  const summaries: UfosintSidequestSummary[] = [];
  for (const row of result.results ?? []) {
    const lifecycle = requireRootLifecycle(row.lifecycle);
    const report = parseUfosintReportSnapshot(
      parseStoredJson(row.report_snapshot_json, "Stored report snapshot"),
    );
    const taskRows = await db
      .prepare(
        `SELECT status, COUNT(*) AS count
         FROM ufosint_sidequest_tasks
         WHERE environment = ? AND sidequest_id = ?
         GROUP BY status`,
      )
      .bind(environmentName, row.sidequest_id)
      .all<{ status: string; count: number }>();
    const counts: Record<UfosintSidequestTaskStatus, number> = {
      pending: 0,
      in_progress: 0,
      completed: 0,
      waived: 0,
      unavailable: 0,
    };
    for (const countRow of taskRows.results ?? []) {
      counts[taskStatus(countRow.status)] = Number(countRow.count);
    }
    summaries.push({
      schemaVersion: UFOSINT_SIDEQUEST_SCHEMA_VERSION,
      templateVersion: row.template_version,
      environment: environmentName,
      sidequestId: row.sidequest_id,
      reportId: row.report_id,
      reportTitle: report.title,
      title: row.title,
      lifecycle,
      revision: row.revision,
      taskCounts: counts,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    });
  }
  return summaries;
}

export async function listUfosintSidequestEvents(
  db: D1Database,
  input: ListUfosintSidequestEventsInput,
): Promise<UfosintSidequestEvent[]> {
  const environmentName = environment(input.environment);
  const sidequestId = validateIdentifier(input.sidequestId, "sidequest ID");
  const afterRevision = input.afterRevision === undefined
    ? 0
    : expectedRevision(input.afterRevision);
  const limit = input.limit === undefined ? 100 : expectedRevision(input.limit);
  if (limit < 1 || limit > 500) {
    throw new HttpError(400, "invalid_limit", "Event limit must be from 1 through 500.");
  }
  await requireRoot(db, environmentName, sidequestId);
  const result = await db
    .prepare(
      `SELECT revision, operation_id, operation_type, request_sha256,
              actor_participant_id, actor_display_name, created_at
       FROM ufosint_sidequest_events
       WHERE environment = ? AND sidequest_id = ? AND revision > ?
       ORDER BY revision
       LIMIT ?`,
    )
    .bind(environmentName, sidequestId, afterRevision, limit)
    .all<EventRow>();
  return (result.results ?? []).map((row) => ({
    revision: row.revision,
    operationId: row.operation_id,
    operationType: row.operation_type,
    requestSha256: row.request_sha256,
    actor: {
      participantId: row.actor_participant_id,
      displayName: row.actor_display_name,
    },
    createdAt: row.created_at,
  }));
}

export async function createUfosintSidequest(
  db: D1Database,
  input: CreateUfosintSidequestInput,
): Promise<UfosintSidequestSnapshot> {
  const environmentName = environment(input.environment);
  const sidequestId = validateIdentifier(input.sidequestId, "sidequest ID");
  const operationId = validateIdentifier(input.operationId, "operation ID");
  if (input.expectedRevision !== undefined && input.expectedRevision !== 0) {
    throw new HttpError(400, "invalid_expected_revision", "Create expects revision zero.");
  }
  const actor = validateActor(input.actor);
  const templateVersion = validateIdentifier(input.templateVersion, "sidequest template version");
  let reportSnapshot;
  let tasks;
  try {
    reportSnapshot = parseUfosintReportSnapshot(input.reportSnapshot);
    tasks = parseUfosintTaskDefinitions(input.tasks);
  } catch (error) {
    throw new HttpError(
      400,
      "invalid_sidequest_input",
      error instanceof Error ? error.message : "Sidequest input is invalid.",
    );
  }
  const title = boundedText(input.title, UFOSINT_SIDEQUEST_LIMITS.title, "sidequest title");
  const createdAt = operationTime(input.occurredAt);
  const reportSnapshotJson = canonicalJson(reportSnapshot);
  validateJson(reportSnapshot, UFOSINT_SIDEQUEST_LIMITS.jsonBytes, "report snapshot");
  const reportSnapshotSha256 = await sha256Hex(reportSnapshotJson);
  const digest = await requestDigest("sidequest_created", {
    environment: environmentName,
    sidequestId,
    operationId,
    actor,
    templateVersion,
    reportSnapshot,
    title,
    tasks,
  });
  const replay = await idempotentResult(
    db,
    environmentName,
    sidequestId,
    operationId,
    digest,
  );
  if (replay) return replay;
  const eventPayload = {
    templateVersion,
    reportSnapshotSha256,
    reportId: reportSnapshot.reportId,
    taskIds: tasks.map((task) => task.taskId),
  };
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `INSERT INTO ufosint_sidequests (
          environment, sidequest_id, template_version, report_source_key, report_id,
          report_snapshot_json, report_snapshot_sha256, title, lifecycle,
          revision, opened_by_participant_id, opened_by_display_name,
          created_at, updated_at, concluded_at, archived_at
        ) VALUES (?, ?, ?, 'ufosint', ?, ?, ?, ?, 'open', 0, ?, ?, ?, ?, NULL, NULL)`,
      )
      .bind(
        environmentName,
        sidequestId,
        templateVersion,
        reportSnapshot.reportId,
        reportSnapshotJson,
        reportSnapshotSha256,
        title,
        actor.participantId,
        actor.displayName,
        createdAt,
        createdAt,
      ),
  ];
  for (const task of tasks) {
    statements.push(
      db
        .prepare(
          `INSERT INTO ufosint_sidequest_tasks (
            environment, sidequest_id, task_id, ordinal, task_kind, title,
            instructions, required, status, assigned_participant_id,
            assigned_display_name, completion_note, completed_at, updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, NULL, ?)`,
        )
        .bind(
          environmentName,
          sidequestId,
          task.taskId,
          task.ordinal,
          task.kind,
          task.title,
          task.instructions,
          task.required ? 1 : 0,
          createdAt,
        ),
    );
  }
  statements.push(
    operationStatement(db, {
      environment: environmentName,
      sidequestId,
      revision: 1,
      operationId,
      operationType: "sidequest_created",
      requestSha256: digest,
      actor,
      payloadJson: validateJson(
        eventPayload,
        UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
        "sidequest event",
      ),
      createdAt,
    }),
    advanceStatement(db, {
      environment: environmentName,
      sidequestId,
      expectedRevision: 0,
      updatedAt: createdAt,
    }),
  );
  try {
    await db.batch(statements);
  } catch (error) {
    return recoverConcurrentOperation(
      db,
      environmentName,
      sidequestId,
      operationId,
      digest,
      error,
    );
  }
  const created = await getUfosintSidequest(db, environmentName, sidequestId);
  if (!created) throw new HttpError(500, "sidequest_create_failed", "Sidequest was not persisted.");
  return created;
}

export async function updateUfosintSidequestLifecycle(
  db: D1Database,
  input: UpdateUfosintSidequestLifecycleInput,
): Promise<UfosintSidequestSnapshot> {
  const environmentName = environment(input.environment);
  const sidequestId = validateIdentifier(input.sidequestId, "sidequest ID");
  const operationId = validateIdentifier(input.operationId, "operation ID");
  const actor = validateActor(input.actor);
  const wantedRevision = expectedRevision(input.expectedRevision);
  if (!isUfosintSidequestLifecycle(input.lifecycle)) {
    throw new HttpError(400, "invalid_lifecycle", "Sidequest lifecycle is invalid.");
  }
  const createdAt = operationTime(input.occurredAt);
  const digest = await requestDigest("lifecycle_updated", {
    environment: environmentName,
    sidequestId,
    operationId,
    expectedRevision: wantedRevision,
    actor,
    lifecycle: input.lifecycle,
  });
  const replay = await idempotentResult(db, environmentName, sidequestId, operationId, digest);
  if (replay) return replay;
  const root = await requireRoot(db, environmentName, sidequestId, wantedRevision);
  const current = requireRootLifecycle(root.lifecycle);
  if (!canTransitionUfosintSidequest(current, input.lifecycle)) {
    throw new HttpError(
      409,
      "invalid_sidequest_transition",
      `Sidequest cannot transition from ${current} to ${input.lifecycle}.`,
    );
  }
  if (input.lifecycle === "concluded") {
    const incomplete = await db
      .prepare(
        `SELECT task_id
         FROM ufosint_sidequest_tasks
         WHERE environment = ? AND sidequest_id = ? AND required = 1
           AND status NOT IN ('completed', 'waived', 'unavailable')
         LIMIT 1`,
      )
      .bind(environmentName, sidequestId)
      .first<{ task_id: string }>();
    if (incomplete) {
      throw new HttpError(
        409,
        "sidequest_tasks_incomplete",
        "All required checklist tasks must be completed, waived, or marked unavailable with an audit note.",
      );
    }
    const reviewedConclusion = await db
      .prepare(
        `SELECT finding.finding_id
         FROM ufosint_sidequest_finding_revisions AS finding
         WHERE finding.environment = ? AND finding.sidequest_id = ?
           AND finding.finding_kind = 'conclusion'
           AND finding.finding_revision = (
             SELECT MAX(latest.finding_revision)
             FROM ufosint_sidequest_finding_revisions AS latest
             WHERE latest.environment = finding.environment
               AND latest.sidequest_id = finding.sidequest_id
               AND latest.finding_id = finding.finding_id
           )
           AND EXISTS (
             SELECT 1 FROM ufosint_sidequest_reviews AS endorsement
             WHERE endorsement.environment = finding.environment
               AND endorsement.sidequest_id = finding.sidequest_id
               AND endorsement.finding_id = finding.finding_id
               AND endorsement.finding_revision = finding.finding_revision
               AND endorsement.disposition = 'endorse'
           )
           AND NOT EXISTS (
             SELECT 1 FROM ufosint_sidequest_reviews AS blocker
             WHERE blocker.environment = finding.environment
               AND blocker.sidequest_id = finding.sidequest_id
               AND blocker.finding_id = finding.finding_id
               AND blocker.finding_revision = finding.finding_revision
               AND blocker.disposition IN ('challenge', 'request_revision')
           )
         LIMIT 1`,
      )
      .bind(environmentName, sidequestId)
      .first<{ finding_id: string }>();
    if (!reviewedConclusion) {
      throw new HttpError(
        409,
        "sidequest_peer_review_incomplete",
        "Conclusion requires an independently endorsed current conclusion finding with no blockers.",
      );
    }
  }
  const nextRevision = wantedRevision + 1;
  const concludedAt = input.lifecycle === "concluded" ? createdAt : root.concluded_at;
  const archivedAt = input.lifecycle === "archived" ? createdAt : null;
  try {
    await db.batch([
      operationStatement(db, {
        environment: environmentName,
        sidequestId,
        revision: nextRevision,
        operationId,
        operationType: "lifecycle_updated",
        requestSha256: digest,
        actor,
        payloadJson: validateJson(
          { from: current, to: input.lifecycle },
          UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
          "lifecycle event",
        ),
        createdAt,
      }),
      db
        .prepare(
          `UPDATE ufosint_sidequests
           SET lifecycle = ?, revision = revision + 1, updated_at = ?,
               concluded_at = ?, archived_at = ?
           WHERE environment = ? AND sidequest_id = ? AND revision = ?`,
        )
        .bind(
          input.lifecycle,
          createdAt,
          concludedAt,
          archivedAt,
          environmentName,
          sidequestId,
          wantedRevision,
        ),
    ]);
  } catch (error) {
    return recoverConcurrentOperation(
      db,
      environmentName,
      sidequestId,
      operationId,
      digest,
      error,
    );
  }
  return requireSnapshot(db, environmentName, sidequestId);
}

export async function updateUfosintSidequestTask(
  db: D1Database,
  input: UpdateUfosintSidequestTaskInput,
): Promise<UfosintSidequestSnapshot> {
  const environmentName = environment(input.environment);
  const sidequestId = validateIdentifier(input.sidequestId, "sidequest ID");
  const operationId = validateIdentifier(input.operationId, "operation ID");
  const taskId = validateIdentifier(input.taskId, "task ID");
  const actor = validateActor(input.actor);
  const assignee = input.assignee === null ? null : validateActor(input.assignee);
  const wantedRevision = expectedRevision(input.expectedRevision);
  if (!isUfosintSidequestTaskStatus(input.status)) {
    throw new HttpError(400, "invalid_task_status", "Task status is invalid.");
  }
  const completionNote = nullableText(
    input.completionNote,
    UFOSINT_SIDEQUEST_LIMITS.completionNote,
    "task completion note",
  );
  if (
    (input.status === "completed" || input.status === "waived" || input.status === "unavailable") &&
    completionNote === null
  ) {
    throw new HttpError(
      400,
      "task_completion_note_required",
      "Completed, waived, and unavailable tasks require an audit note.",
    );
  }
  if (input.status === "in_progress" && assignee === null) {
    throw new HttpError(
      400,
      "task_assignee_required",
      "An in-progress task must have an assignee.",
    );
  }
  const createdAt = operationTime(input.occurredAt);
  const digest = await requestDigest("task_updated", {
    environment: environmentName,
    sidequestId,
    operationId,
    expectedRevision: wantedRevision,
    actor,
    taskId,
    status: input.status,
    assignee,
    completionNote,
  });
  const replay = await idempotentResult(db, environmentName, sidequestId, operationId, digest);
  if (replay) return replay;
  const root = await requireRoot(db, environmentName, sidequestId, wantedRevision);
  const lifecycle = requireRootLifecycle(root.lifecycle);
  if (lifecycle === "concluded" || lifecycle === "archived") {
    throw new HttpError(409, "sidequest_closed", "Closed sidequests cannot change tasks.");
  }
  const row = await db
    .prepare(
      `SELECT task_id, ordinal, task_kind, title, instructions, required,
              status, assigned_participant_id, assigned_display_name,
              completion_note, completed_at, updated_at
       FROM ufosint_sidequest_tasks
       WHERE environment = ? AND sidequest_id = ? AND task_id = ?`,
    )
    .bind(environmentName, sidequestId, taskId)
    .first<TaskRow>();
  if (!row) throw new HttpError(404, "sidequest_task_not_found", "Checklist task was not found.");
  const current = taskFromRow(row);
  if (!canTransitionUfosintTask(current.status, input.status)) {
    throw new HttpError(
      409,
      "invalid_task_transition",
      `Task cannot transition from ${current.status} to ${input.status}.`,
    );
  }
  if (
    current.status === input.status &&
    current.assignee?.participantId === assignee?.participantId &&
    current.completionNote === completionNote
  ) {
    throw new HttpError(409, "task_no_change", "Task update does not change durable state.");
  }
  const completedAt =
    input.status === "completed" || input.status === "waived" || input.status === "unavailable"
    ? createdAt
    : null;
  const nextRevision = wantedRevision + 1;
  try {
    await db.batch([
      operationStatement(db, {
        environment: environmentName,
        sidequestId,
        revision: nextRevision,
        operationId,
        operationType: "task_updated",
        requestSha256: digest,
        actor,
        payloadJson: validateJson(
          { taskId, from: current.status, to: input.status, assignee, completionNote },
          UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
          "task event",
        ),
        createdAt,
      }),
      db
        .prepare(
          `UPDATE ufosint_sidequest_tasks
           SET status = ?, assigned_participant_id = ?, assigned_display_name = ?,
               completion_note = ?, completed_at = ?, updated_at = ?
           WHERE environment = ? AND sidequest_id = ? AND task_id = ?`,
        )
        .bind(
          input.status,
          assignee?.participantId ?? null,
          assignee?.displayName ?? null,
          completionNote,
          completedAt,
          createdAt,
          environmentName,
          sidequestId,
          taskId,
        ),
      advanceStatement(db, {
        environment: environmentName,
        sidequestId,
        expectedRevision: wantedRevision,
        updatedAt: createdAt,
      }),
    ]);
  } catch (error) {
    return recoverConcurrentOperation(
      db,
      environmentName,
      sidequestId,
      operationId,
      digest,
      error,
    );
  }
  return requireSnapshot(db, environmentName, sidequestId);
}

export async function addUfosintSidequestFinding(
  db: D1Database,
  input: AddUfosintSidequestFindingInput,
): Promise<UfosintSidequestSnapshot> {
  const environmentName = environment(input.environment);
  const sidequestId = validateIdentifier(input.sidequestId, "sidequest ID");
  const operationId = validateIdentifier(input.operationId, "operation ID");
  const actor = validateActor(input.actor);
  const wantedRevision = expectedRevision(input.expectedRevision);
  const createdAt = operationTime(input.occurredAt);
  let finding: UfosintSidequestFindingRevision;
  try {
    finding = parseUfosintFindingRevision({
      ...input.finding,
      author: actor,
      createdAt,
    });
  } catch (error) {
    throw new HttpError(
      400,
      "invalid_finding",
      error instanceof Error ? error.message : "Finding is invalid.",
    );
  }
  if (finding.evidenceReferences.length < 1) {
    throw new HttpError(
      400,
      "finding_evidence_required",
      "A finding requires at least one explicit evidence reference.",
    );
  }
  const digest = await requestDigest("finding_added", {
    environment: environmentName,
    sidequestId,
    operationId,
    expectedRevision: wantedRevision,
    actor,
    finding,
  });
  const replay = await idempotentResult(db, environmentName, sidequestId, operationId, digest);
  if (replay) return replay;
  const root = await requireRoot(db, environmentName, sidequestId, wantedRevision);
  const lifecycle = requireRootLifecycle(root.lifecycle);
  if (lifecycle === "concluded" || lifecycle === "archived") {
    throw new HttpError(409, "sidequest_closed", "Closed sidequests cannot add findings.");
  }
  const latest = await db
    .prepare(
      `SELECT MAX(finding_revision) AS finding_revision
       FROM ufosint_sidequest_finding_revisions
       WHERE environment = ? AND sidequest_id = ? AND finding_id = ?`,
    )
    .bind(environmentName, sidequestId, finding.findingId)
    .first<{ finding_revision: number | null }>();
  const latestRevision = latest?.finding_revision ?? null;
  if (
    (latestRevision === null && finding.revision !== 1) ||
    (latestRevision !== null && finding.revision !== latestRevision + 1)
  ) {
    throw new HttpError(
      409,
      "finding_revision_conflict",
      "Finding revision must follow the current exact revision.",
    );
  }
  for (const artifactId of finding.artifactIds) {
    const artifact = await artifactHash(db, environmentName, sidequestId, artifactId);
    if (!artifact) {
      throw new HttpError(
        409,
        "finding_artifact_missing",
        `Finding references unknown artifact ${artifactId}.`,
      );
    }
  }
  for (const reference of finding.evidenceReferences) {
    if (
      reference.sourceType === "report_snapshot" &&
      reference.sourceReference !== root.report_id &&
      reference.sourceReference !== `ufosint:${root.report_id}`
    ) {
      throw new HttpError(
        409,
        "finding_report_scope_mismatch",
        "Finding report reference does not match the sidequest snapshot.",
      );
    }
    if (
      reference.sourceType === "artifact" &&
      !(await artifactHash(db, environmentName, sidequestId, reference.sourceReference))
    ) {
      throw new HttpError(
        409,
        "finding_artifact_missing",
        `Finding evidence references unknown artifact ${reference.sourceReference}.`,
      );
    }
  }
  const findingJson = validateJson(
    finding,
    UFOSINT_SIDEQUEST_LIMITS.jsonBytes,
    "finding revision",
  );
  const nextRevision = wantedRevision + 1;
  try {
    await db.batch([
      operationStatement(db, {
        environment: environmentName,
        sidequestId,
        revision: nextRevision,
        operationId,
        operationType: "finding_added",
        requestSha256: digest,
        actor,
        payloadJson: validateJson(
          { findingId: finding.findingId, findingRevision: finding.revision },
          UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
          "finding event",
        ),
        createdAt,
      }),
      db
        .prepare(
          `INSERT INTO ufosint_sidequest_finding_revisions (
            environment, sidequest_id, finding_id, finding_revision,
            previous_revision, finding_kind, statement, confidence,
            finding_json, author_participant_id, author_display_name, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          environmentName,
          sidequestId,
          finding.findingId,
          finding.revision,
          finding.previousRevision,
          finding.kind,
          finding.statement,
          finding.confidence,
          findingJson,
          actor.participantId,
          actor.displayName,
          createdAt,
        ),
      advanceStatement(db, {
        environment: environmentName,
        sidequestId,
        expectedRevision: wantedRevision,
        updatedAt: createdAt,
      }),
    ]);
  } catch (error) {
    return recoverConcurrentOperation(
      db,
      environmentName,
      sidequestId,
      operationId,
      digest,
      error,
    );
  }
  return requireSnapshot(db, environmentName, sidequestId);
}

export async function addUfosintSidequestReview(
  db: D1Database,
  input: AddUfosintSidequestReviewInput,
): Promise<UfosintSidequestSnapshot> {
  const environmentName = environment(input.environment);
  const sidequestId = validateIdentifier(input.sidequestId, "sidequest ID");
  const operationId = validateIdentifier(input.operationId, "operation ID");
  const actor = validateActor(input.actor);
  const wantedRevision = expectedRevision(input.expectedRevision);
  const createdAt = operationTime(input.occurredAt);
  let review: UfosintSidequestReview;
  try {
    review = parseUfosintSidequestReview({
      ...input.review,
      reviewer: actor,
      createdAt,
    });
  } catch (error) {
    throw new HttpError(
      400,
      "invalid_review",
      error instanceof Error ? error.message : "Finding review is invalid.",
    );
  }
  if (review.rubric === null) {
    throw new HttpError(
      400,
      "review_rubric_required",
      "New UFOSINT reviews require the five-part quality rubric.",
    );
  }
  const digest = await requestDigest("review_added", {
    environment: environmentName,
    sidequestId,
    operationId,
    expectedRevision: wantedRevision,
    actor,
    review,
  });
  const replay = await idempotentResult(db, environmentName, sidequestId, operationId, digest);
  if (replay) return replay;
  const root = await requireRoot(db, environmentName, sidequestId, wantedRevision);
  if (requireRootLifecycle(root.lifecycle) !== "review") {
    throw new HttpError(
      409,
      "sidequest_not_in_review",
      "Finding reviews are accepted only while the sidequest is in review.",
    );
  }
  const findingRow = await db
    .prepare(
      `SELECT finding.finding_json,
              (
                SELECT MAX(latest.finding_revision)
                FROM ufosint_sidequest_finding_revisions AS latest
                WHERE latest.environment = finding.environment
                  AND latest.sidequest_id = finding.sidequest_id
                  AND latest.finding_id = finding.finding_id
              ) AS latest_revision
       FROM ufosint_sidequest_finding_revisions AS finding
       WHERE finding.environment = ? AND finding.sidequest_id = ?
         AND finding.finding_id = ? AND finding.finding_revision = ?`,
    )
    .bind(
      environmentName,
      sidequestId,
      review.findingId,
      review.findingRevision,
    )
    .first<FindingAuthorRow>();
  if (!findingRow) {
    throw new HttpError(404, "finding_not_found", "Exact finding revision was not found.");
  }
  if (findingRow.latest_revision !== review.findingRevision) {
    throw new HttpError(
      409,
      "stale_finding_revision",
      "New reviews must target the current exact finding revision.",
    );
  }
  const finding = parseUfosintFindingRevision(
    parseStoredJson(findingRow.finding_json, "Stored finding revision"),
  );
  if (finding.author.participantId === actor.participantId) {
    throw new HttpError(409, "self_review_forbidden", "Finding authors cannot review their own revision.");
  }
  const reviewJson = validateJson(review, UFOSINT_SIDEQUEST_LIMITS.jsonBytes, "finding review");
  const nextRevision = wantedRevision + 1;
  try {
    await db.batch([
      operationStatement(db, {
        environment: environmentName,
        sidequestId,
        revision: nextRevision,
        operationId,
        operationType: "review_added",
        requestSha256: digest,
        actor,
        payloadJson: validateJson(
          {
            reviewId: review.reviewId,
            findingId: review.findingId,
            findingRevision: review.findingRevision,
            disposition: review.disposition,
          },
          UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
          "review event",
        ),
        createdAt,
      }),
      db
        .prepare(
          `INSERT INTO ufosint_sidequest_reviews (
            environment, sidequest_id, review_id, finding_id, finding_revision,
            reviewer_participant_id, reviewer_display_name, disposition,
            rationale, rubric_json, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          environmentName,
          sidequestId,
          review.reviewId,
          review.findingId,
          review.findingRevision,
          actor.participantId,
          actor.displayName,
          review.disposition,
          review.rationale,
          JSON.stringify(review.rubric),
          createdAt,
        ),
      advanceStatement(db, {
        environment: environmentName,
        sidequestId,
        expectedRevision: wantedRevision,
        updatedAt: createdAt,
      }),
    ]);
  } catch (error) {
    return recoverConcurrentOperation(
      db,
      environmentName,
      sidequestId,
      operationId,
      digest,
      error,
    );
  }
  return requireSnapshot(db, environmentName, sidequestId);
}

function artifactKind(value: string): UfosintArtifactKind {
  if (!(UFOSINT_ARTIFACT_KINDS as readonly string[]).includes(value)) {
    throw new HttpError(500, "invalid_sidequest_storage", "Stored artifact kind is invalid.");
  }
  return value as UfosintArtifactKind;
}

async function artifactHash(
  db: D1Database,
  environmentName: UfosintSidequestEnvironment,
  sidequestId: string,
  artifactId: string,
): Promise<ArtifactHashRow | null> {
  return db
    .prepare(
      `SELECT artifact_id, content_sha256
       FROM ufosint_sidequest_artifacts
       WHERE environment = ? AND sidequest_id = ? AND artifact_id = ?`,
    )
    .bind(environmentName, sidequestId, artifactId)
    .first<ArtifactHashRow>();
}

export async function getUfosintSidequestArtifactContent(
  db: D1Database,
  environmentValue: UfosintSidequestEnvironment,
  sidequestValue: string,
  artifactValue: string,
): Promise<UfosintSidequestArtifactContent | null> {
  const environmentName = environment(environmentValue);
  const sidequestId = validateIdentifier(sidequestValue, "sidequest ID");
  const artifactId = validateIdentifier(artifactValue, "artifact ID");
  const row = await db
    .prepare(
      `SELECT artifact_id, media_type, content_sha256, byte_length,
              content_base64, created_at
       FROM ufosint_sidequest_artifacts
       WHERE environment = ? AND sidequest_id = ? AND artifact_id = ?`,
    )
    .bind(environmentName, sidequestId, artifactId)
    .first<ArtifactContentRow>();
  if (!row) return null;

  let bytes: Uint8Array;
  try {
    bytes = decodeCanonicalArtifactContent(row.content_base64);
  } catch {
    throw new HttpError(
      500,
      "invalid_sidequest_storage",
      "Stored artifact content is not canonical Base64.",
    );
  }
  const contentSha256 = await sha256Hex(bytes);
  if (
    bytes.byteLength !== row.byte_length ||
    contentSha256 !== row.content_sha256
  ) {
    throw new HttpError(
      500,
      "sidequest_artifact_content_mismatch",
      "Stored artifact bytes failed their immutable length or SHA-256 check.",
    );
  }
  return {
    artifactId: row.artifact_id,
    mediaType: row.media_type,
    contentSha256: row.content_sha256,
    byteLength: row.byte_length,
    bytes,
    createdAt: row.created_at,
  };
}

async function validateArtifactProvenance(
  db: D1Database,
  root: SidequestRow,
  artifact: UfosintSidequestArtifact,
): Promise<void> {
  let exactReportSnapshotEdge = false;
  for (const provenance of artifact.provenance) {
    if (provenance.parentType === "report_snapshot") {
      if (provenance.parentReference !== root.report_id) {
        throw new HttpError(
          409,
          "artifact_report_scope_mismatch",
          "Artifact provenance references a different UFOSINT report.",
        );
      }
      if (provenance.parentContentSha256 !== root.report_snapshot_sha256) {
        throw new HttpError(
          409,
          "artifact_report_hash_mismatch",
          "Artifact provenance must pin the immutable report snapshot hash.",
        );
      }
      exactReportSnapshotEdge = true;
    }
    if (provenance.parentType === "artifact") {
      if (provenance.parentReference === artifact.artifactId) {
        throw new HttpError(409, "artifact_provenance_cycle", "Artifact cannot derive from itself.");
      }
      const parent = await artifactHash(
        db,
        root.environment as UfosintSidequestEnvironment,
        root.sidequest_id,
        provenance.parentReference,
      );
      if (!parent) {
        throw new HttpError(
          409,
          "artifact_parent_missing",
          `Artifact provenance references unknown artifact ${provenance.parentReference}.`,
        );
      }
      if (provenance.parentContentSha256 !== parent.content_sha256) {
        throw new HttpError(
          409,
          "artifact_parent_hash_mismatch",
          "Artifact provenance does not match its parent content hash.",
        );
      }
    }
    if (
      provenance.relation === "derived_from" &&
      provenance.parentContentSha256 === null
    ) {
      throw new HttpError(
        409,
        "artifact_parent_hash_required",
        "Derived artifacts require a content hash for every provenance input.",
      );
    }
  }
  if (artifact.kind === "dynamical_analysis" && !exactReportSnapshotEdge) {
    throw new HttpError(
      409,
      "artifact_report_provenance_required",
      "Dynamical analysis artifacts require an exact immutable report-snapshot provenance edge.",
    );
  }
}

export async function attachUfosintSidequestArtifact(
  db: D1Database,
  input: AttachUfosintSidequestArtifactInput,
): Promise<UfosintSidequestSnapshot> {
  const environmentName = environment(input.environment);
  const sidequestId = validateIdentifier(input.sidequestId, "sidequest ID");
  const operationId = validateIdentifier(input.operationId, "operation ID");
  const actor = validateActor(input.actor);
  const wantedRevision = expectedRevision(input.expectedRevision);
  const createdAt = operationTime(input.occurredAt);
  let artifact: UfosintSidequestArtifact;
  try {
    artifact = parseUfosintSidequestArtifact({
      ...input.artifact,
      createdBy: actor,
      createdAt,
    });
  } catch (error) {
    throw new HttpError(
      400,
      "invalid_artifact",
      error instanceof Error ? error.message : "Artifact is invalid.",
    );
  }
  const contentBase64 = input.contentBase64;
  const contentBytes = decodeCanonicalArtifactContent(contentBase64);
  if (contentBytes.byteLength !== artifact.byteLength) {
    throw new HttpError(
      400,
      "artifact_byte_length_mismatch",
      "Artifact byteLength does not match the decoded contentBase64 bytes.",
    );
  }
  const contentSha256 = await sha256Hex(contentBytes);
  if (contentSha256 !== artifact.contentSha256) {
    throw new HttpError(
      400,
      "artifact_content_hash_mismatch",
      "Artifact contentSha256 does not match the decoded contentBase64 bytes.",
    );
  }
  const digest = await requestDigest("artifact_attached", {
    environment: environmentName,
    sidequestId,
    operationId,
    expectedRevision: wantedRevision,
    actor,
    artifact,
    contentBase64,
  });
  const replay = await idempotentResult(db, environmentName, sidequestId, operationId, digest);
  if (replay) return replay;
  const root = await requireRoot(db, environmentName, sidequestId, wantedRevision);
  const lifecycle = requireRootLifecycle(root.lifecycle);
  if (lifecycle === "concluded" || lifecycle === "archived") {
    throw new HttpError(409, "sidequest_closed", "Closed sidequests cannot attach artifacts.");
  }
  await validateArtifactProvenance(db, root, artifact);
  const artifactJson = validateJson(
    artifact,
    UFOSINT_SIDEQUEST_LIMITS.jsonBytes,
    "sidequest artifact",
  );
  const nextRevision = wantedRevision + 1;
  const statements: D1PreparedStatement[] = [
    operationStatement(db, {
      environment: environmentName,
      sidequestId,
      revision: nextRevision,
      operationId,
      operationType: "artifact_attached",
      requestSha256: digest,
      actor,
      payloadJson: validateJson(
        {
          artifactId: artifact.artifactId,
          artifactKind: artifact.kind,
          contentSha256: artifact.contentSha256,
        },
        UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
        "artifact event",
      ),
      createdAt,
    }),
    db
      .prepare(
        `INSERT INTO ufosint_sidequest_artifacts (
          environment, sidequest_id, artifact_id, artifact_kind, title,
          media_type, content_sha256, byte_length, content_base64,
          artifact_uri, artifact_json,
          created_by_participant_id, created_by_display_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        environmentName,
        sidequestId,
        artifact.artifactId,
        artifactKind(artifact.kind),
        artifact.title,
        artifact.mediaType,
        artifact.contentSha256,
        artifact.byteLength,
        contentBase64,
        artifact.artifactUri,
        artifactJson,
        actor.participantId,
        actor.displayName,
        createdAt,
      ),
  ];
  for (const provenance of artifact.provenance) {
    statements.push(
      db
        .prepare(
          `INSERT INTO ufosint_sidequest_artifact_provenance (
            environment, sidequest_id, artifact_id, provenance_id,
            parent_type, parent_reference, parent_content_sha256, relation,
            description, retrieved_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          environmentName,
          sidequestId,
          artifact.artifactId,
          provenance.provenanceId,
          provenance.parentType,
          provenance.parentReference,
          provenance.parentContentSha256,
          provenance.relation,
          provenance.description,
          provenance.retrievedAt,
        ),
    );
  }
  statements.push(
    advanceStatement(db, {
      environment: environmentName,
      sidequestId,
      expectedRevision: wantedRevision,
      updatedAt: createdAt,
    }),
  );
  try {
    await db.batch(statements);
  } catch (error) {
    return recoverConcurrentOperation(
      db,
      environmentName,
      sidequestId,
      operationId,
      digest,
      error,
    );
  }
  return requireSnapshot(db, environmentName, sidequestId);
}

async function requireSnapshot(
  db: D1Database,
  environmentName: UfosintSidequestEnvironment,
  sidequestId: string,
): Promise<UfosintSidequestSnapshot> {
  const snapshot = await getUfosintSidequest(db, environmentName, sidequestId);
  if (!snapshot) {
    throw new HttpError(500, "sidequest_mutation_failed", "Sidequest disappeared after mutation.");
  }
  return snapshot;
}

// These imports are intentionally exercised here so drift between the SQL
// CHECK domains and the shared domain constants is caught by TypeScript and by
// the focused migration validator.
void UFOSINT_SIDEQUEST_LIFECYCLES;
void UFOSINT_FINDING_KINDS;
void UFOSINT_FINDING_CONFIDENCE;
