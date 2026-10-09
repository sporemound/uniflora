import {
  FINDING_REVIEW_DISPOSITIONS,
  type FindingReviewDisposition,
  type FindingReviewRubric,
  type ProvenanceAvailability,
} from "./finding-review";

export const UFOSINT_SIDEQUEST_SCHEMA_VERSION = "1.0.0" as const;
export const UFOSINT_REPORT_SNAPSHOT_SCHEMA_VERSION = "1.0.0" as const;
export const UFOSINT_SIDEQUEST_TEMPLATE_VERSION = "ufosint-sidequest-v1" as const;

export const UFOSINT_SIDEQUEST_LIFECYCLES = [
  "open",
  "collecting",
  "review",
  "concluded",
  "archived",
] as const;

export const UFOSINT_SIDEQUEST_TASK_KINDS = [
  "provenance",
  "witness",
  "geographic",
  "temporal",
  "meteorological",
  "aviation",
  "astronomical",
  "sensor",
  "alternative_hypothesis",
  "synthesis",
  "peer_review",
] as const;

export const UFOSINT_SIDEQUEST_TASK_STATUSES = [
  "pending",
  "in_progress",
  "completed",
  "waived",
  "unavailable",
] as const;

export const UFOSINT_SIDEQUEST_TASK_STATUS_LABELS = Object.freeze({
  pending: "Pending",
  in_progress: "In progress",
  completed: "Completed",
  waived: "Waived as nonrequired",
  unavailable: "Unavailable from external sources",
} as const satisfies Record<UfosintSidequestTaskStatus, string>);

export const UFOSINT_FINDING_KINDS = [
  "observation",
  "provenance",
  "correlation",
  "ordinary_explanation",
  "limitation",
  "conclusion",
] as const;

export const UFOSINT_FINDING_CONFIDENCE = [
  "unknown",
  "low",
  "moderate",
  "high",
] as const;

export const UFOSINT_ARTIFACT_KINDS = [
  "source_capture",
  "metadata_extract",
  "weather_context",
  "flight_context",
  "satellite_context",
  "astronomical_context",
  "geospatial_analysis",
  "dynamical_analysis",
  "timeline",
  "comparison_matrix",
  "narrative_note",
] as const;

export const UFOSINT_PROVENANCE_PARENT_TYPES = [
  "report_snapshot",
  "artifact",
  "external_source",
] as const;

export const UFOSINT_PROVENANCE_RELATIONS = [
  "derived_from",
  "summarizes",
  "visualizes",
  "validates",
  "challenges",
  "contextualizes",
] as const;

export const UFOSINT_EVIDENCE_SOURCE_TYPES = [
  "report_snapshot",
  "artifact",
  "external_source",
  "map_observation",
] as const;

export const UFOSINT_PROVENANCE_AVAILABILITY = [
  "available",
  "incomplete",
  "unavailable",
] as const satisfies readonly ProvenanceAvailability[];

export const UFOSINT_SIDEQUEST_LIMITS = Object.freeze({
  id: 128,
  reportId: 180,
  title: 240,
  reportTitle: 180,
  reportSummary: 2_000,
  locationName: 180,
  coordinatePrecision: 64,
  sourceName: 180,
  taskCount: 24,
  taskInstructions: 4_000,
  completionNote: 2_000,
  findingCount: 128,
  findingAggregateJsonBytes: 300_000,
  findingStatement: 2_000,
  findingInterpretation: 4_000,
  limitationCount: 16,
  limitation: 1_000,
  evidenceReferenceCount: 32,
  evidenceLabel: 240,
  reviewRationale: 2_000,
  reviewAggregateJsonBytes: 150_000,
  artifactCount: 128,
  artifactAggregateJsonBytes: 300_000,
  artifactAggregateContentBytes: 8_000_000,
  artifactMediaType: 120,
  artifactUri: 2_000,
  artifactContentBytes: 256_000,
  artifactContentBase64Length: 341_336,
  artifactAttachmentJsonBytes: 640_000,
  provenanceCount: 32,
  provenanceDescription: 1_000,
  dynamicalEntries: 64,
  jsonBytes: 256_000,
  snapshotJsonBytes: 1_000_000,
  displayName: 120,
  eventPayloadBytes: 128_000,
} as const);

export type UfosintSidequestEnvironment = "live" | "test";
export type UfosintSidequestLifecycle =
  (typeof UFOSINT_SIDEQUEST_LIFECYCLES)[number];
export type UfosintSidequestTaskKind =
  (typeof UFOSINT_SIDEQUEST_TASK_KINDS)[number];
export type UfosintSidequestTaskStatus =
  (typeof UFOSINT_SIDEQUEST_TASK_STATUSES)[number];
export type UfosintFindingKind = (typeof UFOSINT_FINDING_KINDS)[number];
export type UfosintFindingConfidence =
  (typeof UFOSINT_FINDING_CONFIDENCE)[number];
