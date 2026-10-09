import { useEffect, useId, useMemo, useState } from "react";
import type { InvestigationRoomController } from "../hooks/useInvestigationRoom";
import {
  FINDING_INTERPRETATION_MAX_LENGTH,
  FINDING_LIMITATION_MAX_LENGTH,
  FINDING_RELATIONSHIP_TYPES,
  FINDING_REVISION_REASON_MAX_LENGTH,
  FINDING_REVIEW_DISPOSITIONS,
  FINDING_STATEMENT_MAX_LENGTH,
  REFERENCE_LABEL_MAX_LENGTH,
  RELATIONSHIP_RATIONALE_MAX_LENGTH,
  REVIEW_RATIONALE_MAX_LENGTH,
  resolutionForReview,
  type FindingAnalysisArtifactReference,
  type FindingRelationshipType,
  type FindingReview,
  type FindingReviewDisposition,
  type FindingReviewRubric,
  type FindingRevision,
  type ProvenanceAvailability,
  type PublicConclusion,
} from "../shared/finding-review";
import type { RoomFinding } from "../shared/investigation-room";

interface FindingReviewPanelProps {
  room: InvestigationRoomController;
  finding: RoomFinding;
  onOpenFinding(finding: RoomFinding): void;
}

const SAFE_IDENTIFIER_PATTERN = "[A-Za-z0-9][A-Za-z0-9._:-]{0,191}";
const SHA256_PATTERN = "[a-f0-9]{64}";

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function revisionLabel(revision: FindingRevision, currentRevision: number): string {
  const position = revision.revision === currentRevision ? "current" : "historical";
  return `Revision ${revision.revision}, ${position}, ${humanize(revision.lifecycleState)}`;
}

function operationSucceeded(
  room: InvestigationRoomController,
  operationId: string | null,
): boolean {
  return Boolean(
    operationId &&
      room.operationFeedback?.operationId === operationId &&
      (room.operationFeedback.outcome === "accepted" ||
        room.operationFeedback.outcome === "duplicate"),
  );
}

function newAnalysisReference(): FindingAnalysisArtifactReference {
  return {
    referenceId: `analysis-ref-${globalThis.crypto.randomUUID()}`,
    analysisJobId: null,
    analysisArtifactId: "",
    artifactHash: null,
    label: "",
    availability: "available",
    publicSafe: false,
  };
}

