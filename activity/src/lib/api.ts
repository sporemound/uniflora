import {
  normalizePublicActivitySnapshot,
  type EnvironmentName,
  type PublicActivitySnapshot,
  type PublicActivitySnapshotV20,
} from "../shared/public-state";

const PUBLIC_STATE_ENDPOINT = "/api/public-state";
const PREVIEW_CAPTURE_ENDPOINT = "/api/preview-capture";
const PUBLIC_RECORD_ENDPOINT = "/api/public-record";
const PREVIEW_ONLY = import.meta.env.VITE_PREVIEW_ONLY === "true";

export type SnapshotOrigin = "published" | "archived" | "unavailable";

export interface SnapshotResult {
  snapshot: PublicActivitySnapshot;
  origin: SnapshotOrigin;
  warning: string | null;
}

export interface PublicRecordEntry {
  revision: number;
  updatedAt: string;
  sequence: number | null;
  positionId: string;
  positionTitle: string;
  stateHeadHash: string;
  observationSummary: string | null;
}

export interface PublicRecordPage {
  environment: "live";
  entries: PublicRecordEntry[];
  hasMore: boolean;
}

export class PublicRecordError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "PublicRecordError";
  }
}

function unavailableSnapshot(environment: EnvironmentName): PublicActivitySnapshotV20 {
  return {
    schemaVersion: "2.0.0",
    source: "mock",
    environment,
    revision: 0,
    stateHeadHash: "unavailable",
    previousStateHeadHash: null,
    positionId: "unavailable",
    positionTitle: "Public record unavailable",
    focusLocationId: "",
    updatedAt: "",
    zuluTime: "—",
    facilityTime: "—",
    facilityTimezone: "Pacific",
    metrics: {
      activeAssignments: 0,
      completedArtifacts: 0,
      unresolvedContradictions: 0,
      awaitingVerification: 0,
    },
    locations: [],
    assignments: [],
    latestPublication: null,
    nextRequirement: "Wait for a published public projection.",
  };
}

function endpoint(path: string, environment: EnvironmentName): URL {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("environment", environment);
  return url;
}

async function readSnapshot(response: Response, environment: EnvironmentName): Promise<PublicActivitySnapshot> {
  const value: unknown = await response.json();
  const snapshot = normalizePublicActivitySnapshot(value);
  if (snapshot === null) {
    throw new Error("Public-state payload failed the supported 2.0–2.4 schema check.");
  }
  if (snapshot.environment !== environment) {
    throw new Error(
      `Public-state payload environment ${snapshot.environment} did not match requested ${environment}.`,
    );
  }
  return snapshot;
}

async function responseFailure(response: Response, label: string): Promise<Error> {
  const detail = (await response.text()).slice(0, 200);
  return new Error(`${label} returned ${response.status}${detail ? `: ${detail}` : ""}.`);
}

export async function loadPublicSnapshot(
  environment: EnvironmentName,
): Promise<SnapshotResult> {
  let liveFailure: string | null = null;
  try {
    if (!PREVIEW_ONLY || environment === "live") {
      const response = await fetch(endpoint(PUBLIC_STATE_ENDPOINT, environment), {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (response.ok) {
        if (!PREVIEW_ONLY || response.headers.get("X-Public-Source") === "live-projection") {
          return {
            snapshot: await readSnapshot(response, environment),
            origin: "published",
            warning: null,
          };
        }
        liveFailure = "The live endpoint did not identify an authoritative projection.";
      } else {
        liveFailure = (await responseFailure(response, "Public-state endpoint")).message;
      }
      if (!PREVIEW_ONLY) throw new Error(liveFailure);
    }

    // The captured case is intentionally separate from the live projection.
    const capture = await fetch(endpoint(PREVIEW_CAPTURE_ENDPOINT, environment), {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!capture.ok) throw await responseFailure(capture, "Captured-case endpoint");
    if (capture.headers.get("X-Preview-Source") !== "captured-public-projection") {
      throw new Error("Captured-case response was missing its archive marker.");
    }
    return {
      snapshot: await readSnapshot(capture, environment),
      origin: "archived",
      warning: liveFailure
        ? "Showing the captured case because the live public projection is not available."
        : "Showing the captured case archive.",
    };
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unknown API failure.";
    return {
      snapshot: unavailableSnapshot(environment),
      origin: "unavailable",
      warning: `Public record unavailable: ${detail}`,
    };
  }
}

function isPublicRecordEntry(value: unknown): value is PublicRecordEntry {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  return Number.isSafeInteger(item.revision) && Number(item.revision) > 0 &&
    typeof item.updatedAt === "string" && item.updatedAt.length > 0 &&
    (item.sequence === null || (Number.isSafeInteger(item.sequence) && Number(item.sequence) >= 0)) &&
    typeof item.positionId === "string" && item.positionId.length > 0 &&
    typeof item.positionTitle === "string" && item.positionTitle.length > 0 &&
    typeof item.stateHeadHash === "string" && item.stateHeadHash.length > 0 &&
    (item.observationSummary === null || typeof item.observationSummary === "string");
}

export async function loadPublicRecordPage(
  after: number,
  signal?: AbortSignal,
): Promise<PublicRecordPage> {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new Error("Invalid public record cursor.");
  }
  const url = endpoint(PUBLIC_RECORD_ENDPOINT, "live");
  url.searchParams.set("after", String(after));
  url.searchParams.set("limit", "100");
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 200);
    throw new PublicRecordError(
      response.status,
      `Public record returned ${response.status}${detail ? `: ${detail}` : ""}.`,
    );
  }
  const value: unknown = await response.json();
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Public record did not match its expected format.");
  }
  const page = value as Record<string, unknown>;
  if (page.environment !== "live" || !Array.isArray(page.entries) ||
    typeof page.hasMore !== "boolean" || page.entries.length > 100 ||
    !page.entries.every(isPublicRecordEntry)) {
    throw new Error("Public record did not match its expected format.");
  }
  let prior = after;
  for (const item of page.entries as PublicRecordEntry[]) {
    if (item.revision <= prior) throw new Error("Public record entries are out of order.");
    prior = item.revision;
  }
  if (page.hasMore && page.entries.length === 0) {
    throw new Error("Public record pagination did not advance.");
  }
  return page as unknown as PublicRecordPage;
}

export async function loadPublicRevisionSnapshot(
  entry: PublicRecordEntry,
  signal?: AbortSignal,
): Promise<PublicActivitySnapshot> {
  const url = new URL(`${PUBLIC_RECORD_ENDPOINT}/${entry.revision}`, window.location.origin);
  url.searchParams.set("environment", "live");
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 200);
    throw new PublicRecordError(
      response.status,
      `Published revision ${entry.revision} returned ${response.status}${detail ? `: ${detail}` : ""}.`,
    );
  }
  if (response.headers.get("X-Public-Source") !== "live-projection") {
    throw new Error("Published revision was missing its live-source marker.");
  }
  const snapshot = await readSnapshot(response, "live");
  if (snapshot.revision !== entry.revision ||
    snapshot.stateHeadHash !== entry.stateHeadHash ||
    snapshot.updatedAt !== entry.updatedAt) {
    throw new Error("Published revision does not match its record entry.");
  }
  return snapshot;
}
