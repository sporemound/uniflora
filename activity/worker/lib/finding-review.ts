import {
  assessPromotion,
  type FindingRelationship,
  type FindingReview,
  type FindingReviewResolution,
  type FindingRevision,
  type PromotionAssessment,
  type PublicConclusion,
} from "../../src/shared/finding-review";
import type {
  InvestigationRoomReviewState,
  RoomFinding,
} from "../../src/shared/investigation-room";

export interface PersistedFindingReviewState {
  findings: Record<string, RoomFinding>;
  revisions: Record<string, FindingRevision>;
  reviews: Record<string, FindingReview>;
  reviewResolutions: Record<string, FindingReviewResolution>;
  relationships: Record<string, FindingRelationship>;
  publicConclusions: Record<string, PublicConclusion>;
}

export interface FindingReviewStatePatch {
  findings?: RoomFinding[];
  revisions?: FindingRevision[];
  reviews?: FindingReview[];
  reviewResolutions?: FindingReviewResolution[];
  relationships?: FindingRelationship[];
  publicConclusions?: PublicConclusion[];
}

export interface FindingReviewDomainEvent {
  eventId: string;
  operationId: string;
  eventType:
    | "finding_created"
    | "finding_revised"
    | "review_started"
    | "review_submitted"
    | "review_blocker_resolved"
    | "relationship_created"
    | "finding_promoted"
    | "finding_superseded"
    | "finding_withdrawn";
  roomRevision: number;
  createdAt: string;
  audit: {
    actorParticipantId: string;
    actorDisplayName: string;
    rationale: string | null;
  };
  patch: FindingReviewStatePatch;
}

function safeRecord<T>(): Record<string, T> {
  return Object.create(null) as Record<string, T>;
}

function normalizedRecord<T>(value: Record<string, T> | undefined): Record<string, T> {
  const result = safeRecord<T>();
  if (!value || typeof value !== "object") return result;
  for (const [key, item] of Object.entries(value)) result[key] = item;
  return result;
}

export function emptyFindingReviewState(): PersistedFindingReviewState {
  return {
    findings: safeRecord(),
    revisions: safeRecord(),
    reviews: safeRecord(),
    reviewResolutions: safeRecord(),
    relationships: safeRecord(),
    publicConclusions: safeRecord(),
  };
}

export function normalizeFindingReviewState(
  value: Partial<PersistedFindingReviewState> | undefined,
): PersistedFindingReviewState {
  return {
    findings: normalizedRecord(value?.findings),
    revisions: normalizedRecord(value?.revisions),
    reviews: normalizedRecord(value?.reviews),
    reviewResolutions: normalizedRecord(value?.reviewResolutions),
    relationships: normalizedRecord(value?.relationships),
    publicConclusions: normalizedRecord(value?.publicConclusions),
  };
}

export function findingRevisionKey(findingId: string, revision: number): string {
  return `${findingId}:revision:${revision}`;
}

export function applyFindingReviewPatch(
  state: PersistedFindingReviewState,
  patch: FindingReviewStatePatch,
): PersistedFindingReviewState {
  for (const finding of patch.findings ?? []) {
    state.findings[finding.findingId] = structuredClone(finding);
  }
  for (const revision of patch.revisions ?? []) {
    state.revisions[findingRevisionKey(revision.findingId, revision.revision)] =
      structuredClone(revision);
  }
  for (const review of patch.reviews ?? []) {
    state.reviews[review.reviewId] = structuredClone(review);
  }
  for (const resolution of patch.reviewResolutions ?? []) {
    state.reviewResolutions[resolution.resolutionId] = structuredClone(resolution);
  }
  for (const relationship of patch.relationships ?? []) {
    state.relationships[relationship.relationshipId] = structuredClone(relationship);
  }
  for (const conclusion of patch.publicConclusions ?? []) {
    state.publicConclusions[conclusion.conclusionId] = structuredClone(conclusion);
  }
  return state;
}