export type UfosintArtifactKind = (typeof UFOSINT_ARTIFACT_KINDS)[number];
export type UfosintProvenanceParentType =
  (typeof UFOSINT_PROVENANCE_PARENT_TYPES)[number];
export type UfosintProvenanceRelation =
  (typeof UFOSINT_PROVENANCE_RELATIONS)[number];
export type UfosintEvidenceSourceType =
  (typeof UFOSINT_EVIDENCE_SOURCE_TYPES)[number];
export type UfosintFindingReviewState =
  | "draft"
  | "reviewed"
  | "challenged"
  | "revision_requested";

export interface UfosintActor {
  participantId: string;
  displayName: string;
}

/**
 * A privacy-reduced, immutable copy of the UFOSINT fields used to open a
 * sidequest. It intentionally excludes raw response bodies and contact data.
 */
export interface UfosintReportSnapshot {
  schemaVersion: typeof UFOSINT_REPORT_SNAPSHOT_SCHEMA_VERSION;
  sourceKey: "ufosint";
  reportId: string;
  sourceName: string;
  sourcePageUrl: string;
  sourceUrl: string | null;
  observedAt: string;
  indexedAt: string;
  latitude: number;
  longitude: number;
  title: string;
  locationName: string;
  coordinatePrecision: string;
  summary: string;
  status: "unverified";
  qualityScore: number;
}

export interface UfosintSidequestTaskDefinition {
  taskId: string;
  ordinal: number;
  kind: UfosintSidequestTaskKind;
  title: string;
  instructions: string;
  required: boolean;
}

export interface UfosintSidequestTask extends UfosintSidequestTaskDefinition {
  status: UfosintSidequestTaskStatus;
  assignee: UfosintActor | null;
  completionNote: string | null;
  completedAt: string | null;
  updatedAt: string;
}

export interface UfosintFindingEvidenceReference {
  referenceId: string;
  sourceType: UfosintEvidenceSourceType;
  sourceReference: string;
  label: string;
  availability: ProvenanceAvailability;
  publicSafe: boolean;
}

export interface UfosintSidequestFindingRevision {
  findingId: string;
  revision: number;
  previousRevision: number | null;
  kind: UfosintFindingKind;
  statement: string;
  interpretation: string | null;
  confidence: UfosintFindingConfidence;
  limitations: string[];
  evidenceReferences: UfosintFindingEvidenceReference[];
  artifactIds: string[];
  author: UfosintActor;
  createdAt: string;
}

export interface UfosintSidequestReview {
  reviewId: string;
  findingId: string;
  findingRevision: number;
  reviewer: UfosintActor;
  disposition: FindingReviewDisposition;
  rationale: string;
  rubric: FindingReviewRubric | null;
  createdAt: string;
}

export type UfosintArtifactScalar = string | number | boolean | null;

export interface UfosintNamedValue {
  name: string;
  value: UfosintArtifactScalar;
  unit: string | null;
  uncertainty: string | null;
}

export interface UfosintSoftwareVersion {
  name: string;
  version: string;
}

/** Reproducibility contract for trajectory, propagation, or motion models. */
export interface UfosintDynamicalAnalysis {
  modelId: string;
  modelVersion: string;
  implementation: string;
  coordinateFrame: string;
  timeStandard: string;
  timeWindowStart: string;
  timeWindowEnd: string;
  initialConditions: UfosintNamedValue[];
  parameters: UfosintNamedValue[];
  derivedValues: UfosintNamedValue[];
  assumptions: string[];
  uncertaintyStatements: string[];
  limitations: string[];
  softwareVersions: UfosintSoftwareVersion[];
}

export interface UfosintArtifactProvenance {
  provenanceId: string;
  parentType: UfosintProvenanceParentType;
  parentReference: string;
  parentContentSha256: string | null;
  relation: UfosintProvenanceRelation;
  description: string;
  retrievedAt: string | null;
}

/**
 * Snapshot-safe artifact metadata. Exact bounded bytes are stored separately
 * and are available only through the authenticated immutable-content route.
 */
export interface UfosintSidequestArtifact {
  artifactId: string;
  kind: UfosintArtifactKind;
  title: string;
  mediaType: string;
  contentSha256: string;
  byteLength: number;
  artifactUri: string | null;
  dynamicalAnalysis: UfosintDynamicalAnalysis | null;
  provenance: UfosintArtifactProvenance[];
  createdBy: UfosintActor;
  createdAt: string;
}

export interface UfosintSidequestEvent {
  revision: number;
  operationId: string;
  operationType:
    | "sidequest_created"
    | "lifecycle_updated"
    | "task_updated"
    | "finding_added"
    | "review_added"
    | "artifact_attached";
  requestSha256: string;
  actor: UfosintActor;
  createdAt: string;
}

