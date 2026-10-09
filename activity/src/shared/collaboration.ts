import type { EnvironmentName } from "./public-state";

export const COLLABORATION_SCHEMA_VERSION = "4.0.0" as const;

export interface RoomParticipant {
  participantId: string;
  displayName: string;
  avatarUrl: string | null;
}

export interface SharedLayerState {
  raw: boolean;
  calibrated: boolean;
  residual: boolean;
  uncertainty: boolean;
  events: boolean;
  quality: boolean;
}

export interface SharedViewState {
  artifactId: string;
  visualizationId: string;
  minimumSeconds: number;
  maximumSeconds: number;
  startSeconds: number;
  endSeconds: number;
  timeBasis: string;
  layers: SharedLayerState;
  selectedEventId: string | null;
  revision: number;
  updatedAt: string;
  updatedBy: string | null;
}

export interface RoomSnapshot {
  schemaVersion: typeof COLLABORATION_SCHEMA_VERSION;
  environment: EnvironmentName;
  roomId: string;
  presenterParticipantId: string | null;
  participants: RoomParticipant[];
  connectionCount: number;
  view: SharedViewState;
}

export interface SharedViewPatch {
  startSeconds?: number;
  endSeconds?: number;
  timeBasis?: string;
  layers?: Partial<SharedLayerState>;
  selectedEventId?: string | null;
}

export type RoomClientMessage =
  | {
      type: "view-patch";
      baseRevision: number;
      patch: SharedViewPatch;
    }
  | {
      type: "claim-presenter";
    }
  | {
      type: "release-presenter";
    }
  | {
      type: "ping";
      sentAt: string;
    };

export type RoomServerMessage =
  | {
      type: "room-ready" | "room-snapshot";
      snapshot: RoomSnapshot;
    }
  | {
      type: "room-error";
      code: string;
      message: string;
      snapshot?: RoomSnapshot;
    }
  | {
      type: "pong";
      sentAt: string;
      receivedAt: string;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isSafeInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isSafeInteger(value);
}

function hasString(record: Record<string, unknown>, key: string): boolean {
  return typeof record[key] === "string" && (record[key] as string).length > 0;
}