export function replayFindingReviewEvents(
  events: readonly FindingReviewDomainEvent[],
): PersistedFindingReviewState {
  const state = emptyFindingReviewState();
  for (const event of events) applyFindingReviewPatch(state, event.patch);
  return state;
}

export function isValidFindingReviewEventSequence(
  events: readonly FindingReviewDomainEvent[],
): boolean {
  const eventIds = new Set<string>();
  const operationIds = new Set<string>();
  let previousRoomRevision = -1;
  for (const event of events) {
    if (
      typeof event !== "object" ||
      event === null ||
      typeof event.eventId !== "string" ||
      typeof event.operationId !== "string" ||
      typeof event.createdAt !== "string" ||
      !Number.isSafeInteger(event.roomRevision) ||
      event.roomRevision <= previousRoomRevision ||
      eventIds.has(event.eventId) ||
      operationIds.has(event.operationId) ||
      typeof event.patch !== "object" ||
      event.patch === null
    ) {
      return false;
    }
    for (const field of [
      "findings",
      "revisions",
      "reviews",
      "reviewResolutions",
      "relationships",
      "publicConclusions",
    ] as const) {
      if (event.patch[field] !== undefined && !Array.isArray(event.patch[field])) {
        return false;
      }
    }
    eventIds.add(event.eventId);
    operationIds.add(event.operationId);
    previousRoomRevision = event.roomRevision;
  }
  return true;
}

function sorted<T>(
  values: Iterable<T>,
  compare: (left: T, right: T) => number,
): T[] {
  return [...values].sort(compare);
}

export function findingReviewSnapshot(
  state: PersistedFindingReviewState,
): InvestigationRoomReviewState {
  const findings = sorted(
    Object.values(state.findings),
    (left, right) =>
      right.updatedAt.localeCompare(left.updatedAt) ||
      left.findingId.localeCompare(right.findingId),
  );
  const findingRevisions = sorted(
    Object.values(state.revisions),
    (left, right) =>
      left.findingId.localeCompare(right.findingId) ||
      left.revision - right.revision,
  );
  const reviews = sorted(
    Object.values(state.reviews),
    (left, right) =>
      left.findingId.localeCompare(right.findingId) ||
      left.findingRevision - right.findingRevision ||
      left.createdAt.localeCompare(right.createdAt) ||
      left.reviewId.localeCompare(right.reviewId),
  );
  const reviewResolutions = sorted(
    Object.values(state.reviewResolutions),
    (left, right) =>
      left.createdAt.localeCompare(right.createdAt) ||
      left.resolutionId.localeCompare(right.resolutionId),
  );
  const relationships = sorted(
    Object.values(state.relationships),
    (left, right) =>
      left.createdAt.localeCompare(right.createdAt) ||
      left.relationshipId.localeCompare(right.relationshipId),
  );
  const publicConclusions = sorted(
    Object.values(state.publicConclusions),
    (left, right) =>
      left.publishedAt.localeCompare(right.publishedAt) ||
      left.conclusionId.localeCompare(right.conclusionId),
  );
  const promotionAssessments: PromotionAssessment[] = findings.map((finding) => {
    const revision =
      state.revisions[findingRevisionKey(finding.findingId, finding.currentRevision)];
    if (!revision) {
      return {
        findingId: finding.findingId,
        findingRevision: finding.currentRevision,
        eligible: false,
        checks: [],
        blockerCodes: ["exact_current_revision"],
      };
    }
    return assessPromotion({
      findingId: finding.findingId,
      requestedRevision: finding.currentRevision,
      currentRevision: finding.currentRevision,
      lifecycleState: finding.lifecycleState,
      revision,
      reviews,
      resolutions: reviewResolutions,
    });
  });
  return {
    findings,
    findingRevisions,
    reviews,
    reviewResolutions,
    relationships,
    publicConclusions,
    promotionAssessments,
  };
}
