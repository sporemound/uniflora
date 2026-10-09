import { createHash } from "node:crypto";

export const REVIEW_DISPOSITIONS = Object.freeze([
  "endorse",
  "challenge",
  "request_revision",
]);

export const RELATIONSHIP_TYPES = Object.freeze([
  "supports",
  "related_to",
  "conflicts_with",
  "supersedes",
]);

export const LIFECYCLE_STATES = Object.freeze([
  "draft",
  "under_review",
  "revision_requested",
  "challenged",
  "reviewed",
  "promoted",
  "superseded",
  "withdrawn",
]);

export const FORBIDDEN_PUBLIC_KEYS = Object.freeze([
  "discorduserid",
  "privateparticipantid",
  "participantid",
  "revieweridentity",
  "reviewerparticipantid",
  "authorparticipantid",
  "creatorparticipantid",
  "requestedbyplayerid",
  "sessiontoken",
  "roomticket",
  "roomticketsecret",
  "hmac",
  "hmackey",
  "hmacmaterial",
  "clientoperationid",
  "operationid",
  "clientinstanceid",
  "websocketattachment",
  "durableobjectmetadata",
  "storagemetadata",
  "privatenotes",
  "unredactedroomlogs",
  "roomlogs",
  "environmentsecrets",
  "devvars",
  "leasetoken",
  "secret",
]);

const HASH_PATTERN = /^[0-9a-f]{64}$/;
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/;
const BASE_TIME_MS = Date.parse("2026-07-25T00:00:00.000Z");

const hasOwn = (record, key) => Object.prototype.hasOwnProperty.call(record, key);
const clone = (value) => structuredClone(value);

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalize(value[key])]),
  );
}

function stableStringify(value) {
  return JSON.stringify(canonicalize(value));
}

function operationFingerprint(participant, operation) {
  return createHash("sha256")
    .update(
      stableStringify({
        participant: {
          id: participant.id,
          canEdit: participant.canEdit === true,
          canResolve: participant.canResolve === true,
        },
        operation,
      }),
    )
    .digest("hex");
}

function timestampForRevision(roomRevision) {
  return new Date(BASE_TIME_MS + roomRevision * 1_000).toISOString();
}

function entityId(kind, roomRevision, suffix = "") {
  const revision = String(roomRevision).padStart(4, "0");
  return `${kind}_${revision}${suffix}`;
}

function normalizedKey(key) {
  return key.toLowerCase().replace(/[^a-z0-9]/g, "");
}

export class Phase4CModelError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.name = "Phase4CModelError";
    this.code = code;
    this.details = details;
  }
}

function malformed(message, details = undefined) {
  throw new Phase4CModelError("malformed_request", message, details);
}

function requireText(value, label, { optional = false, maximum = 4_000 } = {}) {
  if (value === undefined || value === null) {
    if (optional) return null;
    malformed(`${label} must be a string.`);
  }
  if (typeof value !== "string") malformed(`${label} must be a string.`);
  const normalized = value.trim();
  if (!normalized && !optional) malformed(`${label} must not be blank.`);
  if (normalized.length > maximum) malformed(`${label} exceeds ${maximum} characters.`);
  return normalized || null;
}

function requireId(value, label) {
  const normalized = requireText(value, label, { maximum: 96 });
  if (
    !ID_PATTERN.test(normalized) ||
    ["__proto__", "constructor", "prototype"].includes(normalized)
  ) {
    malformed(`${label} has an invalid format.`);
  }
  return normalized;
}

function requireRevision(value, label = "finding revision") {
  if (!Number.isSafeInteger(value) || value < 1) {
    malformed(`${label} must be a positive integer.`);
  }
  return value;
}

function requireStringArray(value, label, { maximumItems = 32, optional = true } = {}) {
  if (value === undefined && optional) return [];
  if (!Array.isArray(value)) malformed(`${label} must be an array.`);
  if (value.length > maximumItems) malformed(`${label} exceeds ${maximumItems} entries.`);
  const normalized = value.map((item, index) =>
    requireText(item, `${label}[${index}]`, { maximum: 2_000 }),
  );
  if (new Set(normalized).size !== normalized.length) {
    malformed(`${label} must not contain duplicates.`);
  }
  return normalized;
}

function parseEvidenceReferences(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) malformed("evidenceReferences must be an array.");
  if (value.length > 32) malformed("evidenceReferences exceeds 32 entries.");
  const references = value.map((item, index) => {
    if (!isRecord(item)) malformed(`evidenceReferences[${index}] must be an object.`);
    const availability = item.availability ?? "available";
    if (!["available", "unavailable"].includes(availability)) {
      malformed(`evidenceReferences[${index}].availability is invalid.`);
    }
    return {
      evidenceId: requireId(item.evidenceId, `evidenceReferences[${index}].evidenceId`),
      label: requireText(item.label, `evidenceReferences[${index}].label`, {
        optional: true,
        maximum: 240,
      }),
      availability,
      publicSafe: item.publicSafe !== false,
    };
  });
  if (new Set(references.map((item) => item.evidenceId)).size !== references.length) {
    malformed("evidenceReferences must not contain duplicate evidence IDs.");
  }
  return references;
}

