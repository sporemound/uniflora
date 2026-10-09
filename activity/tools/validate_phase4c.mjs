import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  LIFECYCLE_STATES,
  Phase4CModelError,
  Phase4CReferenceModel,
  RELATIONSHIP_TYPES,
  REVIEW_DISPOSITIONS,
  assertPublicConclusionSafe,
} from "./phase4c_reference_model.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageJson = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
const phase4Source = await readFile(path.join(root, "tools/validate_phase4.mjs"), "utf8");
const phase4bSource = await readFile(path.join(root, "tools/validate_phase4b.mjs"), "utf8");
const referenceSource = await readFile(
  path.join(root, "tools/phase4c_reference_model.mjs"),
  "utf8",
);
const requiredSources = {
  "src/shared/finding-review.ts": [
    "FINDING_LIFECYCLE_STATES",
    "FINDING_REVIEW_DISPOSITIONS",
    "FINDING_RELATIONSHIP_TYPES",
    "assessPromotion",
    "assertPublicSanitized",
    "buildPublicProvenance",
    "createPublicConclusion",
  ],
  "src/shared/investigation-room.ts": [
    "finding:revise",
    "finding:review:start",
    "finding:review:submit",
    "finding:review:resolve",
    "finding:relationship:create",
    "finding:promote",
  ],
  "worker/lib/finding-review.ts": [
    "PersistedFindingReviewState",
    "applyFindingReviewPatch",
    "replayFindingReviewEvents",
    "isValidFindingReviewEventSequence",
    "findingReviewSnapshot",
  ],
  "worker/lib/investigation-room.ts": [
    "processedOperations",
    "stale_finding_revision",
    "promotion_blocked",
    "finding:review:submit",
    "finding:relationship:create",
    "finding:promote",
    "privatePublicationValues",
    "evidence_scope_mismatch",
    "serverBoundEvidenceReferences",
    "hasServerBoundEvidenceReference",
  ],
  "worker/index.ts": [
    "datasetFilename",
    "room_visualization_scope_mismatch",
    "scientificScope",
  ],
};
const sourceChecks = [];
const checkedSource = new Map();
for (const [relative, needles] of Object.entries(requiredSources)) {
  const source = await readFile(path.join(root, relative), "utf8");
  checkedSource.set(relative, source);
  for (const needle of needles) {
    assert.ok(source.includes(needle), `${relative} contains ${needle}`);
  }
  sourceChecks.push(relative);
}

assert.deepEqual(REVIEW_DISPOSITIONS, ["endorse", "challenge", "request_revision"]);
assert.deepEqual(RELATIONSHIP_TYPES, [
  "supports",
  "related_to",
  "conflicts_with",
  "supersedes",
]);
assert.deepEqual(LIFECYCLE_STATES, [
  "draft",
  "under_review",
  "revision_requested",
  "challenged",
  "reviewed",
  "promoted",
  "superseded",
  "withdrawn",
]);
assert.match(referenceSource, /public_sanitation_failed/);
assert.match(referenceSource, /addressed_by_revision/);
assert.doesNotMatch(referenceSource, /execute_clock_alignment_action/);

const cases = new Map();
const hasOwn = (record, key) => Object.prototype.hasOwnProperty.call(record, key);

function recordCase(number, name, assertion) {
  assert.equal(cases.has(number), false, `case ${number} recorded once`);
  assertion();
  cases.set(number, { number, name, ok: true });
}

function accepted(response, code) {
  assert.equal(response.status, "accepted", JSON.stringify(response));
  assert.equal(response.code, code);
  return response;
}

function rejected(response, code) {
  assert.equal(response.status, "rejected", JSON.stringify(response));
  assert.equal(response.code, code);
  return response;
}

function blockerCodes(responseOrEligibility) {
  const blockers =
    responseOrEligibility.blockers ??
    responseOrEligibility.data?.blockers ??
    responseOrEligibility.data?.conclusion?.blockers ??
    [];
  return blockers.map((blocker) => blocker.code);
}

function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

const alice = Object.freeze({ id: "participant_alice" });
const bob = Object.freeze({ id: "participant_bob" });
const charlie = Object.freeze({ id: "participant_charlie" });
const moderator = Object.freeze({
  id: "participant_moderator",
  canEdit: true,
  canResolve: true,
});

const authoritativeState = deepFreeze({
  positionId: "boundary_event",
  deterministicResources: {
    signalCredits: 3,
    calibrationTokens: 1,
  },
  eligibility: {
    compareSourceTiming: true,
    advanceInvestigation: false,
  },
  resolvedPlayerActions: ["inspect_optical_record"],
  discordRoles: {
    participant_alice: ["field_observer"],
  },
});
const authoritativeBefore = structuredClone(authoritativeState);