export interface UfosintSidequestSummary {
  schemaVersion: typeof UFOSINT_SIDEQUEST_SCHEMA_VERSION;
  templateVersion: string;
  environment: UfosintSidequestEnvironment;
  sidequestId: string;
  reportId: string;
  reportTitle: string;
  title: string;
  lifecycle: UfosintSidequestLifecycle;
  revision: number;
  taskCounts: Record<UfosintSidequestTaskStatus, number>;
  createdAt: string;
  updatedAt: string;
}

export interface UfosintSidequestSnapshot extends UfosintSidequestSummary {
  reportSnapshot: UfosintReportSnapshot;
  reportSnapshotSha256: string;
  openedBy: UfosintActor;
  concludedAt: string | null;
  archivedAt: string | null;
  tasks: UfosintSidequestTask[];
  findings: UfosintSidequestFindingRevision[];
  reviews: UfosintSidequestReview[];
  artifacts: UfosintSidequestArtifact[];
}

export interface UfosintSidequestOperationBase {
  environment: UfosintSidequestEnvironment;
  sidequestId: string;
  operationId: string;
  expectedRevision: number;
  actor: UfosintActor;
  occurredAt?: string;
}

export interface CreateUfosintSidequestInput
  extends Omit<UfosintSidequestOperationBase, "expectedRevision"> {
  expectedRevision?: 0;
  templateVersion: string;
  reportSnapshot: UfosintReportSnapshot;
  title: string;
  tasks: UfosintSidequestTaskDefinition[];
}

export interface UpdateUfosintSidequestLifecycleInput
  extends UfosintSidequestOperationBase {
  lifecycle: UfosintSidequestLifecycle;
}

export interface UpdateUfosintSidequestTaskInput
  extends UfosintSidequestOperationBase {
  taskId: string;
  status: UfosintSidequestTaskStatus;
  assignee: UfosintActor | null;
  completionNote: string | null;
}

export interface AddUfosintSidequestFindingInput
  extends UfosintSidequestOperationBase {
  finding: Omit<UfosintSidequestFindingRevision, "author" | "createdAt">;
}

export interface AddUfosintSidequestReviewInput
  extends UfosintSidequestOperationBase {
  review: Omit<UfosintSidequestReview, "reviewer" | "createdAt">;
}

export interface AttachUfosintSidequestArtifactInput
  extends UfosintSidequestOperationBase {
  artifact: Omit<UfosintSidequestArtifact, "createdBy" | "createdAt">;
  contentBase64: string;
}

export class UfosintSidequestValidationError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "UfosintSidequestValidationError";
    this.code = code;
  }
}

type JsonRecord = Record<string, unknown>;

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/u;
const SHA256 = /^[0-9a-f]{64}$/u;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function oneOf<const T extends readonly string[]>(
  value: unknown,
  values: T,
): value is T[number] {
  return typeof value === "string" && values.includes(value);
}

function text(value: unknown, maximum: number, label: string): string {
  if (typeof value !== "string") {
    throw new UfosintSidequestValidationError("invalid_text", `${label} must be text.`);
  }
  const normalized = value.replaceAll("\u0000", " ").trim().replace(/\s+/gu, " ");
  if (!normalized || normalized.length > maximum) {
    throw new UfosintSidequestValidationError(
      "invalid_text",
      `${label} must contain between 1 and ${maximum} characters.`,
    );
  }
  return normalized;
}

function optionalText(
  value: unknown,
  maximum: number,
  label: string,
): string | null {
  if (value === null || value === undefined || value === "") return null;
  return text(value, maximum, label);
}

function identifier(value: unknown, label: string): string {
  const normalized = text(value, UFOSINT_SIDEQUEST_LIMITS.id, label);
  if (!IDENTIFIER.test(normalized)) {
    throw new UfosintSidequestValidationError(
      "invalid_identifier",
      `${label} contains unsupported characters.`,
    );
  }
  return normalized;
}

function isoTimestamp(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new UfosintSidequestValidationError(
      "invalid_timestamp",
      `${label} must be an ISO-8601 timestamp.`,
    );
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new UfosintSidequestValidationError(
      "invalid_timestamp",
      `${label} must be an ISO-8601 timestamp.`,
    );
  }
  return parsed.toISOString();
}

function optionalTimestamp(value: unknown, label: string): string | null {
  return value === null || value === undefined ? null : isoTimestamp(value, label);
}

function sha256(value: unknown, label: string): string {
  if (typeof value !== "string" || !SHA256.test(value)) {
    throw new UfosintSidequestValidationError(
      "invalid_sha256",
      `${label} must be a lowercase SHA-256 digest.`,
    );
  }
  return value;
}

function nonnegativeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new UfosintSidequestValidationError(
      "invalid_integer",
      `${label} must be a nonnegative safe integer.`,
    );
  }
  return Number(value);
}