function optionalHash(value, label) {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || !HASH_PATTERN.test(value)) {
    malformed(`${label} must be a lowercase SHA-256 digest.`);
  }
  return value;
}

function parseAnalysisReferences(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) malformed("analysisArtifactReferences must be an array.");
  if (value.length > 32) malformed("analysisArtifactReferences exceeds 32 entries.");
  return value.map((item, index) => {
    if (!isRecord(item)) {
      malformed(`analysisArtifactReferences[${index}] must be an object.`);
    }
    const availability = item.availability ?? "available";
    if (!["available", "unavailable", "incomplete"].includes(availability)) {
      malformed(`analysisArtifactReferences[${index}].availability is invalid.`);
    }
    const analysisJobId =
      item.analysisJobId === undefined || item.analysisJobId === null
        ? null
        : requireId(item.analysisJobId, `analysisArtifactReferences[${index}].analysisJobId`);
    const analysisArtifactId =
      item.analysisArtifactId === undefined || item.analysisArtifactId === null
        ? null
        : requireId(
            item.analysisArtifactId,
            `analysisArtifactReferences[${index}].analysisArtifactId`,
          );
    if (availability === "available" && (!analysisJobId || !analysisArtifactId)) {
      malformed(
        `analysisArtifactReferences[${index}] marked available requires job and artifact IDs.`,
      );
    }
    return {
      analysisJobId,
      analysisArtifactId,
      artifactHash: optionalHash(
        item.artifactHash,
        `analysisArtifactReferences[${index}].artifactHash`,
      ),
      inputManifestHash: optionalHash(
        item.inputManifestHash,
        `analysisArtifactReferences[${index}].inputManifestHash`,
      ),
      availability,
      sourceEvidenceIds: requireStringArray(
        item.sourceEvidenceIds,
        `analysisArtifactReferences[${index}].sourceEvidenceIds`,
      ).map((sourceEvidenceId) =>
        requireId(
          sourceEvidenceId,
          `analysisArtifactReferences[${index}].sourceEvidenceIds entry`,
        ),
      ),
      publicSafe: item.publicSafe !== false,
    };
  });
}

function parseRevisionContent(operation, context) {
  return {
    findingId: context.findingId,
    revision: context.revision,
    previousRevision: context.previousRevision,
    statement: requireText(operation.statement, "statement", { maximum: 2_000 }),
    interpretation: requireText(operation.interpretation, "interpretation", {
      optional: true,
      maximum: 4_000,
    }),
    limitations: requireStringArray(operation.limitations, "limitations"),
    evidenceReferences: parseEvidenceReferences(operation.evidenceReferences),
    analysisArtifactReferences: parseAnalysisReferences(
      operation.analysisArtifactReferences,
    ),
    authorParticipantId: context.authorParticipantId,
    createdAt: context.createdAt,
    revisionReason: requireText(operation.revisionReason, "revisionReason", {
      maximum: 1_000,
    }),
    lifecycleState: "draft",
  };
}

function exactFinding(state, findingId) {
  const normalized = requireId(findingId, "findingId");
  if (!hasOwn(state.findings, normalized)) {
    throw new Phase4CModelError(
      "finding_not_found",
      `Finding ${normalized} does not exist.`,
    );
  }
  return state.findings[normalized];
}

function exactRevision(state, findingId, revision) {
  const finding = exactFinding(state, findingId);
  const normalizedRevision = requireRevision(revision);
  if (!hasOwn(finding.revisions, String(normalizedRevision))) {
    throw new Phase4CModelError(
      "revision_not_found",
      `Finding ${finding.findingId} has no revision ${normalizedRevision}.`,
    );
  }
  return {
    finding,
    revision: finding.revisions[String(normalizedRevision)],
  };
}

function exactCurrentRevision(state, findingId, revision) {
  const result = exactRevision(state, findingId, revision);
  if (result.finding.currentRevision !== result.revision.revision) {
    throw new Phase4CModelError(
      "stale_finding_revision",
      `Finding ${result.finding.findingId} revision ${result.revision.revision} is obsolete; current revision is ${result.finding.currentRevision}.`,
      {
        suppliedRevision: result.revision.revision,
        currentRevision: result.finding.currentRevision,
      },
    );
  }
  return result;
}

function reviewResolution(state, reviewId) {
  return Object.values(state.reviewResolutions).find(
    (resolution) => resolution.blockingReviewId === reviewId,
  );
}

function exactReviews(state, findingId, findingRevision) {
  return Object.values(state.reviews)
    .filter(
      (review) =>
        review.findingId === findingId && review.findingRevision === findingRevision,
    )
    .sort((left, right) => left.reviewId.localeCompare(right.reviewId));
}