const completeRevision = Object.freeze({
  statement: "The retained optical and radio observations share a stable timing offset.",
  interpretation:
    "The supplied analysis artifact supports a timing alignment without establishing shared cause.",
  limitations: [
    "Clock uncertainty bounds the attainable precision.",
    "The alignment does not establish source distance or trajectory.",
  ],
  evidenceReferences: [
    {
      evidenceId: "optical_record",
      label: "Retained optical observation",
      availability: "available",
      publicSafe: true,
    },
    {
      evidenceId: "private_operator_note",
      label: "Private operator note",
      availability: "available",
      publicSafe: false,
    },
  ],
  analysisArtifactReferences: [
    {
      analysisJobId: "job_clock_alignment",
      analysisArtifactId: "artifact_clock_alignment",
      artifactHash: "a".repeat(64),
      inputManifestHash: "b".repeat(64),
      availability: "available",
      sourceEvidenceIds: ["optical_record", "radio_return"],
      publicSafe: true,
    },
  ],
});

const model = new Phase4CReferenceModel({
  roomId: "phase4c-lab",
  institutionContext: "Boundary Array collaborative investigation",
});
const replayEvents = [];

function operation(type, operationId, fields = {}, expectedRevision = model.roomRevision) {
  return {
    type,
    operationId,
    expectedRevision,
    ...structuredClone(fields),
  };
}

function perform(participant, value) {
  const event = {
    participant: structuredClone(participant),
    operation: structuredClone(value),
  };
  replayEvents.push(event);
  return model.mutate(event.participant, event.operation);
}

const createPrimary = operation("finding:create", "op-create-primary", {
  ...completeRevision,
  revisionReason: "Initial retained-source comparison.",
});
const createdPrimary = accepted(
  perform(alice, createPrimary),
  "finding_created",
);
const primaryFindingId = createdPrimary.data.findingId;

accepted(
  perform(
    alice,
    operation("finding:begin_review", "op-review-start-primary-r1", {
      findingId: primaryFindingId,
      findingRevision: 1,
    }),
  ),
  "finding_review_started",
);

const authorEndorsement = accepted(
  perform(
    alice,
    operation("review:submit", "op-author-endorse-primary-r1", {
      findingId: primaryFindingId,
      findingRevision: 1,
      disposition: "endorse",
      rationale: "The author confirms the intended wording.",
    }),
  ),
  "review_submitted",
);
assert.ok(authorEndorsement.data.reviewId);

recordCase(2, "revision author cannot satisfy independent review alone", () => {
  const eligibility = model.promotionEligibility(primaryFindingId, 1);
  assert.equal(eligibility.eligible, false);
  assert.ok(blockerCodes(eligibility).includes("independent_endorsement_required"));
});

const bobEndorseOperation = operation(
  "review:submit",
  "op-bob-endorse-primary-r1",
  {
    findingId: primaryFindingId,
    findingRevision: 1,
    disposition: "endorse",
    rationale: "The evidence and limitation wording are reviewable.",
  },
);
const bobEndorsement = accepted(
  perform(bob, bobEndorseOperation),
  "review_submitted",
);

recordCase(1, "second participant endorses the current finding revision", () => {
  assert.equal(bobEndorsement.data.findingRevision, 1);
  assert.equal(model.promotionEligibility(primaryFindingId, 1).eligible, true);
  assert.equal(
    model.getFindingRevision(primaryFindingId, 1).lifecycleState,
    "reviewed",
  );
});

const beforeDuplicateReview = model.exportState();
const duplicateReview = perform(bob, bobEndorseOperation);
recordCase(3, "duplicate review operations are idempotent", () => {
  assert.equal(duplicateReview.status, "duplicate");
  assert.equal(duplicateReview.code, "duplicate_operation");
  assert.equal(duplicateReview.originalCode, "review_submitted");
  assert.deepEqual(model.exportState(), beforeDuplicateReview);
  assert.equal(model.reviewsFor(primaryFindingId, 1).length, 2);
});

const primaryRevisionOne = model.getFindingRevision(primaryFindingId, 1);
const primaryReviewsOne = model.reviewsFor(primaryFindingId, 1);
const revisedPrimary = accepted(
  perform(
    alice,
    operation("finding:revise", "op-create-primary-r2", {
      ...completeRevision,
      statement:
        "The retained observations exhibit a repeatable timing offset within the stated uncertainty.",
      revisionReason: "Clarify that the measured offset is bounded by uncertainty.",
      findingId: primaryFindingId,
      findingRevision: 1,
      addressesReviewIds: [],
    }),
  ),
  "finding_revision_created",
);
assert.equal(revisedPrimary.data.findingRevision, 2);

