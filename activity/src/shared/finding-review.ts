export const FINDING_STATEMENT_MAX_LENGTH = 240;
export const FINDING_INTERPRETATION_MAX_LENGTH = 4_000;
export const FINDING_LIMITATION_MAX_LENGTH = 1_000;
export const FINDING_REVISION_REASON_MAX_LENGTH = 1_000;
export const REVIEW_RATIONALE_MAX_LENGTH = 2_000;
export const RELATIONSHIP_RATIONALE_MAX_LENGTH = 1_000;
export const REFERENCE_LABEL_MAX_LENGTH = 240;

export const FINDING_LIFECYCLE_STATES = [
  "draft",
  "under_review",
  "revision_requested",
  "challenged",
  "reviewed",
  "promoted",
  "superseded",
  "withdrawn",
] as const;

export const FINDING_REVIEW_DISPOSITIONS = [
  "endorse",
  "challenge",
  "request_revision",
] as const;

export const FINDING_RELATIONSHIP_TYPES = [
  "supports",
  "related_to",
  "conflicts_with",
  "supersedes",
] as const;

export type FindingLifecycleState = (typeof FINDING_LIFECYCLE_STATES)[number];
export type FindingReviewDisposition = (typeof FINDING_REVIEW_DISPOSITIONS)[number];
export type FindingRelationshipType = (typeof FINDING_RELATIONSHIP_TYPES)[number];
export type ProvenanceAvailability = "available" | "incomplete" | "unavailable";

export interface FindingReviewRubric {
  evidenceSupport: number;
  ordinaryAlternatives: number;
  contradictionsPreserved: number;
  confidenceCalibration: number;
  reproducibility: number;
}

export interface FindingEvidenceReference {
  referenceId: string;
  sourceType: "observation" | "activity_artifact";
  observationId: string | null;
  artifactId: string | null;
  visualizationId: string | null;
  label: string;
  availability: ProvenanceAvailability;
  publicSafe: boolean;
}

export interface FindingAnalysisArtifactReference {
  referenceId: string;
  analysisJobId: string | null;
  analysisArtifactId: string;
  artifactHash: string | null;
  label: string;
  availability: ProvenanceAvailability;
  publicSafe: boolean;
}

export interface FindingRevision {
  findingId: string;
  revision: number;
  previousRevision: number | null;
  statement: string;
  interpretation: string | null;
  limitations: string[];
  evidenceReferences: FindingEvidenceReference[];
  analysisArtifactReferences: FindingAnalysisArtifactReference[];
  authorParticipantId: string;
  authorDisplayName: string;
  createdAt: string;
  revisionReason: string;
  lifecycleState: FindingLifecycleState;
  addressedReviewIds: string[];
}

export interface FindingReview {
  reviewId: string;
  findingId: string;
  findingRevision: number;
  reviewerParticipantId: string;
  reviewerDisplayName: string;
  disposition: FindingReviewDisposition;
  rationale: string | null;
  rubric: FindingReviewRubric | null;
  createdAt: string;
  clientOperationId: string;
  roomContext: {
    roomId: string;
    artifactId: string;
    visualizationId: string;
  };
}

export type ReviewResolutionStatus =
  | "withdrawn"
  | "resolved"
  | "addressed_by_revision";

export interface FindingReviewResolution {
  resolutionId: string;
  blockingReviewId: string;
  status: ReviewResolutionStatus;
  resolverParticipantId: string;
  resolverDisplayName: string;
  rationale: string;
  createdAt: string;
  clientOperationId: string;
  findingId: string;
  findingRevision: number;
  resultingRevision: number | null;
}

export interface FindingRelationship {
  relationshipId: string;
  sourceFindingId: string;
  sourceRevision: number;
  targetFindingId: string;
  targetRevision: number;
  relationshipType: FindingRelationshipType;
  creatorParticipantId: string;
  creatorDisplayName: string;
  rationale: string | null;
  createdAt: string;
  clientOperationId: string;
}

export interface PublicEvidenceReference {
  referenceId: string;
  sourceType: FindingEvidenceReference["sourceType"];
  observationId: string | null;
  artifactId: string | null;
  visualizationId: string | null;
  label: string;
  availability: ProvenanceAvailability;
}

export interface PublicAnalysisArtifactReference {
  referenceId: string;
  analysisJobId: string | null;
  analysisArtifactId: string;
  artifactHash: string | null;
  label: string;
  availability: ProvenanceAvailability;
}