function unresolvedBlockingReviews(state, findingId, findingRevision) {
  return Object.values(state.reviews)
    .filter(
      (review) =>
        review.findingId === findingId &&
        ["challenge", "request_revision"].includes(review.disposition) &&
        (review.findingRevision === findingRevision ||
          (review.disposition === "request_revision" &&
            review.findingRevision < findingRevision)) &&
        !reviewResolution(state, review.reviewId),
    )
    .sort((left, right) => left.reviewId.localeCompare(right.reviewId));
}

function hasIndependentEndorsement(state, revision) {
  return exactReviews(state, revision.findingId, revision.revision).some(
    (review) =>
      review.disposition === "endorse" &&
      review.reviewerParticipantId !== revision.authorParticipantId,
  );
}

function replaceRevision(finding, revision) {
  finding.revisions[String(revision.revision)] = revision;
}

function recalculateCurrentLifecycle(state, finding) {
  const revision = finding.revisions[String(finding.currentRevision)];
  if (["promoted", "superseded", "withdrawn"].includes(revision.lifecycleState)) return;
  const blockers = unresolvedBlockingReviews(
    state,
    finding.findingId,
    revision.revision,
  );
  let lifecycleState = "under_review";
  if (blockers.some((review) => review.disposition === "request_revision")) {
    lifecycleState = "revision_requested";
  } else if (blockers.some((review) => review.disposition === "challenge")) {
    lifecycleState = "challenged";
  } else if (hasIndependentEndorsement(state, revision)) {
    lifecycleState = "reviewed";
  }
  replaceRevision(finding, { ...revision, lifecycleState });
}

function structurallyValidReferences(revision) {
  try {
    parseEvidenceReferences(revision.evidenceReferences);
    parseAnalysisReferences(revision.analysisArtifactReferences);
    return true;
  } catch (error) {
    if (error instanceof Phase4CModelError) return false;
    throw error;
  }
}

function assessPromotion(state, finding, revision) {
  const blockers = [];
  if (!["under_review", "reviewed"].includes(revision.lifecycleState)) {
    blockers.push({
      code: "lifecycle_not_reviewable",
      message: `Lifecycle ${revision.lifecycleState} cannot be promoted.`,
    });
  }
  if (!hasIndependentEndorsement(state, revision)) {
    blockers.push({
      code: "independent_endorsement_required",
      message: "At least one endorsement from someone other than the revision author is required.",
    });
  }
  for (const review of unresolvedBlockingReviews(
    state,
    finding.findingId,
    revision.revision,
  )) {
    blockers.push({
      code:
        review.disposition === "challenge"
          ? "unresolved_challenge"
          : "unresolved_revision_request",
      reviewId: review.reviewId,
      message: `Review ${review.reviewId} remains unresolved.`,
    });
  }
  if (!structurallyValidReferences(revision)) {
    blockers.push({
      code: "invalid_provenance_reference",
      message: "Evidence or analysis references are structurally invalid.",
    });
  }
  return {
    eligible: blockers.length === 0,
    findingId: finding.findingId,
    findingRevision: revision.revision,
    blockers,
  };
}

function publicEvidenceReferences(revision) {
  return revision.evidenceReferences
    .filter((reference) => reference.publicSafe)
    .map((reference) => ({
      evidenceId: reference.evidenceId,
      label: reference.label,
      availability: reference.availability,
    }));
}

function publicAnalysisReferences(revision) {
  return revision.analysisArtifactReferences
    .filter((reference) => reference.publicSafe)
    .map((reference) => ({
      analysisJobId: reference.analysisJobId,
      analysisArtifactId: reference.analysisArtifactId,
      artifactHash: reference.artifactHash,
      inputManifestHash: reference.inputManifestHash,
      availability: reference.availability,
      sourceEvidenceIds: [...reference.sourceEvidenceIds],
    }));
}

function provenanceSummary(state, revision, conclusionId) {
  const evidence = publicEvidenceReferences(revision);
  const analyses = publicAnalysisReferences(revision);
  const reviews = exactReviews(state, revision.findingId, revision.revision);
  const observationReferences = [
    ...new Set([
      ...evidence.map((reference) => reference.evidenceId),
      ...analyses.flatMap((reference) => reference.sourceEvidenceIds),
    ]),
  ].sort();
  const analysisJobReferences = [
    ...new Set(
      analyses
        .map((reference) => reference.analysisJobId)
        .filter((value) => value !== null),
    ),
  ].sort();
  const analysisArtifactReferences = [
    ...new Set(
      analyses
        .map((reference) => reference.analysisArtifactId)
        .filter((value) => value !== null),
    ),
  ].sort();
  const missingLinks = [];
  if (observationReferences.length === 0) missingLinks.push("observation");
  if (analysisJobReferences.length === 0) missingLinks.push("analysis_job");
  if (analysisArtifactReferences.length === 0) missingLinks.push("analysis_artifact");
  if (reviews.length === 0) missingLinks.push("peer_review");
  return {
    status: missingLinks.length === 0 ? "complete" : "incomplete",
    observationReferences,
    analysisJobReferences,
    analysisArtifactReferences,
    findingRevisionReference: {
      findingId: revision.findingId,
      findingRevision: revision.revision,
    },
    reviewReferences: reviews.map((review) => ({
      reviewId: review.reviewId,
      findingRevision: review.findingRevision,
      disposition: review.disposition,
      resolutionStatus:
        review.disposition === "endorse"
          ? "not_applicable"
          : reviewResolution(state, review.reviewId)?.resolutionStatus ??
            "unresolved",
    })),
    promotedConclusionReference: conclusionId,
    missingLinks,
  };
}

