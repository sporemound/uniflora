import type { PublicLocation } from "./public-state";
import { facilityMapCoordinate } from "./facility-geography";
import {
  DYNAMICAL_DATASETS,
  type DynamicalDatasetId,
} from "./dynamical-data";

export type ExternalMapLayerId =
  | "nasa-true-color"
  | "noaa-radar"
  | "nws-alerts"
  | "uap-public-reports"
  | DynamicalDatasetId;

export interface ExternalMapLayerDefinition {
  id: ExternalMapLayerId;
  label: string;
  provider: "NASA GIBS" | "NOAA/NWS" | "UAPDrop + UFOSINT" | "Dynamical";
  kind: "raster" | "geojson" | "timeline" | "coverage";
  description: string;
  refreshMinutes: number | null;
}

export const EXTERNAL_MAP_LAYERS: readonly ExternalMapLayerDefinition[] = [
  {
    id: "nasa-true-color",
    label: "Orbital true color",
    provider: "NASA GIBS",
    kind: "raster",
    description: "VIIRS corrected-reflectance imagery for the latest complete UTC day.",
    refreshMinutes: null,
  },
  {
    id: "noaa-radar",
    label: "Base reflectivity",
    provider: "NOAA/NWS",
    kind: "raster",
    description: "Quality-controlled MRMS composite radar, updated approximately every five minutes.",
    refreshMinutes: 5,
  },
  {
    id: "nws-alerts",
    label: "Active alerts",
    provider: "NOAA/NWS",
    kind: "geojson",
    description: "Active watches, warnings, and advisories intersecting facility coordinates.",
    refreshMinutes: 5,
  },
  {
    id: "uap-public-reports",
    label: "Public reports",
    provider: "UAPDrop + UFOSINT",
    kind: "timeline",
    description: "Historical archive records plus UFOSINT API records scoring above 50, with privacy-quantized coordinates.",
    refreshMinutes: 360,
  },
  ...DYNAMICAL_DATASETS.map((dataset) => ({
    id: dataset.id,
    label: dataset.shortLabel,
    provider: "Dynamical" as const,
    kind: "coverage" as const,
    description:
      `${dataset.label} catalog coverage plus query-compatible public-report windows; ` +
      `${dataset.spatialDomain}, ${dataset.spatialResolution}, ${dataset.temporalResolution} ` +
      `from ${dataset.temporalStart.slice(0, 10)}.`,
    refreshMinutes: null,
  })),
] as const;

export const NOAA_RADAR_TILE_URL =
  "https://mapservices.weather.noaa.gov/eventdriven/rest/services/" +
  "radar/radar_base_reflectivity/MapServer/export" +
  "?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857" +
  "&size=256,256&format=png32&transparent=true&f=image";

export function latestCompleteUtcDate(now = new Date()): string {
  const date = new Date(now);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

export function nasaTrueColorTileUrl(date: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error("NASA imagery date must use YYYY-MM-DD.");
  }
  return (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" +
    "VIIRS_SNPP_CorrectedReflectance_TrueColor/default/" +
    `${date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`
  );
}

export function nwsAlertUrls(locations: readonly PublicLocation[]): string[] {
  const urls = new Set<string>();
  for (const location of locations.slice(0, 8)) {
    const coordinate = facilityMapCoordinate(location);
    if (!coordinate) continue;
    const point = `${coordinate.latitude.toFixed(4)},${coordinate.longitude.toFixed(4)}`;
    urls.add(`https://api.weather.gov/alerts/active?point=${encodeURIComponent(point)}`);
  }
  return [...urls];
}

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedText(value: unknown, maximum = 512): string {
  return typeof value === "string" ? value.slice(0, maximum) : "";
}

function sanitizePosition(value: unknown): [number, number] | null {
  if (
    !Array.isArray(value) ||
    value.length < 2 ||
    typeof value[0] !== "number" ||
    !Number.isFinite(value[0]) ||
    value[0] < -180 ||
    value[0] > 180 ||
    typeof value[1] !== "number" ||
    !Number.isFinite(value[1]) ||
    value[1] < -90 ||
    value[1] > 90
  ) {
    return null;
  }
  return [value[0], value[1]];
}

