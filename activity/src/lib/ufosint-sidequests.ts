import {
  UFOSINT_SIDEQUEST_LIMITS,
  UFOSINT_SIDEQUEST_SCHEMA_VERSION,
  UFOSINT_SIDEQUEST_TASK_STATUSES,
  assertBoundedJson,
  assertUfosintActor,
  assertUfosintIdentifier,
  assertUfosintTimestamp,
  isUfosintSidequestLifecycle,
  isUfosintSidequestTaskStatus,
  parseUfosintFindingRevision,
  parseUfosintReportSnapshot,
  parseUfosintSidequestArtifact,
  parseUfosintSidequestReview,
  parseUfosintTaskDefinitions,
  type UfosintActor,
  type UfosintSidequestArtifact,
  type UfosintSidequestFindingRevision,
  type UfosintSidequestLifecycle,
  type UfosintSidequestReview,
  type UfosintSidequestSnapshot,
  type UfosintSidequestTask,
  type UfosintSidequestTaskStatus,
} from "../shared/ufosint-sidequest";
import { siteAuthHeaders } from "./site-auth";

export const UFOSINT_SIDEQUESTS_ENDPOINT = "/api/ufosint-sidequests";

const ERROR_RESPONSE_LIMIT_BYTES = 16_384;
const SESSION_TOKEN_LIMIT = 8_192;

export interface UfosintSidequestRequestOptions {
  signal?: AbortSignal;
}

export type UfosintSidequestAction =
  | {
      action: "update_lifecycle";
      lifecycle: UfosintSidequestLifecycle;
    }
  | {
      action: "update_task";
      taskId: string;
      status: UfosintSidequestTaskStatus;
      assignee: UfosintActor | null;
      completionNote: string | null;
    }
  | {
      action: "add_finding";
      finding: Omit<UfosintSidequestFindingRevision, "author" | "createdAt">;
    }
  | {
      action: "add_review";
      review: Omit<UfosintSidequestReview, "reviewer" | "createdAt">;
    }
  | {
      action: "attach_artifact";
      artifact: Omit<UfosintSidequestArtifact, "createdBy" | "createdAt">;
      contentBase64: string;
    };

export interface UfosintSidequestActionOptions
  extends UfosintSidequestRequestOptions {
  operationId?: string;
}

export class UfosintSidequestApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;

  constructor(status: number, code: string, message: string, retryable = false) {
    super(message);
    this.name = "UfosintSidequestApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedText(value: unknown, maximum: number, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} must be text.`);
  }
  const normalized = value.trim();
  if (!normalized || normalized.length > maximum) {
    throw new Error(`${label} is missing or exceeds its ${maximum}-character limit.`);
  }
  return normalized;
}

function nullableText(value: unknown, maximum: number, label: string): string | null {
  if (value === null) return null;
  return boundedText(value, maximum, label);
}

function nonnegativeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new Error(`${label} must be a nonnegative safe integer.`);
  }
  return Number(value);
}

function nullableTimestamp(value: unknown, label: string): string | null {
  return value === null ? null : assertUfosintTimestamp(value, label);
}

function validSessionToken(sessionToken: string): string {
  if (
    typeof sessionToken !== "string" ||
    !sessionToken.trim() ||
    sessionToken.length > SESSION_TOKEN_LIMIT ||
    /[\r\n]/u.test(sessionToken)
  ) {
    throw new UfosintSidequestApiError(
      0,
      "authentication_required",
      "A valid Activity session is required for UFOSINT sidequests.",
    );
  }
  return sessionToken;
}

function validReportId(reportId: string): string {
  return boundedText(
    reportId,
    UFOSINT_SIDEQUEST_LIMITS.reportId,
    "UFOSINT report ID",
  );
}

function sidequestActionEndpoint(sidequestId: string): string {
  return `${UFOSINT_SIDEQUESTS_ENDPOINT}/${encodeURIComponent(
    assertUfosintIdentifier(sidequestId, "sidequest ID"),
  )}/actions`;
}

