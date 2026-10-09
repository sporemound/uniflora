export type EnvironmentName = "live" | "test";
export type LocationStatus = "focus" | "available" | "locked";
export type AssignmentStatus =
  | "examining"
  | "awaiting-review"
  | "available"
  | "complete";
export type PublicPositionProgression = "available" | "completed" | "locked";
export type PublicConsoleMode = "workspace" | "reference" | "locked";

export type PublicCasePhase =
  | "establish"
  | "perturb"
  | "reconcile"
  | "review"
  | "complete";
export type PublicEvidenceStatus = "locked" | "available" | "examined";
export type PublicActionStatus =
  | "locked"
  | "developing"
  | "available"
  | "completed";
export type PublicRouteStatus = "available" | "complete";
export type PublicStrategicClass =
  | "observe"
  | "prepare"
  | "probe"
  | "secure"
  | "coordinate"
  | "commit"
  | "reconcile";
export type PublicStochasticMode =
  | "none"
  | "emit_only"
  | "intervention_then_emit";
export type PublicStrategicGrade =
  | "controlled"
  | "compromised"
  | "incomplete"
  | "critical";

export interface PublicEvidenceState {
  id: string;
  name: string;
  status: PublicEvidenceStatus;
  sourceClass: string;
  originLocationId: string;
  instrumentName: string | null;
  recordType: string;
}

export interface PublicActionState {
  id: string;
  title: string;
  description: string;
  status: PublicActionStatus;
  command: string | null;
  locationId: string;
  requiredRoleIds: string[];
  requiredEvidenceIds: string[];
  candidateEvidenceIds: string[];
  minimumExaminedEvidenceCount: number;
  requiredActionIds: string[];
  candidateActionIds: string[];
  minimumCompletedActionCount: number;
  requiredStochasticProcessIds: string[];
  minimumObservationCount: number;
  blockers: string[];
  stochasticProcessId: string | null;
  stochasticChannelId: string | null;
  variableOutcome: boolean;
  strategicClass: PublicStrategicClass | null;
  capacityCost: number;
  coordinationCost: number;
  supporterCount: number;
  irreversible: boolean;
  stochasticMode: PublicStochasticMode;
}

export interface PublicCompletionRoute {
  id: string;
  title: string;
  description: string;
  status: PublicRouteStatus;
  progress: string;
  requiredActionIds: string[];
  candidateActionIds: string[];
  minimumCompletedActionCount: number;
  completedCandidateCount: number;
  requiredStochasticProcessIds: string[];
  minimumObservationCount: number;
  observationCount: number;
}

export interface PublicModelSupport {
  modelId: string;
  label: string;
  basisPoints: number;
  percent: number;
}

export interface PublicStochasticProcess {
  id: string;
  title: string;
  description: string;
  locationId: string;
  algorithm: "hidden_markov" | "semi_markov";
  algorithmVersion: number;
  observationCount: number;
  lastSequence: number | null;
  observedState: string | null;
  modelSupport: PublicModelSupport[];
}

export interface PublicStochasticMeasurement {
  key: string;
  value: string | number | boolean;
  unit: string | null;
  uncertainty: string | null;
}

export interface PublicStochasticObservation {
  processId: string;
  actionId: string;
  channelId: string;
  outcomeId: string;
  summary: string;
  sequence: number;
  observedState: string | null;
  measurements: PublicStochasticMeasurement[];
}

export interface PublicCampaignTrack {
  id: string;
  label: string;
  value: number;
  minimum: number;
  maximum: number;
}

export interface PublicStrategicResource {
  id: string;
  title: string;
  value: number;
  minimum: number;
  maximum: number;
}

export interface PublicStrategicCondition {
  id: string;
  label: string;
  duration: "round" | "next_round" | "position" | "campaign";
  createdRound: number;
  expiresAfterRound: number | null;
}

export interface PublicStrategicProposal {
  proposalId: string;
  actionId: string;
  roundIndex: number;
  requiredSupporterCount: number;
  currentSupporterCount: number;
  status: "active" | "resolved" | "expired";
  command: string;
}

export interface PublicStrategicBoard {
  positionId: string;
  roundIndex: number;
  maxRounds: number;
  capacityRemaining: number;
  capacityPerRound: number;
  coordination: number;
  coordinationMaximum: number;
  escalation: number;
  escalationMaximum: number;
  localResource: PublicStrategicResource;
  conditions: PublicStrategicCondition[];
  proposals: PublicStrategicProposal[];
  forcedReview: boolean;
}

export interface PublicStrategicOutcome {
  positionId: string;
  grade: PublicStrategicGrade;
  roundIndex: number;
  caseIntegrity: number;
  institutionalTrust: number;
  escalation: number;
  assetIds: string[];
  liabilityIds: string[];
}

export interface PublicCampaignModifier {
  id: string;
  label: string;
}

export interface PublicLocation {
  id: string;
  name: string;
  shortName: string;
  status: LocationStatus;
  timezone: string;
  activeAssignments: number;
  mapCoordinates?: {
    latitude: number;
    longitude: number;
    label: string;
    precisionKm: number;
    basis: "WGS84 facility site";
  } | null;
}

export interface PublicAssignment {
  assignmentId: string;
  workingName: string;
  roleTitle: string;
  locationId: string;
  station: string;
  status: AssignmentStatus;
  paletteToken: string;
}

export interface PublicPosition {
  id: string;
  ordinal: number;
  title: string;
  locationId: string;
  progression: PublicPositionProgression;
  consoleMode: PublicConsoleMode;
}

export interface PublicAdaptivePresentation {
  presentationId: string;
  targetId: string;
  kind: "opening" | "ending";
  prose: string;
  guidance: string[];
  requiredActionId: string | null;
  optionalActionIds: string[];
}

export interface PublicPublicationAsset {
  filename: string;
  contentType: string;
  byteLength: number;
  sha256: string;
  url: string;
}

export interface PublicPublication {
  publicationId: string;
  artifactId: string;
  title: string;
  institution: string;
  finding: string;
  limitation: string;
  status: "preview" | "verified" | "published";
  primaryAsset: PublicPublicationAsset | null;
  manifestUrl: string | null;
}

interface PublicActivitySnapshotBase {
  source: "mock" | "hypha";
  environment: EnvironmentName;
  revision: number;
  stateHeadHash: string;
  previousStateHeadHash: string | null;
  positionId: string;
  positionTitle: string;
  focusLocationId: string;
  updatedAt: string;
  zuluTime: string;
  facilityTime: string;
  facilityTimezone: string;
  metrics: {
    activeAssignments: number;
    completedArtifacts: number;
    unresolvedContradictions: number;
    awaitingVerification: number;
  };
  locations: PublicLocation[];
  assignments: PublicAssignment[];
  latestPublication: PublicPublication | null;
  nextRequirement: string;
}

export interface PublicActivitySnapshotV20 extends PublicActivitySnapshotBase {
  schemaVersion: "2.0.0";
}

export interface PublicActivitySnapshotV21 extends PublicActivitySnapshotBase {
  schemaVersion: "2.1.0";
  positions: PublicPosition[];
}