function sanitizeRing(value: unknown): [number, number][] | null {
  if (!Array.isArray(value) || value.length < 4 || value.length > 10_000) {
    return null;
  }
  const ring = value.map(sanitizePosition);
  return ring.every((position) => position !== null)
    ? (ring as [number, number][])
    : null;
}

function sanitizePolygon(value: unknown): [number, number][][] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > 128) {
    return null;
  }
  const polygon = value.map(sanitizeRing);
  return polygon.every((ring) => ring !== null)
    ? (polygon as [number, number][][])
    : null;
}

function sanitizeGeometry(value: unknown) {
  if (!isRecord(value)) return null;
  if (value.type === "Polygon") {
    const coordinates = sanitizePolygon(value.coordinates);
    return coordinates ? { type: "Polygon" as const, coordinates } : null;
  }
  if (
    value.type === "MultiPolygon" &&
    Array.isArray(value.coordinates) &&
    value.coordinates.length > 0 &&
    value.coordinates.length <= 256
  ) {
    const coordinates = value.coordinates.map(sanitizePolygon);
    return coordinates.every((polygon) => polygon !== null)
      ? {
          type: "MultiPolygon" as const,
          coordinates: coordinates as [number, number][][][],
        }
      : null;
  }
  return null;
}

export function sanitizeNwsAlertCollection(value: unknown) {
  if (!isRecord(value) || !Array.isArray(value.features)) {
    return { type: "FeatureCollection" as const, features: [] };
  }
  return {
    type: "FeatureCollection" as const,
    features: value.features.slice(0, 100).flatMap((candidate, index) => {
      if (!isRecord(candidate)) return [];
      const geometry = sanitizeGeometry(candidate.geometry);
      if (!geometry) return [];
      const properties = isRecord(candidate.properties)
        ? candidate.properties
        : {};
      return [{
        type: "Feature" as const,
        id: boundedText(candidate.id, 256) || `alert-${index}`,
        geometry,
        properties: {
          event: boundedText(properties.event),
          headline: boundedText(properties.headline, 1_024),
          severity: boundedText(properties.severity, 32),
          urgency: boundedText(properties.urgency, 32),
          effective: boundedText(properties.effective, 64),
          expires: boundedText(properties.expires, 64),
          senderName: boundedText(properties.senderName),
        },
      }];
    }),
  };
}

export interface PublicReportRecord {
  reportId: string;
  observedAt: string;
  observedYear: number;
  latitude: number;
  longitude: number;
  title: string;
  locationName: string;
  coordinatePrecision: string | null;
  sourceKey: string;
  sourceName: string;
  sourceUrl: string | null;
  publishedAt: string | null;
  indexedAt: string | null;
  summary: string;
  status: string;
  qualityScore: number;
  reportClass:
    | "historical-archive"
    | "current-index"
    | "recently-published"
    | "newly-published-historical";
}

export interface PublicReportSnapshot {
  sourceName: string;
  sourcePageUrl: string;
  license: string;
  startYear: number;
  endYear: number;
  reports: PublicReportRecord[];
}

function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

function normalizedHost(value: string): string {
  return value.toLowerCase().replace(/^www\./u, "").replace(/\.$/u, "");
}

function safeReportSourceUrl(
  value: unknown,
  allowedHosts: ReadonlySet<string>,
): string | null {
  const sourceUrl = safeHttpUrl(value);
  if (!sourceUrl) return null;
  const url = new URL(sourceUrl);
  return url.protocol === "https:" && allowedHosts.has(normalizedHost(url.hostname))
    ? url.toString()
    : null;
}