recordCase(9, "new revision preserves the complete earlier revision", () => {
  assert.deepEqual(model.getFindingRevision(primaryFindingId, 1), primaryRevisionOne);
  assert.equal(model.getFindingRevision(primaryFindingId, 2).previousRevision, 1);
  assert.notEqual(
    model.getFindingRevision(primaryFindingId, 2).statement,
    primaryRevisionOne.statement,
  );
});

recordCase(10, "new revision does not inherit endorsement or eligibility", () => {
  assert.equal(model.reviewsFor(primaryFindingId, 2).length, 0);
  const eligibility = model.promotionEligibility(primaryFindingId, 2);
  assert.equal(eligibility.eligible, false);
  assert.ok(blockerCodes(eligibility).includes("independent_endorsement_required"));
});

recordCase(11, "reviews remain attached to their exact revision", () => {
  assert.deepEqual(model.reviewsFor(primaryFindingId, 1), primaryReviewsOne);
  assert.ok(
    model
      .reviewsFor(primaryFindingId, 1)
      .every((review) => review.findingRevision === 1),
  );
  assert.deepEqual(model.reviewsFor(primaryFindingId, 2), []);
});

accepted(
  perform(
    alice,
    operation("finding:begin_review", "op-review-start-primary-r2", {
      findingId: primaryFindingId,
      findingRevision: 2,
    }),
  ),
  "finding_review_started",
);

const obsoleteReview = rejected(
  perform(
    bob,
    operation("review:submit", "op-review-obsolete-primary-r1", {
      findingId: primaryFindingId,
      findingRevision: 1,
      disposition: "endorse",
      rationale: "This intentionally targets an obsolete revision.",
    }),
  ),
  "stale_finding_revision",
);
recordCase(4, "review against an obsolete revision is rejected", () => {
  assert.equal(obsoleteReview.data.suppliedRevision, 1);
  assert.equal(obsoleteReview.data.currentRevision, 2);
  assert.equal(model.reviewsFor(primaryFindingId, 1).length, 2);
});

const nonexistentRevisionReview = rejected(
  perform(
    bob,
    operation("review:submit", "op-review-missing-primary-r99", {
      findingId: primaryFindingId,
      findingRevision: 99,
      disposition: "endorse",
      rationale: "This revision was never created.",
    }),
  ),
  "revision_not_found",
);
recordCase(5, "review against a nonexistent revision is rejected", () => {
  assert.match(nonexistentRevisionReview.message, /no revision 99/);
});

const stalePromotion = rejected(
  perform(
    bob,
    operation("finding:promote", "op-promote-obsolete-primary-r1", {
      findingId: primaryFindingId,
      findingRevision: 1,
    }),
  ),
  "stale_finding_revision",
);
recordCase(16, "promotion requires the exact current revision", () => {
  assert.equal(stalePromotion.data.currentRevision, 2);
});

const unendorsedPromotion = rejected(
  perform(
    bob,
    operation("finding:promote", "op-promote-unendorsed-primary-r2", {
      findingId: primaryFindingId,
      findingRevision: 2,
    }),
  ),
  "promotion_blocked",
);
recordCase(17, "promotion requires an independent endorsement", () => {
  assert.ok(
    blockerCodes(unendorsedPromotion).includes("independent_endorsement_required"),
  );
});

const challenge = accepted(
  perform(
    charlie,
    operation("review:submit", "op-challenge-primary-r2", {
      findingId: primaryFindingId,
      findingRevision: 2,
      disposition: "challenge",
      rationale: "The uncertainty statement needs an explicit bound.",
    }),
  ),
  "review_submitted",
);
const challengeReviewId = challenge.data.reviewId;

accepted(
  perform(
    bob,
    operation("review:submit", "op-bob-endorse-primary-r2", {
      findingId: primaryFindingId,
      findingRevision: 2,
      disposition: "endorse",
      rationale: "The retained data supports review despite the open challenge.",
    }),
  ),
  "review_submitted",
);

recordCase(8, "an endorsement does not erase an existing challenge", () => {
  const challengeRecord = model
    .reviewsFor(primaryFindingId, 2)
    .find((review) => review.reviewId === challengeReviewId);
  assert.equal(challengeRecord.disposition, "challenge");
  const eligibility = model.promotionEligibility(primaryFindingId, 2);
  assert.ok(blockerCodes(eligibility).includes("unresolved_challenge"));
  assert.equal(
    model.getFindingRevision(primaryFindingId, 2).lifecycleState,
    "challenged",
  );
});

