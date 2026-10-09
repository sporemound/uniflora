import type { PublicReportRecord } from "../../src/shared/external-map-layers";
import {
  UFOSINT_REPORT_SNAPSHOT_SCHEMA_VERSION,
  UFOSINT_SIDEQUEST_TEMPLATE_VERSION,
  parseUfosintReportSnapshot,
  type UfosintReportSnapshot,
  type UfosintSidequestTaskDefinition,
} from "../../src/shared/ufosint-sidequest";
import { HttpError } from "./errors";

export { UFOSINT_SIDEQUEST_TEMPLATE_VERSION };

const TASKS: readonly UfosintSidequestTaskDefinition[] = [
  {
    taskId: "source-provenance",
    ordinal: 0,
    kind: "provenance",
    title: "Freeze source provenance",
    instructions:
      "Confirm the immutable report-snapshot hash, UFOSINT index time, source record, quality gate, and template version. Do not add raw witness contact data.",
    required: true,
  },
  {
    taskId: "source-independence",
    ordinal: 1,
    kind: "witness",
    title: "Check duplication and source dependence",
    instructions:
      "Search only public records for duplicates, reposts, and shared upstream sources. Record why apparently separate accounts are or are not independent; do not contact or identify witnesses.",
    required: true,
  },
  {
    taskId: "geographic-envelope",
    ordinal: 2,
    kind: "geographic",
    title: "Bound the geographic context",
    instructions:
      "Treat the displayed point as a privacy-quantized city location. Use an uncertainty envelope and do not infer a street, home, flight path, or exact observer position.",
    required: true,
  },
  {
    taskId: "temporal-envelope",
    ordinal: 3,
    kind: "temporal",
    title: "Bound the temporal context",
    instructions:
      "Treat observedAt as an event date unless a source supplies a supported time. Query the full date with a one-day UTC buffer on each side and preserve ambiguity between observation, publication, and index times.",
    required: true,
  },
  {
    taskId: "historical-weather",
    ordinal: 4,
    kind: "meteorological",
    title: "Collect historical weather context",
    instructions:
      "Use eligible Dynamical datasets in source order: nearby ASOS/AWOS observations, then HRRR or GFS analysis, with MRMS and IMERG for precipitation. Record missing values, station distance, model resolution, and source dependence. Context is not causation.",
    required: true,
  },
  {
    taskId: "aviation-context",
    ordinal: 5,
    kind: "aviation",
    title: "Check ordinary aviation context",
    instructions:
      "Review public and lawful aviation context for the full time/location envelope. Record retention gaps and coverage limits; absence of a public record is not proof of absence.",
    required: true,
  },
  {
    taskId: "astronomical-context",
    ordinal: 6,
    kind: "astronomical",
    title: "Check astronomical context",
    instructions:
      "Evaluate bright planets, Moon geometry, meteors, satellites, and re-entry candidates using the complete uncertainty window. Preserve ephemeris and catalog limitations.",
    required: true,
  },
  {
    taskId: "sensor-media-context",
    ordinal: 7,
    kind: "sensor",
    title: "Assess sensor and media limits",
    instructions:
      "If public media exists, record encoding, metadata, field-of-view, stabilization, compression, and chain-of-custody limits. Mark unavailable rather than reconstructing missing media.",
    required: true,
  },
  {
    taskId: "ordinary-explanations",
    ordinal: 8,
    kind: "alternative_hypothesis",
    title: "Compare ordinary explanations",
    instructions:
      "Compare aircraft, balloons, celestial objects, weather, optical effects, camera artifacts, and insufficient-information outcomes against the same evidence. Do not force a single explanation.",
    required: true,
  },
  {
    taskId: "draft-finding",
    ordinal: 9,
    kind: "synthesis",
    title: "Draft a calibrated finding",
    instructions:
      "Cite public-safe evidence and artifacts, state uncertainty and contradictions, distinguish observation from interpretation, and include an insufficient-data result when warranted.",
    required: true,
  },
  {
    taskId: "independent-peer-review",
    ordinal: 10,
    kind: "peer_review",
    title: "Obtain independent peer review",
    instructions:
      "A participant other than the finding author must endorse, challenge, or request revision with a rationale and calibrated review rubric before conclusion.",
    required: true,
  },
] as const;

export function defaultUfosintSidequestTasks(): UfosintSidequestTaskDefinition[] {
  return TASKS.map((task) => ({ ...task }));
}

export function canonicalUfosintReportId(value: unknown): string {
  if (typeof value !== "string") {
    throw new HttpError(400, "invalid_ufosint_report_id", "A UFOSINT report ID is required.");
  }
  const match = /^(?:ufosint:)?([1-9][0-9]{0,18})$/u.exec(value.trim());
  if (!match) {
    throw new HttpError(
      400,
      "invalid_ufosint_report_id",
      "UFOSINT report ID must use ufosint:<positive integer>.",
    );
  }
  return `ufosint:${match[1]}`;
}

export function buildUfosintReportSnapshot(
  report: PublicReportRecord,
  sourcePageUrl: string,
): UfosintReportSnapshot {
  if (
    report.sourceKey !== "ufosint" ||
    report.status !== "unverified" ||
    report.reportClass !== "current-index" ||
    report.qualityScore < 51 ||
    !report.indexedAt
  ) {
    throw new HttpError(
      409,
      "ufosint_report_ineligible",
      "The current report does not satisfy the sidequest quality and provenance gate.",
    );
  }
  return parseUfosintReportSnapshot({
    schemaVersion: UFOSINT_REPORT_SNAPSHOT_SCHEMA_VERSION,
    sourceKey: "ufosint",
    reportId: canonicalUfosintReportId(report.reportId),
    sourceName: report.sourceName,
    sourcePageUrl,
    sourceUrl: report.sourceUrl,
    observedAt: report.observedAt,
    indexedAt: report.indexedAt,
    latitude: report.latitude,
    longitude: report.longitude,
    title: report.title,
    locationName: report.locationName,
    coordinatePrecision: report.coordinatePrecision || "city",
    summary: report.summary,
    status: "unverified",
    qualityScore: report.qualityScore,
  });
}
