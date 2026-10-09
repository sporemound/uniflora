import {
  FINDING_INTERPRETATION_MAX_LENGTH,
  FINDING_LIMITATION_MAX_LENGTH,
  FINDING_REVISION_REASON_MAX_LENGTH,
  FINDING_STATEMENT_MAX_LENGTH,
  REFERENCE_LABEL_MAX_LENGTH,
  RELATIONSHIP_RATIONALE_MAX_LENGTH,
  REVIEW_RATIONALE_MAX_LENGTH,
  assessPromotion,
  canStartReview,
  canWithdrawFinding,
  createPublicConclusion,
  effectiveReviewLifecycle,
  isAnalysisReferenceStructurallyValid,
  isEvidenceReferenceStructurallyValid,
  isFindingRelationshipType,
  isFindingReviewDisposition,
  isFindingReviewRubric,
  isReviewBlockerResolved,
  isSafeIdentifier,
  type FindingAnalysisArtifactReference,
  type FindingEvidenceReference,
  type FindingLifecycleState,
  type FindingRelationship,
  type FindingReview,
  type FindingReviewResolution,
  type FindingRevision,
  type ProvenanceAvailability,
} from "../../src/shared/finding-review";
import {
  FINDING_OBSERVATION_MAX_LENGTH,
  FINDING_TITLE_MAX_LENGTH,
  INVESTIGATION_ROOM_PROTOCOL_VERSION,
  OPERATION_ID_MAX_LENGTH,
  type InvestigationRoomReviewState,
  type InvestigationRoomSnapshot,
  type RoomClientMessage,
  type RoomFinding,
  type RoomLayerState,
  type RoomOperationErrorCategory,
  type RoomOperationErrorDetails,
  type RoomParticipant,
  type RoomScientificSelection,
  type RoomServerMessage,
} from "../../src/shared/investigation-room";
import { HttpError } from "./errors";
import {
  applyFindingReviewPatch,
  emptyFindingReviewState,
  findingReviewSnapshot,
  findingRevisionKey,
  isValidFindingReviewEventSequence,
  normalizeFindingReviewState,
  replayFindingReviewEvents,
  type FindingReviewDomainEvent,
  type FindingReviewStatePatch,
  type PersistedFindingReviewState,
} from "./finding-review";
import type { RoomTicketPayload } from "./room-ticket";
import type {
  DurableObjectState,
  HibernatingWebSocket,
} from "./cloudflare";

interface SocketAttachment {
  ticket: RoomTicketPayload;
  connectedAt: string;
  messageWindowStartedAt?: number;
  messageCount?: number;
}

interface StoredOperation {
  participantId: string;
  requestFingerprint: string;
  responseType: string;
  resultRoomRevision: number;
}

interface PersistedRoomState {
  schemaVersion: 2;
  roomId: string;
  artifactId: string;
  visualizationId: string;
  roomRevision: number;
  presenterParticipantId: string | null;
  selection: RoomScientificSelection | null;
  layers: RoomLayerState;
  reviewState: PersistedFindingReviewState;
  findingEvents: FindingReviewDomainEvent[];
  processedOperations: Record<string, StoredOperation>;
  usedTickets: Record<string, number>;
}

interface LegacyPersistedRoomState {
  schemaVersion?: 1;
  roomId: string;
  artifactId: string;
  visualizationId: string;
  roomRevision: number;
  selection: RoomScientificSelection | null;
  layers: RoomLayerState;
  findings?: Record<string, RoomFinding>;
  processedOperations?: Record<string, RoomServerMessage>;
  usedTickets?: Record<string, number>;
}

const STATE_KEY = "phase4b-room-state";
const MAX_ROOM_CONNECTIONS = 8;
const MAX_CONNECTIONS_PER_PARTICIPANT = 4;
const MAX_WEBSOCKET_MESSAGE_BYTES = 64 * 1024;
const MESSAGE_RATE_WINDOW_MS = 10_000;
const MAX_MESSAGES_PER_WINDOW = 40;
const MAX_ROOM_STATE_BYTES = 512 * 1024;
const MAX_FINDINGS = 64;
const MAX_REVISIONS = 256;
const MAX_REVIEWS = 256;
const MAX_REVIEW_RESOLUTIONS = 256;
const MAX_RELATIONSHIPS = 128;
const MAX_PUBLIC_CONCLUSIONS = 64;
const MAX_FINDING_EVENTS = 512;
const MAX_PROCESSED_OPERATIONS = 512;
const MAX_EVIDENCE_REFERENCES = 64;
const MAX_USED_TICKETS = 256;
const MAX_SOCKET_AGE_MS = 15 * 60 * 1_000;
const DEFAULT_LAYERS: RoomLayerState = {
  rawVoltageV: true,
  calibratedVoltageV: true,
  residualVoltageV: false,
  uncertainty: true,
};

function safeRecord<T>(): Record<string, T> {
  return Object.create(null) as Record<string, T>;
}

function copyRecord<T>(value: Record<string, T> | undefined): Record<string, T> {
  const result = safeRecord<T>();
  if (!value || typeof value !== "object") return result;
  for (const [key, item] of Object.entries(value)) result[key] = item;
  return result;
}

function hasOwn(record: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(record, key);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(
  value: unknown,
  field: string,
  maximum: number,
  options: { required?: boolean; nullable?: boolean } = {},
): string | null {
  if (value === null && options.nullable) return null;
  if (typeof value !== "string") {
    throw roomError(
      "malformed_request",
      `${field} must be a string${options.nullable ? " or null" : ""}.`,
      "malformed_request",
    );
  }
  const normalized = value.trim();
  if (options.required && !normalized) {
    throw roomError("malformed_request", `${field} is required.`, "malformed_request");
  }
  if (normalized.length > maximum) {
    throw roomError(
      "malformed_request",
      `${field} exceeds ${maximum} characters.`,
      "malformed_request",
    );
  }
  return normalized;
}

function stringArray(
  value: unknown,
  field: string,
  maximumItems: number,
  maximumItemLength: number,
): string[] {
  if (!Array.isArray(value) || value.length > maximumItems) {
    throw roomError(
      "malformed_request",
      `${field} must be an array with at most ${maximumItems} entries.`,
      "malformed_request",
    );
  }
  return value.map((item, index) => {
    const parsed = text(
      item,
      `${field}[${index}]`,
      maximumItemLength,
      { required: true },
    );
    return parsed as string;
  });
}

function parseOperationId(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length < 8 ||
    value.length > OPERATION_ID_MAX_LENGTH ||
    !/^[A-Za-z0-9_-]+$/u.test(value) ||
    value === "__proto__" ||
    value === "constructor"
  ) {
    throw roomError(
      "invalid_operation",
      "operationId is invalid.",
      "malformed_request",
    );
  }
  return value;
}

function parseEntityId(value: unknown, field: string, prefix: string): string {
  if (
    typeof value !== "string" ||
    !value.startsWith(prefix) ||
    !isSafeIdentifier(value)
  ) {
    throw roomError(
      "malformed_request",
      `${field} is invalid.`,
      "malformed_request",
    );
  }
  return value;
}

function parseReferenceId(value: unknown, field: string): string {
  if (typeof value !== "string" || !isSafeIdentifier(value)) {
    throw roomError(
      "malformed_request",
      `${field} is invalid.`,
      "malformed_request",
    );
  }
  return value;
}

function parseExpectedRevision(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw roomError(
      "invalid_operation",
      "expectedRevision must be a non-negative integer.",
      "malformed_request",
    );
  }
  return value as number;
}

function parseFindingRevisionNumber(value: unknown, field = "findingRevision"): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1) {
    throw roomError(
      "malformed_request",
      `${field} must be a positive integer.`,
      "malformed_request",
    );
  }
  return value as number;
}

function parseLayers(value: unknown): RoomLayerState {
  if (!isRecord(value)) {
    throw roomError("invalid_layers", "layers must be an object.", "malformed_request");
  }
  for (const key of [
    "rawVoltageV",
    "calibratedVoltageV",
    "residualVoltageV",
    "uncertainty",
  ] as const) {
    if (typeof value[key] !== "boolean") {
      throw roomError(
        "invalid_layers",
        `${key} must be boolean.`,
        "malformed_request",
      );
    }
  }
  return {
    rawVoltageV: value.rawVoltageV as boolean,
    calibratedVoltageV: value.calibratedVoltageV as boolean,
    residualVoltageV: value.residualVoltageV as boolean,
    uncertainty: value.uncertainty as boolean,
  };
}

