import {
  isDynamicalDatasetId,
  type DynamicalDatasetId,
} from "../../src/shared/dynamical-data";
import type { AssetBinding } from "./cloudflare";
import { HttpError } from "./errors";
import { jsonResponse, methodNotAllowed } from "./responses";

const DYNAMICAL_MANIFEST_ASSET = "/data/dynamical/manifest.json";
const MAX_MANIFEST_BYTES = 256 * 1024;
const MAX_TIME_OFFSET_MILLISECONDS = 60 * 60 * 1_000;
const READY_STATUSES = new Set(["ready", "complete", "available", "ok"]);

type ImageCoordinate = readonly [number, number];
type ImageCoordinates = readonly [
  ImageCoordinate,
  ImageCoordinate,
  ImageCoordinate,
  ImageCoordinate,
];

interface DynamicalImageManifest {
  schemaVersion: 1;
  datasetId: DynamicalDatasetId;
  kind: "image";
  url: string;
  coordinates: ImageCoordinates;
  generatedAt: string;
  validTime: string;
  variable: string;
  units: string;
  attribution: string;
  status: string;
}

interface DynamicalManifestIndex {
  schemaVersion: 1;
  generatedAt: string;
  layers: Record<string, unknown>;
}

interface DynamicalManifestEnv {
  ASSETS: AssetBinding;
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function unavailable(code: string, message: string, status = 503): never {
  throw new HttpError(status, code, message);
}

function boundedText(
  value: unknown,
  label: string,
  maximum: number,
): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > maximum
  ) {
    unavailable(
      "dynamical_manifest_invalid",
      `The precomputed Dynamical ${label} is invalid.`,
    );
  }
  return value;
}

function timestamp(value: unknown, label: string): string {
  const text = boundedText(value, label, 64);
  if (!Number.isFinite(Date.parse(text))) {
    unavailable(
      "dynamical_manifest_invalid",
      `The precomputed Dynamical ${label} is invalid.`,
    );
  }
  return text;
}

function coordinate(value: unknown): ImageCoordinate {
  if (
    !Array.isArray(value) ||
    value.length !== 2 ||
    !Number.isFinite(value[0]) ||
    !Number.isFinite(value[1])
  ) {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical image coordinates are invalid.",
    );
  }
  const longitude = Number(value[0]);
  const latitude = Number(value[1]);
  if (
    longitude < -180 ||
    longitude > 180 ||
    latitude < -85.051129 ||
    latitude > 85.051129
  ) {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical image coordinates are outside the web-map domain.",
    );
  }
  return [longitude, latitude];
}

function imageCoordinates(value: unknown): ImageCoordinates {
  if (!Array.isArray(value) || value.length !== 4) {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical image coordinates are invalid.",
    );
  }
  const coordinates = value.map(coordinate) as unknown as ImageCoordinates;
  const [
    [west, north],
    [east, secondNorth],
    [secondEast, south],
    [secondWest, secondSouth],
  ] = coordinates;
  if (
    west >= east ||
    south >= north ||
    north !== secondNorth ||
    east !== secondEast ||
    south !== secondSouth ||
    west !== secondWest
  ) {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical image bounds are invalid.",
    );
  }
  return coordinates;
}

function imageUrl(
  value: unknown,
  datasetId: DynamicalDatasetId,
  requestUrl: string,
): string {
  const raw = boundedText(value, "image URL", 2_000);
  let parsed: URL;
  let requestOrigin: string;
  try {
    parsed = new URL(raw, requestUrl);
    requestOrigin = new URL(requestUrl).origin;
  } catch {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical image URL is invalid.",
    );
  }
  if (
    parsed.origin !== requestOrigin ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== `/data/dynamical/${datasetId}.png`
  ) {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical image URL is not the expected same-origin asset.",
    );
  }
  return `${parsed.pathname}${parsed.search}`;
}

function parseIndex(value: unknown): DynamicalManifestIndex {
  const candidate = record(value);
  const layers = record(candidate?.layers);
  if (
    candidate?.schemaVersion !== 1 ||
    !layers ||
    !Number.isFinite(Date.parse(String(candidate.generatedAt ?? "")))
  ) {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical manifest index is invalid.",
    );
  }
  return {
    schemaVersion: 1,
    generatedAt: String(candidate.generatedAt),
    layers,
  };
}

function parseLayer(
  value: unknown,
  datasetId: DynamicalDatasetId,
  requestUrl: string,
): DynamicalImageManifest {
  const candidate = record(value);
  if (!candidate) {
    unavailable(
      "dynamical_render_unavailable",
      `No precomputed map render is available for ${datasetId}.`,
      404,
    );
  }
  if (
    candidate.datasetId !== datasetId ||
    candidate.kind !== "image" ||
    (candidate.schemaVersion !== undefined && candidate.schemaVersion !== 1)
  ) {
    unavailable(
      "dynamical_manifest_invalid",
      `The precomputed map render for ${datasetId} is invalid.`,
    );
  }
  const status = boundedText(candidate.status, "status", 80);
  if (!READY_STATUSES.has(status.toLowerCase())) {
    unavailable(
      "dynamical_render_unavailable",
      `The precomputed map render for ${datasetId} is not ready.`,
      404,
    );
  }
  return {
    schemaVersion: 1,
    datasetId,
    kind: "image",
    url: imageUrl(candidate.url, datasetId, requestUrl),
    coordinates: imageCoordinates(candidate.coordinates),
    generatedAt: timestamp(candidate.generatedAt, "generation time"),
    validTime: timestamp(candidate.validTime, "valid time"),
    variable: boundedText(candidate.variable, "variable", 160),
    units: boundedText(candidate.units, "units", 80),
    attribution: boundedText(candidate.attribution, "attribution", 500),
    status,
  };
}