const challengeBlockedPromotion = rejected(
  perform(
    bob,
    operation("finding:promote", "op-promote-challenged-primary-r2", {
      findingId: primaryFindingId,
      findingRevision: 2,
    }),
  ),
  "promotion_blocked",
);
recordCase(6, "unresolved challenge blocks promotion", () => {
  assert.ok(
    blockerCodes(challengeBlockedPromotion).includes("unresolved_challenge"),
  );
});

const unauthorizedResolution = rejected(
  perform(
    alice,
    operation("review:resolve", "op-author-resolve-challenge-primary-r2", {
      reviewId: challengeReviewId,
      findingId: primaryFindingId,
      findingRevision: 2,
      rationale: "The author cannot independently dismiss the challenge.",
    }),
  ),
  "permission_denied",
);
assert.match(unauthorizedResolution.message, /reviewer|independent/);

accepted(
  perform(
    charlie,
    operation("review:resolve", "op-reviewer-resolve-challenge-primary-r2", {
      reviewId: challengeReviewId,
      findingId: primaryFindingId,
      findingRevision: 2,
      rationale: "The clarified uncertainty language resolves this challenge.",
    }),
  ),
  "review_blocker_resolved",
);

const firstRevisionRequest = accepted(
  perform(
    charlie,
    operation("review:submit", "op-request-primary-r2-first", {
      findingId: primaryFindingId,
      findingRevision: 2,
      disposition: "request_revision",
      rationale: "State the retained-source limitation more directly.",
    }),
  ),
  "review_submitted",
);

accepted(
  perform(
    alice,
    operation("review:submit", "op-author-endorse-requested-primary-r2", {
      findingId: primaryFindingId,
      findingRevision: 2,
      disposition: "endorse",
      rationale: "Author endorsement does not withdraw the revision request.",
    }),
  ),
  "review_submitted",
);

const requestBlockedPromotion = rejected(
  perform(
    bob,
    operation("finding:promote", "op-promote-requested-primary-r2", {
      findingId: primaryFindingId,
      findingRevision: 2,
    }),
  ),
  "promotion_blocked",
);
recordCase(7, "unresolved revision request blocks promotion", () => {
  assert.ok(
    blockerCodes(requestBlockedPromotion).includes(
      "unresolved_revision_request",
    ),
  );
  assert.equal(
    model.getFindingRevision(primaryFindingId, 2).lifecycleState,
    "revision_requested",
  );

  const carryModel = new Phase4CReferenceModel({
    roomId: "phase4c-carry-request",
    institutionContext: "Explicit revision-request carry test",
  });
  const carryCreated = accepted(
    carryModel.mutate(alice, {
      type: "finding:create",
      operationId: "carry-create-r1",
      expectedRevision: 0,
      statement: "A revision request must remain explicit across revisions.",
      interpretation: null,
      limitations: [],
      evidenceReferences: [],
      analysisArtifactReferences: [],
      revisionReason: "Initial carry test.",
    }),
    "finding_created",
  );
  const carryFindingId = carryCreated.data.findingId;
  accepted(
    carryModel.mutate(alice, {
      type: "finding:begin_review",
      operationId: "carry-start-r1",
      expectedRevision: 1,
      findingId: carryFindingId,
      findingRevision: 1,
    }),
    "finding_review_started",
  );
  const carriedRevisionRequest = accepted(
    carryModel.mutate(charlie, {
      type: "review:submit",
      operationId: "carry-request-r1",
      expectedRevision: 2,
      findingId: carryFindingId,
      findingRevision: 1,
      disposition: "request_revision",
      rationale: "This request is intentionally not addressed.",
    }),
    "review_submitted",
  );
  accepted(
    carryModel.mutate(alice, {
      type: "finding:revise",
      operationId: "carry-create-r2",
      expectedRevision: 3,
      findingId: carryFindingId,
      findingRevision: 1,
      statement: "The newer revision did not explicitly address the request.",
      interpretation: null,
      limitations: [],
      evidenceReferences: [],
      analysisArtifactReferences: [],
      revisionReason: "Create an intentionally unlinked revision.",
      addressesReviewIds: [],
    }),
    "finding_revision_created",
  );
  accepted(
    carryModel.mutate(alice, {
      type: "finding:begin_review",
      operationId: "carry-start-r2",
      expectedRevision: 4,
      findingId: carryFindingId,
      findingRevision: 2,
    }),
    "finding_review_started",
  );
  accepted(
    carryModel.mutate(bob, {
      type: "review:submit",
      operationId: "carry-endorse-r2",
      expectedRevision: 5,
      findingId: carryFindingId,
      findingRevision: 2,
      disposition: "endorse",
      rationale: "Endorsement cannot erase the unaddressed prior request.",
    }),
    "review_submitted",
  );
  const carryEligibility = carryModel.promotionEligibility(carryFindingId, 2);
  assert.equal(carryEligibility.eligible, false);
  assert.ok(
    blockerCodes(carryEligibility).includes("unresolved_revision_request"),
  );
  accepted(
    carryModel.mutate(charlie, {
      type: "review:withdraw",
      operationId: "carry-withdraw-r1-request",
      expectedRevision: 6,
      reviewId: carriedRevisionRequest.data.reviewId,
      findingId: carryFindingId,
      findingRevision: 1,
      rationale: "Withdraw the historical blocker after reviewing revision two.",
    }),
    "review_blocker_withdrawn",
  );
  assert.equal(
    carryModel.getFindingRevision(carryFindingId, 2).lifecycleState,
    "reviewed",
  );
  assert.equal(carryModel.promotionEligibility(carryFindingId, 2).eligible, true);
});

