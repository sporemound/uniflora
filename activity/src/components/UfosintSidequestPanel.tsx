import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  applyUfosintSidequestAction,
  createUfosintSidequest,
  loadUfosintSidequest,
  loadUfosintSidequestArtifactContent,
  UfosintSidequestApiError,
  type UfosintSidequestAction,
} from "../lib/ufosint-sidequests";
import type { PublicReportRecord } from "../shared/external-map-layers";
import {
  DYNAMICAL_DATASETS,
  planDynamicalEvidence,
} from "../shared/dynamical-data";
import {
  FINDING_REVIEW_DISPOSITIONS,
  type FindingReviewDisposition,
  type FindingReviewRubric,
} from "../shared/finding-review";
import {
  UFOSINT_ARTIFACT_KINDS,
  UFOSINT_FINDING_CONFIDENCE,
  UFOSINT_FINDING_KINDS,
  UFOSINT_PROVENANCE_PARENT_TYPES,
  UFOSINT_PROVENANCE_RELATIONS,
  UFOSINT_SIDEQUEST_LIFECYCLES,
  UFOSINT_SIDEQUEST_LIMITS,
  UFOSINT_SIDEQUEST_TASK_STATUSES,
  UFOSINT_SIDEQUEST_TASK_STATUS_LABELS,
  canTransitionUfosintSidequest,
  canTransitionUfosintTask,
  deriveUfosintFindingReviewState,
  parseUfosintFindingRevision,
  parseUfosintSidequestArtifact,
  parseUfosintSidequestReview,
  type UfosintActor,
  type UfosintArtifactKind,
  type UfosintArtifactScalar,
  type UfosintFindingConfidence,
  type UfosintFindingKind,
  type UfosintNamedValue,
  type UfosintProvenanceParentType,
  type UfosintProvenanceRelation,
  type UfosintSidequestArtifact,
  type UfosintSidequestFindingRevision,
  type UfosintSidequestReview,
  type UfosintSidequestSnapshot,
  type UfosintSidequestTask,
  type UfosintSidequestTaskStatus,
  type UfosintSoftwareVersion,
} from "../shared/ufosint-sidequest";

export interface UfosintSidequestPanelProps {
  reportId: string;
  report?: PublicReportRecord | null;
  sessionToken: string | null;
  participant?: UfosintActor | null;
  open?: boolean;
  presentation?: "dialog" | "drawer" | "inline";
  onClose?: () => void;
  onSnapshotChange?: (snapshot: UfosintSidequestSnapshot | null) => void;
}

type FindingInput = Omit<UfosintSidequestFindingRevision, "author" | "createdAt">;
type ReviewInput = Omit<UfosintSidequestReview, "reviewer" | "createdAt">;
type ArtifactInput = Omit<UfosintSidequestArtifact, "createdBy" | "createdAt">;

const CLIENT_VALIDATION_ACTOR: UfosintActor = {
  participantId: "client-validation",
  displayName: "Client validation",
};

const RUBRIC_FIELDS: readonly {
  key: keyof FindingReviewRubric;
  label: string;
}[] = [
  { key: "evidenceSupport", label: "Evidence support" },
  { key: "ordinaryAlternatives", label: "Ordinary alternatives considered" },
  { key: "contradictionsPreserved", label: "Contradictions preserved" },
  { key: "confidenceCalibration", label: "Confidence calibration" },
  { key: "reproducibility", label: "Reproducibility" },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The UFOSINT sidequest request failed.";
}

function lines(value: string): string[] {
  return value
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .filter(Boolean);
}

function optionalText(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

function newId(): string {
  return globalThis.crypto.randomUUID();
}

function encodeBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 32_768;
  for (let offset = 0; offset < bytes.byteLength; offset += chunkSize) {
    binary += String.fromCharCode(
      ...bytes.subarray(offset, offset + chunkSize),
    );
  }
  return btoa(binary);
}

interface PreparedArtifactFile {
  name: string;
  contentBase64: string;
  contentSha256: string;
  byteLength: number;
}

async function prepareArtifactFile(file: File): Promise<PreparedArtifactFile> {
  if (file.size > UFOSINT_SIDEQUEST_LIMITS.artifactContentBytes) {
    throw new Error(
      `Artifact files are limited to ${UFOSINT_SIDEQUEST_LIMITS.artifactContentBytes.toLocaleString()} bytes.`,
    );
  }
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", buffer));
  return {
    name: file.name,
    contentBase64: encodeBase64(bytes),
    contentSha256: [...digest]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join(""),
    byteLength: bytes.byteLength,
  };
}

function dateOnly(value: string): string {
  return value.slice(0, 10);
}

function displayTimestamp(value: string | null): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isFinite(parsed.valueOf()) ? parsed.toLocaleString() : value;
}

function lifecycleLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function isEligibleReport(report: PublicReportRecord): boolean {
  return (
    report.sourceKey === "ufosint" &&
    report.status === "unverified" &&
    report.reportClass === "current-index" &&
    report.indexedAt !== null &&
    Number.isInteger(report.qualityScore) &&
    report.qualityScore >= 51 &&
    report.qualityScore <= 100
  );
}
function latestFindingRevisions(
  findings: readonly UfosintSidequestFindingRevision[],
): UfosintSidequestFindingRevision[] {
  const latest = new Map<string, UfosintSidequestFindingRevision>();
  for (const finding of findings) {
    const current = latest.get(finding.findingId);
    if (!current || finding.revision > current.revision) latest.set(finding.findingId, finding);
  }
  return [...latest.values()].sort((left, right) =>
    right.createdAt.localeCompare(left.createdAt),
  );
}

function parseScalar(value: string): UfosintArtifactScalar {
  const normalized = value.trim();
  if (normalized === "null") return null;
  if (normalized === "true") return true;
  if (normalized === "false") return false;
  if (/^-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/iu.test(normalized)) {
    return Number(normalized);
  }
  return normalized;
}

function namedValues(value: string): UfosintNamedValue[] {
  return lines(value).map((line, index) => {
    const [name = "", rawValue = "", unit = "", uncertainty = ""] = line
      .split("|")
      .map((part) => part.trim());
    if (!name || !rawValue) {
      throw new Error(`Named value line ${index + 1} needs at least name | value.`);
    }
    return {
      name,
      value: parseScalar(rawValue),
      unit: optionalText(unit),
      uncertainty: optionalText(uncertainty),
    };
  });
}

function softwareVersions(value: string): UfosintSoftwareVersion[] {
  return lines(value).map((line, index) => {
    const [name = "", version = ""] = line.split("|").map((part) => part.trim());
    if (!name || !version) {
      throw new Error(`Software line ${index + 1} needs name | version.`);
    }
    return { name, version };
  });
}