export function sanitizePublicReportSnapshot(
  value: unknown,
): PublicReportSnapshot | null {
  if (
    !isRecord(value) ||
    (
      value.schemaVersion !== "1.0.0" &&
      value.schemaVersion !== "1.1.0" &&
      value.schemaVersion !== "1.2.0"
    ) ||
    !isRecord(value.source) ||
    !isRecord(value.timeExtent) ||
    !Array.isArray(value.reports) ||
    value.reports.length > 6_500
  ) {
    return null;
  }
  const sourcePageUrl = safeHttpUrl(value.source.pageUrl);
  const allowedHosts = new Set<string>([
    "archives.gov",
    "catalog.archives.gov",
    "ufosint.com",
  ]);
  if (sourcePageUrl) {
    allowedHosts.add(normalizedHost(new URL(sourcePageUrl).hostname));
  }
  if (Array.isArray(value.source.allowedHosts)) {
    for (const candidate of value.source.allowedHosts.slice(0, 16)) {
      if (typeof candidate === "string" && candidate.length <= 253) {
        allowedHosts.add(normalizedHost(candidate));
      }
    }
  }
  const start = new Date(String(value.timeExtent.start));
  const end = new Date(String(value.timeExtent.end));
  if (
    !sourcePageUrl ||
    Number.isNaN(start.valueOf()) ||
    Number.isNaN(end.valueOf())
  ) {
    return null;
  }
  const reports: PublicReportRecord[] = [];
  for (const candidate of value.reports) {
    if (!isRecord(candidate)) return null;
    const latitude = candidate.latitude;
    const longitude = candidate.longitude;
    const observed = new Date(String(candidate.observedAt));
    if (
      typeof latitude !== "number" ||
      !Number.isFinite(latitude) ||
      latitude < -90 ||
      latitude > 90 ||
      typeof longitude !== "number" ||
      !Number.isFinite(longitude) ||
      longitude < -180 ||
      longitude > 180 ||
      Number.isNaN(observed.valueOf())
    ) {
      return null;
    }
    const reportId = boundedText(candidate.reportId, 256);
    if (!reportId) return null;
    const reportClass =
      candidate.reportClass === "current-index" ||
      candidate.reportClass === "recently-published" ||
      candidate.reportClass === "newly-published-historical"
        ? candidate.reportClass
        : "historical-archive";
    const parsedQuality = Number(candidate.qualityScore ?? 0);
    const qualityScore = Number.isFinite(parsedQuality)
      ? Math.trunc(parsedQuality)
      : 0;
    // Strict second gate: current UFOSINT records must score above 50.
    if (reportClass === "current-index" && qualityScore < 51) {
      continue;
    }
    reports.push({
      reportId,
      observedAt: observed.toISOString(),
      observedYear: observed.getUTCFullYear(),
      latitude,
      longitude,
      title: boundedText(candidate.title, 180) || "Public report",
      locationName: boundedText(candidate.locationName, 180),
      coordinatePrecision:
        boundedText(candidate.coordinatePrecision, 64) || null,
      sourceKey: boundedText(candidate.sourceKey, 64) || "archive",
      sourceName: boundedText(candidate.sourceName, 180) ||
        boundedText(candidate.sourceKey, 64) ||
        "Archive",
      sourceUrl: safeReportSourceUrl(candidate.sourceUrl, allowedHosts),
      publishedAt: (() => {
        if (!candidate.publishedAt) return null;
        const published = new Date(String(candidate.publishedAt));
        return Number.isNaN(published.valueOf()) ? null : published.toISOString();
      })(),
      indexedAt: (() => {
        if (!candidate.indexedAt) return null;
        const indexed = new Date(String(candidate.indexedAt));
        return Number.isNaN(indexed.valueOf()) ? null : indexed.toISOString();
      })(),
      summary: boundedText(candidate.summary, 350),
      status: boundedText(candidate.status, 32) || "unknown",
      qualityScore,
      reportClass,
    });
  }
  return {
    sourceName: boundedText(value.source.name, 180) || "Public report archive",
    sourcePageUrl,
    license: boundedText(value.source.license, 128),
    startYear: start.getUTCFullYear(),
    endYear: end.getUTCFullYear(),
    reports,
  };
}