export type ProvenanceStage =
  | "observation"
  | "analysis_job"
  | "analysis_artifact"
  | "finding_revision"
  | "peer_review"
  | "promoted_conclusion";

export interface PublicProvenanceStage {
  stage: ProvenanceStage;
  availability: ProvenanceAvailability;
  references: string[];
}

export interface PublicProvenanceSummary {
  stages: PublicProvenanceStage[];
  missingLinks: ProvenanceStage[];
  reviewSummary: {
    total: number;
    endorsements: number;
    challenges: number;
    revisionRequests: number;
    resolvedBlockers: number;
  };
}

export interface PublicConclusion {
  conclusionId: string;
  sourceFindingId: string;
  sourceRevision: number;
  statement: string;
  interpretation: string | null;
  limitations: string[];
  evidenceReferences: PublicEvidenceReference[];
  analysisArtifactReferences: PublicAnalysisArtifactReference[];
  institutionContext: string;
  investigationContext: {
    artifactId: string;
    visualizationId: string;
  };
  publishedAt: string;
  lifecycleStatus: "promoted";
  provenance: PublicProvenanceSummary;
  supersession: {
    supersedesConclusionIds: string[];
    supersededByConclusionId: null;
  };
}

export interface PromotionCheck {
  code:
    | "exact_current_revision"
    | "reviewable_lifecycle"
    | "independent_endorsement"
    | "no_unresolved_challenge"
    | "no_unresolved_revision_request"
    | "valid_evidence_references"
    | "valid_analysis_references";
  satisfied: boolean;
  detail: string;
}

export interface PromotionAssessment {
  findingId: string;
  findingRevision: number;
  eligible: boolean;
  checks: PromotionCheck[];
  blockerCodes: PromotionCheck["code"][];
}

export interface PromotionAssessmentInput {
  findingId: string;
  requestedRevision: number;
  currentRevision: number;
  lifecycleState: FindingLifecycleState;
  revision: FindingRevision;
  reviews: readonly FindingReview[];
  resolutions: readonly FindingReviewResolution[];
}

const SAFE_IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/u;
const SHA256 = /^[a-f0-9]{64}$/u;

export function isSafeIdentifier(value: string): boolean {
  return SAFE_IDENTIFIER.test(value) && value !== "__proto__" && value !== "constructor";
}

export function isFindingLifecycleState(value: unknown): value is FindingLifecycleState {
  return FINDING_LIFECYCLE_STATES.includes(value as FindingLifecycleState);
}

export function isFindingReviewDisposition(value: unknown): value is FindingReviewDisposition {
  return FINDING_REVIEW_DISPOSITIONS.includes(value as FindingReviewDisposition);
}

export function isFindingReviewRubric(value: unknown): value is FindingReviewRubric {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  const keys = [
    "evidenceSupport",
    "ordinaryAlternatives",
    "contradictionsPreserved",
    "confidenceCalibration",
    "reproducibility",
  ] as const;
  return (
    Object.keys(record).length === keys.length &&
    keys.every(
      (key) =>
        Number.isInteger(record[key]) &&
        (record[key] as number) >= 0 &&
        (record[key] as number) <= 2,
    )
  );
}

export function isFindingRelationshipType(value: unknown): value is FindingRelationshipType {
  return FINDING_RELATIONSHIP_TYPES.includes(value as FindingRelationshipType);
}

export function isEvidenceReferenceStructurallyValid(
  reference: FindingEvidenceReference,
): boolean {
  if (
    !isSafeIdentifier(reference.referenceId) ||
    !["observation", "activity_artifact"].includes(reference.sourceType) ||
    !["available", "incomplete", "unavailable"].includes(reference.availability) ||
    typeof reference.publicSafe !== "boolean" ||
    !reference.label.trim() ||
    reference.label.length > REFERENCE_LABEL_MAX_LENGTH
  ) {
    return false;
  }
  if (reference.observationId !== null && !isSafeIdentifier(reference.observationId)) return false;
  if (reference.artifactId !== null && !isSafeIdentifier(reference.artifactId)) return false;
  if (reference.visualizationId !== null && !isSafeIdentifier(reference.visualizationId)) return false;
  if (reference.sourceType === "observation") return reference.observationId !== null;
  return reference.artifactId !== null;
}