function withoutArtifactAuditFields(
  artifact: UfosintSidequestArtifact,
): ArtifactInput {
  const { createdBy: _createdBy, createdAt: _createdAt, ...input } = artifact;
  return input;
}

function withoutFindingAuditFields(
  finding: UfosintSidequestFindingRevision,
): FindingInput {
  const { author: _author, createdAt: _createdAt, ...input } = finding;
  return input;
}

function withoutReviewAuditFields(review: UfosintSidequestReview): ReviewInput {
  const { reviewer: _reviewer, createdAt: _createdAt, ...input } = review;
  return input;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `ufosint-${title.toLowerCase().replace(/[^a-z0-9]+/gu, "-")}`;
  return (
    <section className="ufosint-sidequest-section" aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {children}
    </section>
  );
}

function TaskEditor({
  task,
  participant,
  disabled,
  onUpdate,
}: {
  task: UfosintSidequestTask;
  participant: UfosintActor | null;
  disabled: boolean;
  onUpdate: (
    status: UfosintSidequestTaskStatus,
    assignee: UfosintActor | null,
    note: string | null,
  ) => Promise<boolean>;
}) {
  const [note, setNote] = useState(task.completionNote ?? "");
  const normalizedNote = optionalText(note);
  const noteChanged = normalizedNote !== task.completionNote;
  const legalStatuses = UFOSINT_SIDEQUEST_TASK_STATUSES.filter(
    (status) => status !== task.status && canTransitionUfosintTask(task.status, status),
  );

  return (
    <li className="ufosint-sidequest-task">
      <header>
        <div>
          <strong>
            {task.ordinal + 1}. {task.title}
          </strong>{" "}
          {task.required ? <span>Required</span> : <span>Optional</span>}
        </div>
        <span>{UFOSINT_SIDEQUEST_TASK_STATUS_LABELS[task.status]}</span>
      </header>
      <p>{task.instructions}</p>
      <p>
        Kind: {lifecycleLabel(task.kind)}. Assignee:{" "}
        {task.assignee?.displayName ?? "Unassigned"}. Last updated:{" "}
        {displayTimestamp(task.updatedAt)}.
      </p>
      <label>
        Completion or unavailability note
        <textarea
          value={note}
          maxLength={UFOSINT_SIDEQUEST_LIMITS.completionNote}
          rows={2}
          onChange={(event) => setNote(event.currentTarget.value)}
          disabled={disabled}
        />
      </label>
      <div className="ufosint-sidequest-actions">
        {participant && task.assignee?.participantId !== participant.participantId ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => void onUpdate(task.status, participant, optionalText(note))}
          >
            Assign to me
          </button>
        ) : null}
        {task.assignee ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              void onUpdate(
                task.status === "in_progress" ? "pending" : task.status,
                null,
                normalizedNote,
              )
            }
          >
            {task.status === "in_progress"
              ? "Return to pending and unassign"
              : "Unassign"}
          </button>
        ) : null}
        <button
          type="button"
          disabled={disabled || !noteChanged}
          onClick={() => void onUpdate(task.status, task.assignee, normalizedNote)}
        >
          Save note
        </button>
        {legalStatuses.map((status) => (
          <button
            type="button"
            key={status}
            disabled={
              disabled ||
              (["completed", "waived", "unavailable"] as string[]).includes(status) &&
                !note.trim()
            }
            title={
              (["completed", "waived", "unavailable"] as string[]).includes(status) &&
              !note.trim()
                ? "Add an audit note before marking this task."
                : undefined
            }
            onClick={() => void onUpdate(status, task.assignee, normalizedNote)}
          >
            Mark {UFOSINT_SIDEQUEST_TASK_STATUS_LABELS[status].toLowerCase()}
          </button>
        ))}
      </div>
      {task.status === "unavailable" ? (
        <p>
          “Unavailable” records a missing external source; it does not imply that the
          underlying question was resolved.
        </p>
      ) : null}
    </li>
  );
}

function artifactDownloadName(artifact: UfosintSidequestArtifact): string {
  const safeTitle = artifact.title
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-")
    .replace(/[.\s]+$/g, "")
    .slice(0, 96);
  return safeTitle || `artifact-${artifact.artifactId}`;
}

function ArtifactList({
  artifacts,
  sidequestId,
  sessionToken,
}: {
  artifacts: readonly UfosintSidequestArtifact[];
  sidequestId: string;
  sessionToken: string;
}) {
  const [downloadingArtifactId, setDownloadingArtifactId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const downloadArtifact = async (artifact: UfosintSidequestArtifact) => {
    setDownloadError(null);
    setDownloadingArtifactId(artifact.artifactId);
    try {
      const blob = await loadUfosintSidequestArtifactContent(
        sidequestId,
        artifact,
        sessionToken,
      );
      const objectUrl = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = artifactDownloadName(artifact);
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        URL.revokeObjectURL(objectUrl);
      }
    } catch (error) {
      setDownloadError(errorMessage(error));
    } finally {
      setDownloadingArtifactId(null);
    }
  };

  if (artifacts.length === 0) return <p>No evidence artifacts have been attached.</p>;
  return (
    <>
      {downloadError ? <p role="alert">{downloadError}</p> : null}
      <ul className="ufosint-sidequest-artifacts">
        {artifacts.map((artifact) => (
          <li key={artifact.artifactId}>
          <details>
            <summary>
              {artifact.title} · {lifecycleLabel(artifact.kind)}
            </summary>
            <p>
              {artifact.mediaType}; {artifact.byteLength.toLocaleString()} bytes; SHA-256{" "}
              <code>{artifact.contentSha256}</code>
            </p>
            <p>
              Added by {artifact.createdBy.displayName} at {displayTimestamp(artifact.createdAt)}.
            </p>
            {artifact.artifactUri ? (
              <p>
                <a href={artifact.artifactUri} target="_blank" rel="noreferrer">
                  Open approved artifact location
                </a>
              </p>
            ) : (
              <p>No public artifact URI is recorded.</p>
            )}
            <p>
              <button
                type="button"
                disabled={downloadingArtifactId !== null}
                onClick={() => void downloadArtifact(artifact)}
              >
                {downloadingArtifactId === artifact.artifactId
                  ? "Verifying download…"
                  : "Download verified artifact"}
              </button>
            </p>
            <h4>Provenance</h4>
            <ul>
              {artifact.provenance.map((item) => (
                <li key={item.provenanceId}>
                  {lifecycleLabel(item.relation)} {lifecycleLabel(item.parentType)}:{" "}
                  <code>{item.parentReference}</code>. {item.description}
                  {item.retrievedAt ? ` Retrieved ${displayTimestamp(item.retrievedAt)}.` : ""}
                </li>
              ))}
            </ul>
            {artifact.dynamicalAnalysis ? (
              <div>
                <h4>Dynamical reproducibility contract</h4>
                <dl>
                  <dt>Model</dt>
                  <dd>
                    {artifact.dynamicalAnalysis.modelId} {artifact.dynamicalAnalysis.modelVersion}
                  </dd>
                  <dt>Implementation</dt>
                  <dd>{artifact.dynamicalAnalysis.implementation}</dd>
                  <dt>Frame / time standard</dt>
                  <dd>
                    {artifact.dynamicalAnalysis.coordinateFrame} /{" "}
                    {artifact.dynamicalAnalysis.timeStandard}
                  </dd>
                  <dt>Modeled window</dt>
                  <dd>
                    {displayTimestamp(artifact.dynamicalAnalysis.timeWindowStart)} through{" "}
                    {displayTimestamp(artifact.dynamicalAnalysis.timeWindowEnd)}
                  </dd>
                  <dt>Software</dt>
                  <dd>
                    {artifact.dynamicalAnalysis.softwareVersions
                      .map((software) => `${software.name} ${software.version}`)
                      .join(", ")}
                  </dd>
                </dl>
                <p>
                  Derived values: {artifact.dynamicalAnalysis.derivedValues
                    .map((entry) => `${entry.name}=${String(entry.value)}${entry.unit ?? ""}`)
                    .join(", ")}
                </p>
                <p>
                  Uncertainty: {artifact.dynamicalAnalysis.uncertaintyStatements.join("; ")}
                </p>
                <p>Limitations: {artifact.dynamicalAnalysis.limitations.join("; ")}</p>
              </div>
            ) : null}
          </details>
          </li>
        ))}
      </ul>
    </>
  );
}