function supersessionSummary(state, revision) {
  const supersedes = Object.values(state.relationships)
    .filter(
      (relationship) =>
        relationship.relationshipType === "supersedes" &&
        relationship.sourceFindingId === revision.findingId &&
        relationship.sourceRevision === revision.revision,
    )
    .map((relationship) => ({
      findingId: relationship.targetFindingId,
      findingRevision: relationship.targetRevision,
    }));
  const supersededBy = Object.values(state.relationships)
    .filter(
      (relationship) =>
        relationship.relationshipType === "supersedes" &&
        relationship.targetFindingId === revision.findingId &&
        relationship.targetRevision === revision.revision,
    )
    .map((relationship) => ({
      findingId: relationship.sourceFindingId,
      findingRevision: relationship.sourceRevision,
    }));
  return { supersedes, supersededBy };
}

export function assertPublicConclusionSafe(value, { forbiddenValues = [] } = {}) {
  const secrets = forbiddenValues
    .filter((item) => typeof item === "string" && item.length >= 6)
    .sort((left, right) => right.length - left.length);

  function visit(item, path) {
    if (Array.isArray(item)) {
      item.forEach((entry, index) => visit(entry, `${path}[${index}]`));
      return;
    }
    if (isRecord(item)) {
      for (const [key, entry] of Object.entries(item)) {
        const normalized = normalizedKey(key);
        if (
          FORBIDDEN_PUBLIC_KEYS.some((fragment) => normalized.includes(fragment))
        ) {
          throw new Phase4CModelError(
            "public_sanitation_failed",
            `Forbidden public field ${path}.${key}.`,
          );
        }
        visit(entry, `${path}.${key}`);
      }
      return;
    }
    if (typeof item === "string") {
      if (
        /\.dev\.vars/iu.test(item) ||
        /\b\d{17,20}\b/u.test(item) ||
        /(?:bearer\s+[a-f0-9]{32,}|(?:session|room[\s_-]*ticket|hmac|secret|client[\s_-]*operation)[\s_-]*(?:token|id|material)?\s*[:=])/iu.test(
          item,
        )
      ) {
        throw new Phase4CModelError(
          "public_sanitation_failed",
          `Credential-like value leaked at ${path}.`,
        );
      }
      const leaked = secrets.find((secret) => item.includes(secret));
      if (leaked) {
        throw new Phase4CModelError(
          "public_sanitation_failed",
          `Private value leaked at ${path}.`,
        );
      }
    }
  }

  visit(value, "$");
  return true;
}

function buildConclusion(state, revision, conclusionId, publishedAt) {
  const conclusion = {
    publicConclusionId: conclusionId,
    sourceFindingId: revision.findingId,
    sourceRevision: revision.revision,
    statement: revision.statement,
    interpretation: revision.interpretation,
    limitations: [...revision.limitations],
    evidenceReferences: publicEvidenceReferences(revision),
    analysisArtifactReferences: publicAnalysisReferences(revision),
    institutionContext: state.institutionContext,
    publicationTimestamp: publishedAt,
    lifecycleStatus: "promoted",
    provenanceSummary: provenanceSummary(state, revision, conclusionId),
    supersession: supersessionSummary(state, revision),
  };
  const forbiddenValues = [
    revision.authorParticipantId,
    ...Object.values(state.reviews).map((review) => review.reviewerParticipantId),
    ...Object.keys(state.processedOperations),
  ];
  assertPublicConclusionSafe(conclusion, { forbiddenValues });
  return conclusion;
}

function initialState({ roomId, institutionContext }) {
  return {
    schemaVersion: 1,
    roomId: requireId(roomId, "roomId"),
    institutionContext: requireText(institutionContext, "institutionContext", {
      maximum: 240,
    }),
    roomRevision: 0,
    findings: {},
    reviews: {},
    reviewResolutions: {},
    relationships: {},
    publicConclusions: {},
    processedOperations: {},
    operationOrder: [],
  };
}