function validateOptionalViewportParameters(url: URL): void {
  const rawBbox = url.searchParams.get("bbox");
  if (rawBbox !== null) {
    const values = rawBbox.split(",").map(Number);
    if (
      values.length !== 4 ||
      !values.every(Number.isFinite) ||
      values[0] < -180 ||
      values[2] > 180 ||
      values[1] < -85.051129 ||
      values[3] > 85.051129 ||
      values[0] >= values[2] ||
      values[1] >= values[3]
    ) {
      throw new HttpError(
        400,
        "invalid_render_viewport",
        "bbox must be west,south,east,north within the web-map domain.",
      );
    }
  }

  for (const [name, minimum, maximum] of [
    ["width", 256, 1_280],
    ["height", 192, 960],
  ] as const) {
    const raw = url.searchParams.get(name);
    if (raw === null) continue;
    const value = Number(raw);
    if (!Number.isInteger(value) || value < minimum || value > maximum) {
      throw new HttpError(
        400,
        "invalid_render_viewport",
        `${name} must be an integer from ${minimum} through ${maximum}.`,
      );
    }
  }
}

function validateRequestedTime(url: URL, layer: DynamicalImageManifest): void {
  const requested = url.searchParams.get("time");
  if (requested === null) return;

  const requestedMilliseconds = Date.parse(requested);

  if (!Number.isFinite(requestedMilliseconds)) {
    throw new HttpError(
      400,
      "invalid_render_time",
      "time must be an ISO-8601 timestamp.",
    );
  }

  /*
   * Temporary sidequest compatibility mode.
   *
   * The current dynamical service publishes only its latest GFS render.
   * Historical sidequest timestamps therefore cannot be matched.
   *
   * Do not reject the request. The manifest still exposes validTime so
   * the client can identify the actual represented time.
   */
}

async function readManifestIndex(
  request: Request,
  env: DynamicalManifestEnv,
): Promise<DynamicalManifestIndex> {
  const assetUrl = new URL(DYNAMICAL_MANIFEST_ASSET, request.url);
  let response: Response;
  try {
    response = await env.ASSETS.fetch(new Request(assetUrl, {
      method: "GET",
      headers: { Accept: "application/json" },
    }));
  } catch {
    unavailable(
      "dynamical_manifest_unavailable",
      "The precomputed Dynamical manifest asset could not be loaded.",
    );
  }
  const declaredLength = Number(response.headers.get("Content-Length") ?? "0");
  if (
    !response.ok ||
    !response.headers.get("Content-Type")?.toLowerCase().includes("application/json") ||
    (Number.isFinite(declaredLength) && declaredLength > MAX_MANIFEST_BYTES)
  ) {
    unavailable(
      "dynamical_manifest_unavailable",
      "The precomputed Dynamical manifest asset is unavailable.",
    );
  }
  const body = await response.text();
  if (body.length > MAX_MANIFEST_BYTES) {
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical manifest asset is too large.",
    );
  }
  try {
    return parseIndex(JSON.parse(body) as unknown);
  } catch (error) {
    if (error instanceof HttpError) throw error;
    unavailable(
      "dynamical_manifest_invalid",
      "The precomputed Dynamical manifest asset is not valid JSON.",
    );
  }
}

/**
 * Return the latest immutable HoloViews/Datashader image contract for one
 * closed-registry Dynamical dataset. Viewport dimensions are accepted for
 * frontend compatibility; the current assets are precomputed full-domain
 * rasters. A requested historical time is never silently mapped to latest.
 */
export async function handleDynamicalRenderManifest(
  request: Request,
  env: DynamicalManifestEnv,
): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowed(["GET", "HEAD"]);
  }
  const url = new URL(request.url);
  const rawDatasetId = url.searchParams.get("dataset") ?? "";
  if (!isDynamicalDatasetId(rawDatasetId)) {
    throw new HttpError(
      400,
      "invalid_dynamical_dataset",
      "dataset must identify one of the five registered Dynamical map layers.",
    );
  }
  validateOptionalViewportParameters(url);
  const index = await readManifestIndex(request, env);
  const layer = parseLayer(index.layers[rawDatasetId], rawDatasetId, request.url);
  validateRequestedTime(url, layer);

  const response = jsonResponse(layer);
  if (request.method === "HEAD") {
    return new Response(null, {
      status: response.status,
      headers: response.headers,
    });
  }
  return response;
}