function parseSelection(
  value: unknown,
  ticket: RoomTicketPayload,
): RoomScientificSelection {
  if (!isRecord(value)) {
    throw roomError(
      "invalid_selection",
      "selection must be an object.",
      "malformed_request",
    );
  }
  const startSeconds = value.startSeconds;
  const endSeconds = value.endSeconds;
  if (
    typeof startSeconds !== "number" ||
    !Number.isFinite(startSeconds) ||
    typeof endSeconds !== "number" ||
    !Number.isFinite(endSeconds)
  ) {
    throw roomError(
      "invalid_selection",
      "Selection bounds must be finite numbers.",
      "malformed_request",
    );
  }
  if (startSeconds >= endSeconds) {
    throw roomError(
      "invalid_selection",
      "Selection start must precede its end.",
      "malformed_request",
    );
  }
  if (startSeconds < ticket.minimumSeconds || endSeconds > ticket.maximumSeconds) {
    throw roomError(
      "selection_out_of_bounds",
      "Selection is outside the published visualization bounds.",
      "malformed_request",
    );
  }
  if (typeof value.timeBasis !== "string" || !ticket.timeBases.includes(value.timeBasis)) {
    throw roomError(
      "invalid_time_basis",
      "Selection time basis is unavailable.",
      "malformed_request",
    );
  }
  if (value.sourceView !== "waveform" && value.sourceView !== "spectrogram") {
    throw roomError(
      "invalid_selection",
      "Selection source must be waveform or spectrogram.",
      "malformed_request",
    );
  }
  return {
    startSeconds,
    endSeconds,
    timeBasis: value.timeBasis,
    sourceView: value.sourceView,
  };
}

function parseAvailability(value: unknown, field: string): ProvenanceAvailability {
  if (value === "available" || value === "incomplete" || value === "unavailable") {
    return value;
  }
  throw roomError(
    "malformed_request",
    `${field} must be available, incomplete, or unavailable.`,
    "malformed_request",
  );
}

function nullableIdentifier(value: unknown, field: string): string | null {
  if (value === null) return null;
  return parseReferenceId(value, field);
}

function parseEvidenceReferences(value: unknown): FindingEvidenceReference[] {
  if (!Array.isArray(value) || value.length > MAX_EVIDENCE_REFERENCES) {
    throw roomError(
      "malformed_request",
      "evidenceReferences must contain at most 64 entries.",
      "malformed_request",
    );
  }
  return value.map((item, index) => {
    if (!isRecord(item)) {
      throw roomError(
        "malformed_request",
        `evidenceReferences[${index}] must be an object.`,
        "malformed_request",
      );
    }
    if (item.sourceType !== "observation" && item.sourceType !== "activity_artifact") {
      throw roomError(
        "malformed_request",
        `evidenceReferences[${index}].sourceType is invalid.`,
        "malformed_request",
      );
    }
    if (typeof item.publicSafe !== "boolean") {
      throw roomError(
        "malformed_request",
        `evidenceReferences[${index}].publicSafe must be boolean.`,
        "malformed_request",
      );
    }
    const reference: FindingEvidenceReference = {
      referenceId: parseReferenceId(
        item.referenceId,
        `evidenceReferences[${index}].referenceId`,
      ),
      sourceType: item.sourceType,
      observationId: nullableIdentifier(
        item.observationId,
        `evidenceReferences[${index}].observationId`,
      ),
      artifactId: nullableIdentifier(
        item.artifactId,
        `evidenceReferences[${index}].artifactId`,
      ),
      visualizationId: nullableIdentifier(
        item.visualizationId,
        `evidenceReferences[${index}].visualizationId`,
      ),
      label: text(
        item.label,
        `evidenceReferences[${index}].label`,
        REFERENCE_LABEL_MAX_LENGTH,
        { required: true },
      ) as string,
      availability: parseAvailability(
        item.availability,
        `evidenceReferences[${index}].availability`,
      ),
      publicSafe: item.publicSafe,
    };
    if (!isEvidenceReferenceStructurallyValid(reference)) {
      throw roomError(
        "malformed_request",
        `evidenceReferences[${index}] is structurally invalid.`,
        "malformed_request",
      );
    }
    return reference;
  });
}

function parseAnalysisReferences(
  value: unknown,
): FindingAnalysisArtifactReference[] {
  if (!Array.isArray(value) || value.length > 64) {
    throw roomError(
      "malformed_request",
      "analysisArtifactReferences must contain at most 64 entries.",
      "malformed_request",
    );
  }
  return value.map((item, index) => {
    if (!isRecord(item) || typeof item.publicSafe !== "boolean") {
      throw roomError(
        "malformed_request",
        `analysisArtifactReferences[${index}] is invalid.`,
        "malformed_request",
      );
    }
    const hash = item.artifactHash;
    if (hash !== null && typeof hash !== "string") {
      throw roomError(
        "malformed_request",
        `analysisArtifactReferences[${index}].artifactHash is invalid.`,
        "malformed_request",
      );
    }
    const reference: FindingAnalysisArtifactReference = {
      referenceId: parseReferenceId(
        item.referenceId,
        `analysisArtifactReferences[${index}].referenceId`,
      ),
      analysisJobId: nullableIdentifier(
        item.analysisJobId,
        `analysisArtifactReferences[${index}].analysisJobId`,
      ),
      analysisArtifactId: parseReferenceId(
        item.analysisArtifactId,
        `analysisArtifactReferences[${index}].analysisArtifactId`,
      ),
      artifactHash: hash,
      label: text(
        item.label,
        `analysisArtifactReferences[${index}].label`,
        REFERENCE_LABEL_MAX_LENGTH,
        { required: true },
      ) as string,
      availability: parseAvailability(
        item.availability,
        `analysisArtifactReferences[${index}].availability`,
      ),
      publicSafe: item.publicSafe,
    };
    if (!isAnalysisReferenceStructurallyValid(reference)) {
      throw roomError(
        "malformed_request",
        `analysisArtifactReferences[${index}] is structurally invalid.`,
        "malformed_request",
      );
    }
    return reference;
  });
}

function parseRevisionContent(
  value: unknown,
): {
  statement: string;
  interpretation: string | null;
  limitations: string[];
  evidenceReferences: FindingEvidenceReference[];
  analysisArtifactReferences: FindingAnalysisArtifactReference[];
  revisionReason: string;
  addressedReviewIds: string[];
} {
  if (!isRecord(value)) {
    throw roomError(
      "malformed_request",
      "revision must be an object.",
      "malformed_request",
    );
  }
  const interpretation = text(
    value.interpretation,
    "interpretation",
    FINDING_INTERPRETATION_MAX_LENGTH,
    { nullable: true },
  );
  const addressedReviewIds = stringArray(
    value.addressedReviewIds,
    "addressedReviewIds",
    64,
    192,
  ).map((reviewId) => parseEntityId(reviewId, "addressedReviewIds entry", "review_"));
  if (new Set(addressedReviewIds).size !== addressedReviewIds.length) {
    throw roomError(
      "malformed_request",
      "addressedReviewIds must not contain duplicates.",
      "malformed_request",
    );
  }
  return {
    statement: text(
      value.statement,
      "statement",
      FINDING_STATEMENT_MAX_LENGTH,
      { required: true },
    ) as string,
    interpretation,
    limitations: stringArray(
      value.limitations,
      "limitations",
      32,
      FINDING_LIMITATION_MAX_LENGTH,
    ),
    evidenceReferences: parseEvidenceReferences(value.evidenceReferences),
    analysisArtifactReferences: parseAnalysisReferences(
      value.analysisArtifactReferences,
    ),
    revisionReason: text(
      value.revisionReason,
      "revisionReason",
      FINDING_REVISION_REASON_MAX_LENGTH,
      { required: true },
    ) as string,
    addressedReviewIds,
  };
}

function hibernatingSocket(socket: WebSocket): HibernatingWebSocket {
  return socket as HibernatingWebSocket;
}

class RoomOperationError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly details: RoomOperationErrorDetails,
  ) {
    super(message);
  }
}

function roomError(
  code: string,
  message: string,
  category: RoomOperationErrorCategory,
  details: Omit<RoomOperationErrorDetails, "category"> = {},
): RoomOperationError {
  return new RoomOperationError(code, message, { category, ...details });
}

function errorMessage(
  state: PersistedRoomState,
  error: unknown,
  operationId: string | null,
): Extract<RoomServerMessage, { type: "room:error" }> {
  if (error instanceof RoomOperationError) {
    return {
      protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
      type: "room:error",
      operationId,
      code: error.code,
      message: error.message,
      roomRevision: state.roomRevision,
      details: error.details,
      reviewState: findingReviewSnapshot(state.reviewState),
    };
  }
  return {
    protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
    type: "room:error",
    operationId,
    code: "room_operation_failed",
    message: "The room operation failed safely.",
    roomRevision: state.roomRevision,
    details: { category: "malformed_request" },
    reviewState: findingReviewSnapshot(state.reviewState),
  };
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!isRecord(value)) return value;
  const result: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) result[key] = canonicalValue(value[key]);
  return result;
}

async function requestFingerprint(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalValue(value)));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function legacyEvidenceReference(
  state: LegacyPersistedRoomState,
  finding: RoomFinding,
): FindingEvidenceReference {
  return {
    referenceId: `activity-${finding.findingId}`,
    sourceType: "activity_artifact",
    observationId: null,
    artifactId: state.artifactId,
    visualizationId: state.visualizationId,
    label: "Phase 4B retained scientific Activity selection",
    availability: "available",
    publicSafe: true,
  };
}