export interface PublicActivitySnapshotV22 extends PublicActivitySnapshotBase {
  schemaVersion: "2.2.0";
  contentVersion: string;
  positions: PublicPosition[];
  adaptivePresentation: PublicAdaptivePresentation | null;
}

export interface PublicActivitySnapshotV23 extends PublicActivitySnapshotBase {
  schemaVersion: "2.3.0";
  contentVersion: string;
  sequence: number;
  casePhase: PublicCasePhase;
  positions: PublicPosition[];
  adaptivePresentation: PublicAdaptivePresentation | null;
  evidence: PublicEvidenceState[];
  actions: PublicActionState[];
  completionRoutes: PublicCompletionRoute[];
  stochasticProcesses: PublicStochasticProcess[];
  recentObservations: PublicStochasticObservation[];
}

export interface PublicActivitySnapshotV24
  extends Omit<PublicActivitySnapshotV23, "schemaVersion"> {
  schemaVersion: "2.4.0";
  campaignTracks: PublicCampaignTrack[];
  strategicBoard: PublicStrategicBoard | null;
  strategicOutcomes: PublicStrategicOutcome[];
  campaignModifiers: PublicCampaignModifier[];
}

export type PublicActivitySnapshot =
  | PublicActivitySnapshotV20
  | PublicActivitySnapshotV21
  | PublicActivitySnapshotV22
  | PublicActivitySnapshotV23
  | PublicActivitySnapshotV24;

const ROOT_KEYS_V20 = [
  "schemaVersion",
  "source",
  "environment",
  "revision",
  "stateHeadHash",
  "previousStateHeadHash",
  "positionId",
  "positionTitle",
  "focusLocationId",
  "updatedAt",
  "zuluTime",
  "facilityTime",
  "facilityTimezone",
  "metrics",
  "locations",
  "assignments",
  "latestPublication",
  "nextRequirement",
] as const;
const ROOT_KEYS_V21 = [...ROOT_KEYS_V20, "positions"] as const;
const ROOT_KEYS_V22_LEGACY = [
  ...ROOT_KEYS_V21,
  "adaptivePresentation",
] as const;
const ROOT_KEYS_V22 = [...ROOT_KEYS_V22_LEGACY, "contentVersion"] as const;
const ROOT_KEYS_V23 = [
  ...ROOT_KEYS_V22,
  "sequence",
  "casePhase",
  "evidence",
  "actions",
  "completionRoutes",
  "stochasticProcesses",
  "recentObservations",
] as const;
const ROOT_KEYS_V24 = [
  ...ROOT_KEYS_V23,
  "campaignTracks",
  "strategicBoard",
  "strategicOutcomes",
  "campaignModifiers",
] as const;
const EVIDENCE_KEYS = [
  "id",
  "name",
  "status",
  "sourceClass",
  "originLocationId",
  "instrumentName",
  "recordType",
] as const;
const ACTION_KEYS_V23 = [
  "id",
  "title",
  "description",
  "status",
  "command",
  "locationId",
  "requiredRoleIds",
  "requiredEvidenceIds",
  "candidateEvidenceIds",
  "minimumExaminedEvidenceCount",
  "requiredActionIds",
  "candidateActionIds",
  "minimumCompletedActionCount",
  "requiredStochasticProcessIds",
  "minimumObservationCount",
  "blockers",
  "stochasticProcessId",
  "stochasticChannelId",
  "variableOutcome",
] as const;
const ACTION_KEYS_V24 = [
  ...ACTION_KEYS_V23,
  "strategicClass",
  "capacityCost",
  "coordinationCost",
  "supporterCount",
  "irreversible",
  "stochasticMode",
] as const;
const ROUTE_KEYS = [
  "id",
  "title",
  "description",
  "status",
  "progress",
  "requiredActionIds",
  "candidateActionIds",
  "minimumCompletedActionCount",
  "completedCandidateCount",
  "requiredStochasticProcessIds",
  "minimumObservationCount",
  "observationCount",
] as const;
const PROCESS_KEYS = [
  "id",
  "title",
  "description",
  "locationId",
  "algorithm",
  "algorithmVersion",
  "observationCount",
  "lastSequence",
  "observedState",
  "modelSupport",
] as const;
const MODEL_SUPPORT_KEYS = [
  "modelId",
  "label",
  "basisPoints",
  "percent",
] as const;
const OBSERVATION_KEYS = [
  "processId",
  "actionId",
  "channelId",
  "outcomeId",
  "summary",
  "sequence",
  "observedState",
  "measurements",
] as const;
const MEASUREMENT_KEYS = [
  "key",
  "value",
  "unit",
  "uncertainty",
] as const;
const CAMPAIGN_TRACK_KEYS = [
  "id",
  "label",
  "value",
  "minimum",
  "maximum",
] as const;
const STRATEGIC_RESOURCE_KEYS = [
  "id",
  "title",
  "value",
  "minimum",
  "maximum",
] as const;
const STRATEGIC_CONDITION_KEYS = [
  "id",
  "label",
  "duration",
  "createdRound",
  "expiresAfterRound",
] as const;
const STRATEGIC_PROPOSAL_KEYS = [
  "proposalId",
  "actionId",
  "roundIndex",
  "requiredSupporterCount",
  "currentSupporterCount",
  "status",
  "command",
] as const;
const STRATEGIC_BOARD_KEYS = [
  "positionId",
  "roundIndex",
  "maxRounds",
  "capacityRemaining",
  "capacityPerRound",
  "coordination",
  "coordinationMaximum",
  "escalation",
  "escalationMaximum",
  "localResource",
  "conditions",
  "proposals",
  "forcedReview",
] as const;
const STRATEGIC_OUTCOME_KEYS = [
  "positionId",
  "grade",
  "roundIndex",
  "caseIntegrity",
  "institutionalTrust",
  "escalation",
  "assetIds",
  "liabilityIds",
] as const;
const CAMPAIGN_MODIFIER_KEYS = ["id", "label"] as const;
const METRIC_KEYS = [
  "activeAssignments",
  "completedArtifacts",
  "unresolvedContradictions",
  "awaitingVerification",
] as const;
const LOCATION_KEYS = [
  "id",
  "name",
  "shortName",
  "status",
  "timezone",
  "activeAssignments",
  "mapCoordinates",
] as const;
const MAP_COORDINATE_KEYS = [
  "latitude",
  "longitude",
  "label",
  "precisionKm",
  "basis",
] as const;
const ASSIGNMENT_KEYS = [
  "assignmentId",
  "workingName",
  "roleTitle",
  "locationId",
  "station",
  "status",
  "paletteToken",
] as const;
const POSITION_KEYS = [
  "id",
  "ordinal",
  "title",
  "locationId",
  "progression",
  "consoleMode",
] as const;
const ADAPTIVE_PRESENTATION_KEYS = [
  "presentationId",
  "targetId",
  "kind",
  "prose",
  "guidance",
  "requiredActionId",
  "optionalActionIds",
] as const;
const PUBLICATION_KEYS = [
  "publicationId",
  "artifactId",
  "title",
  "institution",
  "finding",
  "limitation",
  "status",
  "primaryAsset",
  "manifestUrl",
] as const;
const PUBLICATION_ASSET_KEYS = [
  "filename",
  "contentType",
  "byteLength",
  "sha256",
  "url",
] as const;

