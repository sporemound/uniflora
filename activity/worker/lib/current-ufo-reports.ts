import type { AssetBinding } from "./cloudflare";
import { HttpError } from "./errors";

const UFOSINT_MCP_URL = "https://ufosint.com/mcp";
const UFOSINT_PAGE_URL = "https://ufosint.com/";
const MAX_TOOL_BYTES = 2_000_000;
const MAX_MERGED_REPORTS = 6_500;
const DEFAULT_MINIMUM_QUALITY = 51;
const DEFAULT_LOOKBACK_DAYS = 365;
const DEFAULT_CANDIDATE_LIMIT = 200;
const DEFAULT_CACHE_SECONDS = 21_600;

type JsonRecord = Record<string, unknown>;

interface CurrentReportEnv {
  ASSETS: AssetBinding;
  UFOSINT_MIN_QUALITY_SCORE?: string;
  UFOSINT_LOOKBACK_DAYS?: string;
  UFOSINT_CANDIDATE_LIMIT?: string;
  UFOSINT_CACHE_SECONDS?: string;
}

interface CachedResult {
  expiresAt: number;
  body: string;
}

interface UfosintSettings {
  minimumQuality: number;
  lookbackDays: number;
  candidateLimit: number;
  cacheSeconds: number;
}

interface UfosintReport {
  reportId: string;
  observedAt: string;
  publishedAt: null;
  indexedAt: string;
  latitude: number;
  longitude: number;
  title: string;
  locationName: string;
  coordinatePrecision: "city";
  sourceKey: "ufosint";
  sourceName: "UFOSINT Explorer";
  sourceUrl: null;
  summary: string;
  status: "unverified";
  reportClass: "current-index";
  qualityScore: number;
}

let cached: CachedResult | null = null;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown, maximum: number): string {
  if (typeof value !== "string") return "";
  return value
    .replaceAll("\u0000", " ")
    .trim()
    .replace(/\s+/gu, " ")
    .slice(0, maximum);
}

function listText(value: unknown, maximum: number): string {
  if (typeof value === "string") return text(value, maximum);
  if (!Array.isArray(value)) return "";
  return value
    .slice(0, 8)
    .map((item) => text(item, 50))
    .filter(Boolean)
    .join(", ")
    .slice(0, maximum);
}

function integer(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function removedOrEmptyDescription(value: unknown): boolean {
  const description = text(value, 2_000).toLowerCase();

  if (!description) return true;

  const rejectionPhrases = [
    "no description available",
    "post was deleted",
    "post was removed",
    "removed by moderators",
    "original post was removed",
    "original post was deleted",
    "post body was removed",
    "post body was deleted",
    "op comments were removed",
    "contains no description",
    "no information is available",
  ];

  return rejectionPhrases.some((phrase) =>
    description.includes(phrase),
  );
}

function localQualityScore(
  record: JsonRecord,
  observed: Date,
  indexedAt: Date,
): number {
  let score = 0;

  if (
    !Number.isNaN(observed.valueOf()) &&
    observed.valueOf() <= indexedAt.valueOf()
  ) {
    score += 15;
  }

  const latitude = Number(record.latitude);
  const longitude = Number(record.longitude);

  if (
    Number.isFinite(latitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    Number.isFinite(longitude) &&
    longitude >= -180 &&
    longitude <= 180
  ) {
    score += 25;
  }

  if (
    text(record.city, 100) &&
    text(record.country, 100)
  ) {
    score += 15;
  }

  const description = text(record.description, 2_000);

  if (
    description.length >= 40 &&
    !removedOrEmptyDescription(description)
  ) {
    score += 20;
  }

  if (text(record.standardized_shape || record.shape, 64)) {
    score += 10;
  }

  if (text(record.duration, 100)) {
    score += 5;
  }

  const witnesses = integer(record.num_witnesses);

  if (witnesses !== null && witnesses > 0) {
    score += 5;
  }

  if (text(record.source_name || record.source, 80)) {
    score += 5;
  }

  return Math.min(100, score);
}

function boundedInteger(
  value: string | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isSafeInteger(parsed) && parsed >= minimum && parsed <= maximum
    ? parsed
    : fallback;
}

function settings(env: CurrentReportEnv): UfosintSettings {
  return {
    // User requirement: a score of 50 is rejected; 51 is the minimum.
    minimumQuality: boundedInteger(
      env.UFOSINT_MIN_QUALITY_SCORE,
      DEFAULT_MINIMUM_QUALITY,
      51,
      100,
    ),
    lookbackDays: boundedInteger(
      env.UFOSINT_LOOKBACK_DAYS,
      DEFAULT_LOOKBACK_DAYS,
      7,
      3_650,
    ),
    // Each monthly search is capped at 200 records.
    candidateLimit: boundedInteger(
      env.UFOSINT_CANDIDATE_LIMIT,
      DEFAULT_CANDIDATE_LIMIT,
      1,
      200,
    ),
    cacheSeconds: boundedInteger(
      env.UFOSINT_CACHE_SECONDS,
      DEFAULT_CACHE_SECONDS,
      3_600,
      86_400,
    ),
  };
}

function quantize(value: number): number {
  return Number((Math.round(value / 0.05) * 0.05).toFixed(4));
}

function exactEventDate(value: unknown): Date | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{4}-\d{2}-\d{2})(?:$|[T ])/u.exec(value.trim());
  if (!match) return null;
  const date = new Date(`${match[1]}T00:00:00.000Z`);
  return Number.isNaN(date.valueOf()) ? null : date;
}