function migrateState(
  stored: LegacyPersistedRoomState | PersistedRoomState,
): PersistedRoomState {
  if ((stored as PersistedRoomState).schemaVersion === 2) {
    const current = stored as PersistedRoomState;
    const events = Array.isArray(current.findingEvents) ? current.findingEvents : [];
    const normalized = normalizeFindingReviewState(current.reviewState);
    const replayed =
      events.length > 0 && isValidFindingReviewEventSequence(events)
        ? replayFindingReviewEvents(events)
        : null;
    const replayMatchesMaterialized =
      replayed !== null &&
      JSON.stringify(findingReviewSnapshot(replayed)) ===
        JSON.stringify(findingReviewSnapshot(normalized));
    return {
      ...current,
      presenterParticipantId: current.presenterParticipantId ?? null,
      reviewState: replayMatchesMaterialized && replayed ? replayed : normalized,
      findingEvents: events,
      processedOperations: copyRecord(current.processedOperations),
      usedTickets: copyRecord(current.usedTickets),
    };
  }

  const legacy = stored as LegacyPersistedRoomState;
  const reviewState = emptyFindingReviewState();
  const events: FindingReviewDomainEvent[] = [];
  for (const finding of Object.values(legacy.findings ?? {})) {
    const currentFinding: RoomFinding = {
      ...finding,
      revision: 1,
      currentRevision: 1,
      lifecycleState: "draft",
    };
    const statement = finding.title.trim() || "Untitled finding";
    const revision: FindingRevision = {
      findingId: finding.findingId,
      revision: 1,
      previousRevision: null,
      statement,
      interpretation: finding.observation.trim() || null,
      limitations: [],
      evidenceReferences: [legacyEvidenceReference(legacy, finding)],
      analysisArtifactReferences: [],
      authorParticipantId: finding.creatorParticipantId,
      authorDisplayName: finding.creatorDisplayName,
      createdAt: finding.createdAt,
      revisionReason: "Imported without alteration from the Phase 4B finding record.",
      lifecycleState: "draft",
      addressedReviewIds: [],
    };
    const event: FindingReviewDomainEvent = {
      eventId: `event_migration_${finding.findingId}`,
      operationId: `migration_${finding.findingId}`,
      eventType: "finding_created",
      roomRevision: finding.revision,
      createdAt: finding.updatedAt,
      audit: {
        actorParticipantId: finding.creatorParticipantId,
        actorDisplayName: finding.creatorDisplayName,
        rationale: "Imported from the Phase 4B finding record.",
      },
      patch: { findings: [currentFinding], revisions: [revision] },
    };
    applyFindingReviewPatch(reviewState, event.patch);
    events.push(event);
  }
  const operations = safeRecord<StoredOperation>();
  for (const [operationId, response] of Object.entries(
    legacy.processedOperations ?? {},
  )) {
    operations[operationId] = {
      participantId: "",
      requestFingerprint: "",
      responseType: response.type,
      resultRoomRevision:
        "roomRevision" in response ? response.roomRevision : legacy.roomRevision,
    };
  }
  return {
    schemaVersion: 2,
    roomId: legacy.roomId,
    artifactId: legacy.artifactId,
    visualizationId: legacy.visualizationId,
    roomRevision: legacy.roomRevision,
    presenterParticipantId: null,
    selection: legacy.selection,
    layers: legacy.layers,
    reviewState,
    findingEvents: events,
    processedOperations: operations,
    usedTickets: copyRecord(legacy.usedTickets),
  };
}

export class InvestigationRoom {
  private messageQueue: Promise<void> = Promise.resolve();

  constructor(private readonly state: DurableObjectState) {
    this.state.setWebSocketAutoResponse(
      new WebSocketRequestResponsePair("ping", "pong"),
    );
  }

  async fetch(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      throw new HttpError(
        426,
        "websocket_required",
        "Investigation rooms require a WebSocket upgrade.",
      );
    }
    const encoded = request.headers.get("X-Investigation-Room-Ticket");
    if (!encoded) {
      throw new HttpError(
        401,
        "room_ticket_missing",
        "Validated room ticket payload is missing.",
      );
    }
    let ticket: RoomTicketPayload;
    try {
      ticket = JSON.parse(decodeURIComponent(encoded)) as RoomTicketPayload;
    } catch {
      throw new HttpError(
        401,
        "invalid_room_ticket",
        "Validated room ticket payload is malformed.",
      );
    }
    const connected = this.state.getWebSockets().filter((peer) => {
      const attachment =
        hibernatingSocket(peer).deserializeAttachment() as SocketAttachment | null;
      if (attachment && this.isSocketAttachmentFresh(attachment)) return true;
      try {
        peer.close(1008, "Activity session refresh required.");
      } catch {
        // The runtime retires closing peers; stale sockets must not consume capacity.
      }
      return false;
    });
    if (connected.length >= MAX_ROOM_CONNECTIONS) {
      throw new HttpError(
        429,
        "room_connection_limit",
        "This private test room has reached its connection limit.",
      );
    }
    const participantConnections = connected.filter((peer) => {
      const attachment =
        hibernatingSocket(peer).deserializeAttachment() as SocketAttachment | null;
      return attachment?.ticket.participantId === ticket.participantId;
    }).length;
    if (participantConnections >= MAX_CONNECTIONS_PER_PARTICIPANT) {
      throw new HttpError(
        429,
        "participant_connection_limit",
        "This participant has reached the room connection limit.",
      );
    }