async function readBoundedResponseBytes(
  response: Response,
  maximumBytes: number,
): Promise<Uint8Array> {
  const declaredLength = response.headers.get("Content-Length");
  if (declaredLength !== null) {
    const parsedLength = Number(declaredLength);
    if (Number.isFinite(parsedLength) && parsedLength > maximumBytes) {
      await response.body?.cancel().catch(() => undefined);
      throw new UfosintSidequestApiError(
        response.status,
        "response_too_large",
        "The UFOSINT sidequest endpoint returned an oversized response.",
      );
    }
  }

  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maximumBytes) {
        await reader.cancel().catch(() => undefined);
        throw new UfosintSidequestApiError(
          response.status,
          "response_too_large",
          "The UFOSINT sidequest endpoint returned an oversized response.",
        );
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

async function readBoundedResponseText(
  response: Response,
  maximumBytes: number,
): Promise<string> {
  const bytes = await readBoundedResponseBytes(response, maximumBytes);
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function parseJsonText(text: string, label: string): unknown {
  if (!text.trim()) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new UfosintSidequestApiError(
      0,
      "invalid_json",
      `${label} returned malformed JSON.`,
    );
  }
}

function errorDetail(value: unknown, status: number): UfosintSidequestApiError {
  const record = isRecord(value) ? value : null;
  const nestedError = isRecord(record?.error) ? record.error : null;
  const codeCandidate =
    record?.code ??
    (typeof record?.error === "string" ? record.error : nestedError?.code);
  const detailCandidate =
    record?.detail ?? record?.message ?? nestedError?.message ??
    (typeof record?.error === "string" ? record.error : null);
  const code =
    typeof codeCandidate === "string" && /^[a-z0-9_-]{1,80}$/u.test(codeCandidate)
      ? codeCandidate
      : `http_${status}`;
  const message =
    typeof detailCandidate === "string" && detailCandidate.trim()
      ? detailCandidate.trim().slice(0, 1_000)
      : `The UFOSINT sidequest endpoint returned ${status}.`;
  return new UfosintSidequestApiError(
    status,
    code,
    message,
    status === 409 || status === 429 || status >= 500,
  );
}

async function responseJson(response: Response): Promise<unknown> {
  const maximum = response.ok
    ? UFOSINT_SIDEQUEST_LIMITS.snapshotJsonBytes
    : ERROR_RESPONSE_LIMIT_BYTES;
  let value: unknown;
  try {
    value = parseJsonText(
      await readBoundedResponseText(response, maximum),
      "The UFOSINT sidequest endpoint",
    );
  } catch (error) {
    if (!response.ok && !(error instanceof UfosintSidequestApiError)) {
      throw errorDetail(null, response.status);
    }
    throw error;
  }
  if (!response.ok) throw errorDetail(value, response.status);
  return value;
}

function parseTask(value: unknown, definition: UfosintSidequestTask): UfosintSidequestTask {
  if (!isRecord(value) || !isUfosintSidequestTaskStatus(value.status)) {
    throw new Error(`Task ${definition.taskId} has an invalid status.`);
  }
  return {
    ...definition,
    status: value.status,
    assignee:
      value.assignee === null
        ? null
        : assertUfosintActor(value.assignee, `task ${definition.taskId} assignee`),
    completionNote: nullableText(
      value.completionNote,
      UFOSINT_SIDEQUEST_LIMITS.completionNote,
      `task ${definition.taskId} completion note`,
    ),
    completedAt: nullableTimestamp(
      value.completedAt,
      `task ${definition.taskId} completion time`,
    ),
    updatedAt: assertUfosintTimestamp(
      value.updatedAt,
      `task ${definition.taskId} update time`,
    ),
  };
}

function unique(values: readonly string[], label: string): void {
  if (new Set(values).size !== values.length) {
    throw new Error(`${label} must be unique.`);
  }
}

export function parseUfosintSidequestSnapshot(
  value: unknown,
): UfosintSidequestSnapshot {
  if (!isRecord(value) || value.schemaVersion !== UFOSINT_SIDEQUEST_SCHEMA_VERSION) {
    throw new Error("UFOSINT sidequest response has an unsupported schema.");
  }
  if (value.environment !== "live" && value.environment !== "test") {
    throw new Error("UFOSINT sidequest response has an invalid environment.");
  }
  if (!isUfosintSidequestLifecycle(value.lifecycle)) {
    throw new Error("UFOSINT sidequest response has an invalid lifecycle.");
  }

  const sidequestId = assertUfosintIdentifier(value.sidequestId, "sidequest ID");
  const reportId = boundedText(
    value.reportId,
    UFOSINT_SIDEQUEST_LIMITS.reportId,
    "sidequest report ID",
  );
  const reportSnapshot = parseUfosintReportSnapshot(value.reportSnapshot);
  if (reportSnapshot.reportId !== reportId) {
    throw new Error("UFOSINT sidequest report identifiers do not match.");
  }
  if (!Array.isArray(value.tasks)) {
    throw new Error("UFOSINT sidequest checklist is missing.");
  }
  const definitions = parseUfosintTaskDefinitions(value.tasks);
  const taskValues = new Map(
    value.tasks.map((task) => [
      isRecord(task) && typeof task.taskId === "string" ? task.taskId : "",
      task,
    ]),
  );
  const tasks = definitions.map((definition) => {
    const fullDefinition: UfosintSidequestTask = {
      ...definition,
      status: "pending",
      assignee: null,
      completionNote: null,
      completedAt: null,
      updatedAt: "",
    };
    return parseTask(taskValues.get(definition.taskId), fullDefinition);
  });

  const taskCounts = Object.fromEntries(
    UFOSINT_SIDEQUEST_TASK_STATUSES.map((status) => [
      status,
      tasks.filter((task) => task.status === status).length,
    ]),
  ) as Record<UfosintSidequestTaskStatus, number>;
  if (!isRecord(value.taskCounts)) {
    throw new Error("UFOSINT sidequest checklist counts are missing.");
  }
  for (const status of UFOSINT_SIDEQUEST_TASK_STATUSES) {
    if (value.taskCounts[status] !== taskCounts[status]) {
      throw new Error(`UFOSINT sidequest ${status} task count is inconsistent.`);
    }
  }

  if (
    !Array.isArray(value.findings) ||
    value.findings.length > UFOSINT_SIDEQUEST_LIMITS.findingCount ||
    !Array.isArray(value.reviews) ||
    value.reviews.length > UFOSINT_SIDEQUEST_LIMITS.findingCount ||
    !Array.isArray(value.artifacts) ||
    value.artifacts.length > UFOSINT_SIDEQUEST_LIMITS.artifactCount
  ) {
    throw new Error("UFOSINT sidequest evidence collections exceed their limits.");
  }
  const findings = value.findings.map(parseUfosintFindingRevision);
  const reviews = value.reviews.map(parseUfosintSidequestReview);
  const artifacts = value.artifacts.map(parseUfosintSidequestArtifact);
  unique(
    findings.map((finding) => `${finding.findingId}:${finding.revision}`),
    "Finding revisions",
  );
  unique(reviews.map((review) => review.reviewId), "Review IDs");
  unique(artifacts.map((artifact) => artifact.artifactId), "Artifact IDs");

  const reportSnapshotSha256 = boundedText(
    value.reportSnapshotSha256,
    64,
    "report snapshot hash",
  );
  if (!/^[a-f0-9]{64}$/u.test(reportSnapshotSha256)) {
    throw new Error("UFOSINT report snapshot hash is invalid.");
  }

  return {
    schemaVersion: UFOSINT_SIDEQUEST_SCHEMA_VERSION,
    templateVersion: boundedText(
      value.templateVersion,
      UFOSINT_SIDEQUEST_LIMITS.title,
      "sidequest template version",
    ),
    environment: value.environment,
    sidequestId,
    reportId,
    reportTitle: boundedText(
      value.reportTitle,
      UFOSINT_SIDEQUEST_LIMITS.reportTitle,
      "sidequest report title",
    ),
    title: boundedText(value.title, UFOSINT_SIDEQUEST_LIMITS.title, "sidequest title"),
    lifecycle: value.lifecycle,
    revision: nonnegativeInteger(value.revision, "sidequest revision"),
    taskCounts,
    createdAt: assertUfosintTimestamp(value.createdAt, "sidequest creation time"),
    updatedAt: assertUfosintTimestamp(value.updatedAt, "sidequest update time"),
    reportSnapshot,
    reportSnapshotSha256,
    openedBy: assertUfosintActor(value.openedBy, "sidequest opener"),
    concludedAt: nullableTimestamp(value.concludedAt, "sidequest conclusion time"),
    archivedAt: nullableTimestamp(value.archivedAt, "sidequest archive time"),
    tasks,
    findings,
    reviews,
    artifacts,
  };
}

function snapshotCandidate(value: unknown, requestedReportId: string): unknown | null {
  if (value === null) return null;
  if (Array.isArray(value)) {
    return value.find(
      (item) => isRecord(item) && item.reportId === requestedReportId,
    ) ?? null;
  }
  if (!isRecord(value)) return value;
  if ("sidequest" in value) return value.sidequest;
  if ("snapshot" in value) return value.snapshot;
  if (Array.isArray(value.sidequests)) {
    return value.sidequests.find(
      (item) => isRecord(item) && item.reportId === requestedReportId,
    ) ?? null;
  }
  return value;
}

function parseSnapshotResponse(value: unknown, reportId: string): UfosintSidequestSnapshot {
  const candidate = snapshotCandidate(value, reportId);
  if (candidate === null) {
    throw new UfosintSidequestApiError(
      0,
      "missing_sidequest",
      "The UFOSINT sidequest response did not contain the requested sidequest.",
    );
  }
  try {
    const snapshot = parseUfosintSidequestSnapshot(candidate);
    if (snapshot.reportId !== reportId) {
      throw new Error("The returned sidequest belongs to another report.");
    }
    return snapshot;
  } catch (error) {
    if (error instanceof UfosintSidequestApiError) throw error;
    throw new UfosintSidequestApiError(
      0,
      "invalid_response",
      error instanceof Error
        ? error.message
        : "The UFOSINT sidequest response failed validation.",
    );
  }
}

export async function loadUfosintSidequest(
  reportId: string,
  sessionToken: string,
  options: UfosintSidequestRequestOptions = {},
): Promise<UfosintSidequestSnapshot | null> {
  const requestedReportId = validReportId(reportId);
  const url = new URL(UFOSINT_SIDEQUESTS_ENDPOINT, window.location.origin);
  url.searchParams.set("reportId", requestedReportId);
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      ...siteAuthHeaders(validSessionToken(sessionToken)),
    },
    cache: "no-store",
    signal: options.signal,
  });
  if (response.status === 404) {
    await readBoundedResponseText(response, ERROR_RESPONSE_LIMIT_BYTES).catch(
      () => undefined,
    );
    return null;
  }
  const value = await responseJson(response);
  const candidate = snapshotCandidate(value, requestedReportId);
  return candidate === null ? null : parseSnapshotResponse(candidate, requestedReportId);
}