function ArtifactForm({
  sidequest,
  participant,
  disabled,
  onAttach,
}: {
  sidequest: UfosintSidequestSnapshot;
  participant: UfosintActor | null;
  disabled: boolean;
  onAttach: (artifact: ArtifactInput, contentBase64: string) => Promise<boolean>;
}) {
  const [kind, setKind] = useState<UfosintArtifactKind>("source_capture");
  const [title, setTitle] = useState("");
  const [mediaType, setMediaType] = useState("application/json");
  const [preparedFile, setPreparedFile] = useState<PreparedArtifactFile | null>(null);
  const [fileProcessing, setFileProcessing] = useState(false);
  const [artifactUri, setArtifactUri] = useState("");
  const [parentType, setParentType] =
    useState<UfosintProvenanceParentType>("report_snapshot");
  const [parentReference, setParentReference] = useState(sidequest.reportId);
  const [parentHash, setParentHash] = useState(sidequest.reportSnapshotSha256);
  const [relation, setRelation] = useState<UfosintProvenanceRelation>("derived_from");
  const [provenanceDescription, setProvenanceDescription] = useState("");
  const [retrievedAt, setRetrievedAt] = useState("");
  const [modelId, setModelId] = useState("");
  const [modelVersion, setModelVersion] = useState("");
  const [implementation, setImplementation] = useState("");
  const [coordinateFrame, setCoordinateFrame] = useState("");
  const [timeStandard, setTimeStandard] = useState("UTC");
  const [timeWindowStart, setTimeWindowStart] = useState("");
  const [timeWindowEnd, setTimeWindowEnd] = useState("");
  const [initialConditions, setInitialConditions] = useState("");
  const [parameters, setParameters] = useState("");
  const [derivedValues, setDerivedValues] = useState("");
  const [assumptions, setAssumptions] = useState("");
  const [uncertainties, setUncertainties] = useState("");
  const [limitations, setLimitations] = useState("");
  const [software, setSoftware] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fileSelectionRevision = useRef(0);

  async function selectFile(file: File | null) {
    const revision = ++fileSelectionRevision.current;
    setPreparedFile(null);
    setLocalError(null);
    if (!file) {
      setFileProcessing(false);
      return;
    }
    setFileProcessing(true);
    try {
      const prepared = await prepareArtifactFile(file);
      if (revision !== fileSelectionRevision.current) return;
      setPreparedFile(prepared);
      if (file.type && file.type.length <= UFOSINT_SIDEQUEST_LIMITS.artifactMediaType) {
        setMediaType(file.type);
      }
      if (file.name.length <= UFOSINT_SIDEQUEST_LIMITS.title) {
        setTitle((current) => current || file.name);
      }
    } catch (error) {
      if (revision !== fileSelectionRevision.current) return;
      if (fileInputRef.current) fileInputRef.current.value = "";
      setLocalError(errorMessage(error));
    } finally {
      if (revision === fileSelectionRevision.current) {
        setFileProcessing(false);
      }
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    try {
      if (!preparedFile) {
        throw new Error("Select and prepare an artifact file before attaching it.");
      }
      const dynamicalAnalysis =
        kind === "dynamical_analysis"
          ? {
              modelId,
              modelVersion,
              implementation,
              coordinateFrame,
              timeStandard,
              timeWindowStart,
              timeWindowEnd,
              initialConditions: namedValues(initialConditions),
              parameters: namedValues(parameters),
              derivedValues: namedValues(derivedValues),
              assumptions: lines(assumptions),
              uncertaintyStatements: lines(uncertainties),
              limitations: lines(limitations),
              softwareVersions: softwareVersions(software),
            }
          : null;
      const validated = parseUfosintSidequestArtifact({
        artifactId: newId(),
        kind,
        title,
        mediaType,
        contentSha256: preparedFile.contentSha256,
        byteLength: preparedFile.byteLength,
        artifactUri: optionalText(artifactUri),
        dynamicalAnalysis,
        provenance: [
          {
            provenanceId: newId(),
            parentType,
            parentReference,
            parentContentSha256: optionalText(parentHash)?.toLowerCase() ?? null,
            relation,
            description: provenanceDescription,
            retrievedAt: optionalText(retrievedAt),
          },
        ],
        createdBy: participant ?? CLIENT_VALIDATION_ACTOR,
        createdAt: new Date().toISOString(),
      });
      if (
        await onAttach(
          withoutArtifactAuditFields(validated),
          preparedFile.contentBase64,
        )
      ) {
        setTitle("");
        setPreparedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
        setArtifactUri("");
        setProvenanceDescription("");
      }
    } catch (error) {
      setLocalError(errorMessage(error));
    }
  }

  const dynamical = kind === "dynamical_analysis";
  return (
    <form onSubmit={(event) => void submit(event)}>
      <h4>Attach artifact</h4>
      <p>
        The exact selected bytes are stored with authenticated, immutable artifact metadata.
        Files are limited to {UFOSINT_SIDEQUEST_LIMITS.artifactContentBytes.toLocaleString()} bytes.
        Do not upload witness contact data or other sensitive personal information.
      </p>
      <fieldset disabled={disabled}>
        <legend>Artifact identity</legend>
        <label>
          Kind
          <select value={kind} onChange={(event) => setKind(event.currentTarget.value as UfosintArtifactKind)}>
            {UFOSINT_ARTIFACT_KINDS.filter(
              (value) => value !== "dynamical_analysis" && value !== "weather_context",
            ).map((value) => (
              <option key={value} value={value}>{lifecycleLabel(value)}</option>
            ))}
          </select>
        </label>
        <label>
          Title
          <input value={title} maxLength={UFOSINT_SIDEQUEST_LIMITS.title} onChange={(event) => setTitle(event.currentTarget.value)} required />
        </label>
        <label>
          Media type
          <input value={mediaType} maxLength={UFOSINT_SIDEQUEST_LIMITS.artifactMediaType} onChange={(event) => setMediaType(event.currentTarget.value)} required />
        </label>
        <label>
          Exact artifact file
          <input
            ref={fileInputRef}
            type="file"
            required
            onChange={(event) =>
              void selectFile(event.currentTarget.files?.[0] ?? null)
            }
          />
        </label>
        {fileProcessing ? <p role="status">Computing exact-byte metadata…</p> : null}
        {preparedFile ? (
          <dl>
            <dt>Prepared file</dt><dd>{preparedFile.name}</dd>
            <dt>Byte length</dt><dd>{preparedFile.byteLength.toLocaleString()}</dd>
            <dt>SHA-256</dt><dd><code>{preparedFile.contentSha256}</code></dd>
          </dl>
        ) : null}
        <label>
          Approved HTTPS artifact URI (optional)
          <input type="url" value={artifactUri} maxLength={UFOSINT_SIDEQUEST_LIMITS.artifactUri} onChange={(event) => setArtifactUri(event.currentTarget.value)} />
        </label>
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>Required provenance parent</legend>
        <label>
          Parent type
          <select value={parentType} onChange={(event) => setParentType(event.currentTarget.value as UfosintProvenanceParentType)}>
            {UFOSINT_PROVENANCE_PARENT_TYPES.map((value) => (
              <option key={value} value={value}>{lifecycleLabel(value)}</option>
            ))}
          </select>
        </label>
        <label>
          Parent reference {parentType === "external_source" ? "(HTTPS URL)" : "(safe ID)"}
          <input value={parentReference} maxLength={UFOSINT_SIDEQUEST_LIMITS.artifactUri} onChange={(event) => setParentReference(event.currentTarget.value)} required />
        </label>
        <label>
          Parent SHA-256 (optional)
          <input value={parentHash} maxLength={64} pattern="[a-fA-F0-9]{64}" onChange={(event) => setParentHash(event.currentTarget.value)} />
        </label>
        <label>
          Relation
          <select value={relation} onChange={(event) => setRelation(event.currentTarget.value as UfosintProvenanceRelation)}>
            {UFOSINT_PROVENANCE_RELATIONS.map((value) => (
              <option key={value} value={value}>{lifecycleLabel(value)}</option>
            ))}
          </select>
        </label>
        <label>
          What was done to this parent?
          <textarea value={provenanceDescription} maxLength={UFOSINT_SIDEQUEST_LIMITS.provenanceDescription} onChange={(event) => setProvenanceDescription(event.currentTarget.value)} required />
        </label>
        <label>
          Retrieval time as ISO 8601 (optional)
          <input value={retrievedAt} placeholder="2026-08-02T18:30:00Z" onChange={(event) => setRetrievedAt(event.currentTarget.value)} />
        </label>
      </fieldset>
      {dynamical ? (
        <fieldset disabled={disabled}>
          <legend>Dynamical reproducibility contract</legend>
          <p>
            Do not infer an event time from the report date. Enter only a defensible modeled
            window and preserve frame, time-standard, parameter, software, and uncertainty
            choices. A trajectory match does not identify a cause.
          </p>
          <label>Model ID<input value={modelId} onChange={(event) => setModelId(event.currentTarget.value)} required /></label>
          <label>Model version<input value={modelVersion} onChange={(event) => setModelVersion(event.currentTarget.value)} required /></label>
          <label>Implementation<input value={implementation} onChange={(event) => setImplementation(event.currentTarget.value)} required /></label>
          <label>Coordinate frame<input value={coordinateFrame} onChange={(event) => setCoordinateFrame(event.currentTarget.value)} required /></label>
          <label>Time standard<input value={timeStandard} onChange={(event) => setTimeStandard(event.currentTarget.value)} required /></label>
          <label>Modeled window start (ISO 8601)<input value={timeWindowStart} placeholder="2026-08-02T00:00:00Z" onChange={(event) => setTimeWindowStart(event.currentTarget.value)} required /></label>
          <label>Modeled window end (ISO 8601)<input value={timeWindowEnd} placeholder="2026-08-03T00:00:00Z" onChange={(event) => setTimeWindowEnd(event.currentTarget.value)} required /></label>
          <label>Initial conditions, one per line: name | value | unit | uncertainty<textarea value={initialConditions} onChange={(event) => setInitialConditions(event.currentTarget.value)} /></label>
          <label>Parameters, one per line: name | value | unit | uncertainty<textarea value={parameters} onChange={(event) => setParameters(event.currentTarget.value)} /></label>
          <label>Derived values, one or more: name | value | unit | uncertainty<textarea value={derivedValues} onChange={(event) => setDerivedValues(event.currentTarget.value)} required /></label>
          <label>Assumptions, one per line<textarea value={assumptions} onChange={(event) => setAssumptions(event.currentTarget.value)} /></label>
          <label>Uncertainty statements, one or more<textarea value={uncertainties} onChange={(event) => setUncertainties(event.currentTarget.value)} required /></label>
          <label>Limitations, one or more<textarea value={limitations} onChange={(event) => setLimitations(event.currentTarget.value)} required /></label>
          <label>Software, one or more: name | version<textarea value={software} onChange={(event) => setSoftware(event.currentTarget.value)} required /></label>
        </fieldset>
      ) : null}
      {localError ? <p role="alert">{localError}</p> : null}
      <button
        type="submit"
        disabled={disabled || fileProcessing || preparedFile === null}
      >
        Attach exact file
      </button>
    </form>
  );
}

function FindingHistory({
  sidequest,
}: {
  sidequest: UfosintSidequestSnapshot;
}) {
  const latest = latestFindingRevisions(sidequest.findings);
  if (latest.length === 0) return <p>No findings have been recorded.</p>;
  return (
    <ul className="ufosint-sidequest-findings">
      {latest.map((finding) => {
        const history = sidequest.findings
          .filter((candidate) => candidate.findingId === finding.findingId)
          .sort((left, right) => right.revision - left.revision);
        const state = deriveUfosintFindingReviewState(finding, sidequest.reviews);
        return (
          <li key={finding.findingId}>
            <details>
              <summary>
                {lifecycleLabel(finding.kind)} · revision {finding.revision} · {state} ·{" "}
                {finding.confidence} confidence
              </summary>
              <p>{finding.statement}</p>
              {finding.interpretation ? <p>Interpretation: {finding.interpretation}</p> : null}
              <p>
                Author: {finding.author.displayName}; evidence links:{" "}
                {finding.evidenceReferences.length}; artifacts: {finding.artifactIds.length}.
              </p>
              {finding.limitations.length ? (
                <p>Limitations: {finding.limitations.join("; ")}</p>
              ) : (
                <p>No limitations were recorded on this revision.</p>
              )}
              <h4>Immutable revision history</h4>
              <ol>
                {history.map((revision) => (
                  <li key={revision.revision}>
                    Revision {revision.revision}, {displayTimestamp(revision.createdAt)}:{" "}
                    {revision.statement}
                  </li>
                ))}
              </ol>
            </details>
          </li>
        );
      })}
    </ul>
  );
}

function FindingForm({
  sidequest,
  disabled,
  conclusionOnly,
  onAdd,
}: {
  sidequest: UfosintSidequestSnapshot;
  disabled: boolean;
  conclusionOnly: boolean;
  onAdd: (finding: FindingInput) => Promise<boolean>;
}) {
  const candidates = latestFindingRevisions(sidequest.findings).filter((finding) =>
    conclusionOnly ? finding.kind === "conclusion" : finding.kind !== "conclusion",
  );
  const [selectedId, setSelectedId] = useState("new");
  const [kind, setKind] = useState<UfosintFindingKind>(
    conclusionOnly ? "conclusion" : "observation",
  );
  const [statement, setStatement] = useState("");
  const [interpretation, setInterpretation] = useState("");
  const [confidence, setConfidence] = useState<UfosintFindingConfidence>("unknown");
  const [limitations, setLimitations] = useState("");
  const [artifactIds, setArtifactIds] = useState<string[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);

  function chooseFinding(findingId: string) {
    setSelectedId(findingId);
    if (findingId === "new") {
      setKind(conclusionOnly ? "conclusion" : "observation");
      setStatement("");
      setInterpretation("");
      setConfidence("unknown");
      setLimitations("");
      setArtifactIds([]);
      return;
    }
    const finding = candidates.find((candidate) => candidate.findingId === findingId);
    if (!finding) return;
    setKind(finding.kind);
    setStatement(finding.statement);
    setInterpretation(finding.interpretation ?? "");
    setConfidence(finding.confidence);
    setLimitations(finding.limitations.join("\n"));
    setArtifactIds([...finding.artifactIds]);
  }

  function toggleArtifact(artifactId: string, checked: boolean) {
    setArtifactIds((current) =>
      checked
        ? [...new Set([...current, artifactId])]
        : current.filter((value) => value !== artifactId),
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    try {
      const previous =
        selectedId === "new"
          ? null
          : candidates.find((finding) => finding.findingId === selectedId) ?? null;
      const evidenceReferences = previous
        ? [...previous.evidenceReferences]
        : [
            {
              referenceId: newId(),
              sourceType: "report_snapshot" as const,
              sourceReference: sidequest.reportId,
              label: `Immutable UFOSINT snapshot for ${sidequest.reportId}`,
              availability: "available" as const,
              publicSafe: true,
            },
          ];
      for (const artifactId of artifactIds) {
        if (!evidenceReferences.some((reference) => reference.sourceType === "artifact" && reference.sourceReference === artifactId)) {
          const artifact = sidequest.artifacts.find((candidate) => candidate.artifactId === artifactId);
          evidenceReferences.push({
            referenceId: newId(),
            sourceType: "artifact",
            sourceReference: artifactId,
            label: artifact?.title ?? `Artifact ${artifactId}`,
            availability: "available",
            publicSafe: true,
          });
        }
      }
      const validated = parseUfosintFindingRevision({
        findingId: previous?.findingId ?? newId(),
        revision: previous ? previous.revision + 1 : 1,
        previousRevision: previous?.revision ?? null,
        kind: previous?.kind ?? kind,
        statement,
        interpretation: optionalText(interpretation),
        confidence,
        limitations: lines(limitations),
        evidenceReferences,
        artifactIds,
        author: CLIENT_VALIDATION_ACTOR,
        createdAt: new Date().toISOString(),
      });
      if (await onAdd(withoutFindingAuditFields(validated))) chooseFinding("new");
    } catch (error) {
      setLocalError(errorMessage(error));
    }
  }

  const allowedKinds = conclusionOnly
    ? (["conclusion"] as const)
    : UFOSINT_FINDING_KINDS.filter((value) => value !== "conclusion");
  return (
    <form onSubmit={(event) => void submit(event)}>
      <h4>{conclusionOnly ? "Draft or revise a conclusion" : "Add or revise a finding"}</h4>
      <fieldset disabled={disabled}>
        <legend>Immutable revision</legend>
        <label>
          Record
          <select value={selectedId} onChange={(event) => chooseFinding(event.currentTarget.value)}>
            <option value="new">New {conclusionOnly ? "conclusion" : "finding"}</option>
            {candidates.map((finding) => (
              <option key={finding.findingId} value={finding.findingId}>
                Revise {finding.kind} r{finding.revision}: {finding.statement.slice(0, 80)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Kind
          <select value={kind} disabled={selectedId !== "new" || conclusionOnly} onChange={(event) => setKind(event.currentTarget.value as UfosintFindingKind)}>
            {allowedKinds.map((value) => <option key={value} value={value}>{lifecycleLabel(value)}</option>)}
          </select>
        </label>
        <label>
          Evidence-bounded statement
          <textarea value={statement} maxLength={UFOSINT_SIDEQUEST_LIMITS.findingStatement} onChange={(event) => setStatement(event.currentTarget.value)} required />
        </label>
        <label>
          Interpretation (optional; distinguish it from observation)
          <textarea value={interpretation} maxLength={UFOSINT_SIDEQUEST_LIMITS.findingInterpretation} onChange={(event) => setInterpretation(event.currentTarget.value)} />
        </label>
        <label>
          Confidence
          <select value={confidence} onChange={(event) => setConfidence(event.currentTarget.value as UfosintFindingConfidence)}>
            {UFOSINT_FINDING_CONFIDENCE.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>
          Limitations, one per line
          <textarea value={limitations} onChange={(event) => setLimitations(event.currentTarget.value)} />
        </label>
        <fieldset>
          <legend>Linked artifacts</legend>
          {sidequest.artifacts.length ? sidequest.artifacts.map((artifact) => (
            <label key={artifact.artifactId}>
              <input type="checkbox" checked={artifactIds.includes(artifact.artifactId)} onChange={(event) => toggleArtifact(artifact.artifactId, event.currentTarget.checked)} />
              {artifact.title} ({lifecycleLabel(artifact.kind)})
            </label>
          )) : <p>No artifacts are available; the immutable report snapshot remains linked.</p>}
        </fieldset>
      </fieldset>
      {conclusionOnly ? (
        <p>
          “Conclusion” closes a bounded research record. It does not verify the source report,
          identify an object, certify a location, or grant institutional progression.
        </p>
      ) : null}
      {localError ? <p role="alert">{localError}</p> : null}
      <button type="submit" disabled={disabled}>{selectedId === "new" ? "Add revision 1" : "Add next revision"}</button>
    </form>
  );
}

function ReviewForm({
  sidequest,
  participant,
  disabled,
  onAdd,
}: {
  sidequest: UfosintSidequestSnapshot;
  participant: UfosintActor | null;
  disabled: boolean;
  onAdd: (review: ReviewInput) => Promise<boolean>;
}) {
  const candidates = latestFindingRevisions(sidequest.findings);
  const [findingId, setFindingId] = useState(candidates[0]?.findingId ?? "");
  const [disposition, setDisposition] =
    useState<FindingReviewDisposition>("endorse");
  const [rationale, setRationale] = useState("");
  const [rubric, setRubric] = useState<FindingReviewRubric>({
    evidenceSupport: 1,
    ordinaryAlternatives: 1,
    contradictionsPreserved: 1,
    confidenceCalibration: 1,
    reproducibility: 1,
  });
  const [localError, setLocalError] = useState<string | null>(null);
  const selected = candidates.find((finding) => finding.findingId === findingId) ?? null;
  const selfReview = Boolean(
    selected && participant && selected.author.participantId === participant.participantId,
  );

  useEffect(() => {
    if (!candidates.some((finding) => finding.findingId === findingId)) {
      setFindingId(candidates[0]?.findingId ?? "");
    }
  }, [candidates, findingId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    if (!selected) {
      setLocalError("Choose a current finding revision to review.");
      return;
    }
    if (selfReview) {
      setLocalError("Independent review must come from someone other than the revision author.");
      return;
    }
    try {
      const validated = parseUfosintSidequestReview({
        reviewId: newId(),
        findingId: selected.findingId,
        findingRevision: selected.revision,
        reviewer: participant ?? CLIENT_VALIDATION_ACTOR,
        disposition,
        rationale,
        rubric,
        createdAt: new Date().toISOString(),
      });
      if (await onAdd(withoutReviewAuditFields(validated))) setRationale("");
    } catch (error) {
      setLocalError(errorMessage(error));
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)}>
      <h4>Review the exact current revision</h4>
      <p>
        The server records the authenticated reviewer. Endorsements count as independent only
        when the reviewer is not the revision author.
      </p>
      <fieldset disabled={disabled || candidates.length === 0}>
        <label>
          Finding revision
          <select value={findingId} onChange={(event) => setFindingId(event.currentTarget.value)}>
            {candidates.map((finding) => (
              <option key={finding.findingId} value={finding.findingId}>
                {finding.kind} r{finding.revision}: {finding.statement.slice(0, 90)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Disposition
          <select value={disposition} onChange={(event) => setDisposition(event.currentTarget.value as FindingReviewDisposition)}>
            {FINDING_REVIEW_DISPOSITIONS.map((value) => <option key={value} value={value}>{lifecycleLabel(value)}</option>)}
          </select>
        </label>
        <label>
          Rationale
          <textarea value={rationale} maxLength={UFOSINT_SIDEQUEST_LIMITS.reviewRationale} onChange={(event) => setRationale(event.currentTarget.value)} required />
        </label>
        <fieldset>
          <legend>Rubric: 0 absent, 1 partial, 2 strong</legend>
          {RUBRIC_FIELDS.map(({ key, label }) => (
            <label key={key}>
              {label}
              <select value={rubric[key]} onChange={(event) => setRubric((current) => ({ ...current, [key]: Number(event.currentTarget.value) }))}>
                <option value={0}>0</option><option value={1}>1</option><option value={2}>2</option>
              </select>
            </label>
          ))}
        </fieldset>
      </fieldset>
      {selfReview ? <p role="alert">You authored this revision; ask another participant to review it.</p> : null}
      {localError ? <p role="alert">{localError}</p> : null}
      <button type="submit" disabled={disabled || !selected || selfReview}>Record peer review</button>
    </form>
  );
}

function conclusionAssessment(sidequest: UfosintSidequestSnapshot): {
  conclusion: UfosintSidequestFindingRevision | null;
  blockers: string[];
} {
  const conclusion = latestFindingRevisions(sidequest.findings).find(
    (finding) => finding.kind === "conclusion",
  ) ?? null;
  const blockers: string[] = [];
  if (sidequest.lifecycle !== "review") blockers.push("Move the sidequest into review first.");
  const unresolvedRequired = sidequest.tasks.filter(
    (task) =>
      task.required && !["completed", "waived", "unavailable"].includes(task.status),
  );
  if (unresolvedRequired.length) {
    blockers.push(`${unresolvedRequired.length} required checklist task(s) remain unresolved.`);
  }
  const unavailableRequired = sidequest.tasks.filter(
    (task) => task.required && task.status === "unavailable",
  );
  if (!conclusion) {
    blockers.push("Add a conclusion finding.");
    return { conclusion, blockers };
  }
  if (!conclusion.evidenceReferences.length) blockers.push("Link the conclusion to evidence.");
  if (unavailableRequired.length && !conclusion.limitations.length) {
    blockers.push("State limitations created by unavailable required sources.");
  }
  const exactReviews = sidequest.reviews.filter(
    (review) =>
      review.findingId === conclusion.findingId &&
      review.findingRevision === conclusion.revision,
  );
  if (!exactReviews.some(
    (review) =>
      review.disposition === "endorse" &&
      review.reviewer.participantId !== conclusion.author.participantId,
  )) {
    blockers.push("Obtain an independent endorsement of the exact conclusion revision.");
  }
  if (exactReviews.some((review) => review.disposition === "challenge")) {
    blockers.push("The exact conclusion revision has an unresolved challenge.");
  }
  if (exactReviews.some((review) => review.disposition === "request_revision")) {
    blockers.push("The exact conclusion revision has an unresolved revision request.");
  }
  return { conclusion, blockers };
}

function SidequestWorkspace({
  snapshot,
  participant,
  sessionToken,
  busy,
  commit,
}: {
  snapshot: UfosintSidequestSnapshot;
  participant: UfosintActor | null;
  sessionToken: string;
  busy: boolean;
  commit: (action: UfosintSidequestAction) => Promise<boolean>;
}) {
  const [confirmArchive, setConfirmArchive] = useState(false);
  const assessment = useMemo(() => conclusionAssessment(snapshot), [snapshot]);
  const dynamicalPlan = useMemo(
    () => planDynamicalEvidence(snapshot.reportSnapshot),
    [snapshot.reportSnapshot],
  );
  const mutable = !["concluded", "archived"].includes(snapshot.lifecycle);
  const lifecycleTargets = UFOSINT_SIDEQUEST_LIFECYCLES.filter((lifecycle) =>
    canTransitionUfosintSidequest(snapshot.lifecycle, lifecycle),
  );
  const completed = snapshot.taskCounts.completed;

  return (
    <div className="ufosint-sidequest-workspace">
      <Section title="Sidequest record">
        <dl>
          <dt>Lifecycle</dt><dd>{snapshot.lifecycle}</dd>
          <dt>Revision</dt><dd>{snapshot.revision}</dd>
          <dt>Template</dt><dd>{snapshot.templateVersion}</dd>
          <dt>Environment</dt><dd>{snapshot.environment}</dd>
          <dt>Opened by</dt><dd>{snapshot.openedBy.displayName}</dd>
          <dt>Last updated</dt><dd>{displayTimestamp(snapshot.updatedAt)}</dd>
          <dt>Checklist</dt><dd>{completed} completed of {snapshot.tasks.length}</dd>
        </dl>
        <p>
          Lifecycle states coordinate a research record only. They confer no rank, reward,
          access, report verification, or institutional progression.
        </p>
        <div className="ufosint-sidequest-actions">
          {lifecycleTargets.filter((target) => target !== "archived").map((target) => {
            const blockedConclusion = target === "concluded" && assessment.blockers.length > 0;
            return (
              <button
                type="button"
                key={target}
                disabled={busy || blockedConclusion}
                title={blockedConclusion ? assessment.blockers.join(" ") : undefined}
                onClick={() => void commit({ action: "update_lifecycle", lifecycle: target })}
              >
                Move to {target}
              </button>
            );
          })}
          {lifecycleTargets.includes("archived") ? (
            confirmArchive ? (
              <span>
                Archive is terminal. {" "}
                <button type="button" disabled={busy} onClick={() => void commit({ action: "update_lifecycle", lifecycle: "archived" })}>Confirm archive</button>{" "}
                <button type="button" disabled={busy} onClick={() => setConfirmArchive(false)}>Cancel</button>
              </span>
            ) : (
              <button type="button" disabled={busy} onClick={() => setConfirmArchive(true)}>Archive sidequest…</button>
            )
          ) : null}
        </div>
      </Section>

      <Section title="Report scope and uncertainty">
        <h4>{snapshot.reportSnapshot.title}</h4>
        <dl>
          <dt>UFOSINT report ID</dt><dd>{snapshot.reportId}</dd>
          <dt>Reported event date</dt><dd>{dateOnly(snapshot.reportSnapshot.observedAt)}</dd>
          <dt>Approximate location label</dt><dd>{snapshot.reportSnapshot.locationName}</dd>
          <dt>Privacy-reduced coordinates</dt><dd>{snapshot.reportSnapshot.latitude.toFixed(2)}, {snapshot.reportSnapshot.longitude.toFixed(2)}</dd>
          <dt>Coordinate precision</dt><dd>{snapshot.reportSnapshot.coordinatePrecision}</dd>
          <dt>Feed quality gate</dt><dd>{snapshot.reportSnapshot.qualityScore}/100</dd>
          <dt>Status</dt><dd>{snapshot.reportSnapshot.status}</dd>
        </dl>
        <p>{snapshot.reportSnapshot.summary}</p>
        <ul>
          <li>The feed supplies an event date, not an authoritative observation time.</li>
          <li>The location and coordinates are privacy-reduced, city-scale context—not a witness address or field site.</li>
          <li>The quality score is an ingestion-quality gate, not a truth or confidence score.</li>
          <li>The source remains unverified. Preserve competing ordinary explanations and missing data.</li>
        </ul>
        {snapshot.reportSnapshot.sourceUrl ? <a href={snapshot.reportSnapshot.sourceUrl} target="_blank" rel="noreferrer">Open public source report</a> : <p>No report-specific public source URL is available.</p>}
      </Section>

      <Section title="Investigation checklist">
        <p>
          Work only with lawful public sources. Do not identify or contact witnesses, reverse
          privacy reduction, trespass, surveil a location, or treat unavailable data as negative evidence.
        </p>
        <ul className="ufosint-sidequest-checklist">
          {snapshot.tasks.map((task) => (
            <TaskEditor
              key={`${task.taskId}:${task.updatedAt}`}
              task={task}
              participant={participant}
              disabled={busy || !mutable}
              onUpdate={(status, assignee, completionNote) => commit({
                action: "update_task",
                taskId: task.taskId,
                status,
                assignee,
                completionNote,
              })}
            />
          ))}
        </ul>
      </Section>

      <Section title="Dynamical evidence plan and artifacts">
        <p>
          Dynamical stores are queried by the signed background worker, not as browser
          tiles. These eligibility decisions use the privacy-reduced location and a
          date-only window with a one-day UTC buffer on each side.
        </p>
        <ul className="ufosint-dynamical-plan">
          {dynamicalPlan.map((entry) => {
            const dataset = DYNAMICAL_DATASETS.find(
              (candidate) => candidate.id === entry.datasetId,
            );
            return (
              <li key={entry.datasetId} data-status={entry.status}>
                <header>
                  <strong>{dataset?.shortLabel ?? entry.catalogId}</strong>
                  <span>{entry.status.replaceAll("-", " ")}</span>
                </header>
                <p>{entry.reason}</p>
                <small>
                  {entry.queryStart} through {entry.queryEnd} · envelope {entry.spatialEnvelope
                    .map((value) => value.toFixed(2))
                    .join(", ")}
                </small>
                <small>{entry.limitation}</small>
              </li>
            );
          })}
        </ul>
        <ol>
          <li>Freeze the immutable report snapshot and identify which date, time, and location fields are actually known.</li>
          <li>Capture source metadata and hashes before comparing weather, aviation, satellite, astronomical, or geospatial context.</li>
          <li>For motion or propagation work, declare the model, frame, time standard, window, inputs, parameters, software versions, and derived values.</li>
          <li>Quantify uncertainty and test ordinary alternatives. Preserve null or conflicting results.</li>
          <li>Attach exact approved bytes and metadata, with an unbroken provenance parent.</li>
        </ol>
        <ArtifactList
          artifacts={snapshot.artifacts}
          sidequestId={snapshot.sidequestId}
          sessionToken={sessionToken}
        />
        <p>
          Signed Dynamical artifacts arrive through the Hypha worker boundary. Investigators
          may attach other approved exact files and metadata below; they cannot self-assert a
          Dynamical analysis.
        </p>
        <ArtifactForm
          sidequest={snapshot}
          participant={participant}
          disabled={busy || !mutable}
          onAttach={(artifact, contentBase64) =>
            commit({ action: "attach_artifact", artifact, contentBase64 })
          }
        />
      </Section>

      <Section title="Findings">
        <FindingHistory sidequest={snapshot} />
        <FindingForm sidequest={snapshot} disabled={busy || !mutable} conclusionOnly={false} onAdd={(finding) => commit({ action: "add_finding", finding })} />
      </Section>

      <Section title="Peer review">
        {snapshot.lifecycle !== "review" ? (
          <p role="note">Move the sidequest into review before recording peer review.</p>
        ) : null}
        <ReviewForm sidequest={snapshot} participant={participant} disabled={busy || !mutable || snapshot.lifecycle !== "review"} onAdd={(review) => commit({ action: "add_review", review })} />
      </Section>

      <Section title="Conclusion controls">
        <FindingForm sidequest={snapshot} disabled={busy || !mutable} conclusionOnly onAdd={(finding) => commit({ action: "add_finding", finding })} />
        <h4>Closure assessment</h4>
        {assessment.conclusion ? (
          <p>
            Assessing conclusion {assessment.conclusion.findingId} revision {assessment.conclusion.revision}.
          </p>
        ) : null}
        {assessment.blockers.length ? (
          <ul>{assessment.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
        ) : (
          <p>
            Client checks are satisfied. The server remains authoritative and will recheck the
            expected revision, checklist, evidence, and independent review before closure.
          </p>
        )}
        <p>
          A concluded sidequest is a closed, revisioned research record. It is not an official
          determination of what occurred and does not change the source report’s unverified status.
        </p>
      </Section>
    </div>
  );
}

export function UfosintSidequestPanel({
  reportId,
  report = null,
  sessionToken,
  participant = null,
  open = true,
  presentation = "dialog",
  onClose,
  onSnapshotChange,
}: UfosintSidequestPanelProps) {
  const [snapshot, setSnapshot] = useState<UfosintSidequestSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const eligible = report !== null && isEligibleReport(report);

  const acceptSnapshot = useCallback(
    (value: UfosintSidequestSnapshot | null) => {
      if (value && value.reportId !== reportId) {
        throw new Error("The loaded sidequest belongs to a different report.");
      }
      setSnapshot(value);
      onSnapshotChange?.(value);
    },
    [onSnapshotChange, reportId],
  );

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!sessionToken) {
        acceptSnapshot(null);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        acceptSnapshot(await loadUfosintSidequest(reportId, sessionToken, { signal }));
      } catch (requestError) {
        if (signal?.aborted) return;
        setError(errorMessage(requestError));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [acceptSnapshot, reportId, sessionToken],
  );

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setSnapshot(null);
    void refresh(controller.signal);
    return () => controller.abort();
  }, [open, refresh]);

  useEffect(() => {
    if (!open || presentation === "inline") return;
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => headingRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [open, presentation, reportId]);

  async function create() {
    if (!sessionToken || !eligible) return;
    setSaving(true);
    setError(null);
    try {
      acceptSnapshot(await createUfosintSidequest(reportId, sessionToken));
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setSaving(false);
    }
  }

  async function commit(action: UfosintSidequestAction): Promise<boolean> {
    if (!sessionToken || !snapshot || saving) return false;
    setSaving(true);
    setError(null);
    try {
      acceptSnapshot(
        await applyUfosintSidequestAction(
          snapshot.sidequestId,
          snapshot.revision,
          action,
          sessionToken,
        ),
      );
      return true;
    } catch (requestError) {
      if (
        requestError instanceof UfosintSidequestApiError &&
        requestError.status === 409 &&
        requestError.code === "stale_sidequest_revision"
      ) {
        await refresh();
        setError((current) => current ?? "This sidequest changed in another session. The current revision was reloaded; review it and try again.");
      } else {
        setError(errorMessage(requestError));
      }
      return false;
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;
  const role = presentation === "dialog" ? "dialog" : "region";

  return (
    <aside
      className={`ufosint-sidequest-panel ufosint-sidequest-panel--${presentation}`}
      role={role}
      aria-modal={role === "dialog" ? true : undefined}
      aria-labelledby="ufosint-sidequest-title"
      aria-describedby="ufosint-sidequest-boundary"
      aria-busy={loading || saving}
      onKeyDown={(event) => {
        if (event.key === "Escape" && onClose) {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header>
        <div>
          <p>Optional collaborative desk research</p>
          <h2 ref={headingRef} id="ufosint-sidequest-title" tabIndex={-1}>UFOSINT sidequest</h2>
          <p>{report?.title ?? snapshot?.reportTitle ?? reportId}</p>
        </div>
        {onClose ? <button type="button" onClick={onClose}>Close</button> : null}
      </header>

      <div id="ufosint-sidequest-boundary" role="note">
        <strong>Research boundary:</strong> this sidequest organizes public-source evidence and
        peer review. Do not contact or identify witnesses, visit an inferred location, defeat
        privacy reduction, or claim verification. Sidequests provide no progression, score,
        reward, access, or official status.
      </div>

      {!sessionToken ? (
        <p role="alert">
  Authentication did not complete. Check the Activity connection status above,
  then close and reopen the Activity.
</p>
      ) : loading && !snapshot ? (
        <p role="status">Loading sidequest…</p>
      ) : snapshot ? (
        <SidequestWorkspace
          snapshot={snapshot}
          participant={participant}
          sessionToken={sessionToken}
          busy={saving}
          commit={commit}
        />
      ) : error && !snapshot ? (
        <p>The existing sidequest could not be determined. Refresh before attempting creation.</p>
      ) : report === null ? (
        <p role="note">
          No persisted sidequest was found, and this report is not present in the current
          quality-gated UFOSINT feed. A new sidequest cannot be created from mutable or missing
          source metadata.
        </p>
      ) : !eligible ? (
        <p role="alert">
          This report is not eligible. New sidequests require a current-index, unverified
          UFOSINT record with an indexed timestamp and quality score from 51 through 100.
        </p>
      ) : (
        <div>
          <p>No sidequest exists for this report.</p>
          <button type="button" disabled={saving} onClick={() => void create()}>
            Create research sidequest
          </button>
        </div>
      )}

      {saving ? <p role="status">Saving revision…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {sessionToken ? (
        <button type="button" disabled={loading || saving} onClick={() => void refresh()}>
          Refresh record
        </button>
      ) : null}
    </aside>
  );
}