function unwrapToolResult(value: unknown): JsonRecord | null {
  if (!isRecord(value)) return null;
  if (isRecord(value.result)) return value.result;
  if (isRecord(value.data)) return value.data;
  return value;
}

function locationName(record: JsonRecord): string {
  return [
    text(record.city, 100),
    text(record.state, 100),
    text(record.country, 100),
  ].filter(Boolean).join(", ") || "Approximate location";
}


function sanitizeWitnessSummary(value: unknown, maximum = 2_000): string {
  const raw = text(value, 8_000);
  if (!raw || removedOrEmptyDescription(raw)) return "";

  return raw
    .replace(/https?:\/\/\S+/giu, "[link removed]")
    .replace(/\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/gu, "[contact removed]")
    .replace(/(^|\s)@[A-Za-z0-9_]{2,32}\b/gu, "$1[username removed]")
    .replace(/\b(?:\+?\d[\d(). -]{7,}\d)\b/gu, "[contact removed]")
    .replace(/\s+/gu, " ")
    .trim()
    .slice(0, maximum);
}

function metadataSummary(record: JsonRecord): string {
  // Never copy UFOSINT's description or summary fields. Only structured,
  // derived metadata is transformed into a short Activity/voice description.
  const details: string[] = [];
  const shape = text(record.standardized_shape || record.shape, 64);
  if (shape) details.push(`reported form: ${shape}`);
  const duration = text(record.duration, 100);
  if (duration) details.push(`duration: ${duration}`);
  const witnesses = integer(record.num_witnesses);
  if (witnesses !== null && witnesses > 0) {
    details.push(`witness count: ${witnesses}`);
  }
  const hynek = text(record.hynek, 32);
  if (hynek) details.push(`Hynek class: ${hynek}`);
  const movement = listText(
    record.movement_categories ||
      record.movement_category ||
      record.primary_movement,
    100,
  );
  if (movement) details.push(`movement: ${movement}`);
  const source = text(record.source_name || record.source, 80);
  const prefix = source
    ? `UFOSINT indexed a quality-screened sighting derived from ${source}`
    : "UFOSINT indexed a quality-screened sighting";
  return details.length > 0
    ? `${prefix}; ${details.join("; ")}.`.slice(0, 350)
    : `${prefix}.`;
}

async function responseJsonWithLimit(
  response: Response,
  maximum: number,
): Promise<unknown> {
  const body = await response.text();
  if (new TextEncoder().encode(body).byteLength > maximum) {
    throw new HttpError(
      502,
      "ufosint_response_too_large",
      "UFOSINT response exceeded its size limit.",
    );
  }
  try {
    return JSON.parse(body) as unknown;
  } catch {
    throw new HttpError(
      502,
      "ufosint_invalid_json",
      "UFOSINT returned invalid JSON.",
    );
  }
}