export async function createUfosintSidequest(
  reportId: string,
  sessionToken: string,
  options: UfosintSidequestRequestOptions = {},
): Promise<UfosintSidequestSnapshot> {
  const requestedReportId = validReportId(reportId);
  const body = assertBoundedJson(
    { reportId: requestedReportId },
    UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
    "UFOSINT sidequest create request",
  );
  const response = await fetch(UFOSINT_SIDEQUESTS_ENDPOINT, {
    method: "POST",
    headers: {
      Accept: "application/json",
      ...siteAuthHeaders(validSessionToken(sessionToken)),
      "Content-Type": "application/json",
    },
    body,
    cache: "no-store",
    signal: options.signal,
  });
  return parseSnapshotResponse(await responseJson(response), requestedReportId);
}

export async function applyUfosintSidequestAction(
  sidequestId: string,
  expectedRevision: number,
  action: UfosintSidequestAction,
  sessionToken: string,
  options: UfosintSidequestActionOptions = {},
): Promise<UfosintSidequestSnapshot> {
  const operationId = assertUfosintIdentifier(
    options.operationId ?? globalThis.crypto.randomUUID(),
    "operation ID",
  );
  const envelope = {
    operationId,
    expectedRevision: nonnegativeInteger(expectedRevision, "expected revision"),
    ...action,
  };
  const body = assertBoundedJson(
    envelope,
    action.action === "attach_artifact"
      ? UFOSINT_SIDEQUEST_LIMITS.artifactAttachmentJsonBytes
      : UFOSINT_SIDEQUEST_LIMITS.eventPayloadBytes,
    "UFOSINT sidequest action",
  );
  const response = await fetch(sidequestActionEndpoint(sidequestId), {
    method: "POST",
    headers: {
      Accept: "application/json",
      ...siteAuthHeaders(validSessionToken(sessionToken)),
      "Content-Type": "application/json",
    },
    body,
    cache: "no-store",
    signal: options.signal,
  });
  const value = await responseJson(response);
  const candidate = snapshotCandidate(value, "");
  try {
    const snapshot = parseUfosintSidequestSnapshot(candidate);
    if (snapshot.sidequestId !== sidequestId) {
      throw new Error("The returned sidequest identifier does not match the request.");
    }
    return snapshot;
  } catch (error) {
    if (error instanceof UfosintSidequestApiError) throw error;
    throw new UfosintSidequestApiError(
      0,
      "invalid_response",
      error instanceof Error
        ? error.message
        : "The UFOSINT sidequest response failed validation.",
    );
  }
}