function positiveInteger(value: unknown, label: string): number {
  const parsed = nonnegativeInteger(value, label);
  if (parsed < 1) {
    throw new UfosintSidequestValidationError(
      "invalid_integer",
      `${label} must be at least one.`,
    );
  }
  return parsed;
}

function httpsUrl(
  value: unknown,
  label: string,
  allowedHosts?: ReadonlySet<string>,
): string {
  const raw = text(value, UFOSINT_SIDEQUEST_LIMITS.artifactUri, label);
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new UfosintSidequestValidationError("invalid_url", `${label} is invalid.`);
  }
  const host = parsed.hostname.toLowerCase().replace(/^www\./u, "").replace(/\.$/u, "");
  if (parsed.protocol !== "https:" || (allowedHosts && !allowedHosts.has(host))) {
    throw new UfosintSidequestValidationError(
      "invalid_url",
      `${label} must use an approved HTTPS host.`,
    );
  }
  parsed.hash = "";
  return parsed.toString();
}

function uniqueBy<T>(values: readonly T[], key: (value: T) => string, label: string): void {
  const keys = values.map(key);
  if (new Set(keys).size !== keys.length) {
    throw new UfosintSidequestValidationError(
      "duplicate_value",
      `${label} must be unique.`,
    );
  }
}

function actor(value: unknown, label = "actor"): UfosintActor {
  if (!isRecord(value)) {
    throw new UfosintSidequestValidationError("invalid_actor", `${label} is invalid.`);
  }
  return {
    participantId: identifier(value.participantId, `${label} participant ID`),
    displayName: text(
      value.displayName,
      UFOSINT_SIDEQUEST_LIMITS.displayName,
      `${label} display name`,
    ),
  };
}

function textArray(
  value: unknown,
  maximumItems: number,
  maximumLength: number,
  label: string,
): string[] {
  if (!Array.isArray(value) || value.length > maximumItems) {
    throw new UfosintSidequestValidationError(
      "invalid_collection",
      `${label} must contain at most ${maximumItems} entries.`,
    );
  }
  const result = value.map((item, index) =>
    text(item, maximumLength, `${label} ${index + 1}`),
  );
  uniqueBy(result, (item) => item, label);
  return result;
}

function findingRubric(value: unknown): FindingReviewRubric | null {
  if (value === null || value === undefined) return null;
  if (!isRecord(value)) {
    throw new UfosintSidequestValidationError("invalid_rubric", "review rubric is invalid.");
  }
  const keys = [
    "evidenceSupport",
    "ordinaryAlternatives",
    "contradictionsPreserved",
    "confidenceCalibration",
    "reproducibility",
  ] as const;
  const result = {} as FindingReviewRubric;
  for (const key of keys) {
    const score = value[key];
    if (!Number.isSafeInteger(score) || Number(score) < 0 || Number(score) > 2) {
      throw new UfosintSidequestValidationError(
        "invalid_rubric",
        `review rubric ${key} must be an integer from zero through two.`,
      );
    }
    result[key] = Number(score);
  }
  return result;
}

export function parseUfosintReportSnapshot(value: unknown): UfosintReportSnapshot {
  if (!isRecord(value) || value.schemaVersion !== UFOSINT_REPORT_SNAPSHOT_SCHEMA_VERSION) {
    throw new UfosintSidequestValidationError(
      "invalid_report_snapshot",
      "UFOSINT report snapshot has an unsupported schema.",
    );
  }
  if (value.sourceKey !== "ufosint" || value.status !== "unverified") {
    throw new UfosintSidequestValidationError(
      "invalid_report_snapshot",
      "A sidequest must be bound to an unverified UFOSINT report.",
    );
  }
  const observedAt = isoTimestamp(value.observedAt, "report observed time");
  const indexedAt = isoTimestamp(value.indexedAt, "report indexed time");
  if (new Date(observedAt).valueOf() > new Date(indexedAt).valueOf() + 15 * 60_000) {
    throw new UfosintSidequestValidationError(
      "invalid_report_snapshot",
      "Report observed time cannot be later than its indexed time.",
    );
  }
  const latitude = Number(value.latitude);
  const longitude = Number(value.longitude);
  if (
    !Number.isFinite(latitude) || latitude < -90 || latitude > 90 ||
    !Number.isFinite(longitude) || longitude < -180 || longitude > 180
  ) {
    throw new UfosintSidequestValidationError(
      "invalid_coordinates",
      "Report coordinates are invalid.",
    );
  }
  // The public feed intentionally reduces coordinates to roughly city scale.
  const quantized = (coordinate: number) =>
    Math.abs(coordinate / 0.05 - Math.round(coordinate / 0.05)) < 1e-7;
  if (!quantized(latitude) || !quantized(longitude)) {
    throw new UfosintSidequestValidationError(
      "coordinates_not_privacy_reduced",
      "UFOSINT report coordinates must use the public 0.05-degree grid.",
    );
  }
  const qualityScore = positiveInteger(value.qualityScore, "report quality score");
  if (qualityScore < 51 || qualityScore > 100) {
    throw new UfosintSidequestValidationError(
      "report_below_quality_gate",
      "UFOSINT sidequests require a quality score from 51 through 100.",
    );
  }
  const sourcePageUrl = httpsUrl(
    value.sourcePageUrl,
    "UFOSINT source page URL",
    new Set(["ufosint.com"]),
  );
  const sourceUrl = value.sourceUrl === null
    ? null
    : httpsUrl(value.sourceUrl, "UFOSINT report URL", new Set(["ufosint.com"]));
  return {
    schemaVersion: UFOSINT_REPORT_SNAPSHOT_SCHEMA_VERSION,
    sourceKey: "ufosint",
    reportId: text(value.reportId, UFOSINT_SIDEQUEST_LIMITS.reportId, "report ID"),
    sourceName: text(
      value.sourceName,
      UFOSINT_SIDEQUEST_LIMITS.sourceName,
      "report source name",
    ),
    sourcePageUrl,
    sourceUrl,
    observedAt,
    indexedAt,
    latitude,
    longitude,
    title: text(value.title, UFOSINT_SIDEQUEST_LIMITS.reportTitle, "report title"),
    locationName: text(
      value.locationName,
      UFOSINT_SIDEQUEST_LIMITS.locationName,
      "report location",
    ),
    coordinatePrecision: text(
      value.coordinatePrecision,
      UFOSINT_SIDEQUEST_LIMITS.coordinatePrecision,
      "coordinate precision",
    ),
    summary: text(
      value.summary,
      UFOSINT_SIDEQUEST_LIMITS.reportSummary,
      "report summary",
    ),
    status: "unverified",
    qualityScore,
  };
}