function isEnvironment(value: unknown): value is EnvironmentName {
  return value === "live" || value === "test";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function defaultSharedLayers(): SharedLayerState {
  return {
    raw: true,
    calibrated: true,
    residual: false,
    uncertainty: true,
    events: true,
    quality: true,
  };
}

export function createInitialSharedView(input: {
  artifactId: string;
  visualizationId: string;
  minimumSeconds: number;
  maximumSeconds: number;
  timeBasis?: string;
}): SharedViewState {
  return {
    artifactId: input.artifactId,
    visualizationId: input.visualizationId,
    minimumSeconds: input.minimumSeconds,
    maximumSeconds: input.maximumSeconds,
    startSeconds: input.minimumSeconds,
    endSeconds: input.maximumSeconds,
    timeBasis: input.timeBasis ?? "Zulu",
    layers: defaultSharedLayers(),
    selectedEventId: null,
    revision: 0,
    updatedAt: new Date(0).toISOString(),
    updatedBy: null,
  };
}

export function sanitizeRoomId(value: string): string {
  const trimmed = value.trim();
  if (!/^[A-Za-z0-9._:-]{1,128}$/.test(trimmed)) {
    throw new Error("Room identifiers must contain 1-128 letters, digits, dots, underscores, colons, or hyphens.");
  }
  return trimmed;
}

export function applySharedViewPatch(
  current: SharedViewState,
  patch: SharedViewPatch,
  participantId: string,
  updatedAt: string,
): SharedViewState {
  const startSeconds = patch.startSeconds ?? current.startSeconds;
  const endSeconds = patch.endSeconds ?? current.endSeconds;

  if (!Number.isFinite(startSeconds) || !Number.isFinite(endSeconds)) {
    throw new Error("Shared time-window values must be finite numbers.");
  }
  if (startSeconds < current.minimumSeconds || endSeconds > current.maximumSeconds) {
    throw new Error("Shared time window is outside the published dataset bounds.");
  }
  if (endSeconds <= startSeconds) {
    throw new Error("Shared time window must have positive duration.");
  }
  const minimumSpan = Math.max(
    0.000001,
    (current.maximumSeconds - current.minimumSeconds) / 100_000,
  );
  if (endSeconds - startSeconds < minimumSpan) {
    throw new Error("Shared time window is too narrow.");
  }

  const timeBasis = patch.timeBasis ?? current.timeBasis;
  if (!timeBasis.trim() || timeBasis.length > 80) {
    throw new Error("Shared time basis must contain 1-80 characters.");
  }

  const selectedEventId =
    patch.selectedEventId === undefined
      ? current.selectedEventId
      : patch.selectedEventId;
  if (selectedEventId !== null && !/^[A-Za-z0-9._:-]{1,128}$/.test(selectedEventId)) {
    throw new Error("Selected event identifier has an invalid format.");
  }

  const layers: SharedLayerState = {
    ...current.layers,
    ...(patch.layers ?? {}),
  };
  if (!Object.values(layers).every((value) => typeof value === "boolean")) {
    throw new Error("Shared layer values must be booleans.");
  }

  return {
    ...current,
    startSeconds,
    endSeconds,
    timeBasis,
    layers,
    selectedEventId,
    revision: current.revision + 1,
    updatedAt,
    updatedBy: participantId,
  };
}

function isParticipant(value: unknown): value is RoomParticipant {
  if (!isRecord(value)) return false;
  return (
    hasString(value, "participantId") &&
    hasString(value, "displayName") &&
    (value.avatarUrl === null || typeof value.avatarUrl === "string")
  );
}

function isLayerState(value: unknown): value is SharedLayerState {
  if (!isRecord(value)) return false;
  return ["raw", "calibrated", "residual", "uncertainty", "events", "quality"].every(
    (key) => typeof value[key] === "boolean",
  );
}

export function isSharedViewState(value: unknown): value is SharedViewState {
  if (!isRecord(value)) return false;
  return (
    hasString(value, "artifactId") &&
    hasString(value, "visualizationId") &&
    isFiniteNumber(value.minimumSeconds) &&
    isFiniteNumber(value.maximumSeconds) &&
    isFiniteNumber(value.startSeconds) &&
    isFiniteNumber(value.endSeconds) &&
    hasString(value, "timeBasis") &&
    isLayerState(value.layers) &&
    isNullableString(value.selectedEventId) &&
    isSafeInteger(value.revision) &&
    hasString(value, "updatedAt") &&
    isNullableString(value.updatedBy)
  );
}

export function isRoomSnapshot(value: unknown): value is RoomSnapshot {
  if (!isRecord(value)) return false;
  return (
    value.schemaVersion === COLLABORATION_SCHEMA_VERSION &&
    isEnvironment(value.environment) &&
    hasString(value, "roomId") &&
    isNullableString(value.presenterParticipantId) &&
    Array.isArray(value.participants) &&
    value.participants.every(isParticipant) &&
    isSafeInteger(value.connectionCount) &&
    isSharedViewState(value.view)
  );
}

export function isRoomServerMessage(value: unknown): value is RoomServerMessage {
  if (!isRecord(value) || !hasString(value, "type")) return false;
  if (value.type === "room-ready" || value.type === "room-snapshot") {
    return isRoomSnapshot(value.snapshot);
  }
  if (value.type === "room-error") {
    return hasString(value, "code") && hasString(value, "message") &&
      (value.snapshot === undefined || isRoomSnapshot(value.snapshot));
  }
  if (value.type === "pong") {
    return hasString(value, "sentAt") && hasString(value, "receivedAt");
  }
  return false;
}

export function parseRoomClientMessage(value: unknown): RoomClientMessage {
  if (!isRecord(value) || typeof value.type !== "string") {
    throw new Error("Room messages must be JSON objects with a type.");
  }
  if (value.type === "claim-presenter" || value.type === "release-presenter") {
    return { type: value.type };
  }
  if (value.type === "ping") {
    if (!hasString(value, "sentAt") || (value.sentAt as string).length > 64) {
      throw new Error("Ping messages require a compact sentAt timestamp.");
    }
    return { type: "ping", sentAt: value.sentAt as string };
  }
  if (value.type !== "view-patch") {
    throw new Error("Unsupported room message type.");
  }
  if (!isSafeInteger(value.baseRevision) || !isRecord(value.patch)) {
    throw new Error("View patches require a baseRevision and patch object.");
  }

  const source = value.patch;
  const allowed = new Set([
    "startSeconds",
    "endSeconds",
    "timeBasis",
    "layers",
    "selectedEventId",
  ]);
  if (Object.keys(source).some((key) => !allowed.has(key))) {
    throw new Error("View patch contains an unsupported field.");
  }
  if (
    source.startSeconds !== undefined &&
    !isFiniteNumber(source.startSeconds)
  ) {
    throw new Error("startSeconds must be finite.");
  }
  if (source.endSeconds !== undefined && !isFiniteNumber(source.endSeconds)) {
    throw new Error("endSeconds must be finite.");
  }
  if (source.timeBasis !== undefined && typeof source.timeBasis !== "string") {
    throw new Error("timeBasis must be a string.");
  }
  if (
    source.selectedEventId !== undefined &&
    source.selectedEventId !== null &&
    typeof source.selectedEventId !== "string"
  ) {
    throw new Error("selectedEventId must be a string or null.");
  }
  if (source.layers !== undefined) {
    if (!isRecord(source.layers)) {
      throw new Error("layers must be an object.");
    }
    const layerKeys = new Set([
      "raw",
      "calibrated",
      "residual",
      "uncertainty",
      "events",
      "quality",
    ]);
    if (
      Object.entries(source.layers).some(
        ([key, layerValue]) => !layerKeys.has(key) || typeof layerValue !== "boolean",
      )
    ) {
      throw new Error("layers contains an unsupported key or non-boolean value.");
    }
  }

  return {
    type: "view-patch",
    baseRevision: value.baseRevision,
    patch: source as SharedViewPatch,
  };
}