const MAX_IDENTIFIER_LENGTH = 128;
const MAX_LABEL_LENGTH = 512;
const MAX_TEXT_LENGTH = 8_192;
const MAX_URL_LENGTH = 2_048;
const MAX_LOCATIONS = 64;
const MAX_ASSIGNMENTS = 512;
const MAX_POSITIONS = 64;
const MAX_ADAPTIVE_ITEMS = 32;
const MAX_POSITION_ORDINAL = 1_024;
const MAX_PUBLIC_EVIDENCE = 256;
const MAX_PUBLIC_ACTIONS = 256;
const MAX_PUBLIC_ROUTES = 32;
const MAX_PUBLIC_PROCESSES = 64;
const MAX_PUBLIC_OBSERVATIONS = 64;
const MAX_PUBLIC_MEASUREMENTS = 64;
const MAX_PUBLIC_MODELS = 32;
const MAX_PUBLIC_REQUIREMENTS = 64;
const MAX_CAMPAIGN_TRACKS = 16;
const MAX_STRATEGIC_CONDITIONS = 64;
const MAX_STRATEGIC_PROPOSALS = 32;
const MAX_STRATEGIC_OUTCOMES = 64;
const MAX_CAMPAIGN_MODIFIERS = 64;

/**
 * Closed schema-2.4 association contract for the stochastic Missing Interior campaign.
 * Location IDs may use the engine identifier or its public URL slug, but a
 * signed projection may not remap canonical progression to another facility.
 */
const PUBLIC_POSITION_CONTRACT = [
  {
    id: "network_orientation",
    ordinal: 0,
    title: "The Network Before the Event",
    locationIds: ["boundary_array", "boundary-array"],
  },
  {
    id: "boundary_event",
    ordinal: 1,
    title: "First Return",
    locationIds: ["boundary_array", "boundary-array"],
  },
  {
    id: "aeronautical_incident",
    ordinal: 2,
    title: "The Track That Will Not Close",
    locationIds: [
      "aeronautical_incident_center",
      "aeronautical-incident-center",
    ],
  },
  {
    id: "archive_convergence",
    ordinal: 3,
    title: "A Pattern Without a Common Cause",
    locationIds: ["aerial_phenomena_archive", "aerial-phenomena-archive"],
  },
  {
    id: "holographic_reconstruction",
    ordinal: 4,
    title: "The Volume Defined by Its Absence",
    locationIds: ["holography_laboratory", "holography-laboratory"],
  },
  {
    id: "subsurface_resonance",
    ordinal: 5,
    title: "A Mode Without a Source Point",
    locationIds: [
      "subsurface_resonance_station",
      "subsurface-resonance-station",
    ],
  },
  {
    id: "quantum_state",
    ordinal: 6,
    title: "The View From the Missing Interior",
    locationIds: ["quantum_state_institute", "quantum-state-institute"],
  },
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(
  record: Record<string, unknown>,
  allowedKeys: readonly string[],
): boolean {
  const allowed = new Set(allowedKeys);
  return Object.keys(record).every((key) => allowed.has(key));
}

function isEnvironment(value: unknown): value is EnvironmentName {
  return value === "live" || value === "test";
}

function isBoundedString(
  value: unknown,
  maximumLength: number,
  allowEmpty = false,
): value is string {
  return (
    typeof value === "string" &&
    value.length <= maximumLength &&
    (allowEmpty || value.length > 0)
  );
}

function isNonnegativeInteger(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0
  );
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableBoundedString(
  value: unknown,
  maximumLength: number,
): value is string | null {
  return value === null || isBoundedString(value, maximumLength);
}

function normalizeLocation(value: unknown): PublicLocation | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, LOCATION_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.name, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.shortName, MAX_LABEL_LENGTH) ||
    (value.status !== "focus" &&
      value.status !== "available" &&
      value.status !== "locked") ||
    !isBoundedString(value.timezone, MAX_IDENTIFIER_LENGTH) ||
    !isNonnegativeInteger(value.activeAssignments)
  ) {
    return null;
  }

  const mapCoordinates = value.mapCoordinates;
  if (
    mapCoordinates !== undefined &&
    mapCoordinates !== null &&
    (
      !isRecord(mapCoordinates) ||
      !hasOnlyKeys(mapCoordinates, MAP_COORDINATE_KEYS) ||
      typeof mapCoordinates.latitude !== "number" ||
      !Number.isFinite(mapCoordinates.latitude) ||
      mapCoordinates.latitude < -90 ||
      mapCoordinates.latitude > 90 ||
      typeof mapCoordinates.longitude !== "number" ||
      !Number.isFinite(mapCoordinates.longitude) ||
      mapCoordinates.longitude < -180 ||
      mapCoordinates.longitude > 180 ||
      !isBoundedString(mapCoordinates.label, MAX_LABEL_LENGTH) ||
      typeof mapCoordinates.precisionKm !== "number" ||
      !Number.isFinite(mapCoordinates.precisionKm) ||
      mapCoordinates.precisionKm <= 0 ||
      mapCoordinates.precisionKm > 1000 ||
      mapCoordinates.basis !== "WGS84 facility site"
    )
  ) {
    return null;
  }

  return {
    id: value.id,
    name: value.name,
    shortName: value.shortName,
    status: value.status,
    timezone: value.timezone,
    activeAssignments: value.activeAssignments,
    mapCoordinates:
      mapCoordinates === undefined || mapCoordinates === null
        ? null
        : {
            latitude: mapCoordinates.latitude as number,
            longitude: mapCoordinates.longitude as number,
            label: mapCoordinates.label as string,
            precisionKm: mapCoordinates.precisionKm as number,
            basis: "WGS84 facility site",
          },
  };
}

function normalizeAssignment(value: unknown): PublicAssignment | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ASSIGNMENT_KEYS) ||
    !isBoundedString(value.assignmentId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.workingName, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.roleTitle, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.locationId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.station, MAX_LABEL_LENGTH) ||
    (value.status !== "examining" &&
      value.status !== "awaiting-review" &&
      value.status !== "available" &&
      value.status !== "complete") ||
    !isBoundedString(value.paletteToken, MAX_IDENTIFIER_LENGTH)
  ) {
    return null;
  }

  return {
    assignmentId: value.assignmentId,
    workingName: value.workingName,
    roleTitle: value.roleTitle,
    locationId: value.locationId,
    station: value.station,
    status: value.status,
    paletteToken: value.paletteToken,
  };
}

function normalizePosition(value: unknown): PublicPosition | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, POSITION_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    typeof value.ordinal !== "number" ||
    !Number.isSafeInteger(value.ordinal) ||
    value.ordinal < 0 ||
    value.ordinal > MAX_POSITION_ORDINAL ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.locationId, MAX_IDENTIFIER_LENGTH) ||
    (value.progression !== "available" &&
      value.progression !== "completed" &&
      value.progression !== "locked") ||
    (value.consoleMode !== "workspace" &&
      value.consoleMode !== "reference" &&
      value.consoleMode !== "locked")
  ) {
    return null;
  }

  const progression = value.progression;
  const consoleMode = value.consoleMode;
  if (
    (progression === "locked" && consoleMode !== "locked") ||
    (progression !== "locked" && consoleMode === "locked")
  ) {
    return null;
  }

  return {
    id: value.id,
    ordinal: value.ordinal,
    title: value.title,
    locationId: value.locationId,
    progression,
    consoleMode,
  };
}