    const persisted = await this.loadState(ticket);
    if (
      persisted.presenterParticipantId !== null &&
      !connected.some((peer) => {
        const attachment =
          hibernatingSocket(peer).deserializeAttachment() as SocketAttachment | null;
        return (
          attachment?.ticket.participantId === persisted.presenterParticipantId
        );
      })
    ) {
      persisted.presenterParticipantId = null;
    }
    const now = Math.floor(Date.now() / 1000);
    for (const [nonce, expiresAt] of Object.entries(persisted.usedTickets)) {
      if (expiresAt <= now) delete persisted.usedTickets[nonce];
    }
    if (hasOwn(persisted.usedTickets, ticket.nonce)) {
      throw new HttpError(
        409,
        "room_ticket_replayed",
        "That room ticket has already been used.",
      );
    }
    if (Object.keys(persisted.usedTickets).length >= MAX_USED_TICKETS) {
      throw new HttpError(
        429,
        "room_ticket_capacity",
        "This room has reached its short-lived ticket retention limit.",
      );
    }
    persisted.usedTickets[ticket.nonce] = ticket.expiresAt;
    if (
      persisted.roomId !== ticket.roomId ||
      persisted.artifactId !== ticket.artifactId ||
      persisted.visualizationId !== ticket.visualizationId
    ) {
      throw new HttpError(
        409,
        "room_publication_conflict",
        "Room is already bound to another scientific publication.",
      );
    }

    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1] as HibernatingWebSocket;
    const attachment: SocketAttachment = {
      ticket,
      connectedAt: new Date().toISOString(),
    };
    server.serializeAttachment(attachment);
    this.state.acceptWebSocket(server);
    await this.state.storage.put(STATE_KEY, persisted);

    this.send(server, {
      protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
      type: "room:snapshot",
      snapshot: this.snapshot(persisted),
      selfParticipantId: ticket.participantId,
    });
    this.broadcastRoomState(persisted);
    return new Response(null, {
      status: 101,
      webSocket: client,
    } as ResponseInit & { webSocket: WebSocket });
  }

  async webSocketMessage(
    socket: WebSocket,
    raw: string | ArrayBuffer,
  ): Promise<void> {
    const queued = this.messageQueue.then(() =>
      this.processWebSocketMessage(socket, raw),
    );
    this.messageQueue = queued.catch(() => undefined);
    await queued;
  }

  private async processWebSocketMessage(
    socket: WebSocket,
    raw: string | ArrayBuffer,
  ): Promise<void> {
    const rawBytes =
      typeof raw === "string"
        ? new TextEncoder().encode(raw).byteLength
        : raw.byteLength;
    if (rawBytes > MAX_WEBSOCKET_MESSAGE_BYTES) {
      socket.close(1009, "Room message exceeds the 64 KiB limit.");
      return;
    }
    const peer = hibernatingSocket(socket);
    const attachment =
      peer.deserializeAttachment() as SocketAttachment | null;
    if (!attachment?.ticket) {
      socket.close(1008, "Room participant attachment is missing.");
      return;
    }
    const now = Date.now();
    if (
      attachment.messageWindowStartedAt === undefined ||
      now - attachment.messageWindowStartedAt >= MESSAGE_RATE_WINDOW_MS
    ) {
      attachment.messageWindowStartedAt = now;
      attachment.messageCount = 0;
    }
    if ((attachment.messageCount ?? 0) >= MAX_MESSAGES_PER_WINDOW) {
      socket.close(1008, "Room message rate limit exceeded.");
      return;
    }
    attachment.messageCount = (attachment.messageCount ?? 0) + 1;
    peer.serializeAttachment(attachment);

    const ticket = this.ticketFor(socket);
    const state = await this.loadState(ticket);
    const stateBeforeOperation = structuredClone(state);
    let operationId: string | null = null;
    let fingerprint: string | null = null;
    try {
      const value = JSON.parse(
        typeof raw === "string" ? raw : new TextDecoder().decode(raw),
      ) as unknown;
      if (!isRecord(value) || value.protocolVersion !== INVESTIGATION_ROOM_PROTOCOL_VERSION) {
        throw roomError(
          "protocol_mismatch",
          "Unsupported investigation-room protocol version.",
          "malformed_request",
        );
      }
      operationId = parseOperationId(value.operationId);
      fingerprint = await requestFingerprint(value);
      if (hasOwn(state.processedOperations, operationId)) {
        const duplicate = state.processedOperations[operationId];
        if (
          duplicate.participantId &&
          (duplicate.participantId !== ticket.participantId ||
            duplicate.requestFingerprint !== fingerprint)
        ) {
          throw roomError(
            "operation_id_conflict",
            "That operation ID is already bound to a different request.",
            "operation_conflict",
          );
        }
        this.send(socket, {
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          type: "operation:duplicate",
          operationId,
          roomRevision: state.roomRevision,
          originalResponseType: duplicate.responseType,
        });
        return;
      }
      const expectedRevision = parseExpectedRevision(value.expectedRevision);
      if (expectedRevision !== state.roomRevision) {
        throw roomError(
          "stale_revision",
          `Expected room revision ${expectedRevision}, current revision is ${state.roomRevision}.`,
          "stale_revision",
        );
      }
      await this.applyMessage(
        ticket,
        state,
        value as unknown as RoomClientMessage,
        operationId,
        fingerprint,
      );
    } catch (error) {
      const responseState =
        error instanceof RoomOperationError ? state : stateBeforeOperation;
      const response = errorMessage(responseState, error, operationId);
      this.send(socket, response);
    }
  }

  async webSocketClose(socket: WebSocket): Promise<void> {
    const attachment =
      hibernatingSocket(socket).deserializeAttachment() as SocketAttachment | null;
    const state = await this.state.storage.get<PersistedRoomState>(STATE_KEY);
    if (!state) return;
    const persisted = migrateState(state);
    if (attachment?.ticket.participantId === persisted.presenterParticipantId) {
      const stillConnected = this.state.getWebSockets().some((peer) => {
        if (peer === socket) return false;
        const peerAttachment =
          hibernatingSocket(peer).deserializeAttachment() as SocketAttachment | null;
        return (
          peerAttachment !== null &&
          this.isSocketAttachmentFresh(peerAttachment) &&
          peerAttachment?.ticket.participantId === attachment.ticket.participantId
        );
      });
      if (!stillConnected) {
        persisted.presenterParticipantId = null;
        await this.state.storage.put(STATE_KEY, persisted);
      }
    }
    this.broadcastRoomState(persisted);
  }

  async webSocketError(socket: WebSocket): Promise<void> {
    await this.webSocketClose(socket);
  }

  private ticketFor(socket: WebSocket): RoomTicketPayload {
    const attachment =
      hibernatingSocket(socket).deserializeAttachment() as SocketAttachment | null;
    if (!attachment) {
      throw roomError(
        "participant_missing",
        "Room participant attachment is missing.",
        "permission_denied",
      );
    }
    if (!this.isSocketAttachmentFresh(attachment)) {
      socket.close(1008, "Activity session refresh required.");
      throw roomError(
        "session_expired",
        "This room connection has reached its maximum lifetime; reconnect through Discord.",
        "permission_denied",
      );
    }
    return attachment.ticket;
  }

  private isSocketAttachmentFresh(attachment: SocketAttachment): boolean {
    const connectedAt = Date.parse(attachment.connectedAt);
    const age = Date.now() - connectedAt;
    return Number.isFinite(connectedAt) && age >= 0 && age <= MAX_SOCKET_AGE_MS;
  }

  private async loadState(ticket: RoomTicketPayload): Promise<PersistedRoomState> {
    const existing = await this.state.storage.get<
      LegacyPersistedRoomState | PersistedRoomState
    >(STATE_KEY);
    if (existing) return migrateState(existing);
    const created: PersistedRoomState = {
      schemaVersion: 2,
      roomId: ticket.roomId,
      artifactId: ticket.artifactId,
      visualizationId: ticket.visualizationId,
      roomRevision: 0,
      presenterParticipantId: null,
      selection: null,
      layers: DEFAULT_LAYERS,
      reviewState: emptyFindingReviewState(),
      findingEvents: [],
      processedOperations: safeRecord(),
      usedTickets: safeRecord(),
    };
    await this.state.storage.put(STATE_KEY, created);
    return created;
  }

  private participants(): RoomParticipant[] {
    const unique = new Map<string, RoomParticipant>();
    for (const socket of this.state.getWebSockets()) {
      const attachment =
        hibernatingSocket(socket).deserializeAttachment() as SocketAttachment | null;
      if (!attachment || !this.isSocketAttachmentFresh(attachment)) continue;
      const existing = unique.get(attachment.ticket.participantId);
      if (!existing || attachment.connectedAt < existing.connectedAt) {
        unique.set(attachment.ticket.participantId, {
          participantId: attachment.ticket.participantId,
          displayName: attachment.ticket.displayName,
          connectedAt: attachment.connectedAt,
        });
      }
    }
    return [...unique.values()].sort(
      (left, right) =>
        left.connectedAt.localeCompare(right.connectedAt) ||
        left.participantId.localeCompare(right.participantId),
    );
  }

  private snapshot(state: PersistedRoomState): InvestigationRoomSnapshot {
    const reviewState = findingReviewSnapshot(state.reviewState);
    return {
      protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
      roomId: state.roomId,
      artifactId: state.artifactId,
      visualizationId: state.visualizationId,
      roomRevision: state.roomRevision,
      participants: this.participants(),
      presenterParticipantId: state.presenterParticipantId,
      selection: state.selection,
      layers: state.layers,
      ...reviewState,
    };
  }

  private canControl(
    state: PersistedRoomState,
    participantId: string,
  ): boolean {
    return (
      state.presenterParticipantId === null ||
      state.presenterParticipantId === participantId
    );
  }

  private remember(
    state: PersistedRoomState,
    operationId: string,
    participantId: string,
    fingerprint: string,
    responseType: string,
    resultRoomRevision: number,
  ): void {
    state.processedOperations[operationId] = {
      participantId,
      requestFingerprint: fingerprint,
      responseType,
      resultRoomRevision,
    };
  }

  private async persistAndBroadcast(
    state: PersistedRoomState,
    operationId: string,
    participantId: string,
    fingerprint: string,
    response: RoomServerMessage,
  ): Promise<void> {
    this.remember(
      state,
      operationId,
      participantId,
      fingerprint,
      response.type,
      "roomRevision" in response ? response.roomRevision : state.roomRevision,
    );
    this.assertRoomCapacity(state);
    await this.state.storage.put(STATE_KEY, state);
    this.broadcast(response);
  }

  private assertRoomCapacity(state: PersistedRoomState): void {
    const counts = [
      [Object.keys(state.reviewState.findings).length, MAX_FINDINGS, "findings"],
      [Object.keys(state.reviewState.revisions).length, MAX_REVISIONS, "revisions"],
      [Object.keys(state.reviewState.reviews).length, MAX_REVIEWS, "reviews"],
      [
        Object.keys(state.reviewState.reviewResolutions).length,
        MAX_REVIEW_RESOLUTIONS,
        "review resolutions",
      ],
      [
        Object.keys(state.reviewState.relationships).length,
        MAX_RELATIONSHIPS,
        "relationships",
      ],
      [
        Object.keys(state.reviewState.publicConclusions).length,
        MAX_PUBLIC_CONCLUSIONS,
        "public conclusions",
      ],
      [state.findingEvents.length, MAX_FINDING_EVENTS, "finding events"],
      [
        Object.keys(state.processedOperations).length,
        MAX_PROCESSED_OPERATIONS,
        "processed operations",
      ],
    ] as const;
    const exceeded = counts.find(([count, maximum]) => count > maximum);
    if (exceeded) {
      throw roomError(
        "room_capacity_reached",
        `This private test room has reached its ${exceeded[2]} capacity.`,
        "operation_conflict",
      );
    }
    const serializedBytes = new TextEncoder().encode(
      JSON.stringify(state),
    ).byteLength;
    if (serializedBytes > MAX_ROOM_STATE_BYTES) {
      throw roomError(
        "room_capacity_reached",
        "This private test room has reached its persisted-state capacity.",
        "operation_conflict",
      );
    }
  }

  private revision(
    state: PersistedRoomState,
    findingId: string,
    revision: number,
  ): FindingRevision | null {
    const key = findingRevisionKey(findingId, revision);
    return hasOwn(state.reviewState.revisions, key)
      ? state.reviewState.revisions[key]
      : null;
  }

  private finding(
    state: PersistedRoomState,
    rawFindingId: unknown,
  ): RoomFinding {
    const findingId = parseEntityId(rawFindingId, "findingId", "finding_");
    if (!hasOwn(state.reviewState.findings, findingId)) {
      throw roomError(
        "finding_not_found",
        "Shared finding does not exist.",
        "nonexistent_record",
        { findingId },
      );
    }
    return state.reviewState.findings[findingId];
  }

  private exactCurrentRevision(
    state: PersistedRoomState,
    finding: RoomFinding,
    rawRevision: unknown,
  ): FindingRevision {
    const requested = parseFindingRevisionNumber(rawRevision);
    const revision = this.revision(state, finding.findingId, requested);
    if (!revision) {
      throw roomError(
        "finding_revision_not_found",
        `Finding revision ${requested} does not exist.`,
        "nonexistent_record",
        {
          findingId: finding.findingId,
          requestedFindingRevision: requested,
          currentFindingRevision: finding.currentRevision,
        },
      );
    }
    if (requested !== finding.currentRevision) {
      throw roomError(
        "stale_finding_revision",
        `Finding revision ${requested} is historical; current revision is ${finding.currentRevision}.`,
        "stale_revision",
        {
          findingId: finding.findingId,
          requestedFindingRevision: requested,
          currentFindingRevision: finding.currentRevision,
        },
      );
    }
    return revision;
  }

  private appendEvent(
    state: PersistedRoomState,
    operationId: string,
    eventType: FindingReviewDomainEvent["eventType"],
    createdAt: string,
    patch: FindingReviewStatePatch,
    audit: FindingReviewDomainEvent["audit"],
  ): void {
    const event: FindingReviewDomainEvent = {
      eventId: `event_${crypto.randomUUID()}`,
      operationId,
      eventType,
      roomRevision: state.roomRevision,
      createdAt,
      audit,
      patch,
    };
    applyFindingReviewPatch(state.reviewState, patch);
    state.findingEvents.push(event);
  }

  private reviewStateResponse(
    state: PersistedRoomState,
    operationId: string,
  ): Extract<RoomServerMessage, { type: "room:review-state" }> {
    return {
      protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
      type: "room:review-state",
      operationId,
      roomRevision: state.roomRevision,
      status: "accepted",
      reviewState: findingReviewSnapshot(state.reviewState),
    };
  }

  private async acceptReviewPatch(
    state: PersistedRoomState,
    ticket: RoomTicketPayload,
    operationId: string,
    fingerprint: string,
    eventType: FindingReviewDomainEvent["eventType"],
    createdAt: string,
    patch: FindingReviewStatePatch,
    rationale: string | null = null,
  ): Promise<void> {
    state.roomRevision += 1;
    this.appendEvent(state, operationId, eventType, createdAt, patch, {
      actorParticipantId: ticket.participantId,
      actorDisplayName: ticket.displayName,
      rationale,
    });
    await this.persistAndBroadcast(
      state,
      operationId,
      ticket.participantId,
      fingerprint,
      this.reviewStateResponse(state, operationId),
    );
  }

  private reviews(state: PersistedRoomState): FindingReview[] {
    return Object.values(state.reviewState.reviews);
  }

  private resolutions(state: PersistedRoomState): FindingReviewResolution[] {
    return Object.values(state.reviewState.reviewResolutions);
  }

  private validateEvidenceScope(
    state: PersistedRoomState,
    references: readonly FindingEvidenceReference[],
  ): void {
    const mismatched = references.find(
      (reference) =>
        reference.sourceType === "activity_artifact" &&
        (reference.artifactId !== state.artifactId ||
          reference.visualizationId !== state.visualizationId),
    );
    if (mismatched) {
      throw roomError(
        "evidence_scope_mismatch",
        "Activity-artifact evidence must reference the room's bound artifact and visualization.",
        "malformed_request",
      );
    }
  }

  private serverBoundEvidenceReferences(
    state: PersistedRoomState,
    findingId: string,
    references: readonly FindingEvidenceReference[],
  ): FindingEvidenceReference[] {
    this.validateEvidenceScope(state, references);
    const mandatoryReferenceId = `activity-${findingId}`;
    const supplied = references.filter(
      (reference) => reference.referenceId !== mandatoryReferenceId,
    );
    if (supplied.length >= MAX_EVIDENCE_REFERENCES) {
      throw roomError(
        "malformed_request",
        `evidenceReferences may contain at most ${
          MAX_EVIDENCE_REFERENCES - 1
        } client-supplied entries because the room evidence reference is mandatory.`,
        "malformed_request",
      );
    }
    const seen = new Set<string>();
    for (const reference of supplied) {
      if (seen.has(reference.referenceId)) {
        throw roomError(
          "malformed_request",
          `Duplicate evidence reference ${reference.referenceId} is not allowed.`,
          "malformed_request",
        );
      }
      seen.add(reference.referenceId);
    }
    return [
      {
        referenceId: mandatoryReferenceId,
        sourceType: "activity_artifact",
        observationId: null,
        artifactId: state.artifactId,
        visualizationId: state.visualizationId,
        label: "Published scientific Activity selection",
        availability: "available",
        publicSafe: true,
      },
      ...supplied,
    ];
  }

  private hasServerBoundEvidenceReference(
    state: PersistedRoomState,
    findingId: string,
    references: readonly FindingEvidenceReference[],
  ): boolean {
    return references.some(
      (reference) =>
        reference.referenceId === `activity-${findingId}` &&
        reference.sourceType === "activity_artifact" &&
        reference.observationId === null &&
        reference.artifactId === state.artifactId &&
        reference.visualizationId === state.visualizationId &&
        reference.availability === "available" &&
        reference.publicSafe,
    );
  }

  private privatePublicationValues(state: PersistedRoomState): string[] {
    return [
      state.roomId,
      ...Object.keys(state.processedOperations),
      ...this.participants().flatMap((participant) => [
        participant.participantId,
        participant.displayName,
      ]),
      ...Object.values(state.reviewState.findings).flatMap((finding) => [
        finding.creatorParticipantId,
        finding.creatorDisplayName,
      ]),
      ...Object.values(state.reviewState.revisions).flatMap((revision) => [
        revision.authorParticipantId,
        revision.authorDisplayName,
      ]),
      ...Object.values(state.reviewState.reviews).flatMap((review) => [
        review.reviewerParticipantId,
        review.reviewerDisplayName,
        review.clientOperationId,
      ]),
      ...Object.values(state.reviewState.reviewResolutions).flatMap(
        (resolution) => [
          resolution.resolverParticipantId,
          resolution.resolverDisplayName,
          resolution.clientOperationId,
        ],
      ),
      ...Object.values(state.reviewState.relationships).flatMap(
        (relationship) => [
          relationship.creatorParticipantId,
          relationship.creatorDisplayName,
          relationship.clientOperationId,
        ],
      ),
    ];
  }

  private revisedLifecycle(
    state: PersistedRoomState,
    finding: RoomFinding,
    revision: FindingRevision,
    additionalReviews: FindingReview[] = [],
    additionalResolutions: FindingReviewResolution[] = [],
  ): FindingLifecycleState {
    return effectiveReviewLifecycle({
      findingId: finding.findingId,
      requestedRevision: finding.currentRevision,
      currentRevision: finding.currentRevision,
      lifecycleState: finding.lifecycleState,
      revision,
      reviews: [...this.reviews(state), ...additionalReviews],
      resolutions: [...this.resolutions(state), ...additionalResolutions],
    });
  }

  private findingCanEdit(
    state: PersistedRoomState,
    finding: RoomFinding,
    participantId: string,
  ): boolean {
    return (
      finding.creatorParticipantId === participantId ||
      state.presenterParticipantId === participantId
    );
  }

  private async applyMessage(
    ticket: RoomTicketPayload,
    state: PersistedRoomState,
    message: RoomClientMessage,
    operationId: string,
    fingerprint: string,
  ): Promise<void> {
    const participantId = ticket.participantId;
    if (message.type === "presenter:claim") {
      if (state.presenterParticipantId === participantId) {
        throw roomError(
          "presenter_already_claimed",
          "This participant already holds presenter control.",
          "operation_conflict",
        );
      }
      if (
        state.presenterParticipantId &&
        state.presenterParticipantId !== participantId
      ) {
        throw roomError(
          "presenter_conflict",
          "Another participant currently holds presenter control.",
          "permission_denied",
        );
      }
      state.presenterParticipantId = participantId;
      state.roomRevision += 1;
      const response = this.accepted(operationId, state.roomRevision);
      await this.persistAndBroadcast(
        state,
        operationId,
        participantId,
        fingerprint,
        response,
      );
      this.broadcastRoomState(state);
      return;
    }
    if (message.type === "presenter:release") {
      if (state.presenterParticipantId !== participantId) {
        throw roomError(
          "not_presenter",
          "Only the current presenter can release presenter control.",
          "permission_denied",
        );
      }
      state.presenterParticipantId = null;
      state.roomRevision += 1;
      const response = this.accepted(operationId, state.roomRevision);
      await this.persistAndBroadcast(
        state,
        operationId,
        participantId,
        fingerprint,
        response,
      );
      this.broadcastRoomState(state);
      return;
    }

    if (
      message.type === "selection:set" ||
      message.type === "layers:set" ||
      message.type === "finding:open"
    ) {
      if (!this.canControl(state, participantId)) {
        throw roomError(
          "presenter_locked",
          "Shared scientific controls are locked by the presenter.",
          "permission_denied",
        );
      }
    }

    if (message.type === "selection:set") {
      state.selection = parseSelection(message.selection, ticket);
      state.roomRevision += 1;
      const response = this.accepted(operationId, state.roomRevision);
      await this.persistAndBroadcast(
        state,
        operationId,
        participantId,
        fingerprint,
        response,
      );
      this.broadcastRoomState(state);
      return;
    }
    if (message.type === "layers:set") {
      state.layers = parseLayers(message.layers);
      state.roomRevision += 1;
      const response = this.accepted(operationId, state.roomRevision);
      await this.persistAndBroadcast(
        state,
        operationId,
        participantId,
        fingerprint,
        response,
      );
      this.broadcastRoomState(state);
      return;
    }
    if (message.type === "finding:open") {
      const finding = this.finding(state, message.findingId);
      state.selection = finding.selection;
      state.layers = finding.layers;
      state.roomRevision += 1;
      const response = this.accepted(operationId, state.roomRevision);
      await this.persistAndBroadcast(
        state,
        operationId,
        participantId,
        fingerprint,
        response,
      );
      this.broadcastRoomState(state);
      return;
    }

    if (message.type === "finding:create") {
      if (!isRecord(message.finding)) {
        throw roomError(
          "invalid_finding",
          "finding must be an object.",
          "malformed_request",
        );
      }
      const title = text(
        message.finding.title,
        "title",
        FINDING_TITLE_MAX_LENGTH,
      ) as string;
      const observation = text(
        message.finding.observation,
        "observation",
        FINDING_OBSERVATION_MAX_LENGTH,
      ) as string;
      if (!title && !observation) {
        throw roomError(
          "invalid_finding",
          "A finding requires a title or observation.",
          "malformed_request",
        );
      }
      const interpretation =
        message.finding.interpretation === undefined
          ? observation || null
          : text(
              message.finding.interpretation,
              "interpretation",
              FINDING_INTERPRETATION_MAX_LENGTH,
              { nullable: true },
            );
      const limitations =
        message.finding.limitations === undefined
          ? []
          : stringArray(
              message.finding.limitations,
              "limitations",
              32,
              FINDING_LIMITATION_MAX_LENGTH,
            );
      const selection = parseSelection(message.finding.selection, ticket);
      const layers = parseLayers(message.finding.layers);
      const findingId = `finding_${crypto.randomUUID()}`;
      const now = new Date().toISOString();
      const evidenceReferences = this.serverBoundEvidenceReferences(
        state,
        findingId,
        message.finding.evidenceReferences === undefined
          ? []
          : parseEvidenceReferences(message.finding.evidenceReferences),
      );
      const analysisArtifactReferences =
        message.finding.analysisArtifactReferences === undefined
          ? []
          : parseAnalysisReferences(message.finding.analysisArtifactReferences);
      const finding: RoomFinding = {
        findingId,
        roomId: state.roomId,
        artifactId: state.artifactId,
        visualizationId: state.visualizationId,
        selection,
        layers,
        title: title || "Untitled finding",
        observation,
        creatorParticipantId: participantId,
        creatorDisplayName: ticket.displayName,
        createdAt: now,
        updatedAt: now,
        revision: 1,
        currentRevision: 1,
        lifecycleState: "draft",
      };
      const revision: FindingRevision = {
        findingId,
        revision: 1,
        previousRevision: null,
        statement: finding.title,
        interpretation,
        limitations,
        evidenceReferences,
        analysisArtifactReferences,
        authorParticipantId: participantId,
        authorDisplayName: ticket.displayName,
        createdAt: now,
        revisionReason: "Initial collaborative finding revision.",
        lifecycleState: "draft",
        addressedReviewIds: [],
      };
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        "finding_created",
        now,
        { findings: [finding], revisions: [revision] },
      );
      return;
    }

    if (message.type === "finding:update" || message.type === "finding:revise") {
      const finding = this.finding(state, message.findingId);
      if (!this.findingCanEdit(state, finding, participantId)) {
        throw roomError(
          "finding_forbidden",
          "Only the creator or presenter can create a new revision.",
          "permission_denied",
          { findingId: finding.findingId },
        );
      }
      const previous = this.exactCurrentRevision(
        state,
        finding,
        message.type === "finding:revise"
          ? message.findingRevision
          : finding.currentRevision,
      );
      let content: ReturnType<typeof parseRevisionContent>;
      if (message.type === "finding:revise") {
        content = parseRevisionContent(message.revision);
      } else {
        const title = text(
          message.title,
          "title",
          FINDING_TITLE_MAX_LENGTH,
        ) as string;
        const observation = text(
          message.observation,
          "observation",
          FINDING_OBSERVATION_MAX_LENGTH,
        ) as string;
        if (!title && !observation) {
          throw roomError(
            "invalid_finding",
            "A finding requires a title or observation.",
            "malformed_request",
          );
        }
        content = {
          statement: title || "Untitled finding",
          interpretation: observation || null,
          limitations: [...previous.limitations],
          evidenceReferences: structuredClone(previous.evidenceReferences),
          analysisArtifactReferences: structuredClone(
            previous.analysisArtifactReferences,
          ),
          revisionReason: "Created through the compatible Phase 4B edit operation.",
          addressedReviewIds: [],
        };
      }
      content = {
        ...content,
        evidenceReferences: this.serverBoundEvidenceReferences(
          state,
          finding.findingId,
          content.evidenceReferences,
        ),
      };

      const pendingResolutions: FindingReviewResolution[] = [];
      for (const reviewId of content.addressedReviewIds) {
        if (!hasOwn(state.reviewState.reviews, reviewId)) {
          throw roomError(
            "review_not_found",
            `Addressed review ${reviewId} does not exist.`,
            "nonexistent_record",
            { findingId: finding.findingId, reviewId },
          );
        }
        const review = state.reviewState.reviews[reviewId];
        if (
          review.findingId !== finding.findingId ||
          review.disposition !== "request_revision" ||
          review.findingRevision > finding.currentRevision ||
          isReviewBlockerResolved(review, this.resolutions(state))
        ) {
          throw roomError(
            "invalid_addressed_review",
            `${reviewId} is not an unresolved revision request for this finding.`,
            "malformed_request",
            { findingId: finding.findingId, reviewId },
          );
        }
      }

      const now = new Date().toISOString();
      const nextRevisionNumber = finding.currentRevision + 1;
      for (const reviewId of content.addressedReviewIds) {
        const review = state.reviewState.reviews[reviewId];
        pendingResolutions.push({
          resolutionId: `resolution_${crypto.randomUUID()}`,
          blockingReviewId: reviewId,
          status: "addressed_by_revision",
          resolverParticipantId: participantId,
          resolverDisplayName: ticket.displayName,
          rationale: content.revisionReason,
          createdAt: now,
          clientOperationId: operationId,
          findingId: finding.findingId,
          findingRevision: review.findingRevision,
          resultingRevision: nextRevisionNumber,
        });
      }
      const revision: FindingRevision = {
        findingId: finding.findingId,
        revision: nextRevisionNumber,
        previousRevision: previous.revision,
        statement: content.statement,
        interpretation: content.interpretation,
        limitations: content.limitations,
        evidenceReferences: content.evidenceReferences,
        analysisArtifactReferences: content.analysisArtifactReferences,
        authorParticipantId: participantId,
        authorDisplayName: ticket.displayName,
        createdAt: now,
        revisionReason: content.revisionReason,
        lifecycleState: "draft",
        addressedReviewIds: content.addressedReviewIds,
      };
      const updated: RoomFinding = {
        ...finding,
        title: revision.statement,
        observation: revision.interpretation ?? "",
        updatedAt: now,
        revision: nextRevisionNumber,
        currentRevision: nextRevisionNumber,
        lifecycleState: "draft",
      };
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        "finding_revised",
        now,
        {
          findings: [updated],
          revisions: [revision],
          reviewResolutions: pendingResolutions,
        },
      );
      return;
    }

    if (message.type === "finding:review:start") {
      const finding = this.finding(state, message.findingId);
      const revision = this.exactCurrentRevision(
        state,
        finding,
        message.findingRevision,
      );
      if (!canStartReview(finding.lifecycleState)) {
        throw roomError(
          "invalid_transition",
          `A ${finding.lifecycleState} finding cannot enter review.`,
          "invalid_transition",
          {
            findingId: finding.findingId,
            requestedFindingRevision: revision.revision,
            currentFindingRevision: finding.currentRevision,
          },
        );
      }
      const now = new Date().toISOString();
      const updatedFinding = {
        ...finding,
        lifecycleState: "under_review" as const,
        updatedAt: now,
      };
      const updatedRevision = {
        ...revision,
        lifecycleState: "under_review" as const,
      };
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        "review_started",
        now,
        { findings: [updatedFinding], revisions: [updatedRevision] },
      );
      return;
    }

    if (message.type === "finding:review:submit") {
      const finding = this.finding(state, message.findingId);
      const revision = this.exactCurrentRevision(
        state,
        finding,
        message.findingRevision,
      );
      if (
        ![
          "under_review",
          "reviewed",
          "challenged",
          "revision_requested",
        ].includes(finding.lifecycleState)
      ) {
        throw roomError(
          "invalid_transition",
          "Reviews may only be submitted while the exact revision is in review.",
          "invalid_transition",
          {
            findingId: finding.findingId,
            requestedFindingRevision: revision.revision,
            currentFindingRevision: finding.currentRevision,
          },
        );
      }
      if (!isFindingReviewDisposition(message.disposition)) {
        throw roomError(
          "malformed_review_disposition",
          "Review disposition is invalid.",
          "malformed_request",
        );
      }
      if (!isFindingReviewRubric(message.rubric)) {
        throw roomError(
          "malformed_review_rubric",
          "Every rubric dimension must be an integer from 0 through 2.",
          "malformed_request",
        );
      }
      if (revision.authorParticipantId === participantId) {
        throw roomError(
          "self_review_forbidden",
          "Finding authors cannot review their own revision.",
          "permission_denied",
        );
      }
      if (
        this.reviews(state).some(
          (review) =>
            review.findingId === finding.findingId &&
            review.findingRevision === revision.revision &&
            review.reviewerParticipantId === participantId,
        )
      ) {
        throw roomError(
          "review_already_submitted",
          "Your review of this exact revision is immutable and already recorded.",
          "operation_conflict",
        );
      }
      const rationale = text(
        message.rationale,
        "rationale",
        REVIEW_RATIONALE_MAX_LENGTH,
        { required: true },
      );
      const now = new Date().toISOString();
      const review: FindingReview = {
        reviewId: `review_${crypto.randomUUID()}`,
        findingId: finding.findingId,
        findingRevision: revision.revision,
        reviewerParticipantId: participantId,
        reviewerDisplayName: ticket.displayName,
        disposition: message.disposition,
        rationale: rationale as string,
        rubric: { ...message.rubric },
        createdAt: now,
        clientOperationId: operationId,
        roomContext: {
          roomId: state.roomId,
          artifactId: state.artifactId,
          visualizationId: state.visualizationId,
        },
      };
      const lifecycle = this.revisedLifecycle(
        state,
        finding,
        revision,
        [review],
      );
      const updatedFinding = { ...finding, lifecycleState: lifecycle, updatedAt: now };
      const updatedRevision = { ...revision, lifecycleState: lifecycle };
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        "review_submitted",
        now,
        {
          findings: [updatedFinding],
          revisions: [updatedRevision],
          reviews: [review],
        },
      );
      return;
    }

    if (message.type === "finding:review:resolve") {
      const finding = this.finding(state, message.findingId);
      const revisionNumber = parseFindingRevisionNumber(message.findingRevision);
      const revision = this.revision(state, finding.findingId, revisionNumber);
      if (!revision) {
        throw roomError(
          "finding_revision_not_found",
          `Finding revision ${revisionNumber} does not exist.`,
          "nonexistent_record",
          {
            findingId: finding.findingId,
            requestedFindingRevision: revisionNumber,
            currentFindingRevision: finding.currentRevision,
          },
        );
      }
      const reviewId = parseEntityId(message.reviewId, "reviewId", "review_");
      if (!hasOwn(state.reviewState.reviews, reviewId)) {
        throw roomError(
          "review_not_found",
          "The blocking review does not exist.",
          "nonexistent_record",
          { findingId: finding.findingId, reviewId },
        );
      }
      const review = state.reviewState.reviews[reviewId];
      if (
        review.findingId !== finding.findingId ||
        review.findingRevision !== revisionNumber
      ) {
        throw roomError(
          "review_revision_conflict",
          "The review is attached to a different exact finding revision.",
          "stale_revision",
          {
            findingId: finding.findingId,
            requestedFindingRevision: revisionNumber,
            currentFindingRevision: finding.currentRevision,
            reviewId,
          },
        );
      }
      if (
        review.disposition === "endorse" ||
        isReviewBlockerResolved(review, this.resolutions(state))
      ) {
        throw roomError(
          "invalid_transition",
          "That review is not an unresolved blocker.",
          "invalid_transition",
          { findingId: finding.findingId, reviewId },
        );
      }
      if (
        message.resolutionAction !== "resolve" &&
        message.resolutionAction !== "withdraw"
      ) {
        throw roomError(
          "malformed_request",
          "resolutionAction must be resolve or withdraw.",
          "malformed_request",
        );
      }
      const isReviewer = review.reviewerParticipantId === participantId;
      if (message.resolutionAction === "withdraw" && !isReviewer) {
        throw roomError(
          "review_resolution_forbidden",
          "Only the blocker reviewer may withdraw it.",
          "permission_denied",
          { findingId: finding.findingId, reviewId },
        );
      }
      const eligibleResolver =
        isReviewer ||
        (state.presenterParticipantId === participantId &&
          revision.authorParticipantId !== participantId);
      if (message.resolutionAction === "resolve" && !eligibleResolver) {
        throw roomError(
          "review_resolution_forbidden",
          "Resolution requires the blocker reviewer or an independent current presenter.",
          "permission_denied",
          { findingId: finding.findingId, reviewId },
        );
      }
      const rationale = text(
        message.rationale,
        "rationale",
        REVIEW_RATIONALE_MAX_LENGTH,
        { required: true },
      ) as string;
      const now = new Date().toISOString();
      const resolution: FindingReviewResolution = {
        resolutionId: `resolution_${crypto.randomUUID()}`,
        blockingReviewId: review.reviewId,
        status:
          message.resolutionAction === "withdraw" ? "withdrawn" : "resolved",
        resolverParticipantId: participantId,
        resolverDisplayName: ticket.displayName,
        rationale,
        createdAt: now,
        clientOperationId: operationId,
        findingId: finding.findingId,
        findingRevision: review.findingRevision,
        resultingRevision: null,
      };
      const patch: FindingReviewStatePatch = {
        reviewResolutions: [resolution],
      };
      if (
        [
          "under_review",
          "reviewed",
          "challenged",
          "revision_requested",
        ].includes(finding.lifecycleState)
      ) {
        const currentRevision = this.revision(
          state,
          finding.findingId,
          finding.currentRevision,
        );
        if (!currentRevision) {
          throw roomError(
            "finding_revision_not_found",
            "The current finding revision is unavailable.",
            "nonexistent_record",
            {
              findingId: finding.findingId,
              currentFindingRevision: finding.currentRevision,
            },
          );
        }
        const lifecycle = this.revisedLifecycle(
          state,
          finding,
          currentRevision,
          [],
          [resolution],
        );
        patch.findings = [{ ...finding, lifecycleState: lifecycle, updatedAt: now }];
        patch.revisions = [{ ...currentRevision, lifecycleState: lifecycle }];
      }
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        "review_blocker_resolved",
        now,
        patch,
      );
      return;
    }

    if (message.type === "finding:relationship:create") {
      const source = this.finding(state, message.sourceFindingId);
      const target = this.finding(state, message.targetFindingId);
      const sourceRevisionNumber = parseFindingRevisionNumber(
        message.sourceRevision,
        "sourceRevision",
      );
      const targetRevisionNumber = parseFindingRevisionNumber(
        message.targetRevision,
        "targetRevision",
      );
      const sourceRevision = this.revision(
        state,
        source.findingId,
        sourceRevisionNumber,
      );
      const targetRevision = this.revision(
        state,
        target.findingId,
        targetRevisionNumber,
      );
      if (!sourceRevision || !targetRevision) {
        throw roomError(
          "relationship_revision_not_found",
          "The relationship source or target revision does not exist.",
          "nonexistent_record",
          {
            findingId: !sourceRevision ? source.findingId : target.findingId,
            requestedFindingRevision: !sourceRevision
              ? sourceRevisionNumber
              : targetRevisionNumber,
            currentFindingRevision: !sourceRevision
              ? source.currentRevision
              : target.currentRevision,
          },
        );
      }
      if (source.findingId === target.findingId) {
        throw roomError(
          "relationship_self_link",
          "A finding cannot link to itself.",
          "malformed_request",
          { findingId: source.findingId },
        );
      }
      if (!isFindingRelationshipType(message.relationshipType)) {
        throw roomError(
          "malformed_relationship_type",
          "Relationship type is invalid.",
          "malformed_request",
        );
      }
      if (message.relationshipType === "supersedes") {
        if (
          sourceRevisionNumber !== source.currentRevision ||
          ["promoted", "superseded", "withdrawn"].includes(source.lifecycleState)
        ) {
          throw roomError(
            "invalid_transition",
            "A superseding link must originate from the current active successor before promotion.",
            "invalid_transition",
            {
              findingId: source.findingId,
              requestedFindingRevision: sourceRevisionNumber,
              currentFindingRevision: source.currentRevision,
            },
          );
        }
        const canSupersede =
          source.creatorParticipantId === participantId ||
          sourceRevision.authorParticipantId === participantId ||
          state.presenterParticipantId === participantId;
        if (!canSupersede) {
          throw roomError(
            "relationship_forbidden",
            "Only the successor creator, revision author, or presenter may supersede another finding.",
            "permission_denied",
            { findingId: source.findingId },
          );
        }
      }
      const rationale = text(
        message.rationale,
        "rationale",
        RELATIONSHIP_RATIONALE_MAX_LENGTH,
        { nullable: true },
      );
      const now = new Date().toISOString();
      const relationship: FindingRelationship = {
        relationshipId: `relationship_${crypto.randomUUID()}`,
        sourceFindingId: source.findingId,
        sourceRevision: sourceRevisionNumber,
        targetFindingId: target.findingId,
        targetRevision: targetRevisionNumber,
        relationshipType: message.relationshipType,
        creatorParticipantId: participantId,
        creatorDisplayName: ticket.displayName,
        rationale,
        createdAt: now,
        clientOperationId: operationId,
      };
      const patch: FindingReviewStatePatch = { relationships: [relationship] };
      let eventType: FindingReviewDomainEvent["eventType"] =
        "relationship_created";
      if (
        relationship.relationshipType === "supersedes" &&
        target.currentRevision === targetRevisionNumber &&
        target.lifecycleState !== "withdrawn" &&
        target.lifecycleState !== "superseded"
      ) {
        patch.findings = [
          { ...target, lifecycleState: "superseded", updatedAt: now },
        ];
        patch.revisions = [
          { ...targetRevision, lifecycleState: "superseded" },
        ];
        eventType = "finding_superseded";
      }
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        eventType,
        now,
        patch,
      );
      return;
    }

    if (message.type === "finding:promote") {
      const finding = this.finding(state, message.findingId);
      const revision = this.exactCurrentRevision(
        state,
        finding,
        message.findingRevision,
      );
      const existing = Object.values(state.reviewState.publicConclusions).find(
        (conclusion) =>
          conclusion.sourceFindingId === finding.findingId &&
          conclusion.sourceRevision === revision.revision,
      );
      if (existing) {
        const response = this.reviewStateResponse(state, operationId);
        await this.persistAndBroadcast(
          state,
          operationId,
          participantId,
          fingerprint,
          response,
        );
        return;
      }
      if (
        !this.hasServerBoundEvidenceReference(
          state,
          finding.findingId,
          revision.evidenceReferences,
        )
      ) {
        throw roomError(
          "promotion_blocked",
          "Promotion is blocked: the immutable server-bound room evidence reference is missing.",
          "promotion_blocked",
          {
            findingId: finding.findingId,
            requestedFindingRevision: revision.revision,
            currentFindingRevision: finding.currentRevision,
            blockerCodes: ["valid_evidence_references"],
          },
        );
      }
      const assessment = assessPromotion({
        findingId: finding.findingId,
        requestedRevision: revision.revision,
        currentRevision: finding.currentRevision,
        lifecycleState: finding.lifecycleState,
        revision,
        reviews: this.reviews(state),
        resolutions: this.resolutions(state),
      });
      if (!assessment.eligible) {
        throw roomError(
          "promotion_blocked",
          `Promotion is blocked: ${assessment.blockerCodes.join(", ")}.`,
          "promotion_blocked",
          {
            findingId: finding.findingId,
            requestedFindingRevision: revision.revision,
            currentFindingRevision: finding.currentRevision,
            blockerCodes: assessment.blockerCodes,
          },
        );
      }
      const now = new Date().toISOString();
      const conclusionId = `conclusion_${crypto.randomUUID()}`;
      const supersedesConclusionIds = Object.values(
        state.reviewState.relationships,
      )
        .filter(
          (relationship) =>
            relationship.relationshipType === "supersedes" &&
            relationship.sourceFindingId === finding.findingId &&
            relationship.sourceRevision === revision.revision,
        )
        .flatMap((relationship) =>
          Object.values(state.reviewState.publicConclusions)
            .filter(
              (conclusion) =>
                conclusion.sourceFindingId === relationship.targetFindingId &&
                conclusion.sourceRevision === relationship.targetRevision,
            )
            .map((conclusion) => conclusion.conclusionId),
        )
        .sort();
      let conclusion;
      try {
        conclusion = createPublicConclusion({
          conclusionId,
          revision,
          reviews: this.reviews(state),
          resolutions: this.resolutions(state),
          artifactId: state.artifactId,
          visualizationId: state.visualizationId,
          publishedAt: now,
          supersedesConclusionIds,
          privateValues: [...this.privatePublicationValues(state), operationId],
        });
      } catch {
        throw roomError(
          "promotion_sanitation_failed",
          "Promotion is blocked because the public conclusion did not pass recursive sanitation.",
          "promotion_blocked",
          {
            findingId: finding.findingId,
            requestedFindingRevision: revision.revision,
            currentFindingRevision: finding.currentRevision,
          },
        );
      }
      const promotedFinding = {
        ...finding,
        lifecycleState: "promoted" as const,
        updatedAt: now,
      };
      const promotedRevision = {
        ...revision,
        lifecycleState: "promoted" as const,
      };
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        "finding_promoted",
        now,
        {
          findings: [promotedFinding],
          revisions: [promotedRevision],
          publicConclusions: [conclusion],
        },
      );
      return;
    }

    if (message.type === "finding:withdraw" || message.type === "finding:delete") {
      const finding = this.finding(state, message.findingId);
      const revision = this.exactCurrentRevision(
        state,
        finding,
        message.type === "finding:withdraw"
          ? message.findingRevision
          : finding.currentRevision,
      );
      if (
        !this.findingCanEdit(state, finding, participantId) &&
        revision.authorParticipantId !== participantId
      ) {
        throw roomError(
          "finding_forbidden",
          "Only the creator, current revision author, or presenter may withdraw this finding.",
          "permission_denied",
          { findingId: finding.findingId },
        );
      }
      if (!canWithdrawFinding(finding.lifecycleState)) {
        throw roomError(
          "invalid_transition",
          "The finding is already withdrawn.",
          "invalid_transition",
          { findingId: finding.findingId },
        );
      }
      const withdrawalRationale =
        message.type === "finding:withdraw"
          ? (text(
              message.rationale,
              "rationale",
              FINDING_REVISION_REASON_MAX_LENGTH,
              { required: true },
            ) as string)
          : "Withdrawn through the compatible Phase 4B delete operation.";
      const now = new Date().toISOString();
      await this.acceptReviewPatch(
        state,
        ticket,
        operationId,
        fingerprint,
        "finding_withdrawn",
        now,
        {
          findings: [
            { ...finding, lifecycleState: "withdrawn", updatedAt: now },
          ],
          revisions: [{ ...revision, lifecycleState: "withdrawn" }],
        },
        withdrawalRationale,
      );
      return;
    }

    throw roomError(
      "unsupported_operation",
      "Unsupported room operation.",
      "malformed_request",
    );
  }

  private accepted(
    operationId: string,
    roomRevision: number,
  ): Extract<RoomServerMessage, { type: "operation:accepted" }> {
    return {
      protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
      type: "operation:accepted",
      operationId,
      roomRevision,
    };
  }

  private send(socket: WebSocket, message: RoomServerMessage): void {
    try {
      const attachment =
        hibernatingSocket(socket).deserializeAttachment() as SocketAttachment | null;
      if (!attachment || !this.isSocketAttachmentFresh(attachment)) {
        socket.close(1008, "Activity session refresh required.");
        return;
      }
      socket.send(JSON.stringify(message));
    } catch {
      // The runtime retires closing peers; one peer must not fail another participant.
    }
  }

  private broadcast(message: RoomServerMessage): void {
    for (const socket of this.state.getWebSockets()) this.send(socket, message);
  }

  private broadcastRoomState(state: PersistedRoomState): void {
    this.broadcast({
      protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
      type: "room:state",
      roomRevision: state.roomRevision,
      participants: this.participants(),
      presenterParticipantId: state.presenterParticipantId,
      selection: state.selection,
      layers: state.layers,
    });
  }
}