rejected(
  perform(
    alice,
    operation("review:withdraw", "op-author-withdraw-request-primary-r2", {
      reviewId: firstRevisionRequest.data.reviewId,
      findingId: primaryFindingId,
      findingRevision: 2,
      rationale: "Only the reviewer may withdraw this request.",
    }),
  ),
  "permission_denied",
);

accepted(
  perform(
    charlie,
    operation("review:withdraw", "op-reviewer-withdraw-request-primary-r2", {
      reviewId: firstRevisionRequest.data.reviewId,
      findingId: primaryFindingId,
      findingRevision: 2,
      rationale: "Withdrawn in favor of a more specific revision request.",
    }),
  ),
  "review_blocker_withdrawn",
);

const addressedRevisionRequest = accepted(
  perform(
    charlie,
    operation("review:submit", "op-request-primary-r2-addressed", {
      findingId: primaryFindingId,
      findingRevision: 2,
      disposition: "request_revision",
      rationale: "Name the analysis artifact without implying causation.",
    }),
  ),
  "review_submitted",
);

const primaryRevisionThree = accepted(
  perform(
    alice,
    operation("finding:revise", "op-create-primary-r3", {
      ...completeRevision,
      statement:
        "Artifact artifact_clock_alignment reports a stable retained-source offset without a causal inference.",
      revisionReason: "Address the explicit artifact and causation wording request.",
      findingId: primaryFindingId,
      findingRevision: 2,
      addressesReviewIds: [addressedRevisionRequest.data.reviewId],
    }),
  ),
  "finding_revision_created",
);
assert.deepEqual(primaryRevisionThree.data.addressedReviewIds, [
  addressedRevisionRequest.data.reviewId,
]);

accepted(
  perform(
    alice,
    operation("finding:begin_review", "op-review-start-primary-r3", {
      findingId: primaryFindingId,
      findingRevision: 3,
    }),
  ),
  "finding_review_started",
);
accepted(
  perform(
    alice,
    operation("review:submit", "op-author-endorse-primary-r3", {
      findingId: primaryFindingId,
      findingRevision: 3,
      disposition: "endorse",
      rationale: "The revision addresses the requested wording.",
    }),
  ),
  "review_submitted",
);
accepted(
  perform(
    bob,
    operation("review:submit", "op-bob-endorse-primary-r3", {
      findingId: primaryFindingId,
      findingRevision: 3,
      disposition: "endorse",
      rationale: "Independent review accepts the exact third revision.",
    }),
  ),
  "review_submitted",
);

const promotePrimaryOperation = operation(
  "finding:promote",
  "op-promote-primary-r3",
  {
    findingId: primaryFindingId,
    findingRevision: 3,
  },
);
const promotedPrimary = accepted(
  perform(moderator, promotePrimaryOperation),
  "finding_promoted",
);
const primaryConclusion = promotedPrimary.data.conclusion;
const conclusionCountBeforeDuplicate = model.snapshot().publicConclusions.length;
const stateBeforeDuplicatePromotion = model.exportState();
const duplicatePromotion = perform(moderator, promotePrimaryOperation);

recordCase(18, "promotion is idempotent", () => {
  assert.equal(duplicatePromotion.status, "duplicate");
  assert.equal(duplicatePromotion.originalCode, "finding_promoted");
  assert.deepEqual(model.exportState(), stateBeforeDuplicatePromotion);
  assert.equal(
    model.snapshot().publicConclusions.length,
    conclusionCountBeforeDuplicate,
  );
});