function normalizePublicationAsset(
  value: unknown,
): PublicPublicationAsset | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, PUBLICATION_ASSET_KEYS) ||
    !isBoundedString(value.filename, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.contentType, MAX_IDENTIFIER_LENGTH) ||
    !isNonnegativeInteger(value.byteLength) ||
    !isBoundedString(value.sha256, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.url, MAX_URL_LENGTH)
  ) {
    return null;
  }

  return {
    filename: value.filename,
    contentType: value.contentType,
    byteLength: value.byteLength,
    sha256: value.sha256,
    url: value.url,
  };
}

function normalizePublication(value: unknown): PublicPublication | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, PUBLICATION_KEYS) ||
    !isBoundedString(value.publicationId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.artifactId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.institution, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.finding, MAX_TEXT_LENGTH) ||
    !isBoundedString(value.limitation, MAX_TEXT_LENGTH) ||
    (value.status !== "preview" &&
      value.status !== "verified" &&
      value.status !== "published") ||
    (value.manifestUrl !== null &&
      !isBoundedString(value.manifestUrl, MAX_URL_LENGTH))
  ) {
    return null;
  }

  const primaryAsset =
    value.primaryAsset === null
      ? null
      : normalizePublicationAsset(value.primaryAsset);
  if (value.primaryAsset !== null && primaryAsset === null) {
    return null;
  }

  return {
    publicationId: value.publicationId,
    artifactId: value.artifactId,
    title: value.title,
    institution: value.institution,
    finding: value.finding,
    limitation: value.limitation,
    status: value.status,
    primaryAsset,
    manifestUrl: value.manifestUrl,
  };
}

function normalizeMetrics(
  value: unknown,
): PublicActivitySnapshotBase["metrics"] | null {
  if (!isRecord(value) || !hasOnlyKeys(value, METRIC_KEYS)) {
    return null;
  }
  if (!METRIC_KEYS.every((key) => isNonnegativeInteger(value[key]))) {
    return null;
  }
  return {
    activeAssignments: value.activeAssignments as number,
    completedArtifacts: value.completedArtifacts as number,
    unresolvedContradictions: value.unresolvedContradictions as number,
    awaitingVerification: value.awaitingVerification as number,
  };
}

function normalizeAdaptivePresentation(
  value: unknown,
): PublicAdaptivePresentation | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ADAPTIVE_PRESENTATION_KEYS) ||
    !isBoundedString(value.presentationId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.targetId, MAX_IDENTIFIER_LENGTH) ||
    (value.kind !== "opening" && value.kind !== "ending") ||
    !isBoundedString(value.prose, MAX_TEXT_LENGTH) ||
    (value.requiredActionId !== null &&
      !isBoundedString(value.requiredActionId, MAX_IDENTIFIER_LENGTH))
  ) {
    return null;
  }
  const guidance = normalizeArray(
    value.guidance,
    MAX_ADAPTIVE_ITEMS,
    (item) => isBoundedString(item, MAX_TEXT_LENGTH) ? item : null,
  );
  const optionalActionIds = normalizeArray(
    value.optionalActionIds,
    MAX_ADAPTIVE_ITEMS,
    (item) => isBoundedString(item, MAX_IDENTIFIER_LENGTH) ? item : null,
  );
  if (
    guidance === null ||
    optionalActionIds === null ||
    !hasUniqueValues(optionalActionIds, (item) => item)
  ) {
    return null;
  }
  return {
    presentationId: value.presentationId,
    targetId: value.targetId,
    kind: value.kind,
    prose: value.prose,
    guidance,
    requiredActionId: value.requiredActionId,
    optionalActionIds,
  };
}

function normalizeIdentifierArray(value: unknown): string[] | null {
  const result = normalizeArray(
    value,
    MAX_PUBLIC_REQUIREMENTS,
    (item) => isBoundedString(item, MAX_IDENTIFIER_LENGTH) ? item : null,
  );
  return result !== null && hasUniqueValues(result, (item) => item)
    ? result
    : null;
}

function normalizeEvidenceState(value: unknown): PublicEvidenceState | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, EVIDENCE_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.name, MAX_LABEL_LENGTH) ||
    (value.status !== "locked" &&
      value.status !== "available" &&
      value.status !== "examined") ||
    !isBoundedString(value.sourceClass, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.originLocationId, MAX_IDENTIFIER_LENGTH) ||
    !isNullableBoundedString(value.instrumentName, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.recordType, MAX_IDENTIFIER_LENGTH)
  ) {
    return null;
  }
  return {
    id: value.id,
    name: value.name,
    status: value.status,
    sourceClass: value.sourceClass,
    originLocationId: value.originLocationId,
    instrumentName: value.instrumentName,
    recordType: value.recordType,
  };
}