export class Phase4CReferenceModel {
  constructor({
    roomId = "phase4c-reference-room",
    institutionContext = "Missing Interior collaborative investigation",
    persistedState = null,
  } = {}) {
    if (persistedState === null) {
      this._state = initialState({ roomId, institutionContext });
      return;
    }
    if (!isRecord(persistedState) || persistedState.schemaVersion !== 1) {
      throw new Phase4CModelError(
        "invalid_persisted_state",
        "Persisted Phase 4C reference state is invalid.",
      );
    }
    this._state = clone(persistedState);
  }

  static fromPersistedState(persistedState) {
    return new Phase4CReferenceModel({ persistedState });
  }

  get roomRevision() {
    return this._state.roomRevision;
  }

  exportState() {
    return canonicalize(clone(this._state));
  }

  snapshot() {
    const state = this._state;
    return canonicalize({
      schemaVersion: state.schemaVersion,
      roomId: state.roomId,
      institutionContext: state.institutionContext,
      roomRevision: state.roomRevision,
      findings: Object.values(state.findings)
        .sort((left, right) => left.findingId.localeCompare(right.findingId))
        .map((finding) => ({
          findingId: finding.findingId,
          currentRevision: finding.currentRevision,
          revisions: Object.values(finding.revisions).sort(
            (left, right) => left.revision - right.revision,
          ),
        })),
      reviews: Object.values(state.reviews).sort((left, right) =>
        left.reviewId.localeCompare(right.reviewId),
      ),
      reviewResolutions: Object.values(state.reviewResolutions).sort((left, right) =>
        left.resolutionId.localeCompare(right.resolutionId),
      ),
      relationships: Object.values(state.relationships).sort((left, right) =>
        left.relationshipId.localeCompare(right.relationshipId),
      ),
      publicConclusions: Object.values(state.publicConclusions).sort((left, right) =>
        left.publicConclusionId.localeCompare(right.publicConclusionId),
      ),
    });
  }

  getFindingRevision(findingId, findingRevision) {
    try {
      return clone(exactRevision(this._state, findingId, findingRevision).revision);
    } catch (error) {
      if (
        error instanceof Phase4CModelError &&
        ["finding_not_found", "revision_not_found"].includes(error.code)
      ) {
        return null;
      }
      throw error;
    }
  }

  reviewsFor(findingId, findingRevision) {
    return clone(exactReviews(this._state, findingId, findingRevision));
  }

  promotionEligibility(findingId, findingRevision) {
    try {
      const { finding, revision } = exactCurrentRevision(
        this._state,
        findingId,
        findingRevision,
      );
      return clone(assessPromotion(this._state, finding, revision));
    } catch (error) {
      if (error instanceof Phase4CModelError) {
        return {
          eligible: false,
          findingId,
          findingRevision,
          blockers: [{ code: error.code, message: error.message }],
        };
      }
      throw error;
    }
  }

  mutate(participantValue, operationValue) {
    if (!isRecord(participantValue)) {
      return this._uncachedError(null, "malformed_request", "participant must be an object.");
    }
    let participant;
    try {
      participant = {
        id: requireId(participantValue.id, "participant.id"),
        canEdit: participantValue.canEdit === true,
        canResolve: participantValue.canResolve === true,
      };
    } catch (error) {
      if (error instanceof Phase4CModelError) {
        return this._uncachedError(null, error.code, error.message, error.details);
      }
      throw error;
    }
    if (!isRecord(operationValue)) {
      return this._uncachedError(
        null,
        "malformed_request",
        "operation must be an object.",
      );
    }

    let operationId;
    try {
      operationId = requireId(operationValue.operationId, "operationId");
    } catch (error) {
      if (error instanceof Phase4CModelError) {
        return this._uncachedError(null, error.code, error.message, error.details);
      }
      throw error;
    }

    const operation = clone(operationValue);
    const fingerprint = operationFingerprint(participant, operation);
    const existing = this._state.processedOperations[operationId];
    if (existing) {
      if (existing.fingerprint !== fingerprint) {
        return this._uncachedError(
          operationId,
          "operation_id_conflict",
          "operationId was already used for a different actor or payload.",
        );
      }
      return {
        status: "duplicate",
        code: "duplicate_operation",
        operationId,
        roomRevision: existing.response.roomRevision,
        currentRoomRevision: this._state.roomRevision,
        originalStatus: existing.response.status,
        originalCode: existing.response.code,
        data: clone(existing.response.data ?? null),
      };
    }

    try {
      if (!Number.isSafeInteger(operation.expectedRevision) || operation.expectedRevision < 0) {
        malformed("expectedRevision must be a non-negative integer.");
      }
      if (operation.expectedRevision !== this._state.roomRevision) {
        throw new Phase4CModelError(
          "stale_room_revision",
          `Expected room revision ${operation.expectedRevision}; current revision is ${this._state.roomRevision}.`,
          {
            suppliedRevision: operation.expectedRevision,
            currentRevision: this._state.roomRevision,
          },
        );
      }

      const working = clone(this._state);
      const nextRoomRevision = working.roomRevision + 1;
      const result = this._apply(working, participant, operation, nextRoomRevision);
      working.roomRevision = nextRoomRevision;
      const response = {
        status: "accepted",
        code: result.code,
        operationId,
        roomRevision: nextRoomRevision,
        data: result.data ?? null,
      };
      this._remember(working, operationId, fingerprint, response);
      this._state = working;
      return clone(response);
    } catch (error) {
      if (!(error instanceof Phase4CModelError)) throw error;
      const response = {
        status: "rejected",
        code: error.code,
        operationId,
        roomRevision: this._state.roomRevision,
        message: error.message,
        data: error.details ?? null,
      };
      const working = clone(this._state);
      this._remember(working, operationId, fingerprint, response);
      this._state = working;
      return clone(response);
    }
  }

