import type { DynamicalDatasetId } from "./dynamical-data";

export const DYNAMICAL_RENDER_MANIFEST_ROUTE =
  "/api/map/dynamical/manifest" as const;

export type DynamicalRenderCoordinates = readonly [
  readonly [number, number],
  readonly [number, number],
  readonly [number, number],
  readonly [number, number],
];

interface DynamicalRenderMetadata {
  datasetId: DynamicalDatasetId;
  generatedAt: string;
  validTime: string;
  variable: string;
  units: string;
  attribution: string;
  status: string;
}

export interface DynamicalImageRenderManifest extends DynamicalRenderMetadata {
  kind: "image";
  url: string;
  coordinates: DynamicalRenderCoordinates;
}

export interface DynamicalGeoJsonRenderManifest extends DynamicalRenderMetadata {
  kind: "geojson";
  data: {
    type: "FeatureCollection";
    features: unknown[];
  };
}

export type DynamicalRenderManifest =
  | DynamicalImageRenderManifest
  | DynamicalGeoJsonRenderManifest;

export interface DynamicalRenderRequest {
  datasetId: DynamicalDatasetId;
  bbox: readonly [number, number, number, number];
  width: number;
  height: number;
  time?: string | null;
}

export class DynamicalRenderManifestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DynamicalRenderManifestError";
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function boundedText(value: unknown, label: string, maximum = 500): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) {
    throw new DynamicalRenderManifestError(`The render ${label} is invalid.`);
  }
  return value;
}

function isoTimestamp(value: unknown, label: string): string {
  const text = boundedText(value, label, 64);
  if (!Number.isFinite(Date.parse(text))) {
    throw new DynamicalRenderManifestError(`The render ${label} is invalid.`);
  }
  return text;
}

function finiteCoordinate(value: unknown): readonly [number, number] {
  if (
    !Array.isArray(value) ||
    value.length !== 2 ||
    !Number.isFinite(value[0]) ||
    !Number.isFinite(value[1]) ||
    Number(value[0]) < -180 ||
    Number(value[0]) > 180 ||
    Number(value[1]) < -85.051129 ||
    Number(value[1]) > 85.051129
  ) {
    throw new DynamicalRenderManifestError("The render image coordinates are invalid.");
  }
  return [Number(value[0]), Number(value[1])];
}

function imageCoordinates(value: unknown): DynamicalRenderCoordinates {
  if (!Array.isArray(value) || value.length !== 4) {
    throw new DynamicalRenderManifestError("The render image coordinates are invalid.");
  }
  const coordinates = value.map(finiteCoordinate) as unknown as DynamicalRenderCoordinates;
  const [[west, north], [east, secondNorth], [secondEast, south], [secondWest, secondSouth]] =
    coordinates;
  if (
    west >= east ||
    south >= north ||
    north !== secondNorth ||
    east !== secondEast ||
    south !== secondSouth ||
    west !== secondWest
  ) {
    throw new DynamicalRenderManifestError("The render image bounds are invalid.");
  }
  return coordinates;
}

function safeImageUrl(value: unknown, origin: string): string {
  const raw = boundedText(value, "image URL", 2_000);
  let parsed: URL;
  let base: URL;
  try {
    base = new URL(origin);
    parsed = new URL(raw, origin);
  } catch {
    throw new DynamicalRenderManifestError("The render image URL is invalid.");
  }
  const localDevelopment =
    base.protocol === "http:" &&
    ["localhost", "127.0.0.1"].includes(base.hostname);
  if (
    parsed.origin !== base.origin ||
    (parsed.protocol !== "https:" && !localDevelopment) ||
    parsed.username ||
    parsed.password
  ) {
    throw new DynamicalRenderManifestError("The render image URL must be same-origin HTTPS.");
  }
  return parsed.href;
}

function renderMetadata(
  value: Record<string, unknown>,
  expectedDatasetId: DynamicalDatasetId,
): DynamicalRenderMetadata {
  if (value.datasetId !== expectedDatasetId) {
    throw new DynamicalRenderManifestError("The render returned a different dataset.");
  }
  const status = boundedText(value.status, "status", 80);
  if (!["ready", "complete", "available", "ok"].includes(status.toLowerCase())) {
    throw new DynamicalRenderManifestError(`Renderer status: ${status}.`);
  }
  return {
    datasetId: expectedDatasetId,
    generatedAt: isoTimestamp(value.generatedAt, "generation time"),
    validTime: isoTimestamp(value.validTime, "valid time"),
    variable: boundedText(value.variable, "variable", 160),
    units: boundedText(value.units, "units", 80),
    attribution: boundedText(value.attribution, "attribution", 500),
    status,
  };
}

/**
 * Validate the small same-origin bridge contract used between a server-side
 * HoloViews/Datashader renderer and MapLibre. Dynamic attribution is displayed
 * as text by React and is never passed to MapLibre as HTML.
 */
export function parseDynamicalRenderManifest(
  value: unknown,
  expectedDatasetId: DynamicalDatasetId,
  origin = globalThis.location?.origin ?? "https://activity.invalid",
): DynamicalRenderManifest {
  const candidate = record(value);
  if (!candidate) {
    throw new DynamicalRenderManifestError("The render manifest is invalid.");
  }
  const metadata = renderMetadata(candidate, expectedDatasetId);
  if (candidate.kind === "image") {
    return {
      ...metadata,
      kind: "image",
      url: safeImageUrl(candidate.url, origin),
      coordinates: imageCoordinates(candidate.coordinates),
    };
  }
  if (candidate.kind === "geojson") {
    const data = record(candidate.data);
    if (
      data?.type !== "FeatureCollection" ||
      !Array.isArray(data.features) ||
      data.features.length > 20_000
    ) {
      throw new DynamicalRenderManifestError("The render GeoJSON is invalid or too large.");
    }
    return {
      ...metadata,
      kind: "geojson",
      data: {
        type: "FeatureCollection",
        features: data.features,
      },
    };
  }
  throw new DynamicalRenderManifestError("The render kind is unsupported.");
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function rounded(value: number, digits = 4): string {
  return value.toFixed(digits).replace(/\.?0+$/u, "");
}

export function dynamicalRenderManifestUrl(request: DynamicalRenderRequest): string {
  const [rawWest, rawSouth, rawEast, rawNorth] = request.bbox;
  const west = clamp(rawWest, -180, 180);
  const south = clamp(rawSouth, -85.051129, 85.051129);
  const east = clamp(rawEast, -180, 180);
  const north = clamp(rawNorth, -85.051129, 85.051129);
  if (
    ![west, south, east, north].every(Number.isFinite) ||
    west >= east ||
    south >= north
  ) {
    throw new DynamicalRenderManifestError("The requested map bounds are invalid.");
  }
  const parameters = new URLSearchParams({
    dataset: request.datasetId,
    bbox: [west, south, east, north].map((value) => rounded(value)).join(","),
    width: String(Math.round(clamp(request.width, 256, 1_280))),
    height: String(Math.round(clamp(request.height, 192, 960))),
  });
  if (request.time) {
    parameters.set("time", isoTimestamp(request.time, "requested time"));
  }
  return `${DYNAMICAL_RENDER_MANIFEST_ROUTE}?${parameters.toString()}`;
}