export function isAnalysisReferenceStructurallyValid(
  reference: FindingAnalysisArtifactReference,
): boolean {
  return (
    isSafeIdentifier(reference.referenceId) &&
    isSafeIdentifier(reference.analysisArtifactId) &&
    (reference.analysisJobId === null || isSafeIdentifier(reference.analysisJobId)) &&
    (reference.artifactHash === null || SHA256.test(reference.artifactHash)) &&
    ["available", "incomplete", "unavailable"].includes(reference.availability) &&
    typeof reference.publicSafe === "boolean" &&
    Boolean(reference.label.trim()) &&
    reference.label.length <= REFERENCE_LABEL_MAX_LENGTH
  );
}

export function resolutionForReview(
  reviewId: string,
  resolutions: readonly FindingReviewResolution[],
): FindingReviewResolution | null {
  return (
    [...resolutions]
      .filter((resolution) => resolution.blockingReviewId === reviewId)
      .sort((left, right) => {
        const time = right.createdAt.localeCompare(left.createdAt);
        return time || right.resolutionId.localeCompare(left.resolutionId);
      })[0] ?? null
  );
}

export function isReviewBlockerResolved(
  review: FindingReview,
  resolutions: readonly FindingReviewResolution[],
): boolean {
  if (review.disposition === "endorse") return true;
  return resolutionForReview(review.reviewId, resolutions) !== null;
}

function unresolvedBlockers(
  input: PromotionAssessmentInput,
  disposition: "challenge" | "request_revision",
): FindingReview[] {
  return input.reviews.filter((review) => {
    if (review.findingId !== input.findingId || review.disposition !== disposition) return false;
    const applies =
      review.findingRevision === input.requestedRevision ||
      (disposition === "request_revision" && review.findingRevision < input.requestedRevision);
    return applies && !isReviewBlockerResolved(review, input.resolutions);
  });
}

export function assessPromotion(input: PromotionAssessmentInput): PromotionAssessment {
  const exactReviews = input.reviews.filter(
    (review) =>
      review.findingId === input.findingId &&
      review.findingRevision === input.requestedRevision,
  );
  const hasIndependentEndorsement = exactReviews.some(
    (review) =>
      review.disposition === "endorse" &&
      review.reviewerParticipantId !== input.revision.authorParticipantId,
  );
  const challenges = unresolvedBlockers(input, "challenge");
  const revisionRequests = unresolvedBlockers(input, "request_revision");
  const checks: PromotionCheck[] = [
    {
      code: "exact_current_revision",
      satisfied: input.requestedRevision === input.currentRevision,
      detail: "Promotion targets the exact current immutable revision.",
    },
    {
      code: "reviewable_lifecycle",
      satisfied:
        input.lifecycleState === "under_review" || input.lifecycleState === "reviewed",
      detail: "The current revision is under review or reviewed.",
    },
    {
      code: "independent_endorsement",
      satisfied: hasIndependentEndorsement,
      detail: "At least one endorsement is from someone other than the revision author.",
    },
    {
      code: "no_unresolved_challenge",
      satisfied: challenges.length === 0,
      detail: "No unresolved challenge applies to the current revision.",
    },
    {
      code: "no_unresolved_revision_request",
      satisfied: revisionRequests.length === 0,
      detail: "No unresolved current or explicitly unaddressed prior revision request remains.",
    },
    {
      code: "valid_evidence_references",
      satisfied: input.revision.evidenceReferences.every(isEvidenceReferenceStructurallyValid),
      detail: "Every supplied evidence reference is structurally valid.",
    },
    {
      code: "valid_analysis_references",
      satisfied: input.revision.analysisArtifactReferences.every(
        isAnalysisReferenceStructurallyValid,
      ),
      detail: "Every supplied Milestone 6J analysis-artifact reference is structurally valid.",
    },
  ];
  const blockerCodes = checks
    .filter((check) => !check.satisfied)
    .map((check) => check.code);
  return {
    findingId: input.findingId,
    findingRevision: input.requestedRevision,
    eligible: blockerCodes.length === 0,
    checks,
    blockerCodes,
  };
}

export function effectiveReviewLifecycle(
  input: PromotionAssessmentInput,
): FindingLifecycleState {
  if (unresolvedBlockers(input, "challenge").length > 0) return "challenged";
  if (unresolvedBlockers(input, "request_revision").length > 0) {
    return "revision_requested";
  }
  const independent = input.reviews.some(
    (review) =>
      review.findingId === input.findingId &&
      review.findingRevision === input.requestedRevision &&
      review.disposition === "endorse" &&
      review.reviewerParticipantId !== input.revision.authorParticipantId,
  );
  return independent ? "reviewed" : "under_review";
}