async function callUfosintTool(
  toolName: "search_sightings" | "get_sighting",
  body: JsonRecord,
): Promise<unknown> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20_000);

  try {
    const response = await fetch(UFOSINT_MCP_URL, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Missing-Interior-UFOSINT-Map/3.1",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: `${toolName}-${Date.now()}`,
        method: "tools/call",
        params: {
          name: toolName,
          arguments: body,
        },
      }),
      redirect: "manual",
      signal: controller.signal,
    });

    if (response.status >= 300 && response.status < 400) {
      throw new HttpError(
        502,
        "ufosint_redirect_rejected",
        "UFOSINT returned an unexpected redirect.",
      );
    }

    if (!response.ok) {
      throw new HttpError(
        502,
        "ufosint_unavailable",
        `UFOSINT ${toolName} returned ${response.status}.`,
      );
    }

    const outer = await responseJsonWithLimit(
      response,
      MAX_TOOL_BYTES,
    );

    if (!isRecord(outer) || !isRecord(outer.result)) {
      throw new HttpError(
        502,
        "ufosint_invalid_mcp_response",
        "UFOSINT returned an invalid MCP response.",
      );
    }

    const content = Array.isArray(outer.result.content)
      ? outer.result.content
      : [];

    const textItem = content.find(
      (item) =>
        isRecord(item) &&
        item.type === "text" &&
        typeof item.text === "string",
    );

    if (!isRecord(textItem)) {
      throw new HttpError(
        502,
        "ufosint_missing_tool_payload",
        "UFOSINT returned no tool payload.",
      );
    }

    let parsed: unknown;

    try {
      parsed = JSON.parse(String(textItem.text));
    } catch {
      throw new HttpError(
        502,
        "ufosint_invalid_tool_payload",
        "UFOSINT returned invalid tool JSON.",
      );
    }

    if (outer.result.isError === true) {
      const message =
        isRecord(parsed) && typeof parsed.error === "string"
          ? parsed.error.slice(0, 500)
          : "UFOSINT tool request failed.";

      throw new HttpError(
        502,
        "ufosint_tool_error",
        message,
      );
    }

    return parsed;
  } finally {
    clearTimeout(timeout);
  }
}



function normalizeUfosintReport(
  searchRecord: JsonRecord,
  detail: JsonRecord,
  indexedAt: Date,
  minimumQuality: number,
): UfosintReport | null {
  const merged: JsonRecord = {
    ...searchRecord,
    ...detail,
  };

  const observed = exactEventDate(merged.date_event);

  if (
    !observed ||
    observed.valueOf() > indexedAt.valueOf()
  ) {
    return null;
  }

  if (removedOrEmptyDescription(merged.description)) {
    return null;
  }

  const latitude = Number(merged.latitude);
  const longitude = Number(merged.longitude);

  if (
    !Number.isFinite(latitude) ||
    latitude < -90 ||
    latitude > 90 ||
    !Number.isFinite(longitude) ||
    longitude < -180 ||
    longitude > 180
  ) {
    return null;
  }

  const identifier = integer(merged.id);

  if (identifier === null || identifier < 1) {
    return null;
  }

  const qualityScore = localQualityScore(
    merged,
    observed,
    indexedAt,
  );

  if (qualityScore < minimumQuality) {
    return null;
  }

  const place = locationName(merged);
  const shape = text(
    merged.standardized_shape || merged.shape,
    64,
  );

  return {
    reportId: `ufosint:${identifier}`,
    observedAt: observed.toISOString(),
    publishedAt: null,
    indexedAt: indexedAt.toISOString(),
    latitude: quantize(latitude),
    longitude: quantize(longitude),
    title: (
      shape
        ? `${shape} observation near ${place}`
        : `Unidentified observation near ${place}`
    ).slice(0, 180),
    locationName: place.slice(0, 180),
    coordinatePrecision: "city",
    sourceKey: "ufosint",
    sourceName: "UFOSINT Explorer",
    sourceUrl: null,
    summary: sanitizeWitnessSummary(merged.description) || metadataSummary(merged),
    status: "unverified",
    reportClass: "current-index",
    qualityScore,
  };
}