function ConclusionCard({ conclusion }: { conclusion: PublicConclusion }) {
  return (
    <section className="public-conclusion" aria-labelledby={`conclusion-${conclusion.conclusionId}`}>
      <div className="finding-subheading">
        <div>
          <p className="eyebrow">Sanitized advisory research output</p>
          <h5 id={`conclusion-${conclusion.conclusionId}`}>Promoted public conclusion</h5>
        </div>
        <span className="lifecycle-badge promoted">promoted</span>
      </div>
      <p className="conclusion-statement">{conclusion.statement}</p>
      {conclusion.interpretation ? <p>{conclusion.interpretation}</p> : null}
      <div className="conclusion-metadata">
        <span>Source revision {conclusion.sourceRevision}</span>
        <span>Published {dateLabel(conclusion.publishedAt)}</span>
        <span>{conclusion.institutionContext}</span>
      </div>
      <p className="authority-note">
        This conclusion is advisory research output. It cannot alter authoritative game state,
        progression, resources, eligibility, or roles.
      </p>

      <div className="conclusion-columns">
        <section aria-labelledby={`conclusion-limitations-${conclusion.conclusionId}`}>
          <h6 id={`conclusion-limitations-${conclusion.conclusionId}`}>Limitations</h6>
          {conclusion.limitations.length > 0 ? (
            <ul>
              {conclusion.limitations.map((limitation, index) => (
                <li key={`${index}-${limitation}`}>{limitation}</li>
              ))}
            </ul>
          ) : (
            <p>None supplied.</p>
          )}
        </section>
        <section aria-labelledby={`conclusion-evidence-${conclusion.conclusionId}`}>
          <h6 id={`conclusion-evidence-${conclusion.conclusionId}`}>Public-safe evidence</h6>
          {conclusion.evidenceReferences.length > 0 ? (
            <ul>
              {conclusion.evidenceReferences.map((reference) => (
                <li key={reference.referenceId}>
                  <strong>{reference.label}</strong>
                  <span>{humanize(reference.availability)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>No public-safe evidence references were supplied.</p>
          )}
        </section>
        <section aria-labelledby={`conclusion-analysis-${conclusion.conclusionId}`}>
          <h6 id={`conclusion-analysis-${conclusion.conclusionId}`}>Analysis artifacts</h6>
          {conclusion.analysisArtifactReferences.length > 0 ? (
            <ul>
              {conclusion.analysisArtifactReferences.map((reference) => (
                <li key={reference.referenceId}>
                  <strong>{reference.label}</strong>
                  <span>
                    {reference.analysisArtifactId} · {humanize(reference.availability)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p>Unavailable; no public-safe Milestone 6J artifact link was supplied.</p>
          )}
        </section>
      </div>

      <section
        className="conclusion-provenance"
        aria-labelledby={`conclusion-provenance-${conclusion.conclusionId}`}
      >
        <h6 id={`conclusion-provenance-${conclusion.conclusionId}`}>Provenance chain</h6>
        <ol>
          {conclusion.provenance.stages.map((stage) => (
            <li key={stage.stage}>
              <strong>{humanize(stage.stage)}</strong>
              <span>{humanize(stage.availability)}</span>
              {stage.references.length > 0 ? (
                <small>{stage.references.join(", ")}</small>
              ) : (
                <small>No reference available</small>
              )}
            </li>
          ))}
        </ol>
      </section>
      {conclusion.supersession.supersedesConclusionIds.length > 0 ? (
        <p className="supersession-note">
          Supersedes public conclusion
          {conclusion.supersession.supersedesConclusionIds.length === 1 ? " " : "s "}
          {conclusion.supersession.supersedesConclusionIds.join(", ")}.
        </p>
      ) : null}
    </section>
  );
}

export function FindingReviewPanel({
  room,
  finding,
  onOpenFinding,
}: FindingReviewPanelProps) {
  const formPrefix = useId();
  const snapshot = room.snapshot;
  const revisions = useMemo(
    () =>
      (snapshot?.findingRevisions ?? [])
        .filter((revision) => revision.findingId === finding.findingId)
        .sort((left, right) => right.revision - left.revision),
    [finding.findingId, snapshot?.findingRevisions],
  );
  const currentRevision = revisions.find(
    (revision) => revision.revision === finding.currentRevision,
  ) ?? null;
  const [inspectedRevisionNumber, setInspectedRevisionNumber] = useState(
    finding.currentRevision,
  );
  const inspectedRevision = revisions.find(
    (revision) => revision.revision === inspectedRevisionNumber,
  ) ?? currentRevision;

  const reviews = useMemo(
    () =>
      (snapshot?.reviews ?? [])
        .filter((review) => review.findingId === finding.findingId)
        .sort((left, right) => left.createdAt.localeCompare(right.createdAt)),
    [finding.findingId, snapshot?.reviews],
  );
  const reviewResolutions = snapshot?.reviewResolutions ?? [];
  const relationships = useMemo(
    () =>
      (snapshot?.relationships ?? []).filter(
        (relationship) =>
          relationship.sourceFindingId === finding.findingId ||
          relationship.targetFindingId === finding.findingId,
      ),
    [finding.findingId, snapshot?.relationships],
  );
  const assessment = (snapshot?.promotionAssessments ?? []).find(
    (candidate) =>
      candidate.findingId === finding.findingId &&
      candidate.findingRevision === finding.currentRevision,
  ) ?? null;
  const conclusion = (snapshot?.publicConclusions ?? []).find(
    (candidate) =>
      candidate.sourceFindingId === finding.findingId &&
      candidate.sourceRevision === inspectedRevision?.revision,
  ) ?? null;

  const [revisionEditorOpen, setRevisionEditorOpen] = useState(false);
  const [revisionStatement, setRevisionStatement] = useState("");
  const [revisionInterpretation, setRevisionInterpretation] = useState("");
  const [revisionLimitations, setRevisionLimitations] = useState("");
  const [revisionReason, setRevisionReason] = useState("");
  const [analysisReferences, setAnalysisReferences] = useState<
    FindingAnalysisArtifactReference[]
  >([]);
  const [addressedReviewIds, setAddressedReviewIds] = useState<string[]>([]);
  const [revisionOperationId, setRevisionOperationId] = useState<string | null>(null);

  const [reviewDisposition, setReviewDisposition] =
    useState<FindingReviewDisposition>("endorse");
  const [reviewRationale, setReviewRationale] = useState("");
  const [reviewRubric, setReviewRubric] = useState<FindingReviewRubric>({
    evidenceSupport: 1,
    ordinaryAlternatives: 1,
    contradictionsPreserved: 1,
    confidenceCalibration: 1,
    reproducibility: 1,
  });
  const [reviewOperationId, setReviewOperationId] = useState<string | null>(null);
  const [blockerRationales, setBlockerRationales] = useState<Record<string, string>>({});

  const targetFindings = (snapshot?.findings ?? []).filter(
    (candidate) => candidate.findingId !== finding.findingId,
  );
  const [targetFindingId, setTargetFindingId] = useState("");
  const [targetRevision, setTargetRevision] = useState(1);
  const [relationshipType, setRelationshipType] =
    useState<FindingRelationshipType>("related_to");
  const [relationshipRationale, setRelationshipRationale] = useState("");
  const [relationshipOperationId, setRelationshipOperationId] = useState<string | null>(
    null,
  );

  const [withdrawRationale, setWithdrawRationale] = useState("");
  const [withdrawOperationId, setWithdrawOperationId] = useState<string | null>(null);

  const roomBusy = room.pendingOperationIds.length > 0;
  const connected = room.status === "connected";
  const selfParticipantId = room.selfParticipantId;
  const isCurrentRevision = inspectedRevision?.revision === finding.currentRevision;
  const canRevise =
    selfParticipantId !== null &&
    (finding.creatorParticipantId === selfParticipantId || room.isPresenter);
  const canWithdraw =
    canRevise ||
    (selfParticipantId !== null &&
      currentRevision?.authorParticipantId === selfParticipantId);
  const canCreateSupersedes =
    isCurrentRevision &&
    !["promoted", "superseded", "withdrawn"].includes(finding.lifecycleState) &&
    selfParticipantId !== null &&
    (finding.creatorParticipantId === selfParticipantId ||
      inspectedRevision?.authorParticipantId === selfParticipantId ||
      room.isPresenter);

  const unresolvedRevisionRequests = reviews.filter(
    (review) =>
      review.disposition === "request_revision" &&
      resolutionForReview(review.reviewId, reviewResolutions) === null,
  );
  const limitationItems = revisionLimitations
    .split(/\r?\n/u)
    .map((item) => item.trim())
    .filter(Boolean);
  const invalidLimitations =
    limitationItems.length > 32 ||
    limitationItems.some((item) => item.length > FINDING_LIMITATION_MAX_LENGTH);
  const invalidAnalysisReferences = analysisReferences.some(
    (reference) =>
      !reference.analysisArtifactId.trim() ||
      !reference.label.trim() ||
      (reference.artifactHash !== null &&
        !new RegExp(`^${SHA256_PATTERN}$`, "u").test(reference.artifactHash)),
  );

  const targetFinding = targetFindings.find(
    (candidate) => candidate.findingId === targetFindingId,
  ) ?? null;
  const targetRevisions = (snapshot?.findingRevisions ?? [])
    .filter((revision) => revision.findingId === targetFindingId)
    .sort((left, right) => right.revision - left.revision);

  useEffect(() => {
    setInspectedRevisionNumber(finding.currentRevision);
    setRevisionEditorOpen(false);
    setRevisionOperationId(null);
    setReviewOperationId(null);
    setRelationshipOperationId(null);
    setWithdrawOperationId(null);
  }, [finding.findingId]);

  useEffect(() => {
    if (
      inspectedRevisionNumber !== finding.currentRevision &&
      !revisions.some((revision) => revision.revision === inspectedRevisionNumber)
    ) {
      setInspectedRevisionNumber(finding.currentRevision);
    }
  }, [finding.currentRevision, inspectedRevisionNumber, revisions]);

  useEffect(() => {
    if (!targetFindings.some((candidate) => candidate.findingId === targetFindingId)) {
      setTargetFindingId(targetFindings[0]?.findingId ?? "");
    }
  }, [finding.findingId, snapshot?.findings, targetFindingId]);

  useEffect(() => {
    if (!targetFinding) return;
    if (!targetRevisions.some((revision) => revision.revision === targetRevision)) {
      setTargetRevision(targetFinding.currentRevision);
    }
  }, [targetFinding, targetRevision, targetRevisions]);

  useEffect(() => {
    if (!operationSucceeded(room, revisionOperationId)) return;
    setRevisionOperationId(null);
    setRevisionEditorOpen(false);
    setInspectedRevisionNumber(finding.currentRevision);
  }, [finding.currentRevision, revisionOperationId, room.operationFeedback]);

  useEffect(() => {
    if (!operationSucceeded(room, reviewOperationId)) return;
    setReviewOperationId(null);
    setReviewRationale("");
  }, [reviewOperationId, room.operationFeedback]);

  useEffect(() => {
    if (!operationSucceeded(room, relationshipOperationId)) return;
    setRelationshipOperationId(null);
    setRelationshipRationale("");
  }, [relationshipOperationId, room.operationFeedback]);

  useEffect(() => {
    if (!operationSucceeded(room, withdrawOperationId)) return;
    setWithdrawOperationId(null);
    setWithdrawRationale("");
  }, [room.operationFeedback, withdrawOperationId]);

  if (!currentRevision || !inspectedRevision) {
    return (
      <section className="finding-review-panel" aria-live="polite">
        <h4>Finding review unavailable</h4>
        <p>The immutable revision history has not synchronized yet.</p>
      </section>
    );
  }

  const beginRevision = () => {
    setRevisionStatement(currentRevision.statement);
    setRevisionInterpretation(currentRevision.interpretation ?? "");
    setRevisionLimitations(currentRevision.limitations.join("\n"));
    setRevisionReason("");
    setAnalysisReferences(
      currentRevision.analysisArtifactReferences.map((reference) => ({ ...reference })),
    );
    setAddressedReviewIds([]);
    setRevisionEditorOpen(true);
  };

  const submitRevision = () => {
    const operationId = room.reviseFinding(
      finding.findingId,
      finding.currentRevision,
      {
        statement: revisionStatement.trim(),
        interpretation: revisionInterpretation.trim() || null,
        limitations: limitationItems,
        evidenceReferences: currentRevision.evidenceReferences.map((reference) => ({
          ...reference,
        })),
        analysisArtifactReferences: analysisReferences.map((reference) => ({
          ...reference,
          analysisJobId: reference.analysisJobId?.trim() || null,
          analysisArtifactId: reference.analysisArtifactId.trim(),
          artifactHash: reference.artifactHash?.trim() || null,
          label: reference.label.trim(),
        })),
        revisionReason: revisionReason.trim(),
        addressedReviewIds,
      },
    );
    if (operationId) setRevisionOperationId(operationId);
  };

  const submitReview = () => {
    const operationId = room.submitFindingReview(
      finding.findingId,
      inspectedRevision.revision,
      reviewDisposition,
      reviewRationale.trim(),
      reviewRubric,
    );
    if (operationId) setReviewOperationId(operationId);
  };

  const submitRelationship = () => {
    if (!targetFinding) return;
    const operationId = room.createFindingRelationship(
      finding.findingId,
      inspectedRevision.revision,
      targetFinding.findingId,
      targetRevision,
      relationshipType,
      relationshipRationale.trim() || null,
    );
    if (operationId) setRelationshipOperationId(operationId);
  };

  const submitWithdraw = () => {
    const operationId = room.withdrawFinding(
      finding.findingId,
      finding.currentRevision,
      withdrawRationale.trim(),
    );
    if (operationId) setWithdrawOperationId(operationId);
  };

  const reviewableLifecycle = [
    "under_review",
    "reviewed",
    "challenged",
    "revision_requested",
  ].includes(finding.lifecycleState);

  return (
    <section
      className="finding-review-panel"
      aria-labelledby={`${formPrefix}-review-heading`}
    >
      <div className="finding-review-heading">
        <div>
          <p className="eyebrow">Phase 4C immutable review record</p>
          <h4 id={`${formPrefix}-review-heading`}>{finding.title || "Untitled finding"}</h4>
        </div>
        <div className="finding-state-badges" aria-label="Finding state">
          <span className={`lifecycle-badge ${finding.lifecycleState}`}>
            {humanize(finding.lifecycleState)}
          </span>
          <span className="revision-badge">current revision {finding.currentRevision}</span>
        </div>
      </div>

      <div className="revision-browser">
        <h5>Revision history</h5>
        <div className="revision-tabs" role="group" aria-label="Inspect finding revision">
          {revisions.map((revision) => (
            <button
              key={revision.revision}
              type="button"
              aria-pressed={revision.revision === inspectedRevision.revision}
              aria-label={revisionLabel(revision, finding.currentRevision)}
              onClick={() => setInspectedRevisionNumber(revision.revision)}
            >
              <strong>r{revision.revision}</strong>
              <span>
                {revision.revision === finding.currentRevision ? "current" : "historical"}
              </span>
              <small>{humanize(revision.lifecycleState)}</small>
            </button>
          ))}
        </div>
      </div>

      <article className="revision-detail" aria-labelledby={`${formPrefix}-revision-heading`}>
        <div className="finding-subheading">
          <div>
            <p className="eyebrow">
              {inspectedRevision.revision === finding.currentRevision
                ? "Current immutable revision"
                : "Historical immutable revision"}
            </p>
            <h5 id={`${formPrefix}-revision-heading`}>
              Revision {inspectedRevision.revision}: {inspectedRevision.statement}
            </h5>
          </div>
          <span className={`lifecycle-badge ${inspectedRevision.lifecycleState}`}>
            {humanize(inspectedRevision.lifecycleState)}
          </span>
        </div>
        <dl className="revision-metadata">
          <div>
            <dt>Author</dt>
            <dd>{inspectedRevision.authorDisplayName}</dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>{dateLabel(inspectedRevision.createdAt)}</dd>
          </div>
          <div>
            <dt>Previous</dt>
            <dd>
              {inspectedRevision.previousRevision === null
                ? "initial revision"
                : `revision ${inspectedRevision.previousRevision}`}
            </dd>
          </div>
          <div>
            <dt>Reason</dt>
            <dd>{inspectedRevision.revisionReason}</dd>
          </div>
        </dl>
        {inspectedRevision.interpretation ? (
          <p className="revision-interpretation">
            <strong>Interpretation.</strong> {inspectedRevision.interpretation}
          </p>
        ) : (
          <p className="revision-unavailable">Interpretation unavailable.</p>
        )}
        <div className="revision-reference-grid">
          <section aria-labelledby={`${formPrefix}-limitations-heading`}>
            <h6 id={`${formPrefix}-limitations-heading`}>Limitations</h6>
            {inspectedRevision.limitations.length > 0 ? (
              <ul>
                {inspectedRevision.limitations.map((limitation, index) => (
                  <li key={`${index}-${limitation}`}>{limitation}</li>
                ))}
              </ul>
            ) : (
              <p>None supplied.</p>
            )}
          </section>
          <section aria-labelledby={`${formPrefix}-evidence-heading`}>
            <h6 id={`${formPrefix}-evidence-heading`}>Evidence references</h6>
            {inspectedRevision.evidenceReferences.length > 0 ? (
              <ul>
                {inspectedRevision.evidenceReferences.map((reference) => (
                  <li key={reference.referenceId}>
                    <strong>{reference.label}</strong>
                    <span>
                      {humanize(reference.sourceType)} · {humanize(reference.availability)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>Unavailable; no evidence reference was supplied.</p>
            )}
          </section>
          <section aria-labelledby={`${formPrefix}-analysis-heading`}>
            <h6 id={`${formPrefix}-analysis-heading`}>Milestone 6J analysis artifacts</h6>
            {inspectedRevision.analysisArtifactReferences.length > 0 ? (
              <ul>
                {inspectedRevision.analysisArtifactReferences.map((reference) => (
                  <li key={reference.referenceId}>
                    <strong>{reference.label}</strong>
                    <span>
                      {reference.analysisArtifactId} · {humanize(reference.availability)}
                    </span>
                    <small>
                      Analysis job {reference.analysisJobId ?? "unavailable"}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p>Unavailable; no analysis artifact reference was supplied.</p>
            )}
          </section>
        </div>
        <div className="revision-actions">
          <button
            type="button"
            onClick={() => onOpenFinding(finding)}
            disabled={!room.canControlSharedState}
            aria-describedby={`${formPrefix}-open-evidence-help`}
          >
            Open stored evidence in shared view
          </button>
          <span id={`${formPrefix}-open-evidence-help`}>
            {room.canControlSharedState
              ? "This explicitly synchronizes the finding’s Activity selection and layers."
              : "The current presenter controls the shared scientific view."}
          </span>
          {isCurrentRevision ? (
            <button
              type="button"
              onClick={beginRevision}
              disabled={!connected || roomBusy || !canRevise}
            >
              Create new immutable revision
            </button>
          ) : null}
        </div>
      </article>

      {revisionEditorOpen ? (
        <form
          className="phase4c-form revision-editor"
          onSubmit={(event) => {
            event.preventDefault();
            submitRevision();
          }}
        >
          <div className="finding-subheading">
            <div>
              <p className="eyebrow">Preserves revision {finding.currentRevision}</p>
              <h5>Create revision {finding.currentRevision + 1}</h5>
            </div>
            <button type="button" onClick={() => setRevisionEditorOpen(false)}>
              Cancel
            </button>
          </div>
          <label>
            <span>Statement</span>
            <input
              required
              value={revisionStatement}
              maxLength={FINDING_STATEMENT_MAX_LENGTH}
              onChange={(event) => setRevisionStatement(event.target.value)}
            />
          </label>
          <label>
            <span>Interpretation</span>
            <textarea
              value={revisionInterpretation}
              maxLength={FINDING_INTERPRETATION_MAX_LENGTH}
              rows={5}
              onChange={(event) => setRevisionInterpretation(event.target.value)}
            />
          </label>
          <label>
            <span>Limitations, one per line</span>
            <textarea
              value={revisionLimitations}
              rows={4}
              aria-describedby={`${formPrefix}-limitations-help`}
              onChange={(event) => setRevisionLimitations(event.target.value)}
            />
          </label>
          <small id={`${formPrefix}-limitations-help`}>
            Up to 32 limitations; each may contain {FINDING_LIMITATION_MAX_LENGTH} characters.
            {invalidLimitations ? " The current limitations exceed those limits." : ""}
          </small>
          <label>
            <span>Revision reason</span>
            <textarea
              required
              value={revisionReason}
              maxLength={FINDING_REVISION_REASON_MAX_LENGTH}
              rows={3}
              onChange={(event) => setRevisionReason(event.target.value)}
            />
          </label>

          {unresolvedRevisionRequests.length > 0 ? (
            <fieldset className="addressed-reviews">
              <legend>Revision requests explicitly addressed</legend>
              {unresolvedRevisionRequests.map((review) => (
                <label key={review.reviewId}>
                  <input
                    type="checkbox"
                    checked={addressedReviewIds.includes(review.reviewId)}
                    onChange={(event) =>
                      setAddressedReviewIds((current) =>
                        event.target.checked
                          ? [...current, review.reviewId]
                          : current.filter((reviewId) => reviewId !== review.reviewId),
                      )
                    }
                  />
                  <span>
                    Revision {review.findingRevision}, requested by{" "}
                    {review.reviewerDisplayName}
                    {review.rationale ? `: ${review.rationale}` : ""}
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}

          <fieldset className="analysis-reference-editor">
            <legend>Explicit Milestone 6J analysis-artifact references</legend>
            {analysisReferences.length === 0 ? (
              <p>
                No explicit analysis artifact is supplied. Missing analysis provenance will remain
                unavailable and will not be fabricated.
              </p>
            ) : null}
            {analysisReferences.map((reference, index) => (
              <div className="analysis-reference-row" key={reference.referenceId}>
                <div className="finding-subheading">
                  <strong>Analysis reference {index + 1}</strong>
                  <button
                    type="button"
                    onClick={() =>
                      setAnalysisReferences((current) =>
                        current.filter(
                          (candidate) => candidate.referenceId !== reference.referenceId,
                        ),
                      )
                    }
                  >
                    Remove
                  </button>
                </div>
                <label>
                  <span>Analysis artifact ID</span>
                  <input
                    required
                    pattern={SAFE_IDENTIFIER_PATTERN}
                    value={reference.analysisArtifactId}
                    onChange={(event) =>
                      setAnalysisReferences((current) =>
                        current.map((candidate) =>
                          candidate.referenceId === reference.referenceId
                            ? { ...candidate, analysisArtifactId: event.target.value }
                            : candidate,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  <span>Analysis job ID, when available</span>
                  <input
                    pattern={SAFE_IDENTIFIER_PATTERN}
                    value={reference.analysisJobId ?? ""}
                    onChange={(event) =>
                      setAnalysisReferences((current) =>
                        current.map((candidate) =>
                          candidate.referenceId === reference.referenceId
                            ? { ...candidate, analysisJobId: event.target.value || null }
                            : candidate,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  <span>Artifact SHA-256, when available</span>
                  <input
                    pattern={SHA256_PATTERN}
                    value={reference.artifactHash ?? ""}
                    onChange={(event) =>
                      setAnalysisReferences((current) =>
                        current.map((candidate) =>
                          candidate.referenceId === reference.referenceId
                            ? { ...candidate, artifactHash: event.target.value || null }
                            : candidate,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  <span>Public label</span>
                  <input
                    required
                    maxLength={REFERENCE_LABEL_MAX_LENGTH}
                    value={reference.label}
                    onChange={(event) =>
                      setAnalysisReferences((current) =>
                        current.map((candidate) =>
                          candidate.referenceId === reference.referenceId
                            ? { ...candidate, label: event.target.value }
                            : candidate,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  <span>Availability</span>
                  <select
                    value={reference.availability}
                    onChange={(event) =>
                      setAnalysisReferences((current) =>
                        current.map((candidate) =>
                          candidate.referenceId === reference.referenceId
                            ? {
                                ...candidate,
                                availability: event.target.value as ProvenanceAvailability,
                              }
                            : candidate,
                        ),
                      )
                    }
                  >
                    <option value="available">Available</option>
                    <option value="incomplete">Incomplete</option>
                    <option value="unavailable">Unavailable</option>
                  </select>
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={reference.publicSafe}
                    onChange={(event) =>
                      setAnalysisReferences((current) =>
                        current.map((candidate) =>
                          candidate.referenceId === reference.referenceId
                            ? { ...candidate, publicSafe: event.target.checked }
                            : candidate,
                        ),
                      )
                    }
                  />
                  <span>Validated as safe for a promoted public conclusion</span>
                </label>
              </div>
            ))}
            <button
              type="button"
              onClick={() =>
                setAnalysisReferences((current) => [...current, newAnalysisReference()])
              }
            >
              Add analysis artifact reference
            </button>
          </fieldset>

          <div className="form-actions">
            <button
              type="submit"
              disabled={
                !connected ||
                roomBusy ||
                !revisionStatement.trim() ||
                !revisionReason.trim() ||
                invalidLimitations ||
                invalidAnalysisReferences
              }
            >
              Create revision {finding.currentRevision + 1}
            </button>
            <span>Endorsements and promotion eligibility do not carry into a new revision.</span>
          </div>
        </form>
      ) : null}

      <section className="review-action-panel" aria-labelledby={`${formPrefix}-review-action-heading`}>
        <div className="finding-subheading">
          <div>
            <p className="eyebrow">Exact-revision peer review</p>
            <h5 id={`${formPrefix}-review-action-heading`}>
              Review revision {inspectedRevision.revision}
            </h5>
          </div>
          {isCurrentRevision && finding.lifecycleState === "draft" ? (
            <button
              type="button"
              disabled={!connected || roomBusy}
              onClick={() =>
                setReviewOperationId(
                  room.startFindingReview(finding.findingId, inspectedRevision.revision),
                )
              }
            >
              Start review
            </button>
          ) : null}
        </div>
        {!isCurrentRevision ? (
          <p className="revision-unavailable">
            This revision is historical. Its reviews remain visible, but new reviews must target
            the exact current revision.
          </p>
        ) : reviewableLifecycle ? (
          <form
            className="phase4c-form"
            onSubmit={(event) => {
              event.preventDefault();
              submitReview();
            }}
          >
            <fieldset className="review-dispositions">
              <legend>Disposition for revision {inspectedRevision.revision}</legend>
              {FINDING_REVIEW_DISPOSITIONS.map((disposition) => (
                <label key={disposition}>
                  <input
                    type="radio"
                    name={`${formPrefix}-review-disposition`}
                    value={disposition}
                    checked={reviewDisposition === disposition}
                    onChange={() => setReviewDisposition(disposition)}
                  />
                  <span>{humanize(disposition)}</span>
                </label>
              ))}
            </fieldset>
            <label>
              <span>Review rationale</span>
              <textarea
                required
                value={reviewRationale}
                maxLength={REVIEW_RATIONALE_MAX_LENGTH}
                rows={3}
                onChange={(event) => setReviewRationale(event.target.value)}
              />
            </label>
            <fieldset className="review-rubric">
              <legend>Peer rubric — score each dimension from 0 to 2</legend>
              {([
                ["evidenceSupport", "Evidence supports the stated claim"],
                ["ordinaryAlternatives", "Ordinary alternatives received fair testing"],
                ["contradictionsPreserved", "Contradictions and missing information were preserved"],
                ["confidenceCalibration", "Confidence matches uncertainty and limitations"],
                ["reproducibility", "Another investigator could reproduce or extend the work"],
              ] as const).map(([key, label]) => (
                <label key={key}>
                  <span>{label}</span>
                  <select
                    value={reviewRubric[key]}
                    onChange={(event) =>
                      setReviewRubric((current) => ({
                        ...current,
                        [key]: Number(event.target.value),
                      }))
                    }
                  >
                    <option value={0}>0 — not demonstrated</option>
                    <option value={1}>1 — partly demonstrated</option>
                    <option value={2}>2 — clearly demonstrated</option>
                  </select>
                </label>
              ))}
            </fieldset>
            {inspectedRevision.authorParticipantId === selfParticipantId ? (
              <p className="self-review-note">
                You authored this revision, so the immutable review service will not accept your
                submission.
              </p>
            ) : null}
            <button
              type="submit"
              disabled={
                !connected ||
                roomBusy ||
                !reviewRationale.trim() ||
                inspectedRevision.authorParticipantId === selfParticipantId
              }
            >
              Submit {humanize(reviewDisposition)} for revision {inspectedRevision.revision}
            </button>
          </form>
        ) : (
          <p className="revision-unavailable">
            This lifecycle state does not accept new reviews.
          </p>
        )}
      </section>

      <section className="reviews-by-revision" aria-labelledby={`${formPrefix}-reviews-heading`}>
        <h5 id={`${formPrefix}-reviews-heading`}>Reviews grouped by exact revision</h5>
        {revisions.map((revision) => {
          const exactReviews = reviews.filter(
            (review) => review.findingRevision === revision.revision,
          );
          return (
            <section
              className="review-revision-group"
              key={revision.revision}
              aria-labelledby={`${formPrefix}-reviews-r${revision.revision}`}
            >
              <div className="finding-subheading">
                <h6 id={`${formPrefix}-reviews-r${revision.revision}`}>
                  Revision {revision.revision}
                </h6>
                <span>
                  {revision.revision === finding.currentRevision ? "current" : "historical"} ·{" "}
                  {exactReviews.length} review{exactReviews.length === 1 ? "" : "s"}
                </span>
              </div>
              {exactReviews.length === 0 ? (
                <p>No reviews recorded for this revision.</p>
              ) : (
                <ul className="review-list">
                  {exactReviews.map((review) => {
                    const resolution = resolutionForReview(
                      review.reviewId,
                      reviewResolutions,
                    );
                    const isBlocker = review.disposition !== "endorse";
                    const isReviewer =
                      review.reviewerParticipantId === selfParticipantId;
                    const canResolve =
                      isReviewer ||
                      (room.isPresenter &&
                        revision.authorParticipantId !== selfParticipantId);
                    const rationaleId = `${formPrefix}-${review.reviewId}-resolution`;
                    return (
                      <li key={review.reviewId}>
                        <article>
                          <div className="review-summary">
                            <span className={`review-disposition ${review.disposition}`}>
                              {humanize(review.disposition)}
                            </span>
                            <strong>{review.reviewerDisplayName}</strong>
                            <time dateTime={review.createdAt}>{dateLabel(review.createdAt)}</time>
                          </div>
                          {review.rationale ? <p>{review.rationale}</p> : <p>No rationale supplied.</p>}
                          {review.rubric ? (
                            <dl className="recorded-rubric">
                              <div><dt>Evidence</dt><dd>{review.rubric.evidenceSupport}/2</dd></div>
                              <div><dt>Alternatives</dt><dd>{review.rubric.ordinaryAlternatives}/2</dd></div>
                              <div><dt>Contradictions</dt><dd>{review.rubric.contradictionsPreserved}/2</dd></div>
                              <div><dt>Confidence</dt><dd>{review.rubric.confidenceCalibration}/2</dd></div>
                              <div><dt>Reproducibility</dt><dd>{review.rubric.reproducibility}/2</dd></div>
                            </dl>
                          ) : (
                            <small>Legacy review: no quality rubric was recorded.</small>
                          )}
                          {resolution ? (
                            <div className="review-resolution">
                              <strong>{humanize(resolution.status)}</strong>
                              <span>{resolution.rationale}</span>
                              <small>
                                Recorded by {resolution.resolverDisplayName} on{" "}
                                {dateLabel(resolution.createdAt)}
                              </small>
                            </div>
                          ) : isBlocker ? (
                            <div className="blocker-resolution-form">
                              <label htmlFor={rationaleId}>Resolution rationale</label>
                              <textarea
                                id={rationaleId}
                                required
                                maxLength={REVIEW_RATIONALE_MAX_LENGTH}
                                rows={2}
                                value={blockerRationales[review.reviewId] ?? ""}
                                onChange={(event) =>
                                  setBlockerRationales((current) => ({
                                    ...current,
                                    [review.reviewId]: event.target.value,
                                  }))
                                }
                              />
                              <div className="form-actions">
                                {canResolve ? (
                                  <button
                                    type="button"
                                    disabled={
                                      !connected ||
                                      roomBusy ||
                                      !(blockerRationales[review.reviewId] ?? "").trim()
                                    }
                                    onClick={() =>
                                      room.resolveFindingReview(
                                        review.findingId,
                                        review.findingRevision,
                                        review.reviewId,
                                        "resolve",
                                        (blockerRationales[review.reviewId] ?? "").trim(),
                                      )
                                    }
                                  >
                                    Resolve blocker
                                  </button>
                                ) : null}
                                {isReviewer ? (
                                  <button
                                    type="button"
                                    disabled={
                                      !connected ||
                                      roomBusy ||
                                      !(blockerRationales[review.reviewId] ?? "").trim()
                                    }
                                    onClick={() =>
                                      room.resolveFindingReview(
                                        review.findingId,
                                        review.findingRevision,
                                        review.reviewId,
                                        "withdraw",
                                        (blockerRationales[review.reviewId] ?? "").trim(),
                                      )
                                    }
                                  >
                                    Withdraw my blocker
                                  </button>
                                ) : null}
                                {!canResolve && !isReviewer ? (
                                  <span>
                                    Only its reviewer or an independent current presenter may
                                    resolve this blocker.
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          ) : null}
                        </article>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          );
        })}
      </section>

      <section className="relationship-panel" aria-labelledby={`${formPrefix}-relationships-heading`}>
        <h5 id={`${formPrefix}-relationships-heading`}>Typed finding relationships</h5>
        <form
          className="phase4c-form relationship-form"
          onSubmit={(event) => {
            event.preventDefault();
            submitRelationship();
          }}
        >
          <p>
            Source: this finding, exact revision {inspectedRevision.revision}.
          </p>
          <label>
            <span>Relationship type</span>
            <select
              value={relationshipType}
              onChange={(event) =>
                setRelationshipType(event.target.value as FindingRelationshipType)
              }
            >
              {FINDING_RELATIONSHIP_TYPES.map((type) => (
                <option value={type} key={type}>{humanize(type)}</option>
              ))}
            </select>
          </label>
          {relationshipType === "supersedes" && !canCreateSupersedes ? (
            <p className="revision-unavailable">
              Superseding requires this exact source revision to be current and active, and
              must be created by its creator, revision author, or presenter before promotion.
            </p>
          ) : null}
          <label>
            <span>Target finding</span>
            <select
              required
              value={targetFindingId}
              disabled={targetFindings.length === 0}
              onChange={(event) => setTargetFindingId(event.target.value)}
            >
              {targetFindings.length === 0 ? (
                <option value="">No other finding is available</option>
              ) : null}
              {targetFindings.map((candidate) => (
                <option value={candidate.findingId} key={candidate.findingId}>
                  {candidate.title} · current r{candidate.currentRevision}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Exact target revision</span>
            <select
              required
              value={targetRevision}
              disabled={targetRevisions.length === 0}
              onChange={(event) => setTargetRevision(Number(event.target.value))}
            >
              {targetRevisions.map((revision) => (
                <option value={revision.revision} key={revision.revision}>
                  revision {revision.revision} · {humanize(revision.lifecycleState)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Relationship rationale, optional</span>
            <textarea
              value={relationshipRationale}
              maxLength={RELATIONSHIP_RATIONALE_MAX_LENGTH}
              rows={2}
              onChange={(event) => setRelationshipRationale(event.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={
              !connected ||
              roomBusy ||
              !targetFinding ||
              !inspectedRevision ||
              (relationshipType === "supersedes" && !canCreateSupersedes)
            }
          >
            Link exact revisions
          </button>
        </form>
        {relationships.length > 0 ? (
          <ul className="relationship-list">
            {relationships.map((relationship) => {
              const outgoing = relationship.sourceFindingId === finding.findingId;
              const otherFindingId = outgoing
                ? relationship.targetFindingId
                : relationship.sourceFindingId;
              const otherRevision = outgoing
                ? relationship.targetRevision
                : relationship.sourceRevision;
              const otherFinding = snapshot?.findings.find(
                (candidate) => candidate.findingId === otherFindingId,
              );
              return (
                <li key={relationship.relationshipId}>
                  <strong>{humanize(relationship.relationshipType)}</strong>
                  <span>
                    {outgoing ? "to" : "from"} {otherFinding?.title ?? "Unavailable finding"}{" "}
                    revision {otherRevision}
                  </span>
                  <small>
                    Exact source r{relationship.sourceRevision} → target r
                    {relationship.targetRevision}
                  </small>
                  {relationship.rationale ? <p>{relationship.rationale}</p> : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p>No typed relationships have been recorded for this finding.</p>
        )}
      </section>

      <section className="promotion-panel" aria-labelledby={`${formPrefix}-promotion-heading`}>
        <div className="finding-subheading">
          <div>
            <p className="eyebrow">Deterministic exact-revision policy</p>
            <h5 id={`${formPrefix}-promotion-heading`}>Promotion eligibility</h5>
          </div>
          {assessment ? (
            <span className={`eligibility-badge ${assessment.eligible ? "eligible" : "blocked"}`}>
              {assessment.eligible ? "eligible" : "blocked"}
            </span>
          ) : null}
        </div>
        {!isCurrentRevision ? (
          <p>Historical revisions cannot be promoted.</p>
        ) : assessment ? (
          <>
            <ul
              className="promotion-checklist"
              id={`${formPrefix}-promotion-blockers`}
            >
              {assessment.checks.map((check) => (
                <li className={check.satisfied ? "satisfied" : "blocked"} key={check.code}>
                  <span aria-hidden="true">{check.satisfied ? "✓" : "×"}</span>
                  <div>
                    <strong>{humanize(check.code)}</strong>
                    <p>{check.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
            {!conclusion ? (
              <button
                type="button"
                disabled={!connected || roomBusy || !assessment.eligible}
                aria-describedby={`${formPrefix}-promotion-blockers`}
                onClick={() =>
                  room.promoteFinding(finding.findingId, finding.currentRevision)
                }
              >
                Promote revision {finding.currentRevision}
              </button>
            ) : null}
          </>
        ) : (
          <p>Promotion assessment unavailable; wait for the room state to synchronize.</p>
        )}
      </section>

      {conclusion ? <ConclusionCard conclusion={conclusion} /> : null}

      {isCurrentRevision && finding.lifecycleState !== "withdrawn" ? (
        <details className="withdraw-panel">
          <summary>Withdraw finding while preserving provenance</summary>
          <form
            className="phase4c-form"
            onSubmit={(event) => {
              event.preventDefault();
              submitWithdraw();
            }}
          >
            <label>
              <span>Withdrawal rationale</span>
              <textarea
                required
                value={withdrawRationale}
                maxLength={FINDING_REVISION_REASON_MAX_LENGTH}
                rows={3}
                onChange={(event) => setWithdrawRationale(event.target.value)}
              />
            </label>
            <button
              type="submit"
              disabled={
                !connected || roomBusy || !canWithdraw || !withdrawRationale.trim()
              }
            >
              Withdraw current revision
            </button>
            {!canWithdraw ? (
              <p>Only the finding creator, current revision author, or presenter may withdraw it.</p>
            ) : null}
          </form>
        </details>
      ) : null}
    </section>
  );
}