recordCase(19, "public promotion output is sanitized", () => {
  assert.equal(
    assertPublicConclusionSafe(primaryConclusion, {
      forbiddenValues: [
        alice.id,
        bob.id,
        charlie.id,
        moderator.id,
        promotePrimaryOperation.operationId,
        "private_operator_note",
      ],
    }),
    true,
  );
  const serialized = JSON.stringify(primaryConclusion);
  assert.doesNotMatch(serialized, /participant_/);
  assert.doesNotMatch(serialized, /private_operator_note/);
  assert.doesNotMatch(serialized, /op-promote-primary-r3/);
  assert.equal(primaryConclusion.evidenceReferences.length, 1);
});

recordCase(20, "recursive sanitation rejects forbidden nested fields", () => {
  assert.throws(
    () =>
      assertPublicConclusionSafe({
        statement: "Nominal public text",
        metadata: {
          review: {
            nested: {
              discord_user_id: "discord-private-user",
            },
          },
          secrets: {
            ROOM_TICKET_SECRET: "do-not-publish",
          },
        },
      }),
    (error) =>
      error instanceof Phase4CModelError &&
      error.code === "public_sanitation_failed" &&
      /discord_user_id|ROOM_TICKET_SECRET/.test(error.message),
  );
});

recordCase(25, "provenance includes supplied Milestone 6J references", () => {
  const provenance = primaryConclusion.provenanceSummary;
  assert.equal(provenance.status, "complete");
  assert.deepEqual(provenance.analysisJobReferences, ["job_clock_alignment"]);
  assert.deepEqual(provenance.analysisArtifactReferences, [
    "artifact_clock_alignment",
  ]);
  assert.deepEqual(provenance.findingRevisionReference, {
    findingId: primaryFindingId,
    findingRevision: 3,
  });
  assert.equal(
    provenance.promotedConclusionReference,
    primaryConclusion.publicConclusionId,
  );
  assert.ok(provenance.observationReferences.includes("optical_record"));
  assert.ok(provenance.reviewReferences.length >= 2);
  assert.deepEqual(provenance.missingLinks, []);
});

const createdIncomplete = accepted(
  perform(
    alice,
    operation("finding:create", "op-create-incomplete", {
      statement: "A visible interval warrants advisory follow-up.",
      interpretation: null,
      limitations: ["No Milestone 6J artifact was supplied."],
      evidenceReferences: [],
      analysisArtifactReferences: [],
      revisionReason: "Record an explicitly incomplete provenance chain.",
    }),
  ),
  "finding_created",
);
const incompleteFindingId = createdIncomplete.data.findingId;
accepted(
  perform(
    alice,
    operation("finding:begin_review", "op-review-start-incomplete-r1", {
      findingId: incompleteFindingId,
      findingRevision: 1,
    }),
  ),
  "finding_review_started",
);
accepted(
  perform(
    bob,
    operation("review:submit", "op-bob-endorse-incomplete-r1", {
      findingId: incompleteFindingId,
      findingRevision: 1,
      disposition: "endorse",
      rationale: "The missing provenance is represented explicitly.",
    }),
  ),
  "review_submitted",
);
const promotedIncomplete = accepted(
  perform(
    moderator,
    operation("finding:promote", "op-promote-incomplete-r1", {
      findingId: incompleteFindingId,
      findingRevision: 1,
    }),
  ),
  "finding_promoted",
);

recordCase(26, "missing provenance is explicit and never fabricated", () => {
  const provenance = promotedIncomplete.data.conclusion.provenanceSummary;
  assert.equal(provenance.status, "incomplete");
  assert.deepEqual(provenance.observationReferences, []);
  assert.deepEqual(provenance.analysisJobReferences, []);
  assert.deepEqual(provenance.analysisArtifactReferences, []);
  assert.deepEqual(provenance.missingLinks, [
    "observation",
    "analysis_job",
    "analysis_artifact",
  ]);
});

const createdSuccessor = accepted(
  perform(
    charlie,
    operation("finding:create", "op-create-successor", {
      statement: "A later synthesis supersedes the incomplete advisory finding.",
      interpretation: "The predecessor remains available for provenance inspection.",
      limitations: ["The synthesis does not alter authoritative state."],
      evidenceReferences: [],
      analysisArtifactReferences: [],
      revisionReason: "Create a successor without deleting its predecessor.",
    }),
  ),
  "finding_created",
);
const successorFindingId = createdSuccessor.data.findingId;
const predecessorBeforeSupersession = model.getFindingRevision(incompleteFindingId, 1);
const predecessorConclusionBefore = structuredClone(
  promotedIncomplete.data.conclusion,
);
const supersedesRelationship = accepted(
  perform(
    charlie,
    operation("relationship:create", "op-successor-supersedes-incomplete", {
      sourceFindingId: successorFindingId,
      sourceRevision: 1,
      targetFindingId: incompleteFindingId,
      targetRevision: 1,
      relationshipType: "supersedes",
      rationale: "The new synthesis replaces the advisory interpretation, not its history.",
    }),
  ),
  "relationship_created",
);

