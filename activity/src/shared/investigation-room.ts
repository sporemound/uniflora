import type { EnvironmentName } from "./public-state";
import {
  isFindingLifecycleState,
  isFindingRelationshipType,
  isFindingReviewDisposition,
  isFindingReviewRubric,
} from "./finding-review";
import type {
  FindingAnalysisArtifactReference,
  FindingEvidenceReference,
  FindingLifecycleState,
  FindingRelationship,
  FindingRelationshipType,
  FindingReview,
  FindingReviewDisposition,
  FindingReviewRubric,
  FindingReviewResolution,
  FindingRevision,
  PromotionAssessment,
  PublicConclusion,
} from "./finding-review";

export const INVESTIGATION_ROOM_PROTOCOL_VERSION = "4.3.0" as const;
export const FINDING_TITLE_MAX_LENGTH = 120;
export const FINDING_OBSERVATION_MAX_LENGTH = 2_000;
export const OPERATION_ID_MAX_LENGTH = 96;
export const ROOM_ID_MAX_LENGTH = 96;

export type ScientificSourceView = "waveform" | "spectrogram";
export type RoomConnectionStatus =
  | "disabled"
  | "ticketing"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

export interface RoomScientificSelection {
  startSeconds: number;
  endSeconds: number;
  timeBasis: string;
  sourceView: ScientificSourceView;
}

export interface RoomLayerState {
  rawVoltageV: boolean;
  calibratedVoltageV: boolean;
  residualVoltageV: boolean;
  uncertainty: boolean;
}

export interface RoomParticipant {
  participantId: string;
  displayName: string;
  connectedAt: string;
}

export interface RoomFinding {
  findingId: string;
  roomId: string;
  artifactId: string;
  visualizationId: string;
  selection: RoomScientificSelection;
  layers: RoomLayerState;
  title: string;
  observation: string;
  creatorParticipantId: string;
  creatorDisplayName: string;
  createdAt: string;
  updatedAt: string;
  revision: number;
  currentRevision: number;
  lifecycleState: FindingLifecycleState;
}

export interface InvestigationRoomReviewState {
  findings: RoomFinding[];
  findingRevisions: FindingRevision[];
  reviews: FindingReview[];
  reviewResolutions: FindingReviewResolution[];
  relationships: FindingRelationship[];
  publicConclusions: PublicConclusion[];
  promotionAssessments: PromotionAssessment[];
}

export interface InvestigationRoomSnapshot {
  protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
  roomId: string;
  artifactId: string;
  visualizationId: string;
  roomRevision: number;
  participants: RoomParticipant[];
  presenterParticipantId: string | null;
  selection: RoomScientificSelection | null;
  layers: RoomLayerState;
  findings: RoomFinding[];
  findingRevisions: FindingRevision[];
  reviews: FindingReview[];
  reviewResolutions: FindingReviewResolution[];
  relationships: FindingRelationship[];
  publicConclusions: PublicConclusion[];
  promotionAssessments: PromotionAssessment[];
}

export interface RoomTicketRequest {
  roomId: string;
  environment: EnvironmentName;
  artifactId: string;
  visualizationId: string;
  minimumSeconds: number;
  maximumSeconds: number;
  timeBases: string[];
  clientInstanceId: string;
}

export interface RoomTicketResponse {
  ticket: string;
  expiresAt: string;
  participantId: string;
  displayName: string;
  websocketPath: string;
}

export interface FindingRevisionContent {
  statement: string;
  interpretation: string | null;
  limitations: string[];
  evidenceReferences: FindingEvidenceReference[];
  analysisArtifactReferences: FindingAnalysisArtifactReference[];
}

export type RoomOperationErrorCategory =
  | "stale_revision"
  | "invalid_transition"
  | "permission_denied"
  | "promotion_blocked"
  | "malformed_request"
  | "nonexistent_record"
  | "operation_conflict";

export interface RoomOperationErrorDetails {
  category: RoomOperationErrorCategory;
  findingId?: string;
  requestedFindingRevision?: number;
  currentFindingRevision?: number;
  reviewId?: string;
  relationshipId?: string;
  blockerCodes?: string[];
}