export function canStartReview(state: FindingLifecycleState): boolean {
  return state === "draft";
}

export function canWithdrawFinding(state: FindingLifecycleState): boolean {
  return state !== "withdrawn";
}

const FORBIDDEN_PUBLIC_KEY_FRAGMENTS = [
  "discorduserid",
  "participantid",
  "revieweridentity",
  "reviewerparticipant",
  "authoridentity",
  "authorparticipant",
  "sessiontoken",
  "roomticket",
  "clientoperationid",
  "operationid",
  "clientinstanceid",
  "websocketattachment",
  "durableobjectstorage",
  "privatenote",
  "roomlog",
  "hmac",
  "secret",
  "devvars",
] as const;

function normalizedPublicKey(key: string): string {
  return key.toLowerCase().replace(/[^a-z0-9]/gu, "");
}

function isForbiddenPublicKey(key: string): boolean {
  const normalized = normalizedPublicKey(key);
  return FORBIDDEN_PUBLIC_KEY_FRAGMENTS.some((fragment) => normalized.includes(fragment));
}

export function publicSanitationViolations(
  value: unknown,
  path = "$",
  privateValues: readonly string[] = [],
): string[] {
  if (typeof value === "string") {
    const exposesDiscordSnowflake = /\b\d{17,20}\b/u.test(value);
    const exposesCredentialLabel =
      /(?:bearer\s+[a-f0-9]{32,}|(?:session|room[\s_-]*ticket|hmac|secret|client[\s_-]*operation)[\s_-]*(?:token|id|material)?\s*[:=])/iu.test(
        value,
      );
    const exposesEnvironmentFile = /\.dev\.vars/iu.test(value);
    const digestAllowedAtPath = [
      ".artifactHash",
      ".artifactId",
      ".analysisArtifactId",
      ".analysisJobId",
      ".observationId",
      ".referenceId",
    ].some((suffix) => path.endsWith(suffix));
    const exposesUnlabelledDigest =
      /^[a-f0-9]{64}$/iu.test(value) && !digestAllowedAtPath;
    const isUserSuppliedPublicContent =
      path.endsWith(".statement") ||
      path.endsWith(".interpretation") ||
      path.includes(".limitations[") ||
      path.includes(".evidenceReferences[") ||
      path.includes(".analysisArtifactReferences[");
    const exposesKnownPrivateValue =
      isUserSuppliedPublicContent &&
      privateValues
        .filter((privateValue) => privateValue.length >= 3)
        .some((privateValue) => value.includes(privateValue));
    return exposesDiscordSnowflake ||
      exposesCredentialLabel ||
      exposesEnvironmentFile ||
      exposesUnlabelledDigest ||
      exposesKnownPrivateValue
      ? [path]
      : [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      publicSanitationViolations(item, `${path}[${index}]`, privateValues),
    );
  }
  if (typeof value !== "object" || value === null) return [];
  const violations: string[] = [];
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const childPath = `${path}.${key}`;
    if (isForbiddenPublicKey(key)) violations.push(childPath);
    violations.push(...publicSanitationViolations(child, childPath, privateValues));
  }
  return violations;
}

export function assertPublicSanitized(
  value: unknown,
  privateValues: readonly string[] = [],
): void {
  const violations = publicSanitationViolations(value, "$", privateValues);
  if (violations.length > 0) {
    throw new Error(`Public conclusion contains forbidden fields: ${violations.join(", ")}`);
  }
}

export function publicEvidenceReferences(
  references: readonly FindingEvidenceReference[],
): PublicEvidenceReference[] {
  return references
    .filter((reference) => reference.publicSafe)
    .map((reference) => ({
      referenceId: reference.referenceId,
      sourceType: reference.sourceType,
      observationId: reference.observationId,
      artifactId: reference.artifactId,
      visualizationId: reference.visualizationId,
      label: reference.label,
      availability: reference.availability,
    }));
}

export function publicAnalysisReferences(
  references: readonly FindingAnalysisArtifactReference[],
): PublicAnalysisArtifactReference[] {
  return references
    .filter((reference) => reference.publicSafe)
    .map((reference) => ({
      referenceId: reference.referenceId,
      analysisJobId: reference.analysisJobId,
      analysisArtifactId: reference.analysisArtifactId,
      artifactHash: reference.artifactHash,
      label: reference.label,
      availability: reference.availability,
    }));
}