export function normalizeUfosintReportSnapshot(
  value: unknown,
): UfosintReportSnapshot | null {
  try {
    return parseUfosintReportSnapshot(value);
  } catch {
    return null;
  }
}

export function parseUfosintTaskDefinitions(
  value: unknown,
): UfosintSidequestTaskDefinition[] {
  if (
    !Array.isArray(value) || value.length < 1 ||
    value.length > UFOSINT_SIDEQUEST_LIMITS.taskCount
  ) {
    throw new UfosintSidequestValidationError(
      "invalid_tasks",
      `A sidequest requires 1-${UFOSINT_SIDEQUEST_LIMITS.taskCount} checklist tasks.`,
    );
  }
  const tasks = value.map((item, index): UfosintSidequestTaskDefinition => {
    if (!isRecord(item) || !oneOf(item.kind, UFOSINT_SIDEQUEST_TASK_KINDS)) {
      throw new UfosintSidequestValidationError(
        "invalid_task",
        `Task ${index + 1} is invalid.`,
      );
    }
    if (typeof item.required !== "boolean") {
      throw new UfosintSidequestValidationError(
        "invalid_task",
        `Task ${index + 1} required must be boolean.`,
      );
    }
    return {
      taskId: identifier(item.taskId, `task ${index + 1} ID`),
      ordinal: nonnegativeInteger(item.ordinal, `task ${index + 1} ordinal`),
      kind: item.kind,
      title: text(item.title, UFOSINT_SIDEQUEST_LIMITS.title, `task ${index + 1} title`),
      instructions: text(
        item.instructions,
        UFOSINT_SIDEQUEST_LIMITS.taskInstructions,
        `task ${index + 1} instructions`,
      ),
      required: item.required,
    };
  });
  uniqueBy(tasks, (task) => task.taskId, "task IDs");
  uniqueBy(tasks, (task) => String(task.ordinal), "task ordinals");
  return tasks.sort((left, right) => left.ordinal - right.ordinal);
}

function parseEvidenceReferences(value: unknown): UfosintFindingEvidenceReference[] {
  if (
    !Array.isArray(value) ||
    value.length > UFOSINT_SIDEQUEST_LIMITS.evidenceReferenceCount
  ) {
    throw new UfosintSidequestValidationError(
      "invalid_evidence_references",
      "Finding evidence references are invalid.",
    );
  }
  const references = value.map((item, index): UfosintFindingEvidenceReference => {
    if (
      !isRecord(item) ||
      !oneOf(item.sourceType, UFOSINT_EVIDENCE_SOURCE_TYPES) ||
      !oneOf(item.availability, UFOSINT_PROVENANCE_AVAILABILITY) ||
      typeof item.publicSafe !== "boolean"
    ) {
      throw new UfosintSidequestValidationError(
        "invalid_evidence_reference",
        `Evidence reference ${index + 1} is invalid.`,
      );
    }
    const sourceReference = item.sourceType === "external_source"
      ? httpsUrl(item.sourceReference, `evidence reference ${index + 1} URL`)
      : identifier(item.sourceReference, `evidence reference ${index + 1} source`);
    return {
      referenceId: identifier(item.referenceId, `evidence reference ${index + 1} ID`),
      sourceType: item.sourceType,
      sourceReference,
      label: text(
        item.label,
        UFOSINT_SIDEQUEST_LIMITS.evidenceLabel,
        `evidence reference ${index + 1} label`,
      ),
      availability: item.availability,
      publicSafe: item.publicSafe,
    };
  });
  uniqueBy(references, (reference) => reference.referenceId, "evidence reference IDs");
  return references;
}