export async function loadUfosintSidequestArtifactContent(
  sidequestId: string,
  artifact: Pick<
    UfosintSidequestArtifact,
    "artifactId" | "byteLength" | "contentSha256" | "mediaType"
  >,
  sessionToken: string,
  options: UfosintSidequestRequestOptions = {},
): Promise<Blob> {
  const safeSidequestId = assertUfosintIdentifier(sidequestId, "sidequest ID");
  const safeArtifactId = assertUfosintIdentifier(artifact.artifactId, "artifact ID");
  const endpoint =
    `${UFOSINT_SIDEQUESTS_ENDPOINT}/${encodeURIComponent(safeSidequestId)}` +
    `/artifacts/${encodeURIComponent(safeArtifactId)}/content`;
  const response = await fetch(endpoint, {
    headers: {
      Accept: artifact.mediaType,
      ...siteAuthHeaders(validSessionToken(sessionToken)),
    },
    cache: "no-store",
    signal: options.signal,
  });
  if (!response.ok) {
    throw errorDetail(
      parseJsonText(
        await readBoundedResponseText(response, ERROR_RESPONSE_LIMIT_BYTES),
        "The UFOSINT artifact endpoint",
      ),
      response.status,
    );
  }
  const bytes = await readBoundedResponseBytes(
    response,
    UFOSINT_SIDEQUEST_LIMITS.artifactContentBytes,
  );
  if (bytes.byteLength !== artifact.byteLength) {
    throw new UfosintSidequestApiError(
      0,
      "artifact_byte_length_mismatch",
      "Downloaded artifact bytes do not match the immutable byte length.",
    );
  }
  const digest = new Uint8Array(
    await globalThis.crypto.subtle.digest("SHA-256", bytes.slice().buffer),
  );
  const contentSha256 = [...digest]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  if (contentSha256 !== artifact.contentSha256) {
    throw new UfosintSidequestApiError(
      0,
      "artifact_content_hash_mismatch",
      "Downloaded artifact bytes do not match the immutable SHA-256 digest.",
    );
  }
  return new Blob([bytes.slice().buffer], { type: artifact.mediaType });
}
