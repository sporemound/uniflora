import {
  sanitizePublicReportSnapshot,
  type PublicReportRecord,
} from "../../src/shared/external-map-layers";
import {
  DYNAMICAL_DATASETS,
  planDynamicalEvidence,
} from "../../src/shared/dynamical-data";
import {
  UFOSINT_SIDEQUEST_LIMITS,
  UFOSINT_SIDEQUEST_TEMPLATE_VERSION,
  type AddUfosintSidequestFindingInput,
  type AddUfosintSidequestReviewInput,
  type AttachUfosintSidequestArtifactInput,
  type UfosintActor,
  type UfosintSidequestArtifact,
} from "../../src/shared/ufosint-sidequest";
import type { AssetBinding, D1Database } from "./cloudflare";
import { verifyHyphaSignature } from "./crypto";
import { currentUfoReports } from "./current-ufo-reports";
import { cleanupExpiredRows, nonceInsert } from "./database";
import { HttpError } from "./errors";
import { jsonResponse, methodNotAllowed } from "./responses";
import { requireActivityPrincipal, type ActivityPrincipal, type PrincipalEnv } from "./principal";
import {
  addUfosintSidequestFinding,
  addUfosintSidequestReview,
  attachUfosintSidequestArtifact,
  createUfosintSidequest,
  getUfosintSidequest,
  getUfosintSidequestArtifactContent,
  listUfosintSidequestEvents,
  listUfosintSidequests,
  updateUfosintSidequestLifecycle,
  updateUfosintSidequestTask,
} from "./ufosint-sidequests";
import {
  buildUfosintReportSnapshot,
  canonicalUfosintReportId,
  defaultUfosintSidequestTasks,
} from "./ufosint-sidequest-template";

interface UfosintSidequestApiEnv extends PrincipalEnv {
  ASSETS: AssetBinding;
  PUBLIC_DB: D1Database;
  HYPHA_ACTIVITY_SECRET?: string;
  HYPHA_MAX_CLOCK_SKEW_SECONDS?: string;
  UFOSINT_MIN_QUALITY_SCORE?: string;
  UFOSINT_LOOKBACK_DAYS?: string;
  UFOSINT_CANDIDATE_LIMIT?: string;
  UFOSINT_CACHE_SECONDS?: string;
}

type JsonRecord = Record<string, unknown>;

const MAX_USER_BODY_BYTES = 256 * 1024;
const MAX_ARTIFACT_BODY_BYTES = UFOSINT_SIDEQUEST_LIMITS.artifactAttachmentJsonBytes;
const DEFAULT_CLOCK_SKEW_SECONDS = 300;
const DYNAMICAL_WORKER: UfosintActor = {
  participantId: "hypha_dynamical_worker",
  displayName: "Hypha Dynamical evidence worker",
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numericSetting(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

async function readJson(
  request: Request,
  maximumBytes: number,
): Promise<{ value: unknown; body: ArrayBuffer }> {
  const declared = Number.parseInt(request.headers.get("Content-Length") ?? "0", 10);
  if (Number.isFinite(declared) && declared > maximumBytes) {
    throw new HttpError(413, "payload_too_large", `Request exceeds ${maximumBytes} bytes.`);
  }
  const body = await request.arrayBuffer();
  if (body.byteLength > maximumBytes) {
    throw new HttpError(413, "payload_too_large", `Request exceeds ${maximumBytes} bytes.`);
  }
  try {
    return { value: JSON.parse(new TextDecoder().decode(body)) as unknown, body };
  } catch {
    throw new HttpError(400, "invalid_json", "Request body is not valid JSON.");
  }
}

function operationId(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length < 1 ||
    value.length > UFOSINT_SIDEQUEST_LIMITS.id ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/u.test(value)
  ) {
    throw new HttpError(400, "invalid_operation_id", "A valid operationId is required.");
  }
  return value;
}

function expectedRevision(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1) {
    throw new HttpError(
      400,
      "invalid_expected_revision",
      "expectedRevision must be a positive safe integer.",
    );
  }
  return Number(value);
}

function actorFromSession(session: ActivityPrincipal): UfosintActor {
  return {
    participantId: session.participantId,
    displayName: session.displayName,
  };
}

function decodedSidequestId(encoded: string): string {
  let value: string;
  try {
    value = decodeURIComponent(encoded);
  } catch {
    throw new HttpError(400, "invalid_sidequest_id", "Sidequest ID is not valid URL text.");
  }
  if (
    value.length < 1 ||
    value.length > UFOSINT_SIDEQUEST_LIMITS.id ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/u.test(value)
  ) {
    throw new HttpError(400, "invalid_sidequest_id", "Sidequest ID is invalid.");
  }
  return value;
}