async function mapInBatches<T, R>(
  values: readonly T[],
  batchSize: number,
  operation: (value: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = [];
  for (let index = 0; index < values.length; index += batchSize) {
    const batch = values.slice(index, index + batchSize);
    const settled = await Promise.allSettled(batch.map(operation));
    for (const item of settled) {
      if (item.status === "fulfilled") results.push(item.value);
    }
  }
  return results;
}



interface DateSlice {
  from: string;
  to: string;
}

function monthlyDateSlices(start: Date, end: Date): DateSlice[] {
  const slices: DateSlice[] = [];
  let cursor = new Date(Date.UTC(
    start.getUTCFullYear(),
    start.getUTCMonth(),
    1,
  ));

  while (cursor <= end) {
    const monthStart = new Date(Math.max(cursor.valueOf(), start.valueOf()));
    const nextMonth = new Date(Date.UTC(
      cursor.getUTCFullYear(),
      cursor.getUTCMonth() + 1,
      1,
    ));
    const monthEnd = new Date(Math.min(
      end.valueOf(),
      nextMonth.valueOf() - 1,
    ));

    slices.push({
      from: monthStart.toISOString().slice(0, 10),
      to: monthEnd.toISOString().slice(0, 10),
    });
    cursor = nextMonth;
  }

  return slices;
}

async function loadUfosint(
  current: UfosintSettings,
): Promise<UfosintReport[]> {
  const indexedAt = new Date();
  const start = new Date(indexedAt);
  start.setUTCDate(start.getUTCDate() - current.lookbackDays);

  const slices = monthlyDateSlices(start, indexedAt);
  const payloads = await mapInBatches(
    slices,
    3,
    async (slice) => {
      const value = await callUfosintTool(
        "search_sightings",
        {
          date_from: slice.from,
          date_to: slice.to,
          limit: Math.min(current.candidateLimit, 200),
        },
      );
      const search = unwrapToolResult(value);
      if (!search || !Array.isArray(search.results)) {
        throw new HttpError(
          502,
          "ufosint_invalid_search",
          `UFOSINT search response was invalid for ${slice.from}.`,
        );
      }
      return search.results.filter(isRecord);
    },
  );

  const byId = new Map<number, JsonRecord>();
  for (const records of payloads) {
    for (const record of records) {
      const identifier = integer(record.id);
      if (identifier !== null && identifier > 0) {
        byId.set(identifier, record);
      }
    }
  }

  return [...byId.values()]
    .map((candidate) =>
      normalizeUfosintReport(
        candidate,
        candidate,
        indexedAt,
        current.minimumQuality,
      ),
    )
    .filter(
      (report): report is UfosintReport =>
        report !== null &&
        report.qualityScore >= current.minimumQuality,
    )
    .sort((left, right) =>
      left.observedAt.localeCompare(right.observedAt),
    );
}




async function responseTextWithLimit(
  response: Response,
  maximum: number,
): Promise<string> {
  const body = await response.text();
  if (new TextEncoder().encode(body).byteLength > maximum) {
    throw new HttpError(
      502,
      "ufo_reports_too_large",
      "UFO report response exceeded its size limit.",
    );
  }
  return body;
}

async function loadHistorical(
  request: Request,
  env: CurrentReportEnv,
): Promise<JsonRecord> {
  const historicalUrl = new URL("/science/uap-public-reports.json", request.url);
  const response = await env.ASSETS.fetch(
    new Request(historicalUrl, { method: "GET" }),
  );
  if (!response.ok) {
    throw new HttpError(
      503,
      "historical_reports_unavailable",
      "Historical public reports are unavailable.",
    );
  }
  const body = await responseTextWithLimit(response, 6_000_000);
  const parsed: unknown = JSON.parse(body);
  if (!isRecord(parsed) || !Array.isArray(parsed.reports) || !isRecord(parsed.source)) {
    throw new HttpError(
      503,
      "historical_reports_invalid",
      "Historical public reports are invalid.",
    );
  }
  return parsed;
}

function evenlySample<T>(records: readonly T[], maximum: number): T[] {
  if (records.length <= maximum) return [...records];
  if (maximum <= 0) return [];
  if (maximum === 1) return [records[records.length - 1]];
  return Array.from({ length: maximum }, (_, index) => {
    const sourceIndex = Math.round((index * (records.length - 1)) / (maximum - 1));
    return records[sourceIndex];
  });
}

async function buildMergedBody(
  request: Request,
  env: CurrentReportEnv,
  current: UfosintSettings,
): Promise<string> {
  const historical = await loadHistorical(request, env);
  const historicalReports = (historical.reports as unknown[]).map((report) =>
    isRecord(report)
      ? {
          ...report,
          sourceName: text(report.sourceName || report.sourceKey, 180) || "Archive",
          publishedAt: null,
          indexedAt: null,
          summary: "",
          status: "unknown",
          reportClass: "historical-archive",
          qualityScore: 0,
        }
      : report
  );

  let currentReports: UfosintReport[] = [];
  let currentFeedStatus = "current";
  try {
    currentReports = await loadUfosint(current);
  } catch (error) {
    console.warn("UFOSINT unavailable; serving historical reports only.", error);
    currentFeedStatus = "unavailable";
  }

  // Third quality gate before serialization.
  currentReports = currentReports.filter(
    (report) => report.qualityScore >= current.minimumQuality,
  );
  const historicalLimit = Math.max(0, MAX_MERGED_REPORTS - currentReports.length);
  const selectedHistorical = evenlySample(historicalReports, historicalLimit);
  const reports = [...selectedHistorical, ...currentReports].sort((left, right) => {
    const leftTime = isRecord(left) ? String(left.observedAt ?? "") : "";
    const rightTime = isRecord(right) ? String(right.observedAt ?? "") : "";
    return leftTime.localeCompare(rightTime);
  });
  const observedTimes = reports
    .map((report) => isRecord(report) ? new Date(String(report.observedAt)) : null)
    .filter((value): value is Date => value !== null && !Number.isNaN(value.valueOf()));
  const historicalSource = historical.source as JsonRecord;

  return JSON.stringify({
    schemaVersion: "1.2.0",
    source: {
      name: `${text(historicalSource.name, 180) || "Historical public reports"} + UFOSINT Explorer`,
      pageUrl: text(historicalSource.pageUrl, 500) || UFOSINT_PAGE_URL,
      dataUrl: null,
      license:
        `Mixed sources: ${text(historicalSource.license, 120) || "historical license"}; ` +
        "UFOSINT public derived fields",
      licenseUrl: text(historicalSource.licenseUrl, 500) || null,
      allowedHosts: [
        "archives.gov",
        "catalog.archives.gov",
        "ufosint.com",
      ],
    },
    selection: {
      eligibleCount: reports.length,
      publishedCount: reports.length,
      method:
        "Historical archive plus UFOSINT API records with a strict quality score of " +
        `${current.minimumQuality} or higher and city-level coordinate quantization.`,
    },
    timeExtent: {
      start: observedTimes.at(0)?.toISOString() ?? null,
      end: observedTimes.at(-1)?.toISOString() ?? null,
    },
    currentFeedStatus,
    currentSource: {
      key: "ufosint",
      name: "UFOSINT Explorer",
      pageUrl: UFOSINT_PAGE_URL,
      authorizationMode: "api",
      minimumQualityScore: current.minimumQuality,
      recordCount: currentReports.length,
      terminology: "newly indexed; UFOSINT does not expose per-record publication time",
    },
    reports,
  });
}

function responseFor(
  request: Request,
  body: string,
  current: UfosintSettings,
): Response {
  return new Response(request.method === "HEAD" ? null : body, {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=300, s-maxage=${current.cacheSeconds}`,
      "X-Content-Type-Options": "nosniff",
      "X-UFOSINT-Minimum-Quality": String(current.minimumQuality),
    },
  });
}

export async function currentUfoReports(
  request: Request,
  env: CurrentReportEnv,
): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response(null, {
      status: 405,
      headers: { Allow: "GET, HEAD" },
    });
  }
  const current = settings(env);
  const now = Date.now();
  if (cached && cached.expiresAt > now) {
    return responseFor(request, cached.body, current);
  }

  // The module cache avoids repeated UFOSINT calls within one Worker isolate.
  // HTTP cache headers allow Cloudflare's edge to reuse the response without
  // depending on the non-standard caches.default TypeScript extension.
  const body = await buildMergedBody(request, env, current);
  cached = { body, expiresAt: now + current.cacheSeconds * 1_000 };
  return responseFor(request, body, current);
}