export function parseUfosintFindingRevision(
  value: unknown,
): UfosintSidequestFindingRevision {
  if (
    !isRecord(value) ||
    !oneOf(value.kind, UFOSINT_FINDING_KINDS) ||
    !oneOf(value.confidence, UFOSINT_FINDING_CONFIDENCE)
  ) {
    throw new UfosintSidequestValidationError("invalid_finding", "Finding is invalid.");
  }
  const revision = positiveInteger(value.revision, "finding revision");
  const previousRevision = value.previousRevision === null
    ? null
    : positiveInteger(value.previousRevision, "previous finding revision");
  if (
    (revision === 1 && previousRevision !== null) ||
    (revision > 1 && previousRevision !== revision - 1)
  ) {
    throw new UfosintSidequestValidationError(
      "invalid_finding_revision_chain",
      "Finding revision must point to its exact predecessor.",
    );
  }
  const artifactIds = textArray(
    value.artifactIds,
    UFOSINT_SIDEQUEST_LIMITS.artifactCount,
    UFOSINT_SIDEQUEST_LIMITS.id,
    "finding artifact IDs",
  ).map((item) => identifier(item, "finding artifact ID"));
  return {
    findingId: identifier(value.findingId, "finding ID"),
    revision,
    previousRevision,
    kind: value.kind,
    statement: text(
      value.statement,
      UFOSINT_SIDEQUEST_LIMITS.findingStatement,
      "finding statement",
    ),
    interpretation: optionalText(
      value.interpretation,
      UFOSINT_SIDEQUEST_LIMITS.findingInterpretation,
      "finding interpretation",
    ),
    confidence: value.confidence,
    limitations: textArray(
      value.limitations,
      UFOSINT_SIDEQUEST_LIMITS.limitationCount,
      UFOSINT_SIDEQUEST_LIMITS.limitation,
      "finding limitations",
    ),
    evidenceReferences: parseEvidenceReferences(value.evidenceReferences),
    artifactIds,
    author: actor(value.author, "finding author"),
    createdAt: isoTimestamp(value.createdAt, "finding creation time"),
  };
}

export function parseUfosintSidequestReview(value: unknown): UfosintSidequestReview {
  if (!isRecord(value) || !oneOf(value.disposition, FINDING_REVIEW_DISPOSITIONS)) {
    throw new UfosintSidequestValidationError("invalid_review", "Finding review is invalid.");
  }
  return {
    reviewId: identifier(value.reviewId, "review ID"),
    findingId: identifier(value.findingId, "review finding ID"),
    findingRevision: positiveInteger(value.findingRevision, "review finding revision"),
    reviewer: actor(value.reviewer, "reviewer"),
    disposition: value.disposition,
    rationale: text(
      value.rationale,
      UFOSINT_SIDEQUEST_LIMITS.reviewRationale,
      "review rationale",
    ),
    rubric: findingRubric(value.rubric),
    createdAt: isoTimestamp(value.createdAt, "review creation time"),
  };
}

function parseNamedValues(value: unknown, label: string): UfosintNamedValue[] {
  if (!Array.isArray(value) || value.length > UFOSINT_SIDEQUEST_LIMITS.dynamicalEntries) {
    throw new UfosintSidequestValidationError("invalid_dynamical_analysis", `${label} is invalid.`);
  }
  const result = value.map((item, index): UfosintNamedValue => {
    if (!isRecord(item)) {
      throw new UfosintSidequestValidationError(
        "invalid_dynamical_analysis",
        `${label} ${index + 1} is invalid.`,
      );
    }
    const scalar = item.value;
    if (
      scalar !== null && typeof scalar !== "string" &&
      typeof scalar !== "number" && typeof scalar !== "boolean"
    ) {
      throw new UfosintSidequestValidationError(
        "invalid_dynamical_analysis",
        `${label} ${index + 1} value must be scalar.`,
      );
    }
    if (typeof scalar === "number" && !Number.isFinite(scalar)) {
      throw new UfosintSidequestValidationError(
        "invalid_dynamical_analysis",
        `${label} ${index + 1} value must be finite.`,
      );
    }
    return {
      name: identifier(item.name, `${label} ${index + 1} name`),
      value: scalar,
      unit: optionalText(item.unit, 64, `${label} ${index + 1} unit`),
      uncertainty: optionalText(
        item.uncertainty,
        500,
        `${label} ${index + 1} uncertainty`,
      ),
    };
  });
  uniqueBy(result, (item) => item.name, `${label} names`);
  return result;
}