export type RoomClientMessage =
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "selection:set";
      operationId: string;
      expectedRevision: number;
      selection: RoomScientificSelection;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "layers:set";
      operationId: string;
      expectedRevision: number;
      layers: RoomLayerState;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "presenter:claim" | "presenter:release";
      operationId: string;
      expectedRevision: number;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:create";
      operationId: string;
      expectedRevision: number;
      finding: {
        title: string;
        observation: string;
        selection: RoomScientificSelection;
        layers: RoomLayerState;
        interpretation?: string | null;
        limitations?: string[];
        evidenceReferences?: FindingEvidenceReference[];
        analysisArtifactReferences?: FindingAnalysisArtifactReference[];
      };
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:open";
      operationId: string;
      expectedRevision: number;
      findingId: string;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:update";
      operationId: string;
      expectedRevision: number;
      findingId: string;
      title: string;
      observation: string;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:delete";
      operationId: string;
      expectedRevision: number;
      findingId: string;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:revise";
      operationId: string;
      expectedRevision: number;
      findingId: string;
      findingRevision: number;
      revision: FindingRevisionContent & {
        revisionReason: string;
        addressedReviewIds: string[];
      };
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:review:start";
      operationId: string;
      expectedRevision: number;
      findingId: string;
      findingRevision: number;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:review:submit";
      operationId: string;
      expectedRevision: number;
      findingId: string;
      findingRevision: number;
      disposition: FindingReviewDisposition;
      rationale: string;
      rubric: FindingReviewRubric;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:review:resolve";
      operationId: string;
      expectedRevision: number;
      findingId: string;
      findingRevision: number;
      reviewId: string;
      resolutionAction: "resolve" | "withdraw";
      rationale: string;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:relationship:create";
      operationId: string;
      expectedRevision: number;
      sourceFindingId: string;
      sourceRevision: number;
      targetFindingId: string;
      targetRevision: number;
      relationshipType: FindingRelationshipType;
      rationale: string | null;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:promote";
      operationId: string;
      expectedRevision: number;
      findingId: string;
      findingRevision: number;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:withdraw";
      operationId: string;
      expectedRevision: number;
      findingId: string;
      findingRevision: number;
      rationale: string;
    };

export type RoomServerMessage =
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "room:snapshot";
      snapshot: InvestigationRoomSnapshot;
      selfParticipantId: string;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "room:state";
      roomRevision: number;
      participants: RoomParticipant[];
      presenterParticipantId: string | null;
      selection: RoomScientificSelection | null;
      layers: RoomLayerState;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:created" | "finding:updated";
      operationId: string;
      roomRevision: number;
      finding: RoomFinding;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "finding:deleted";
      operationId: string;
      roomRevision: number;
      findingId: string;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "operation:accepted";
      operationId: string;
      roomRevision: number;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "room:review-state";
      operationId: string;
      roomRevision: number;
      status: "accepted";
      reviewState: InvestigationRoomReviewState;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "operation:duplicate";
      operationId: string;
      roomRevision: number;
      originalResponseType: string;
    }
  | {
      protocolVersion: typeof INVESTIGATION_ROOM_PROTOCOL_VERSION;
      type: "room:error";
      operationId: string | null;
      code: string;
      message: string;
      roomRevision: number;
      details: RoomOperationErrorDetails;
      reviewState: InvestigationRoomReviewState;
    };

export function isRoomServerMessage(value: unknown): value is RoomServerMessage {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (record.protocolVersion !== INVESTIGATION_ROOM_PROTOCOL_VERSION) return false;
  const hasRevision = Number.isSafeInteger(record.roomRevision);
  switch (record.type) {
    case "room:snapshot":
      return (
        typeof record.selfParticipantId === "string" &&
        isReviewSnapshot(record.snapshot)
      );
    case "room:state":
      return (
        hasRevision &&
        isParticipantArray(record.participants) &&
        (record.presenterParticipantId === null ||
          typeof record.presenterParticipantId === "string") &&
        isLayerState(record.layers) &&
        (record.selection === null || isScientificSelection(record.selection))
      );
    case "finding:created":
    case "finding:updated":
      return (
        hasRevision &&
        typeof record.operationId === "string" &&
        isRoomFinding(record.finding)
      );
    case "finding:deleted":
      return (
        hasRevision &&
        typeof record.operationId === "string" &&
        typeof record.findingId === "string"
      );
    case "operation:accepted":
      return hasRevision && typeof record.operationId === "string";
    case "room:review-state":
      return (
        hasRevision &&
        typeof record.operationId === "string" &&
        record.status === "accepted" &&
        isReviewState(record.reviewState)
      );
    case "operation:duplicate":
      return (
        hasRevision &&
        typeof record.operationId === "string" &&
        typeof record.originalResponseType === "string"
      );
    case "room:error":
      return (
        hasRevision &&
        (record.operationId === null || typeof record.operationId === "string") &&
        typeof record.code === "string" &&
        typeof record.message === "string" &&
        typeof record.details === "object" &&
        record.details !== null &&
        isReviewState(record.reviewState)
      );
    default:
      return false;
  }
}

function isLayerState(value: unknown): value is RoomLayerState {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.rawVoltageV === "boolean" &&
    typeof record.calibratedVoltageV === "boolean" &&
    typeof record.residualVoltageV === "boolean" &&
    typeof record.uncertainty === "boolean"
  );
}

function isNonArrayRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isParticipantArray(value: unknown): value is RoomParticipant[] {
  return (
    Array.isArray(value) &&
    value.every(
      (participant) =>
        isNonArrayRecord(participant) &&
        typeof participant.participantId === "string" &&
        typeof participant.displayName === "string" &&
        typeof participant.connectedAt === "string",
    )
  );
}