function stageAvailability(
  references: readonly { availability: ProvenanceAvailability }[],
): ProvenanceAvailability {
  if (references.length === 0) return "unavailable";
  if (references.every((reference) => reference.availability === "available")) return "available";
  if (references.every((reference) => reference.availability === "unavailable")) {
    return "unavailable";
  }
  return "incomplete";
}

export function buildPublicProvenance(
  revision: FindingRevision,
  reviews: readonly FindingReview[],
  resolutions: readonly FindingReviewResolution[],
  conclusionId: string,
): PublicProvenanceSummary {
  const exactReviews = reviews.filter(
    (review) =>
      review.findingId === revision.findingId &&
      review.findingRevision === revision.revision,
  );
  const observationReferences = revision.evidenceReferences.filter(
    (reference) => reference.publicSafe && reference.sourceType === "observation",
  );
  const safeAnalysisReferences = revision.analysisArtifactReferences.filter(
    (reference) => reference.publicSafe,
  );
  const jobs = safeAnalysisReferences
    .map((reference) => reference.analysisJobId)
    .filter((value): value is string => value !== null);
  const artifacts = safeAnalysisReferences.map(
    (reference) => reference.analysisArtifactId,
  );
  const resolvedBlockers = exactReviews.filter(
    (review) =>
      review.disposition !== "endorse" &&
      isReviewBlockerResolved(review, resolutions),
  ).length;
  const stages: PublicProvenanceStage[] = [
    {
      stage: "observation",
      availability: stageAvailability(observationReferences),
      references: observationReferences.map((reference) => reference.referenceId),
    },
    {
      stage: "analysis_job",
      availability:
        jobs.length === 0
          ? "unavailable"
          : jobs.length === safeAnalysisReferences.length
            ? "available"
            : "incomplete",
      references: jobs,
    },
    {
      stage: "analysis_artifact",
      availability: stageAvailability(safeAnalysisReferences),
      references: artifacts,
    },
    {
      stage: "finding_revision",
      availability: "available",
      references: [`${revision.findingId}:revision:${revision.revision}`],
    },
    {
      stage: "peer_review",
      availability: exactReviews.length > 0 ? "available" : "unavailable",
      references: exactReviews.map((review) => review.reviewId),
    },
    {
      stage: "promoted_conclusion",
      availability: "available",
      references: [conclusionId],
    },
  ];
  return {
    stages,
    missingLinks: stages
      .filter((stage) => stage.availability !== "available")
      .map((stage) => stage.stage),
    reviewSummary: {
      total: exactReviews.length,
      endorsements: exactReviews.filter((review) => review.disposition === "endorse").length,
      challenges: exactReviews.filter((review) => review.disposition === "challenge").length,
      revisionRequests: exactReviews.filter(
        (review) => review.disposition === "request_revision",
      ).length,
      resolvedBlockers,
    },
  };
}

export function createPublicConclusion(input: {
  conclusionId: string;
  revision: FindingRevision;
  reviews: readonly FindingReview[];
  resolutions: readonly FindingReviewResolution[];
  artifactId: string;
  visualizationId: string;
  publishedAt: string;
  supersedesConclusionIds: readonly string[];
  privateValues?: readonly string[];
}): PublicConclusion {
  const conclusion: PublicConclusion = {
    conclusionId: input.conclusionId,
    sourceFindingId: input.revision.findingId,
    sourceRevision: input.revision.revision,
    statement: input.revision.statement,
    interpretation: input.revision.interpretation,
    limitations: [...input.revision.limitations],
    evidenceReferences: publicEvidenceReferences(input.revision.evidenceReferences),
    analysisArtifactReferences: publicAnalysisReferences(
      input.revision.analysisArtifactReferences,
    ),
    institutionContext: "Missing Interior collaborative research",
    investigationContext: {
      artifactId: input.artifactId,
      visualizationId: input.visualizationId,
    },
    publishedAt: input.publishedAt,
    lifecycleStatus: "promoted",
    provenance: buildPublicProvenance(
      input.revision,
      input.reviews,
      input.resolutions,
      input.conclusionId,
    ),
    supersession: {
      supersedesConclusionIds: [...input.supersedesConclusionIds],
      supersededByConclusionId: null,
    },
  };
  assertPublicSanitized(conclusion, input.privateValues);
  return conclusion;
}