  _uncachedError(operationId, code, message, data = null) {
    return {
      status: "rejected",
      code,
      operationId,
      roomRevision: this._state.roomRevision,
      message,
      data,
    };
  }

  _remember(state, operationId, fingerprint, response) {
    state.processedOperations[operationId] = {
      fingerprint,
      response: clone(response),
    };
    state.operationOrder.push(operationId);
  }

  _apply(state, participant, operation, nextRoomRevision) {
    switch (operation.type) {
      case "finding:create":
        return this._createFinding(state, participant, operation, nextRoomRevision);
      case "finding:begin_review":
        return this._beginReview(state, operation);
      case "finding:revise":
        return this._reviseFinding(state, participant, operation, nextRoomRevision);
      case "finding:withdraw":
        return this._withdrawFinding(state, participant, operation);
      case "review:submit":
        return this._submitReview(state, participant, operation, nextRoomRevision);
      case "review:resolve":
        return this._resolveReview(
          state,
          participant,
          operation,
          nextRoomRevision,
          "resolved",
        );
      case "review:withdraw":
        return this._resolveReview(
          state,
          participant,
          operation,
          nextRoomRevision,
          "withdrawn",
        );
      case "relationship:create":
        return this._createRelationship(state, participant, operation, nextRoomRevision);
      case "finding:promote":
        return this._promoteFinding(state, operation, nextRoomRevision);
      default:
        malformed(`Unsupported operation type ${String(operation.type)}.`);
    }
  }

  _createFinding(state, participant, operation, nextRoomRevision) {
    const findingId = entityId("finding", nextRoomRevision);
    const revision = parseRevisionContent(operation, {
      findingId,
      revision: 1,
      previousRevision: null,
      authorParticipantId: participant.id,
      createdAt: timestampForRevision(nextRoomRevision),
    });
    state.findings[findingId] = {
      findingId,
      currentRevision: 1,
      revisions: { "1": revision },
    };
    return {
      code: "finding_created",
      data: { findingId, findingRevision: 1 },
    };
  }

  _beginReview(state, operation) {
    const { finding, revision } = exactCurrentRevision(
      state,
      operation.findingId,
      operation.findingRevision,
    );
    if (revision.lifecycleState !== "draft") {
      throw new Phase4CModelError(
        "invalid_transition",
        `Cannot begin review from lifecycle ${revision.lifecycleState}.`,
        { from: revision.lifecycleState, to: "under_review" },
      );
    }
    replaceRevision(finding, { ...revision, lifecycleState: "under_review" });
    return {
      code: "finding_review_started",
      data: {
        findingId: finding.findingId,
        findingRevision: revision.revision,
        lifecycleState: "under_review",
      },
    };
  }

  _reviseFinding(state, participant, operation, nextRoomRevision) {
    const { finding, revision: previous } = exactCurrentRevision(
      state,
      operation.findingId,
      operation.findingRevision,
    );
    if (["withdrawn", "superseded"].includes(previous.lifecycleState)) {
      throw new Phase4CModelError(
        "invalid_transition",
        `Cannot revise lifecycle ${previous.lifecycleState}.`,
      );
    }
    if (
      previous.authorParticipantId !== participant.id &&
      participant.canEdit !== true
    ) {
      throw new Phase4CModelError(
        "permission_denied",
        "Only the revision author or an eligible editor may create a revision.",
      );
    }
    const addressesReviewIds = requireStringArray(
      operation.addressesReviewIds,
      "addressesReviewIds",
    ).map((reviewId) => requireId(reviewId, "addressesReviewIds entry"));
    const addressedReviews = addressesReviewIds.map((reviewId) => {
      const review = state.reviews[reviewId];
      if (!review) {
        throw new Phase4CModelError(
          "review_not_found",
          `Review ${reviewId} does not exist.`,
        );
      }
      if (
        review.findingId !== finding.findingId ||
        review.findingRevision !== previous.revision ||
        review.disposition !== "request_revision"
      ) {
        throw new Phase4CModelError(
          "review_target_conflict",
          `Review ${reviewId} is not a revision request for the revised revision.`,
        );
      }
      if (reviewResolution(state, reviewId)) {
        throw new Phase4CModelError(
          "invalid_transition",
          `Review ${reviewId} is already resolved.`,
        );
      }
      return review;
    });

    const nextRevision = previous.revision + 1;
    const createdAt = timestampForRevision(nextRoomRevision);
    const revision = parseRevisionContent(operation, {
      findingId: finding.findingId,
      revision: nextRevision,
      previousRevision: previous.revision,
      authorParticipantId: participant.id,
      createdAt,
    });
    finding.revisions[String(nextRevision)] = revision;
    finding.currentRevision = nextRevision;
    addressedReviews.forEach((review, index) => {
      const resolutionId = entityId("resolution", nextRoomRevision, `_${index + 1}`);
      state.reviewResolutions[resolutionId] = {
        resolutionId,
        blockingReviewId: review.reviewId,
        resolutionStatus: "addressed_by_revision",
        resolverParticipantId: participant.id,
        rationale: requireText(operation.revisionReason, "revisionReason", {
          maximum: 1_000,
        }),
        createdAt,
        clientOperationId: operation.operationId,
        findingId: finding.findingId,
        findingRevision: previous.revision,
        addressedByRevision: nextRevision,
      };
    });
    return {
      code: "finding_revision_created",
      data: {
        findingId: finding.findingId,
        findingRevision: nextRevision,
        previousRevision: previous.revision,
        addressedReviewIds: addressedReviews.map((review) => review.reviewId),
      },
    };
  }

