/** Sanitized, append-only view of the live campaign's published revisions. */
import type { PublicActivitySnapshot } from "../../src/shared/public-state";
import type { D1Database } from "./cloudflare";
import { HttpError } from "./errors";
import { jsonResponse } from "./responses";
import { parseSnapshot } from "./validation";

interface RevisionRow {
  revision: number;
  state_head_hash: string;
  snapshot_json: string;
  published_at: string;
}

function boundedInteger(raw: string | null, label: string, minimum: number, maximum: number,
  fallback: number): number {
  if (raw === null) return fallback;
  if (!/^(?:0|[1-9]\d*)$/u.test(raw)) {
    throw new HttpError(400, `invalid_${label}`, `${label} must be a nonnegative integer.`);
  }
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new HttpError(400, `invalid_${label}`, `${label} is outside its allowed range.`);
  }
  return parsed;
}

function validatedSnapshot(row: RevisionRow): PublicActivitySnapshot {
  let snapshot: PublicActivitySnapshot;
  try {
    snapshot = parseSnapshot(JSON.parse(row.snapshot_json) as unknown);
  } catch {
    throw new HttpError(500, "invalid_stored_snapshot", "A published public record is invalid.");
  }
  if (snapshot.environment !== "live" || snapshot.revision !== row.revision ||
      snapshot.stateHeadHash !== row.state_head_hash || snapshot.updatedAt !== row.published_at) {
    throw new HttpError(500, "invalid_stored_snapshot", "A published public record is inconsistent.");
  }
  return snapshot;
}

function recordEntry(row: RevisionRow): {
  revision: number;
  updatedAt: string;
  sequence: number | null;
  positionId: string;
  positionTitle: string;
  stateHeadHash: string;
  observationSummary: string | null;
} {
  const snapshot = validatedSnapshot(row);
  const latestObservation = "recentObservations" in snapshot
    ? snapshot.recentObservations.at(-1) : undefined;
  return {
    revision: snapshot.revision,
    updatedAt: snapshot.updatedAt,
    sequence: "sequence" in snapshot ? snapshot.sequence : null,
    positionId: snapshot.positionId,
    positionTitle: snapshot.positionTitle,
    stateHeadHash: snapshot.stateHeadHash,
    observationSummary: "sequence" in snapshot &&
      latestObservation?.sequence === snapshot.sequence ? latestObservation.summary : null,
  };
}

export async function readPublicRecord(request: Request, db: D1Database): Promise<Response> {
  const url = new URL(request.url);
  const after = boundedInteger(url.searchParams.get("after"), "after", 0,
    Number.MAX_SAFE_INTEGER, 0);
  const limit = boundedInteger(url.searchParams.get("limit"), "limit", 1, 100, 50);
  const result = await db.prepare(
    `SELECT revision, state_head_hash, snapshot_json, published_at
     FROM public_state_revisions
     WHERE environment = ? AND revision > ?
     ORDER BY revision ASC LIMIT ?`,
  ).bind("live", after, limit + 1).all<RevisionRow>();
  const rows = result.results ?? [];
  const response = jsonResponse({ environment: "live",
    entries: rows.slice(0, limit).map(recordEntry), hasMore: rows.length > limit });
  return request.method === "HEAD"
    ? new Response(null, { status: response.status, headers: response.headers }) : response;
}

export async function readPublicRecordRevision(
  request: Request,
  db: D1Database,
  rawRevision: string,
): Promise<Response> {
  const revision = boundedInteger(rawRevision, "revision", 1, Number.MAX_SAFE_INTEGER, 0);
  const row = await db.prepare(
    `SELECT revision, state_head_hash, snapshot_json, published_at
     FROM public_state_revisions
     WHERE environment = ? AND revision = ?`,
  ).bind("live", revision).first<RevisionRow>();
  if (!row) {
    throw new HttpError(404, "record_revision_unavailable", "That public revision has not been published.");
  }
  const response = jsonResponse(validatedSnapshot(row));
  response.headers.set("X-Public-Source", "live-projection");
  return request.method === "HEAD"
    ? new Response(null, { status: response.status, headers: response.headers }) : response;
}