function normalizeActionState(value: unknown): PublicActionState | null {
  if (!isRecord(value)) {
    return null;
  }
  const strategicShape = hasOnlyKeys(value, ACTION_KEYS_V24);
  if (
    (!strategicShape && !hasOnlyKeys(value, ACTION_KEYS_V23)) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.description, MAX_TEXT_LENGTH) ||
    (value.status !== "locked" &&
      value.status !== "developing" &&
      value.status !== "available" &&
      value.status !== "completed") ||
    !isNullableBoundedString(value.command, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.locationId, MAX_IDENTIFIER_LENGTH) ||
    !isNonnegativeInteger(value.minimumExaminedEvidenceCount) ||
    !isNonnegativeInteger(value.minimumCompletedActionCount) ||
    !isNonnegativeInteger(value.minimumObservationCount) ||
    !isNullableBoundedString(value.stochasticProcessId, MAX_IDENTIFIER_LENGTH) ||
    !isNullableBoundedString(value.stochasticChannelId, MAX_IDENTIFIER_LENGTH) ||
    typeof value.variableOutcome !== "boolean" ||
    (strategicShape &&
      ((value.strategicClass !== "observe" &&
        value.strategicClass !== "prepare" &&
        value.strategicClass !== "probe" &&
        value.strategicClass !== "secure" &&
        value.strategicClass !== "coordinate" &&
        value.strategicClass !== "commit" &&
        value.strategicClass !== "reconcile") ||
        !isNonnegativeInteger(value.capacityCost) ||
        value.capacityCost > 8 ||
        !isNonnegativeInteger(value.coordinationCost) ||
        value.coordinationCost > 8 ||
        !isNonnegativeInteger(value.supporterCount) ||
        value.supporterCount > 8 ||
        typeof value.irreversible !== "boolean" ||
        (value.stochasticMode !== "none" &&
          value.stochasticMode !== "emit_only" &&
          value.stochasticMode !== "intervention_then_emit")))
  ) {
    return null;
  }
  const requiredRoleIds = normalizeIdentifierArray(value.requiredRoleIds);
  const requiredEvidenceIds = normalizeIdentifierArray(value.requiredEvidenceIds);
  const candidateEvidenceIds = normalizeIdentifierArray(value.candidateEvidenceIds);
  const requiredActionIds = normalizeIdentifierArray(value.requiredActionIds);
  const candidateActionIds = normalizeIdentifierArray(value.candidateActionIds);
  const requiredStochasticProcessIds = normalizeIdentifierArray(
    value.requiredStochasticProcessIds,
  );
  const blockers = normalizeIdentifierArray(value.blockers);
  if (
    requiredRoleIds === null ||
    requiredEvidenceIds === null ||
    candidateEvidenceIds === null ||
    requiredActionIds === null ||
    candidateActionIds === null ||
    requiredStochasticProcessIds === null ||
    blockers === null ||
    value.minimumExaminedEvidenceCount > candidateEvidenceIds.length ||
    value.minimumCompletedActionCount > candidateActionIds.length ||
    (value.minimumObservationCount > 0 && requiredStochasticProcessIds.length === 0)
  ) {
    return null;
  }
  if (
    (value.stochasticProcessId === null) !==
      (value.stochasticChannelId === null) ||
    value.variableOutcome !== (value.stochasticProcessId !== null) ||
    (value.status === "available" && value.command === null)
  ) {
    return null;
  }
  return {
    id: value.id,
    title: value.title,
    description: value.description,
    status: value.status,
    command: value.command,
    locationId: value.locationId,
    requiredRoleIds,
    requiredEvidenceIds,
    candidateEvidenceIds,
    minimumExaminedEvidenceCount: value.minimumExaminedEvidenceCount,
    requiredActionIds,
    candidateActionIds,
    minimumCompletedActionCount: value.minimumCompletedActionCount,
    requiredStochasticProcessIds,
    minimumObservationCount: value.minimumObservationCount,
    blockers,
    stochasticProcessId: value.stochasticProcessId,
    stochasticChannelId: value.stochasticChannelId,
    variableOutcome: value.variableOutcome,
    strategicClass: strategicShape
      ? (value.strategicClass as PublicStrategicClass)
      : null,
    capacityCost: strategicShape ? (value.capacityCost as number) : 0,
    coordinationCost: strategicShape ? (value.coordinationCost as number) : 0,
    supporterCount: strategicShape ? (value.supporterCount as number) : 0,
    irreversible: strategicShape ? (value.irreversible as boolean) : false,
    stochasticMode: strategicShape
      ? (value.stochasticMode as PublicStochasticMode)
      : "none",
  };
}

function normalizeCompletionRoute(value: unknown): PublicCompletionRoute | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ROUTE_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.description, MAX_TEXT_LENGTH) ||
    (value.status !== "available" && value.status !== "complete") ||
    !isBoundedString(value.progress, MAX_TEXT_LENGTH) ||
    !isNonnegativeInteger(value.minimumCompletedActionCount) ||
    !isNonnegativeInteger(value.completedCandidateCount) ||
    !isNonnegativeInteger(value.minimumObservationCount) ||
    !isNonnegativeInteger(value.observationCount)
  ) {
    return null;
  }
  const requiredActionIds = normalizeIdentifierArray(value.requiredActionIds);
  const candidateActionIds = normalizeIdentifierArray(value.candidateActionIds);
  const requiredStochasticProcessIds = normalizeIdentifierArray(
    value.requiredStochasticProcessIds,
  );
  if (
    requiredActionIds === null ||
    candidateActionIds === null ||
    requiredStochasticProcessIds === null ||
    value.minimumCompletedActionCount > candidateActionIds.length ||
    value.completedCandidateCount > candidateActionIds.length
  ) {
    return null;
  }
  return {
    id: value.id,
    title: value.title,
    description: value.description,
    status: value.status,
    progress: value.progress,
    requiredActionIds,
    candidateActionIds,
    minimumCompletedActionCount: value.minimumCompletedActionCount,
    completedCandidateCount: value.completedCandidateCount,
    requiredStochasticProcessIds,
    minimumObservationCount: value.minimumObservationCount,
    observationCount: value.observationCount,
  };
}

function normalizeModelSupport(value: unknown): PublicModelSupport | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, MODEL_SUPPORT_KEYS) ||
    !isBoundedString(value.modelId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.label, MAX_LABEL_LENGTH) ||
    !isNonnegativeInteger(value.basisPoints) ||
    value.basisPoints > 10_000 ||
    !isFiniteNumber(value.percent) ||
    value.percent < 0 ||
    value.percent > 100 ||
    Math.abs(value.percent * 100 - value.basisPoints) > 0.001
  ) {
    return null;
  }
  return {
    modelId: value.modelId,
    label: value.label,
    basisPoints: value.basisPoints,
    percent: value.percent,
  };
}

function normalizeStochasticProcess(value: unknown): PublicStochasticProcess | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, PROCESS_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.description, MAX_TEXT_LENGTH) ||
    !isBoundedString(value.locationId, MAX_IDENTIFIER_LENGTH) ||
    (value.algorithm !== "hidden_markov" && value.algorithm !== "semi_markov") ||
    !isNonnegativeInteger(value.algorithmVersion) ||
    value.algorithmVersion < 1 ||
    !isNonnegativeInteger(value.observationCount) ||
    (value.lastSequence !== null && !isNonnegativeInteger(value.lastSequence)) ||
    !isNullableBoundedString(value.observedState, MAX_LABEL_LENGTH)
  ) {
    return null;
  }
  const modelSupport = normalizeArray(
    value.modelSupport,
    MAX_PUBLIC_MODELS,
    normalizeModelSupport,
  );
  if (
    modelSupport === null ||
    modelSupport.length === 0 ||
    !hasUniqueValues(modelSupport, (item) => item.modelId) ||
    modelSupport.reduce((sum, item) => sum + item.basisPoints, 0) !== 10_000
  ) {
    return null;
  }
  return {
    id: value.id,
    title: value.title,
    description: value.description,
    locationId: value.locationId,
    algorithm: value.algorithm,
    algorithmVersion: value.algorithmVersion,
    observationCount: value.observationCount,
    lastSequence: value.lastSequence,
    observedState: value.observedState,
    modelSupport,
  };
}

function normalizeMeasurement(value: unknown): PublicStochasticMeasurement | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, MEASUREMENT_KEYS) ||
    !isBoundedString(value.key, MAX_IDENTIFIER_LENGTH) ||
    (typeof value.value !== "string" &&
      typeof value.value !== "number" &&
      typeof value.value !== "boolean") ||
    (typeof value.value === "number" && !Number.isFinite(value.value)) ||
    !isNullableBoundedString(value.unit, MAX_LABEL_LENGTH) ||
    !isNullableBoundedString(value.uncertainty, MAX_TEXT_LENGTH)
  ) {
    return null;
  }
  return {
    key: value.key,
    value: value.value,
    unit: value.unit,
    uncertainty: value.uncertainty,
  };
}