recordCase(12, "superseding preserves the predecessor and its history", () => {
  const predecessor = model.getFindingRevision(incompleteFindingId, 1);
  assert.ok(predecessor);
  assert.equal(predecessor.statement, predecessorBeforeSupersession.statement);
  assert.equal(predecessor.lifecycleState, "superseded");
  const storedConclusion = model
    .snapshot()
    .publicConclusions.find(
      (conclusion) =>
        conclusion.publicConclusionId ===
        predecessorConclusionBefore.publicConclusionId,
    );
  assert.deepEqual(storedConclusion, predecessorConclusionBefore);
  assert.equal(supersedesRelationship.data.targetFindingId, incompleteFindingId);
});

const selfLink = rejected(
  perform(
    charlie,
    operation("relationship:create", "op-successor-self-link", {
      sourceFindingId: successorFindingId,
      sourceRevision: 1,
      targetFindingId: successorFindingId,
      targetRevision: 1,
      relationshipType: "related_to",
      rationale: "Self links are invalid.",
    }),
  ),
  "self_link",
);
recordCase(13, "self-links are rejected", () => {
  assert.match(selfLink.message, /cannot be related to itself/);
});

const missingTarget = rejected(
  perform(
    charlie,
    operation("relationship:create", "op-missing-relationship-target", {
      sourceFindingId: successorFindingId,
      sourceRevision: 1,
      targetFindingId: "finding_missing",
      targetRevision: 1,
      relationshipType: "supports",
      rationale: "The target does not exist.",
    }),
  ),
  "finding_not_found",
);
recordCase(14, "missing relationship targets are rejected", () => {
  assert.match(missingTarget.message, /does not exist/);
});

const supportsOperation = operation(
  "relationship:create",
  "op-primary-supports-successor",
  {
    sourceFindingId: primaryFindingId,
    sourceRevision: 3,
    targetFindingId: successorFindingId,
    targetRevision: 1,
    relationshipType: "supports",
    rationale: "The reviewed artifact-linked finding supports the successor.",
  },
);
accepted(perform(bob, supportsOperation), "relationship_created");
const stateBeforeDuplicateRelationship = model.exportState();
const duplicateRelationship = perform(bob, supportsOperation);
recordCase(15, "duplicate relationship operations are idempotent", () => {
  assert.equal(duplicateRelationship.status, "duplicate");
  assert.equal(duplicateRelationship.originalCode, "relationship_created");
  assert.deepEqual(model.exportState(), stateBeforeDuplicateRelationship);
});

rejected(
  perform(
    bob,
    operation("relationship:create", "op-malformed-relationship-type", {
      sourceFindingId: primaryFindingId,
      sourceRevision: 3,
      targetFindingId: successorFindingId,
      targetRevision: 1,
      relationshipType: "proves",
      rationale: "Malformed relationship types are rejected.",
    }),
  ),
  "malformed_request",
);

rejected(
  perform(
    bob,
    operation(
      "finding:begin_review",
      "op-stale-room-revision",
      {
        findingId: successorFindingId,
        findingRevision: 1,
      },
      0,
    ),
  ),
  "stale_room_revision",
);

const invalidTransitionOne = rejected(
  perform(
    alice,
    operation("finding:begin_review", "op-invalid-transition-promoted-one", {
      findingId: primaryFindingId,
      findingRevision: 3,
    }),
  ),
  "invalid_transition",
);
const invalidTransitionTwo = rejected(
  perform(
    alice,
    operation("finding:begin_review", "op-invalid-transition-promoted-two", {
      findingId: primaryFindingId,
      findingRevision: 3,
    }),
  ),
  "invalid_transition",
);
recordCase(24, "invalid transitions return deterministic structured errors", () => {
  assert.equal(invalidTransitionOne.message, invalidTransitionTwo.message);
  assert.deepEqual(invalidTransitionOne.data, invalidTransitionTwo.data);
  assert.match(invalidTransitionOne.message, /Cannot begin review from lifecycle promoted/);
});

recordCase(21, "reconnecting clients receive identical canonical state", () => {
  const first = model.snapshot();
  const second = model.snapshot();
  assert.deepEqual(second, first);
  assert.equal(JSON.stringify(second), JSON.stringify(first));
});