  _withdrawFinding(state, participant, operation) {
    const { finding, revision } = exactCurrentRevision(
      state,
      operation.findingId,
      operation.findingRevision,
    );
    if (
      revision.authorParticipantId !== participant.id &&
      participant.canEdit !== true
    ) {
      throw new Phase4CModelError(
        "permission_denied",
        "Only the revision author or an eligible editor may withdraw a finding.",
      );
    }
    if (["withdrawn", "superseded"].includes(revision.lifecycleState)) {
      throw new Phase4CModelError(
        "invalid_transition",
        `Cannot withdraw lifecycle ${revision.lifecycleState}.`,
      );
    }
    replaceRevision(finding, { ...revision, lifecycleState: "withdrawn" });
    return {
      code: "finding_withdrawn",
      data: {
        findingId: finding.findingId,
        findingRevision: revision.revision,
        lifecycleState: "withdrawn",
      },
    };
  }

  _submitReview(state, participant, operation, nextRoomRevision) {
    const { finding, revision } = exactCurrentRevision(
      state,
      operation.findingId,
      operation.findingRevision,
    );
    if (!["under_review", "reviewed", "challenged", "revision_requested"].includes(
      revision.lifecycleState,
    )) {
      throw new Phase4CModelError(
        "invalid_transition",
        `Lifecycle ${revision.lifecycleState} does not accept reviews.`,
      );
    }
    if (!REVIEW_DISPOSITIONS.includes(operation.disposition)) {
      malformed(`Review disposition ${String(operation.disposition)} is invalid.`);
    }
    const reviewId = entityId("review", nextRoomRevision);
    const review = {
      reviewId,
      findingId: finding.findingId,
      findingRevision: revision.revision,
      reviewerParticipantId: participant.id,
      disposition: operation.disposition,
      rationale: requireText(operation.rationale, "rationale", {
        optional: true,
        maximum: 2_000,
      }),
      createdAt: timestampForRevision(nextRoomRevision),
      clientOperationId: operation.operationId,
      roomId: state.roomId,
    };
    state.reviews[reviewId] = review;
    recalculateCurrentLifecycle(state, finding);
    return {
      code: "review_submitted",
      data: {
        reviewId,
        findingId: finding.findingId,
        findingRevision: revision.revision,
        disposition: review.disposition,
      },
    };
  }