function normalizeStochasticObservation(
  value: unknown,
): PublicStochasticObservation | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, OBSERVATION_KEYS) ||
    !isBoundedString(value.processId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.actionId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.channelId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.outcomeId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.summary, MAX_TEXT_LENGTH) ||
    !isNonnegativeInteger(value.sequence) ||
    value.sequence < 1 ||
    !isNullableBoundedString(value.observedState, MAX_LABEL_LENGTH)
  ) {
    return null;
  }
  const measurements = normalizeArray(
    value.measurements,
    MAX_PUBLIC_MEASUREMENTS,
    normalizeMeasurement,
  );
  if (
    measurements === null ||
    !hasUniqueValues(measurements, (item) => item.key)
  ) {
    return null;
  }
  return {
    processId: value.processId,
    actionId: value.actionId,
    channelId: value.channelId,
    outcomeId: value.outcomeId,
    summary: value.summary,
    sequence: value.sequence,
    observedState: value.observedState,
    measurements,
  };
}

function normalizeCampaignTrack(value: unknown): PublicCampaignTrack | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, CAMPAIGN_TRACK_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.label, MAX_LABEL_LENGTH) ||
    !isNonnegativeInteger(value.minimum) ||
    !isNonnegativeInteger(value.maximum) ||
    !isNonnegativeInteger(value.value) ||
    value.minimum >= value.maximum ||
    value.value < value.minimum ||
    value.value > value.maximum
  ) {
    return null;
  }
  return {
    id: value.id,
    label: value.label,
    value: value.value,
    minimum: value.minimum,
    maximum: value.maximum,
  };
}

function normalizeStrategicResource(
  value: unknown,
): PublicStrategicResource | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, STRATEGIC_RESOURCE_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isNonnegativeInteger(value.minimum) ||
    !isNonnegativeInteger(value.maximum) ||
    !isNonnegativeInteger(value.value) ||
    value.minimum >= value.maximum ||
    value.value < value.minimum ||
    value.value > value.maximum
  ) {
    return null;
  }
  return {
    id: value.id,
    title: value.title,
    value: value.value,
    minimum: value.minimum,
    maximum: value.maximum,
  };
}

function normalizeStrategicCondition(
  value: unknown,
): PublicStrategicCondition | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, STRATEGIC_CONDITION_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.label, MAX_LABEL_LENGTH) ||
    (value.duration !== "round" &&
      value.duration !== "next_round" &&
      value.duration !== "position" &&
      value.duration !== "campaign") ||
    !isNonnegativeInteger(value.createdRound) ||
    value.createdRound < 1 ||
    (value.expiresAfterRound !== null &&
      (!isNonnegativeInteger(value.expiresAfterRound) ||
        value.expiresAfterRound < value.createdRound))
  ) {
    return null;
  }
  return {
    id: value.id,
    label: value.label,
    duration: value.duration,
    createdRound: value.createdRound,
    expiresAfterRound: value.expiresAfterRound,
  };
}

function normalizeStrategicProposal(
  value: unknown,
): PublicStrategicProposal | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, STRATEGIC_PROPOSAL_KEYS) ||
    !isBoundedString(value.proposalId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.actionId, MAX_IDENTIFIER_LENGTH) ||
    !isNonnegativeInteger(value.roundIndex) ||
    value.roundIndex < 1 ||
    !isNonnegativeInteger(value.requiredSupporterCount) ||
    value.requiredSupporterCount < 1 ||
    !isNonnegativeInteger(value.currentSupporterCount) ||
    value.currentSupporterCount > value.requiredSupporterCount ||
    (value.status !== "active" &&
      value.status !== "resolved" &&
      value.status !== "expired") ||
    !isBoundedString(value.command, MAX_LABEL_LENGTH)
  ) {
    return null;
  }
  return {
    proposalId: value.proposalId,
    actionId: value.actionId,
    roundIndex: value.roundIndex,
    requiredSupporterCount: value.requiredSupporterCount,
    currentSupporterCount: value.currentSupporterCount,
    status: value.status,
    command: value.command,
  };
}

function normalizeStrategicBoard(value: unknown): PublicStrategicBoard | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, STRATEGIC_BOARD_KEYS) ||
    !isBoundedString(value.positionId, MAX_IDENTIFIER_LENGTH) ||
    !isNonnegativeInteger(value.roundIndex) ||
    value.roundIndex < 1 ||
    !isNonnegativeInteger(value.maxRounds) ||
    value.maxRounds < value.roundIndex ||
    !isNonnegativeInteger(value.capacityRemaining) ||
    !isNonnegativeInteger(value.capacityPerRound) ||
    value.capacityPerRound < 1 ||
    value.capacityRemaining > value.capacityPerRound ||
    !isNonnegativeInteger(value.coordination) ||
    !isNonnegativeInteger(value.coordinationMaximum) ||
    value.coordination > value.coordinationMaximum ||
    !isNonnegativeInteger(value.escalation) ||
    !isNonnegativeInteger(value.escalationMaximum) ||
    value.escalation > value.escalationMaximum ||
    typeof value.forcedReview !== "boolean"
  ) {
    return null;
  }
  const localResource = normalizeStrategicResource(value.localResource);
  const conditions = normalizeArray(
    value.conditions,
    MAX_STRATEGIC_CONDITIONS,
    normalizeStrategicCondition,
  );
  const proposals = normalizeArray(
    value.proposals,
    MAX_STRATEGIC_PROPOSALS,
    normalizeStrategicProposal,
  );
  if (
    localResource === null ||
    conditions === null ||
    proposals === null ||
    !hasUniqueValues(conditions, (item) => item.id) ||
    !hasUniqueValues(proposals, (item) => item.proposalId) ||
    proposals.some((item) => item.roundIndex !== value.roundIndex)
  ) {
    return null;
  }
  return {
    positionId: value.positionId,
    roundIndex: value.roundIndex,
    maxRounds: value.maxRounds,
    capacityRemaining: value.capacityRemaining,
    capacityPerRound: value.capacityPerRound,
    coordination: value.coordination,
    coordinationMaximum: value.coordinationMaximum,
    escalation: value.escalation,
    escalationMaximum: value.escalationMaximum,
    localResource,
    conditions,
    proposals,
    forcedReview: value.forcedReview,
  };
}

function normalizeStrategicOutcome(
  value: unknown,
): PublicStrategicOutcome | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, STRATEGIC_OUTCOME_KEYS) ||
    !isBoundedString(value.positionId, MAX_IDENTIFIER_LENGTH) ||
    (value.grade !== "controlled" &&
      value.grade !== "compromised" &&
      value.grade !== "incomplete" &&
      value.grade !== "critical") ||
    !isNonnegativeInteger(value.roundIndex) ||
    value.roundIndex < 1 ||
    !isNonnegativeInteger(value.caseIntegrity) ||
    !isNonnegativeInteger(value.institutionalTrust) ||
    !isNonnegativeInteger(value.escalation)
  ) {
    return null;
  }
  const assetIds = normalizeIdentifierArray(value.assetIds);
  const liabilityIds = normalizeIdentifierArray(value.liabilityIds);
  if (assetIds === null || liabilityIds === null) {
    return null;
  }
  return {
    positionId: value.positionId,
    grade: value.grade,
    roundIndex: value.roundIndex,
    caseIntegrity: value.caseIntegrity,
    institutionalTrust: value.institutionalTrust,
    escalation: value.escalation,
    assetIds,
    liabilityIds,
  };
}