recordCase(22, "persisted state survives Durable Object-style reconstruction", () => {
  const persisted = JSON.parse(JSON.stringify(model.exportState()));
  const reconstructed = Phase4CReferenceModel.fromPersistedState(persisted);
  assert.deepEqual(reconstructed.exportState(), model.exportState());
  assert.deepEqual(reconstructed.snapshot(), model.snapshot());
});

recordCase(23, "replaying the same event sequence produces the same final state", () => {
  const replayed = new Phase4CReferenceModel({
    roomId: "phase4c-lab",
    institutionContext: "Boundary Array collaborative investigation",
  });
  for (const event of replayEvents) {
    replayed.mutate(event.participant, event.operation);
  }
  assert.deepEqual(replayed.exportState(), model.exportState());
  assert.deepEqual(replayed.snapshot(), model.snapshot());
});

recordCase(27, "promotion cannot mutate authoritative game state", () => {
  assert.deepEqual(authoritativeState, authoritativeBefore);
  assert.deepEqual(Object.keys(model.exportState()).sort(), [
    "findings",
    "institutionContext",
    "operationOrder",
    "processedOperations",
    "publicConclusions",
    "relationships",
    "reviewResolutions",
    "reviews",
    "roomId",
    "roomRevision",
    "schemaVersion",
  ]);
  assert.equal(hasOwn(model.exportState(), "deterministicResources"), false);
  assert.equal(hasOwn(model.exportState(), "eligibility"), false);
  assert.equal(hasOwn(model.exportState(), "resolvedPlayerActions"), false);
  assert.equal(hasOwn(model.exportState(), "discordRoles"), false);
  const roomWorkerSource = checkedSource.get("worker/lib/investigation-room.ts");
  const promotionStart = roomWorkerSource.indexOf(
    'if (message.type === "finding:promote")',
  );
  const promotionEnd = roomWorkerSource.indexOf(
    'if (message.type === "finding:withdraw"',
    promotionStart,
  );
  assert.ok(promotionStart >= 0 && promotionEnd > promotionStart);
  const productionPromotionHandler = roomWorkerSource.slice(
    promotionStart,
    promotionEnd,
  );
  assert.match(productionPromotionHandler, /publicConclusions/);
  assert.match(productionPromotionHandler, /acceptReviewPatch/);
  assert.doesNotMatch(
    productionPromotionHandler,
    /execute_clock_alignment_action|advancePosition|deterministicResources|resolvedPlayerActions|discordRoles|PUBLIC_DB|PUBLIC_ARTIFACTS/,
  );
});

recordCase(28, "Phase 4A validation command boundary remains registered", () => {
  assert.equal(packageJson.scripts["validate:phase4"], "node tools/validate_phase4.mjs");
  assert.match(phase4Source, /worker\/lib\/investigation-room\.ts/);
  assert.match(phase4Source, /deserializeAttachment/);
});

recordCase(29, "Phase 4B validation command boundary remains registered", () => {
  assert.equal(packageJson.scripts["validate:phase4b"], "node tools/validate_phase4b.mjs");
  assert.match(phase4bSource, /phase4b_reference_model/);
});

recordCase(30, "type-check and production-build command boundaries remain registered", () => {
  assert.equal(packageJson.scripts.check, "npm run build");
  assert.match(packageJson.scripts.build, /tsc --noEmit/);
  assert.match(packageJson.scripts.build, /vite build/);
  assert.match(packageJson.scripts.build, /scrub_build_secrets/);
  assert.equal(
    packageJson.scripts["validate:phase4c"],
    "node tools/validate_phase4c.mjs",
  );
});

const expectedCaseNumbers = Array.from({ length: 30 }, (_, index) => index + 1);
assert.deepEqual([...cases.keys()].sort((left, right) => left - right), expectedCaseNumbers);

const orderedCases = [...cases.values()].sort((left, right) => left.number - right.number);
console.log(
  JSON.stringify(
    {
      ok: true,
      phase: "4C",
      referenceModel: {
        deterministicIdsAndTimestamps: true,
        structuredResponses: true,
        immutableRevisionHistory: true,
        exactRevisionReviews: true,
        explicitBlockerResolution: true,
        recursivePublicSanitation: true,
        canonicalPersistenceAndReplay: true,
        authoritativeMutationCapabilities: false,
      },
      sourceChecks,
      cases: orderedCases,
      totals: {
        required: 30,
        passed: orderedCases.length,
      },
      finalState: {
        roomRevision: model.roomRevision,
        findings: model.snapshot().findings.length,
        reviews: model.snapshot().reviews.length,
        resolutions: model.snapshot().reviewResolutions.length,
        relationships: model.snapshot().relationships.length,
        publicConclusions: model.snapshot().publicConclusions.length,
      },
    },
    null,
    2,
  ),
);