function decodedArtifactId(encoded: string): string {
  let value: string;
  try {
    value = decodeURIComponent(encoded);
  } catch {
    throw new HttpError(400, "invalid_artifact_id", "Artifact ID is not valid URL text.");
  }
  if (
    value.length < 1 ||
    value.length > UFOSINT_SIDEQUEST_LIMITS.id ||
    !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/u.test(value)
  ) {
    throw new HttpError(400, "invalid_artifact_id", "Artifact ID is invalid.");
  }
  return value;
}

async function currentReport(
  request: Request,
  env: UfosintSidequestApiEnv,
  reportId: string,
): Promise<{ report: PublicReportRecord; sourcePageUrl: string }> {
  const feedUrl = new URL("/api/ufo-reports", request.url);
  const feed = await currentUfoReports(
    new Request(feedUrl, {
      method: "GET",
      headers: { Accept: "application/json" },
    }),
    env,
  );
  if (!feed.ok) {
    throw new HttpError(
      503,
      "ufosint_feed_unavailable",
      "The current UFOSINT index could not be captured for this sidequest.",
    );
  }
  const text = await feed.text();
  if (text.length > 6_000_000) {
    throw new HttpError(503, "ufosint_feed_too_large", "The current UFOSINT index is too large.");
  }
  let value: unknown;
  try {
    value = JSON.parse(text) as unknown;
  } catch {
    throw new HttpError(503, "ufosint_feed_invalid", "The current UFOSINT index is invalid.");
  }
  const snapshot = sanitizePublicReportSnapshot(value);
  const report = snapshot?.reports.find(
    (candidate) => candidate.reportId === reportId && candidate.sourceKey === "ufosint",
  );
  if (!snapshot || !report) {
    throw new HttpError(
      404,
      "ufosint_report_not_found",
      "That report is not present in the current quality-gated UFOSINT index.",
    );
  }
  return { report, sourcePageUrl: snapshot.sourcePageUrl };
}

function stableSidequestId(reportId: string): string {
  return `sidequest_${reportId.replace(":", "_")}`;
}

async function handleCollection(
  request: Request,
  env: UfosintSidequestApiEnv,
): Promise<Response> {
  const session = await requireActivityPrincipal(request, env);
  const actor = actorFromSession(session);
  const url = new URL(request.url);
  if (request.method === "GET") {
    const rawReportId = url.searchParams.get("reportId");
    const reportId = rawReportId ? canonicalUfosintReportId(rawReportId) : undefined;
    const sidequests = await listUfosintSidequests(env.PUBLIC_DB, {
      environment: session.environment,
      reportId,
      limit: 50,
    });
    if (reportId) {
      const snapshot = sidequests[0]
        ? await getUfosintSidequest(env.PUBLIC_DB, session.environment, sidequests[0].sidequestId)
        : null;
      return jsonResponse({ sidequests: snapshot ? [snapshot] : [] });
    }
    return jsonResponse({ sidequests });
  }
  if (request.method !== "POST") return methodNotAllowed(["GET", "POST"]);
  const { value } = await readJson(request, 32 * 1024);
  if (!isRecord(value)) {
    throw new HttpError(400, "invalid_sidequest_create", "Sidequest request must be an object.");
  }
  const reportId = canonicalUfosintReportId(value.reportId);
  const existing = await listUfosintSidequests(env.PUBLIC_DB, {
    environment: session.environment,
    reportId,
    limit: 1,
  });
  if (existing[0]) {
    const snapshot = await getUfosintSidequest(
      env.PUBLIC_DB,
      session.environment,
      existing[0].sidequestId,
    );
    if (snapshot) return jsonResponse(snapshot);
  }
  const source = await currentReport(request, env, reportId);
  const reportSnapshot = buildUfosintReportSnapshot(source.report, source.sourcePageUrl);
  try {
    const created = await createUfosintSidequest(env.PUBLIC_DB, {
      environment: session.environment,
      sidequestId: stableSidequestId(reportId),
      operationId: `create_${crypto.randomUUID()}`,
      actor,
      templateVersion: UFOSINT_SIDEQUEST_TEMPLATE_VERSION,
      reportSnapshot,
      title: `UFOSINT sidequest · ${reportSnapshot.title}`.slice(
        0,
        UFOSINT_SIDEQUEST_LIMITS.title,
      ),
      tasks: defaultUfosintSidequestTasks(),
    });
    return jsonResponse(created, 201);
  } catch (error) {
    // A concurrent create can win the unique report constraint. Read it back
    // rather than asking the investigator to retry an already-open case.
    const raced = await listUfosintSidequests(env.PUBLIC_DB, {
      environment: session.environment,
      reportId,
      limit: 1,
    });
    if (raced[0]) {
      const snapshot = await getUfosintSidequest(env.PUBLIC_DB, session.environment, raced[0].sidequestId);
      if (snapshot) return jsonResponse(snapshot);
    }
    throw error;
  }
}