function normalizeCampaignModifier(
  value: unknown,
): PublicCampaignModifier | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, CAMPAIGN_MODIFIER_KEYS) ||
    !isBoundedString(value.id, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.label, MAX_LABEL_LENGTH)
  ) {
    return null;
  }
  return { id: value.id, label: value.label };
}

function normalizeArray<T>(
  value: unknown,
  maximumLength: number,
  normalizeItem: (item: unknown) => T | null,
): T[] | null {
  if (!Array.isArray(value) || value.length > maximumLength) {
    return null;
  }
  const normalized: T[] = [];
  for (const item of value) {
    const result = normalizeItem(item);
    if (result === null) {
      return null;
    }
    normalized.push(result);
  }
  return normalized;
}

function hasUniqueValues<T>(
  values: readonly T[],
  select: (value: T) => string | number,
): boolean {
  const seen = new Set<string | number>();
  for (const value of values) {
    const selected = select(value);
    if (seen.has(selected)) {
      return false;
    }
    seen.add(selected);
  }
  return true;
}

export function normalizePublicActivitySnapshot(
  value: unknown,
): PublicActivitySnapshot | null {
  if (
    !isRecord(value) ||
    (value.schemaVersion !== "2.0.0" &&
      value.schemaVersion !== "2.1.0" &&
      value.schemaVersion !== "2.2.0" &&
      value.schemaVersion !== "2.3.0" &&
      value.schemaVersion !== "2.4.0") ||
    !hasOnlyKeys(
      value,
      value.schemaVersion === "2.0.0"
        ? ROOT_KEYS_V20
        : value.schemaVersion === "2.1.0"
          ? ROOT_KEYS_V21
          : value.schemaVersion === "2.4.0"
            ? ROOT_KEYS_V24
            : value.schemaVersion === "2.3.0"
              ? ROOT_KEYS_V23
              : "contentVersion" in value
              ? ROOT_KEYS_V22
              : ROOT_KEYS_V22_LEGACY,
    ) ||
    (value.source !== "mock" && value.source !== "hypha") ||
    !isEnvironment(value.environment) ||
    !isNonnegativeInteger(value.revision) ||
    !isBoundedString(value.stateHeadHash, MAX_IDENTIFIER_LENGTH) ||
    (value.previousStateHeadHash !== null &&
      !isBoundedString(value.previousStateHeadHash, MAX_IDENTIFIER_LENGTH)) ||
    !isBoundedString(value.positionId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.positionTitle, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.focusLocationId, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.updatedAt, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.zuluTime, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.facilityTime, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.facilityTimezone, MAX_IDENTIFIER_LENGTH) ||
    !isBoundedString(value.nextRequirement, MAX_TEXT_LENGTH)
  ) {
    return null;
  }

  const metrics = normalizeMetrics(value.metrics);
  const locations = normalizeArray(
    value.locations,
    MAX_LOCATIONS,
    normalizeLocation,
  );
  const assignments = normalizeArray(
    value.assignments,
    MAX_ASSIGNMENTS,
    normalizeAssignment,
  );
  const latestPublication =
    value.latestPublication === null
      ? null
      : normalizePublication(value.latestPublication);
  if (
    metrics === null ||
    locations === null ||
    assignments === null ||
    (value.latestPublication !== null && latestPublication === null) ||
    !hasUniqueValues(locations, (location) => location.id) ||
    !hasUniqueValues(assignments, (assignment) => assignment.assignmentId)
  ) {
    return null;
  }

  const locationIds = new Set(locations.map((location) => location.id));
  const focusLocations = locations.filter(
    (location) => location.status === "focus",
  );
  if (
    !locationIds.has(value.focusLocationId) ||
    focusLocations.length !== 1 ||
    focusLocations[0].id !== value.focusLocationId ||
    assignments.some((assignment) => !locationIds.has(assignment.locationId))
  ) {
    return null;
  }

  const common: PublicActivitySnapshotBase = {
    source: value.source,
    environment: value.environment,
    revision: value.revision,
    stateHeadHash: value.stateHeadHash,
    previousStateHeadHash: value.previousStateHeadHash,
    positionId: value.positionId,
    positionTitle: value.positionTitle,
    focusLocationId: value.focusLocationId,
    updatedAt: value.updatedAt,
    zuluTime: value.zuluTime,
    facilityTime: value.facilityTime,
    facilityTimezone: value.facilityTimezone,
    metrics,
    locations,
    assignments,
    latestPublication,
    nextRequirement: value.nextRequirement,
  };

  if (value.schemaVersion === "2.0.0") {
    return {
      schemaVersion: "2.0.0",
      ...common,
    };
  }

  const positions = normalizeArray(
    value.positions,
    MAX_POSITIONS,
    normalizePosition,
  );
  if (
    positions === null ||
    positions.length !== PUBLIC_POSITION_CONTRACT.length ||
    !hasUniqueValues(positions, (position) => position.id) ||
    !hasUniqueValues(positions, (position) => position.ordinal) ||
    positions.some(
      (position, index) =>
        position.ordinal !== index,
    ) ||
    positions.some((position, index) => {
      const expected = PUBLIC_POSITION_CONTRACT[index];
      return (
        !expected ||
        position.id !== expected.id ||
        position.ordinal !== expected.ordinal ||
        position.title !== expected.title ||
        !expected.locationIds.some(
          (locationId) => locationId === position.locationId,
        ) ||
        !locationIds.has(position.locationId)
      );
    }) ||
    !positions.some((position) => position.id === value.positionId)
  ) {
    return null;
  }

  const currentPosition = positions.find(
    (position) => position.id === value.positionId,
  );
  const availablePositions = positions.filter(
    (position) => position.progression === "available",
  );
  if (
    !currentPosition ||
    currentPosition.title !== value.positionTitle ||
    currentPosition.locationId !== value.focusLocationId ||
    currentPosition.progression === "locked" ||
    availablePositions.length > 1 ||
    (availablePositions.length === 1 &&
      availablePositions[0].id !== currentPosition.id)
  ) {
    return null;
  }

  if (value.schemaVersion === "2.1.0") {
    return {
      schemaVersion: "2.1.0",
      ...common,
      positions,
    };
  }

  const adaptivePresentation =
    value.adaptivePresentation === null
      ? null
      : normalizeAdaptivePresentation(value.adaptivePresentation);
  if (
    value.adaptivePresentation !== null &&
    adaptivePresentation === null
  ) {
    return null;
  }
  if (
    adaptivePresentation !== null &&
    adaptivePresentation.targetId !== value.positionId &&
    adaptivePresentation.targetId !== "ending"
  ) {
    return null;
  }
  const contentVersion =
    value.contentVersion === undefined ? "legacy" : value.contentVersion;
  if (!isBoundedString(contentVersion, MAX_IDENTIFIER_LENGTH)) {
    return null;
  }
  if (value.schemaVersion === "2.2.0") {
    return {
      schemaVersion: "2.2.0",
      contentVersion,
      ...common,
      positions,
      adaptivePresentation,
    };
  }

  if (
    !isNonnegativeInteger(value.sequence) ||
    (value.casePhase !== "establish" &&
      value.casePhase !== "perturb" &&
      value.casePhase !== "reconcile" &&
      value.casePhase !== "review" &&
      value.casePhase !== "complete")
  ) {
    return null;
  }
  const evidence = normalizeArray(
    value.evidence,
    MAX_PUBLIC_EVIDENCE,
    normalizeEvidenceState,
  );
  const actions = normalizeArray(
    value.actions,
    MAX_PUBLIC_ACTIONS,
    normalizeActionState,
  );
  const completionRoutes = normalizeArray(
    value.completionRoutes,
    MAX_PUBLIC_ROUTES,
    normalizeCompletionRoute,
  );
  const stochasticProcesses = normalizeArray(
    value.stochasticProcesses,
    MAX_PUBLIC_PROCESSES,
    normalizeStochasticProcess,
  );
  const recentObservations = normalizeArray(
    value.recentObservations,
    MAX_PUBLIC_OBSERVATIONS,
    normalizeStochasticObservation,
  );
  if (
    evidence === null ||
    actions === null ||
    completionRoutes === null ||
    stochasticProcesses === null ||
    recentObservations === null ||
    !hasUniqueValues(evidence, (item) => item.id) ||
    !hasUniqueValues(actions, (item) => item.id) ||
    !hasUniqueValues(completionRoutes, (item) => item.id) ||
    !hasUniqueValues(stochasticProcesses, (item) => item.id) ||
    actions.some((item) => !locationIds.has(item.locationId)) ||
    evidence.some((item) => !locationIds.has(item.originLocationId)) ||
    stochasticProcesses.some((item) => !locationIds.has(item.locationId)) ||
    recentObservations.some(
      (item) =>
        !stochasticProcesses.some((process) => process.id === item.processId),
    )
  ) {
    return null;
  }
  const stochasticCommon = {
    contentVersion,
    sequence: value.sequence,
    casePhase: value.casePhase,
    ...common,
    positions,
    adaptivePresentation,
    evidence,
    actions,
    completionRoutes,
    stochasticProcesses,
    recentObservations,
  } as const;
  if (value.schemaVersion === "2.3.0") {
    return {
      schemaVersion: "2.3.0",
      ...stochasticCommon,
    };
  }

  const campaignTracks = normalizeArray(
    value.campaignTracks,
    MAX_CAMPAIGN_TRACKS,
    normalizeCampaignTrack,
  );
  const strategicBoard =
    value.strategicBoard === null
      ? null
      : normalizeStrategicBoard(value.strategicBoard);
  const strategicOutcomes = normalizeArray(
    value.strategicOutcomes,
    MAX_STRATEGIC_OUTCOMES,
    normalizeStrategicOutcome,
  );
  const campaignModifiers = normalizeArray(
    value.campaignModifiers,
    MAX_CAMPAIGN_MODIFIERS,
    normalizeCampaignModifier,
  );
  if (
    campaignTracks === null ||
    strategicOutcomes === null ||
    campaignModifiers === null ||
    (value.strategicBoard !== null && strategicBoard === null) ||
    !hasUniqueValues(campaignTracks, (item) => item.id) ||
    !hasUniqueValues(strategicOutcomes, (item) => item.positionId) ||
    !hasUniqueValues(campaignModifiers, (item) => item.id) ||
    (strategicBoard !== null && strategicBoard.positionId !== value.positionId) ||
    strategicBoard?.proposals.some(
      (proposal) => !actions.some((action) => action.id === proposal.actionId),
    )
  ) {
    return null;
  }
  return {
    schemaVersion: "2.4.0",
    ...stochasticCommon,
    campaignTracks,
    strategicBoard,
    strategicOutcomes,
    campaignModifiers,
  };
}