  _resolveReview(
    state,
    participant,
    operation,
    nextRoomRevision,
    resolutionStatus,
  ) {
    const reviewId = requireId(operation.reviewId, "reviewId");
    const review = state.reviews[reviewId];
    if (!review) {
      throw new Phase4CModelError(
        "review_not_found",
        `Review ${reviewId} does not exist.`,
      );
    }
    const { finding, revision } = exactRevision(
      state,
      operation.findingId,
      operation.findingRevision,
    );
    if (
      review.findingId !== finding.findingId ||
      review.findingRevision !== revision.revision
    ) {
      throw new Phase4CModelError(
        "review_target_conflict",
        `Review ${reviewId} does not target the supplied revision.`,
      );
    }
    if (!["challenge", "request_revision"].includes(review.disposition)) {
      throw new Phase4CModelError(
        "invalid_transition",
        `Review ${reviewId} is not a blocking review.`,
      );
    }
    if (reviewResolution(state, reviewId)) {
      throw new Phase4CModelError(
        "invalid_transition",
        `Review ${reviewId} is already resolved.`,
      );
    }
    const isReviewer = participant.id === review.reviewerParticipantId;
    if (resolutionStatus === "withdrawn" && !isReviewer) {
      throw new Phase4CModelError(
        "permission_denied",
        "Only the blocking reviewer may withdraw their review.",
      );
    }
    if (
      resolutionStatus === "resolved" &&
      !isReviewer &&
      !(participant.canResolve && participant.id !== revision.authorParticipantId)
    ) {
      throw new Phase4CModelError(
        "permission_denied",
        "Only the reviewer or an independent eligible resolver may resolve this blocker.",
      );
    }
    const resolutionId = entityId("resolution", nextRoomRevision);
    state.reviewResolutions[resolutionId] = {
      resolutionId,
      blockingReviewId: reviewId,
      resolutionStatus,
      resolverParticipantId: participant.id,
      rationale: requireText(operation.rationale, "rationale", {
        maximum: 2_000,
      }),
      createdAt: timestampForRevision(nextRoomRevision),
      clientOperationId: operation.operationId,
      findingId: review.findingId,
      findingRevision: review.findingRevision,
      addressedByRevision: null,
    };
    const current = finding.revisions[String(finding.currentRevision)];
    if (
      current &&
      ["under_review", "reviewed", "challenged", "revision_requested"].includes(
        current.lifecycleState,
      )
    ) {
      recalculateCurrentLifecycle(state, finding);
    }
    return {
      code:
        resolutionStatus === "withdrawn"
          ? "review_blocker_withdrawn"
          : "review_blocker_resolved",
      data: {
        resolutionId,
        reviewId,
        resolutionStatus,
        findingId: review.findingId,
        findingRevision: review.findingRevision,
      },
    };
  }

  _createRelationship(state, participant, operation, nextRoomRevision) {
    const source = exactRevision(
      state,
      operation.sourceFindingId,
      operation.sourceRevision,
    );
    const target = exactRevision(
      state,
      operation.targetFindingId,
      operation.targetRevision,
    );
    if (source.finding.findingId === target.finding.findingId) {
      throw new Phase4CModelError(
        "self_link",
        "A finding cannot be related to itself.",
      );
    }
    if (!RELATIONSHIP_TYPES.includes(operation.relationshipType)) {
      malformed(`Relationship type ${String(operation.relationshipType)} is invalid.`);
    }
    if (operation.relationshipType === "supersedes") {
      if (
        source.finding.currentRevision !== source.revision.revision ||
        ["promoted", "superseded", "withdrawn"].includes(
          source.revision.lifecycleState,
        )
      ) {
        throw new Phase4CModelError(
          "invalid_transition",
          "A superseding link must originate from the current active successor before promotion.",
        );
      }
      if (
        source.revision.authorParticipantId !== participant.id &&
        participant.canEdit !== true
      ) {
        throw new Phase4CModelError(
          "permission_denied",
          "Only the successor author or an eligible editor may create a superseding link.",
        );
      }
    }
    const relationshipId = entityId("relationship", nextRoomRevision);
    const relationship = {
      relationshipId,
      sourceFindingId: source.finding.findingId,
      sourceRevision: source.revision.revision,
      targetFindingId: target.finding.findingId,
      targetRevision: target.revision.revision,
      relationshipType: operation.relationshipType,
      creatorParticipantId: participant.id,
      rationale: requireText(operation.rationale, "rationale", {
        optional: true,
        maximum: 2_000,
      }),
      createdAt: timestampForRevision(nextRoomRevision),
      clientOperationId: operation.operationId,
    };
    state.relationships[relationshipId] = relationship;
    if (
      relationship.relationshipType === "supersedes" &&
      target.finding.currentRevision === target.revision.revision
    ) {
      replaceRevision(target.finding, {
        ...target.revision,
        lifecycleState: "superseded",
      });
    }
    return {
      code: "relationship_created",
      data: {
        relationshipId,
        relationshipType: relationship.relationshipType,
        sourceFindingId: relationship.sourceFindingId,
        sourceRevision: relationship.sourceRevision,
        targetFindingId: relationship.targetFindingId,
        targetRevision: relationship.targetRevision,
      },
    };
  }

  _promoteFinding(state, operation, nextRoomRevision) {
    const { finding, revision } = exactCurrentRevision(
      state,
      operation.findingId,
      operation.findingRevision,
    );
    const eligibility = assessPromotion(state, finding, revision);
    if (!eligibility.eligible) {
      throw new Phase4CModelError(
        "promotion_blocked",
        "Finding revision is not eligible for promotion.",
        { blockers: eligibility.blockers },
      );
    }
    const publicConclusionId = entityId("conclusion", nextRoomRevision);
    const conclusion = buildConclusion(
      state,
      revision,
      publicConclusionId,
      timestampForRevision(nextRoomRevision),
    );
    state.publicConclusions[publicConclusionId] = conclusion;
    replaceRevision(finding, { ...revision, lifecycleState: "promoted" });
    return {
      code: "finding_promoted",
      data: {
        publicConclusionId,
        findingId: finding.findingId,
        findingRevision: revision.revision,
        conclusion: clone(conclusion),
      },
    };
  }
}