async function handleActions(
  request: Request,
  env: UfosintSidequestApiEnv,
  sidequestId: string,
): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const session = await requireActivityPrincipal(request, env);
  const actor = actorFromSession(session);
  const { value, body } = await readJson(request, MAX_ARTIFACT_BODY_BYTES);
  if (!isRecord(value) || typeof value.action !== "string") {
    throw new HttpError(400, "invalid_sidequest_action", "Sidequest action is invalid.");
  }
  if (value.action !== "attach_artifact" && body.byteLength > MAX_USER_BODY_BYTES) {
    throw new HttpError(413, "payload_too_large", `Request exceeds ${MAX_USER_BODY_BYTES} bytes.`);
  }
  const base = {
    environment: session.environment,
    sidequestId,
    operationId: operationId(value.operationId),
    expectedRevision: expectedRevision(value.expectedRevision),
    actor,
  };

  switch (value.action) {
    case "update_lifecycle":
      return jsonResponse(await updateUfosintSidequestLifecycle(env.PUBLIC_DB, {
        ...base,
        lifecycle: value.lifecycle as never,
      }));
    case "update_task": {
      const status = value.status;
      const assignee = status === "in_progress"
        ? actor
        : value.assignee === null
          ? null
          : actor;
      return jsonResponse(await updateUfosintSidequestTask(env.PUBLIC_DB, {
        ...base,
        taskId: String(value.taskId ?? ""),
        status: status as never,
        assignee,
        completionNote:
          value.completionNote === null || value.completionNote === undefined
            ? null
            : String(value.completionNote),
      }));
    }
    case "add_finding":
      if (!isRecord(value.finding)) {
        throw new HttpError(400, "invalid_finding", "Finding payload is required.");
      }
      return jsonResponse(await addUfosintSidequestFinding(env.PUBLIC_DB, {
        ...base,
        finding: value.finding as AddUfosintSidequestFindingInput["finding"],
      }));
    case "add_review":
      if (!isRecord(value.review)) {
        throw new HttpError(400, "invalid_review", "Review payload is required.");
      }
      return jsonResponse(await addUfosintSidequestReview(env.PUBLIC_DB, {
        ...base,
        review: value.review as AddUfosintSidequestReviewInput["review"],
      }));
    case "attach_artifact":
      if (!isRecord(value.artifact) || typeof value.contentBase64 !== "string") {
        throw new HttpError(
          400,
          "invalid_artifact",
          "Artifact metadata and canonical contentBase64 are required.",
        );
      }
      if (
        value.artifact.kind === "dynamical_analysis" ||
        value.artifact.kind === "weather_context"
      ) {
        throw new HttpError(
          403,
          "signed_worker_required",
          "Weather and Dynamical analysis artifacts require the signed background-worker endpoint.",
        );
      }
      return jsonResponse(await attachUfosintSidequestArtifact(env.PUBLIC_DB, {
        ...base,
        artifact: value.artifact as AttachUfosintSidequestArtifactInput["artifact"],
        contentBase64: value.contentBase64,
      }));
    default:
      throw new HttpError(400, "unknown_sidequest_action", "Unknown sidequest action.");
  }
}

async function handleItem(
  request: Request,
  env: UfosintSidequestApiEnv,
  sidequestId: string,
  suffix: string | undefined,
): Promise<Response> {
  if (suffix === "actions") return handleActions(request, env, sidequestId);
  const session = await requireActivityPrincipal(request, env);
  if (suffix === "events") {
    if (request.method !== "GET") return methodNotAllowed(["GET"]);
    const url = new URL(request.url);
    const after = Number.parseInt(url.searchParams.get("afterRevision") ?? "0", 10);
    return jsonResponse({
      events: await listUfosintSidequestEvents(env.PUBLIC_DB, {
        environment: session.environment,
        sidequestId,
        afterRevision: Number.isSafeInteger(after) && after >= 0 ? after : 0,
        limit: 200,
      }),
    });
  }
  if (suffix !== undefined) {
    throw new HttpError(404, "not_found", "The requested sidequest route does not exist.");
  }
  if (request.method !== "GET") return methodNotAllowed(["GET"]);
  const snapshot = await getUfosintSidequest(env.PUBLIC_DB, session.environment, sidequestId);
  if (!snapshot) throw new HttpError(404, "sidequest_not_found", "Sidequest was not found.");
  return jsonResponse(snapshot);
}