export function isPublicActivitySnapshot(
  value: unknown,
): value is PublicActivitySnapshot {
  return normalizePublicActivitySnapshot(value) !== null;
}

export const MOCK_PUBLIC_STATE: PublicActivitySnapshot = {
  schemaVersion: "2.0.0",
  source: "mock",
  environment: "test",
  revision: 0,
  stateHeadHash: "phase2-preview-8f21c7",
  previousStateHeadHash: null,
  positionId: "position-0",
  positionTitle: "The First Bad Timestamp",
  focusLocationId: "interfacility-intake",
  updatedAt: "2026-07-24T23:17:12Z",
  zuluTime: "23:17Z",
  facilityTime: "16:17",
  facilityTimezone: "Pacific",
  metrics: {
    activeAssignments: 3,
    completedArtifacts: 1,
    unresolvedContradictions: 2,
    awaitingVerification: 1,
  },
  locations: [
    {
      id: "interfacility-intake",
      name: "Interfacility Intake",
      shortName: "Intake",
      status: "focus",
      timezone: "America/Los_Angeles",
      activeAssignments: 3,
    },
    {
      id: "boundary-array",
      name: "Boundary Array",
      shortName: "Boundary",
      status: "available",
      timezone: "America/Los_Angeles",
      activeAssignments: 0,
    },
    {
      id: "aeronautical-incident-center",
      name: "Aeronautical Incident Center",
      shortName: "Aeronautical",
      status: "locked",
      timezone: "America/New_York",
      activeAssignments: 0,
    },
    {
      id: "aerial-phenomena-archive",
      name: "Aerial Phenomena Archive",
      shortName: "Archive",
      status: "locked",
      timezone: "America/Chicago",
      activeAssignments: 0,
    },
    {
      id: "holography-laboratory",
      name: "Holography Laboratory",
      shortName: "Holography",
      status: "locked",
      timezone: "America/Denver",
      activeAssignments: 0,
    },
    {
      id: "subsurface-resonance-station",
      name: "Subsurface Resonance Station",
      shortName: "Subsurface",
      status: "locked",
      timezone: "America/Los_Angeles",
      activeAssignments: 0,
    },
    {
      id: "quantum-state-institute",
      name: "Quantum State Institute",
      shortName: "Quantum",
      status: "locked",
      timezone: "America/New_York",
      activeAssignments: 0,
    },
  ],
  assignments: [
    {
      assignmentId: "assignment-signal-reader",
      workingName: "Primary Investigator",
      roleTitle: "Signal Reader",
      locationId: "interfacility-intake",
      station: "Routing Terminal",
      status: "examining",
      paletteToken: "cyan-03",
    },
    {
      assignmentId: "assignment-records-custodian",
      workingName: "Unclaimed Review Seat",
      roleTitle: "Records Custodian",
      locationId: "interfacility-intake",
      station: "Quarantine Archive",
      status: "examining",
      paletteToken: "rust-02",
    },
    {
      assignmentId: "assignment-protocol-auditor",
      workingName: "Unclaimed Audit Seat",
      roleTitle: "Protocol Auditor",
      locationId: "interfacility-intake",
      station: "Intake Desk",
      status: "awaiting-review",
      paletteToken: "blue-04",
    },
  ],
  latestPublication: {
    publicationId: "publication-phase2-preview",
    artifactId: "artifact-phase2-preview",
    title: "SR-03 packet timing reconstruction",
    institution: "Interfacility Intake",
    finding:
      "The declared transmission time follows the verified receipt time by three seconds.",
    limitation:
      "A misconfigured source clock remains a viable ordinary explanation.",
    status: "preview",
    primaryAsset: null,
    manifestUrl: null,
  },
  nextRequirement:
    "A different participant must verify, qualify, or dispute the provisional timing assessment.",
};