function parseDynamicalAnalysis(value: unknown): UfosintDynamicalAnalysis {
  if (!isRecord(value)) {
    throw new UfosintSidequestValidationError(
      "invalid_dynamical_analysis",
      "Dynamical analysis metadata is required.",
    );
  }
  const timeWindowStart = isoTimestamp(value.timeWindowStart, "model time-window start");
  const timeWindowEnd = isoTimestamp(value.timeWindowEnd, "model time-window end");
  if (timeWindowStart >= timeWindowEnd) {
    throw new UfosintSidequestValidationError(
      "invalid_dynamical_analysis",
      "Dynamical model time-window start must precede its end.",
    );
  }
  if (!Array.isArray(value.softwareVersions) || value.softwareVersions.length < 1 || value.softwareVersions.length > 32) {
    throw new UfosintSidequestValidationError(
      "invalid_dynamical_analysis",
      "Dynamical analysis requires bounded software-version provenance.",
    );
  }
  const softwareVersions = value.softwareVersions.map((item, index): UfosintSoftwareVersion => {
    if (!isRecord(item)) {
      throw new UfosintSidequestValidationError(
        "invalid_dynamical_analysis",
        `Software version ${index + 1} is invalid.`,
      );
    }
    return {
      name: text(item.name, 120, `software ${index + 1} name`),
      version: text(item.version, 120, `software ${index + 1} version`),
    };
  });
  uniqueBy(softwareVersions, (item) => item.name, "software names");
  const derivedValues = parseNamedValues(value.derivedValues, "derived values");
  if (derivedValues.length < 1) {
    throw new UfosintSidequestValidationError(
      "invalid_dynamical_analysis",
      "Dynamical analysis requires at least one derived value.",
    );
  }
  const uncertaintyStatements = textArray(
    value.uncertaintyStatements,
    32,
    UFOSINT_SIDEQUEST_LIMITS.limitation,
    "uncertainty statements",
  );
  const limitations = textArray(
    value.limitations,
    UFOSINT_SIDEQUEST_LIMITS.limitationCount,
    UFOSINT_SIDEQUEST_LIMITS.limitation,
    "dynamical limitations",
  );
  if (uncertaintyStatements.length < 1 || limitations.length < 1) {
    throw new UfosintSidequestValidationError(
      "invalid_dynamical_analysis",
      "Dynamical analysis requires uncertainty and limitation statements.",
    );
  }
  return {
    modelId: identifier(value.modelId, "model ID"),
    modelVersion: text(value.modelVersion, 120, "model version"),
    implementation: text(value.implementation, 500, "model implementation"),
    coordinateFrame: text(value.coordinateFrame, 120, "model coordinate frame"),
    timeStandard: text(value.timeStandard, 64, "model time standard"),
    timeWindowStart,
    timeWindowEnd,
    initialConditions: parseNamedValues(value.initialConditions, "initial conditions"),
    parameters: parseNamedValues(value.parameters, "model parameters"),
    derivedValues,
    assumptions: textArray(value.assumptions, 32, 1_000, "model assumptions"),
    uncertaintyStatements,
    limitations,
    softwareVersions,
  };
}

function parseProvenance(value: unknown): UfosintArtifactProvenance[] {
  if (
    !Array.isArray(value) || value.length < 1 ||
    value.length > UFOSINT_SIDEQUEST_LIMITS.provenanceCount
  ) {
    throw new UfosintSidequestValidationError(
      "invalid_provenance",
      "Artifacts require one or more bounded provenance inputs.",
    );
  }
  const result = value.map((item, index): UfosintArtifactProvenance => {
    if (
      !isRecord(item) ||
      !oneOf(item.parentType, UFOSINT_PROVENANCE_PARENT_TYPES) ||
      !oneOf(item.relation, UFOSINT_PROVENANCE_RELATIONS)
    ) {
      throw new UfosintSidequestValidationError(
        "invalid_provenance",
        `Artifact provenance ${index + 1} is invalid.`,
      );
    }
    const parentReference = item.parentType === "external_source"
      ? httpsUrl(item.parentReference, `provenance ${index + 1} source URL`)
      : identifier(item.parentReference, `provenance ${index + 1} parent reference`);
    return {
      provenanceId: identifier(item.provenanceId, `provenance ${index + 1} ID`),
      parentType: item.parentType,
      parentReference,
      parentContentSha256: item.parentContentSha256 === null
        ? null
        : sha256(item.parentContentSha256, `provenance ${index + 1} content hash`),
      relation: item.relation,
      description: text(
        item.description,
        UFOSINT_SIDEQUEST_LIMITS.provenanceDescription,
        `provenance ${index + 1} description`,
      ),
      retrievedAt: optionalTimestamp(item.retrievedAt, `provenance ${index + 1} retrieval time`),
    };
  });
  uniqueBy(result, (item) => item.provenanceId, "artifact provenance IDs");
  return result;
}