async function handleArtifactContent(
  request: Request,
  env: UfosintSidequestApiEnv,
  sidequestId: string,
  artifactId: string,
): Promise<Response> {
  if (request.method !== "GET") return methodNotAllowed(["GET"]);
  const session = await requireActivityPrincipal(request, env);
  const content = await getUfosintSidequestArtifactContent(
    env.PUBLIC_DB,
    session.environment,
    sidequestId,
    artifactId,
  );
  if (!content) {
    throw new HttpError(404, "sidequest_artifact_not_found", "Artifact content was not found.");
  }
  const body = new Uint8Array(content.bytes.byteLength);
  body.set(content.bytes);
  return new Response(body.buffer, {
    headers: {
      "Cache-Control": "private, max-age=31536000, immutable",
      "Content-Disposition": `attachment; filename="ufosint-artifact-${content.contentSha256.slice(0, 16)}"`,
      "Content-Length": String(content.byteLength),
      "Content-Security-Policy": "sandbox; default-src 'none'",
      "Content-Type": content.mediaType,
      "Cross-Origin-Resource-Policy": "same-origin",
      ETag: `"${content.contentSha256}"`,
      "Last-Modified": new Date(content.createdAt).toUTCString(),
      "Referrer-Policy": "no-referrer",
      Vary: "Authorization, Cookie",
      "X-Content-SHA256": content.contentSha256,
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function consumeSignedNonce(
  request: Request,
  env: UfosintSidequestApiEnv,
  body: ArrayBuffer,
): Promise<void> {
  const signed = await verifyHyphaSignature(
    request,
    body,
    env.HYPHA_ACTIVITY_SECRET ?? "",
    numericSetting(env.HYPHA_MAX_CLOCK_SKEW_SECONDS, DEFAULT_CLOCK_SKEW_SECONDS),
  );
  const now = Math.floor(Date.now() / 1000);
  await cleanupExpiredRows(env.PUBLIC_DB, now);
  try {
    await nonceInsert(env.PUBLIC_DB, {
      nonce: signed.nonce,
      requestPath: new URL(request.url).pathname,
      bodySha256: signed.bodySha256,
      acceptedAt: now,
      expiresAt: now + 86_400,
    }).run();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (detail.includes("hypha_request_nonces")) {
      throw new HttpError(409, "replayed_request", "The Hypha nonce has already been used.");
    }
    throw error;
  }
}

async function handleHyphaJobs(
  request: Request,
  env: UfosintSidequestApiEnv,
): Promise<Response> {
  if (request.method !== "GET") return methodNotAllowed(["GET"]);
  const body = new ArrayBuffer(0);
  await consumeSignedNonce(request, env, body);
  const requestedLimit = Number.parseInt(new URL(request.url).searchParams.get("limit") ?? "10", 10);
  const limit = Number.isSafeInteger(requestedLimit)
    ? Math.max(1, Math.min(requestedLimit, 25))
    : 10;
  const summaries = await listUfosintSidequests(env.PUBLIC_DB, {
    environment: "test",
    limit: 100,
  });
  const jobs = [];
  for (const summary of summaries) {
    if (jobs.length >= limit || summary.lifecycle === "concluded" || summary.lifecycle === "archived") {
      continue;
    }
    const snapshot = await getUfosintSidequest(env.PUBLIC_DB, "test", summary.sidequestId);
    if (!snapshot) continue;
    const task = snapshot.tasks.find((candidate) => candidate.kind === "meteorological");
    if (!task || ["completed", "waived", "unavailable"].includes(task.status)) {
      continue;
    }
    const requiredDatasetKeys = planDynamicalEvidence(snapshot.reportSnapshot)
      .filter((entry) => entry.status === "eligible" || entry.status === "station-check-required")
      .map((entry) => {
        const definition = DYNAMICAL_DATASETS.find((dataset) => dataset.id === entry.datasetId);
        if (!definition) {
          throw new HttpError(500, "dynamical_registry_error", "Dynamical dataset registry is inconsistent.");
        }
        return definition.analysisKey;
      });
    const completedDatasetKeys = [...new Set(snapshot.artifacts.flatMap((artifact) => {
      if (artifact.kind !== "dynamical_analysis") return [];
      const modelId = artifact.dynamicalAnalysis?.modelId;
      if (!modelId?.startsWith("dynamical_context:")) return [];
      const analysisKey = modelId.slice("dynamical_context:".length);
      const definition = DYNAMICAL_DATASETS.find(
        (dataset) => dataset.analysisKey === analysisKey,
      );
      return definition ? [definition.analysisKey] : [];
    }))].filter((key) => requiredDatasetKeys.includes(key));
    if (requiredDatasetKeys.every((key) => completedDatasetKeys.includes(key))) {
      continue;
    }
    jobs.push({
      sidequestId: snapshot.sidequestId,
      revision: snapshot.revision,
      reportSnapshot: snapshot.reportSnapshot,
      reportSnapshotSha256: snapshot.reportSnapshotSha256,
      timeUncertainty: {
        basis: "day_only",
        reportDay: snapshot.reportSnapshot.observedAt.slice(0, 10),
        dayUncertaintyDays: 1,
      },
      requiredDatasetKeys,
      completedDatasetKeys,
    });
  }
  return jsonResponse({ schemaVersion: "1.0.0", jobs });
}

async function handleHyphaArtifact(
  request: Request,
  env: UfosintSidequestApiEnv,
  sidequestId: string,
): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const { value, body } = await readJson(request, MAX_ARTIFACT_BODY_BYTES);
  await consumeSignedNonce(request, env, body);
  if (
    !isRecord(value) ||
    !isRecord(value.artifact) ||
    typeof value.contentBase64 !== "string"
  ) {
    throw new HttpError(400, "invalid_sidequest_artifact", "Signed artifact payload is invalid.");
  }
  const artifact = value.artifact as unknown as Omit<
    UfosintSidequestArtifact,
    "createdBy" | "createdAt"
  >;
  if (artifact.kind !== "dynamical_analysis") {
    throw new HttpError(
      400,
      "invalid_sidequest_artifact",
      "This worker endpoint accepts only Dynamical analysis artifacts.",
    );
  }
  const snapshot = await attachUfosintSidequestArtifact(env.PUBLIC_DB, {
    environment: "test",
    sidequestId,
    operationId: operationId(value.operationId),
    expectedRevision: expectedRevision(value.expectedRevision),
    actor: DYNAMICAL_WORKER,
    artifact,
    contentBase64: value.contentBase64,
  });
  return jsonResponse({
    ok: true,
    sidequestId: snapshot.sidequestId,
    revision: snapshot.revision,
    artifactId: artifact.artifactId,
  }, 201);
}

export function matchesUfosintSidequestApi(pathname: string): boolean {
  return (
    pathname === "/api/ufosint-sidequests" ||
    pathname.startsWith("/api/ufosint-sidequests/") ||
    pathname === "/api/hypha/ufosint-sidequests/jobs" ||
    pathname.startsWith("/api/hypha/ufosint-sidequests/")
  );
}

export async function handleUfosintSidequestApi(
  request: Request,
  env: UfosintSidequestApiEnv,
): Promise<Response> {
  const pathname = new URL(request.url).pathname;
  if (pathname === "/api/ufosint-sidequests") {
    return handleCollection(request, env);
  }
  if (pathname === "/api/hypha/ufosint-sidequests/jobs") {
    return handleHyphaJobs(request, env);
  }
  const hyphaArtifact = /^\/api\/hypha\/ufosint-sidequests\/([^/]+)\/artifacts$/u.exec(pathname);
  if (hyphaArtifact) {
    return handleHyphaArtifact(request, env, decodedSidequestId(hyphaArtifact[1]));
  }
  const artifactContent =
    /^\/api\/ufosint-sidequests\/([^/]+)\/artifacts\/([^/]+)\/content$/u.exec(pathname);
  if (artifactContent) {
    return handleArtifactContent(
      request,
      env,
      decodedSidequestId(artifactContent[1]),
      decodedArtifactId(artifactContent[2]),
    );
  }
  const item = /^\/api\/ufosint-sidequests\/([^/]+)(?:\/(actions|events))?$/u.exec(pathname);
  if (item) {
    return handleItem(request, env, decodedSidequestId(item[1]), item[2]);
  }
  throw new HttpError(404, "not_found", "The requested sidequest route does not exist.");
}