function isRoomFinding(value: unknown): value is RoomFinding {
  return (
    isNonArrayRecord(value) &&
    typeof value.findingId === "string" &&
    typeof value.roomId === "string" &&
    typeof value.artifactId === "string" &&
    typeof value.visualizationId === "string" &&
    typeof value.title === "string" &&
    typeof value.observation === "string" &&
    typeof value.creatorParticipantId === "string" &&
    typeof value.creatorDisplayName === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.updatedAt === "string" &&
    Number.isSafeInteger(value.currentRevision) &&
    isFindingLifecycleState(value.lifecycleState) &&
    isScientificSelection(value.selection) &&
    isLayerState(value.layers)
  );
}

function isScientificSelection(value: unknown): value is RoomScientificSelection {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.startSeconds === "number" &&
    Number.isFinite(record.startSeconds) &&
    typeof record.endSeconds === "number" &&
    Number.isFinite(record.endSeconds) &&
    typeof record.timeBasis === "string" &&
    (record.sourceView === "waveform" || record.sourceView === "spectrogram")
  );
}

function isReviewState(value: unknown): value is InvestigationRoomReviewState {
  if (!isNonArrayRecord(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    Array.isArray(record.findings) &&
    record.findings.every(isRoomFinding) &&
    Array.isArray(record.findingRevisions) &&
    record.findingRevisions.every(
      (revision) =>
        isNonArrayRecord(revision) &&
        typeof revision.findingId === "string" &&
        Number.isSafeInteger(revision.revision) &&
        typeof revision.statement === "string" &&
        typeof revision.authorParticipantId === "string" &&
        typeof revision.createdAt === "string" &&
        isFindingLifecycleState(revision.lifecycleState) &&
        Array.isArray(revision.limitations) &&
        Array.isArray(revision.evidenceReferences) &&
        Array.isArray(revision.analysisArtifactReferences),
    ) &&
    Array.isArray(record.reviews) &&
    record.reviews.every(
      (review) =>
        isNonArrayRecord(review) &&
        typeof review.reviewId === "string" &&
        typeof review.findingId === "string" &&
        Number.isSafeInteger(review.findingRevision) &&
        typeof review.reviewerParticipantId === "string" &&
        isFindingReviewDisposition(review.disposition) &&
        (review.rubric === undefined ||
          review.rubric === null ||
          isFindingReviewRubric(review.rubric)),
    ) &&
    Array.isArray(record.reviewResolutions) &&
    record.reviewResolutions.every(
      (resolution) =>
        isNonArrayRecord(resolution) &&
        typeof resolution.resolutionId === "string" &&
        typeof resolution.blockingReviewId === "string" &&
        ["withdrawn", "resolved", "addressed_by_revision"].includes(
          String(resolution.status),
        ),
    ) &&
    Array.isArray(record.relationships) &&
    record.relationships.every(
      (relationship) =>
        isNonArrayRecord(relationship) &&
        typeof relationship.relationshipId === "string" &&
        typeof relationship.sourceFindingId === "string" &&
        Number.isSafeInteger(relationship.sourceRevision) &&
        typeof relationship.targetFindingId === "string" &&
        Number.isSafeInteger(relationship.targetRevision) &&
        isFindingRelationshipType(relationship.relationshipType),
    ) &&
    Array.isArray(record.publicConclusions) &&
    record.publicConclusions.every(
      (conclusion) =>
        isNonArrayRecord(conclusion) &&
        typeof conclusion.conclusionId === "string" &&
        typeof conclusion.sourceFindingId === "string" &&
        Number.isSafeInteger(conclusion.sourceRevision) &&
        conclusion.lifecycleStatus === "promoted",
    ) &&
    Array.isArray(record.promotionAssessments) &&
    record.promotionAssessments.every(
      (assessment) =>
        isNonArrayRecord(assessment) &&
        typeof assessment.findingId === "string" &&
        Number.isSafeInteger(assessment.findingRevision) &&
        typeof assessment.eligible === "boolean" &&
        Array.isArray(assessment.checks) &&
        Array.isArray(assessment.blockerCodes),
    )
  );
}

function isReviewSnapshot(value: unknown): value is InvestigationRoomSnapshot {
  if (!isReviewState(value)) return false;
  const record = value as unknown as Record<string, unknown>;
  return (
    typeof record.roomId === "string" &&
    typeof record.artifactId === "string" &&
    typeof record.visualizationId === "string" &&
    Number.isSafeInteger(record.roomRevision) &&
    isParticipantArray(record.participants) &&
    (record.presenterParticipantId === null ||
      typeof record.presenterParticipantId === "string") &&
    isLayerState(record.layers) &&
    (record.selection === null || isScientificSelection(record.selection))
  );
}