export function parseUfosintSidequestArtifact(
  value: unknown,
): UfosintSidequestArtifact {
  if (!isRecord(value) || !oneOf(value.kind, UFOSINT_ARTIFACT_KINDS)) {
    throw new UfosintSidequestValidationError("invalid_artifact", "Artifact is invalid.");
  }
  const artifactUri = value.artifactUri === null
    ? null
    : httpsUrl(value.artifactUri, "artifact URI");
  const dynamicalAnalysis = value.dynamicalAnalysis === null
    ? null
    : parseDynamicalAnalysis(value.dynamicalAnalysis);
  if (
    (value.kind === "dynamical_analysis" && dynamicalAnalysis === null) ||
    (value.kind !== "dynamical_analysis" && dynamicalAnalysis !== null)
  ) {
    throw new UfosintSidequestValidationError(
      "invalid_artifact",
      "Only dynamical-analysis artifacts may carry the dynamical reproducibility contract.",
    );
  }
  return {
    artifactId: identifier(value.artifactId, "artifact ID"),
    kind: value.kind,
    title: text(value.title, UFOSINT_SIDEQUEST_LIMITS.title, "artifact title"),
    mediaType: text(
      value.mediaType,
      UFOSINT_SIDEQUEST_LIMITS.artifactMediaType,
      "artifact media type",
    ),
    contentSha256: sha256(value.contentSha256, "artifact content hash"),
    byteLength: nonnegativeInteger(value.byteLength, "artifact byte length"),
    artifactUri,
    dynamicalAnalysis,
    provenance: parseProvenance(value.provenance),
    createdBy: actor(value.createdBy, "artifact creator"),
    createdAt: isoTimestamp(value.createdAt, "artifact creation time"),
  };
}

export function deriveUfosintFindingReviewState(
  finding: Pick<UfosintSidequestFindingRevision, "findingId" | "revision">,
  reviews: readonly UfosintSidequestReview[],
): UfosintFindingReviewState {
  const exact = reviews.filter(
    (review) =>
      review.findingId === finding.findingId &&
      review.findingRevision === finding.revision,
  );
  if (exact.some((review) => review.disposition === "challenge")) return "challenged";
  if (exact.some((review) => review.disposition === "request_revision")) {
    return "revision_requested";
  }
  if (exact.some((review) => review.disposition === "endorse")) return "reviewed";
  return "draft";
}

const SIDEQUEST_TRANSITIONS: Record<
  UfosintSidequestLifecycle,
  readonly UfosintSidequestLifecycle[]
> = {
  open: ["collecting", "archived"],
  collecting: ["review", "archived"],
  review: ["collecting", "concluded", "archived"],
  concluded: ["archived"],
  archived: [],
};

export function canTransitionUfosintSidequest(
  current: UfosintSidequestLifecycle,
  next: UfosintSidequestLifecycle,
): boolean {
  return SIDEQUEST_TRANSITIONS[current].includes(next);
}

const TASK_TRANSITIONS: Record<
  UfosintSidequestTaskStatus,
  readonly UfosintSidequestTaskStatus[]
> = {
  pending: ["in_progress", "completed", "waived", "unavailable"],
  in_progress: ["pending", "completed", "waived", "unavailable"],
  completed: [],
  waived: [],
  unavailable: [],
};

export function canTransitionUfosintTask(
  current: UfosintSidequestTaskStatus,
  next: UfosintSidequestTaskStatus,
): boolean {
  return current === next || TASK_TRANSITIONS[current].includes(next);
}

export function isUfosintSidequestLifecycle(
  value: unknown,
): value is UfosintSidequestLifecycle {
  return oneOf(value, UFOSINT_SIDEQUEST_LIFECYCLES);
}

export function isUfosintSidequestTaskStatus(
  value: unknown,
): value is UfosintSidequestTaskStatus {
  return oneOf(value, UFOSINT_SIDEQUEST_TASK_STATUSES);
}

export function assertBoundedJson(value: unknown, maximumBytes: number, label: string): string {
  const serialized = JSON.stringify(value);
  if (new TextEncoder().encode(serialized).byteLength > maximumBytes) {
    throw new UfosintSidequestValidationError(
      "payload_too_large",
      `${label} exceeds its ${maximumBytes}-byte limit.`,
    );
  }
  return serialized;
}

export function assertUfosintActor(value: unknown, label = "actor"): UfosintActor {
  return actor(value, label);
}

export function assertUfosintIdentifier(value: unknown, label: string): string {
  return identifier(value, label);
}

export function assertUfosintTimestamp(value: unknown, label: string): string {
  return isoTimestamp(value, label);
}
