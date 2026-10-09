import {
  MOCK_PUBLIC_STATE,
  type EnvironmentName,
} from "../src/shared/public-state";
import { exchangeDiscordCode, requireSession, revokeSession } from "./lib/auth";
import {
  handleMagicLinkRequest,
  handleMagicLinkVerify,
  readWebSession,
  revokeWebSession,
} from "./lib/magic-link-auth";
import { hasActivityCredential, requireActivityPrincipal, type ActivityPrincipal } from "./lib/principal";
import { handleGameProxy } from "./lib/game-proxy";
import type {
  AssetBinding,
  D1Database,
  DurableObjectNamespace,
  R2Bucket,
} from "./lib/cloudflare";
import { verifyHyphaSignature } from "./lib/crypto";
import {
  cleanupExpiredRows,
  cleanupExpiredChatRows,
  claimNextHyphaChatRequest,
  completeHyphaChatRequest,
  createHyphaChatRequest,
  getArtifactFile,
  getHyphaChatAudio,
  getHyphaChatMessage,
  getHyphaChatMessagesForRequest,
  getCurrentSnapshot,
  getLatestPublication,
  listArtifactFiles,
  listHyphaChatMessages,
  nonceInsert,
  publishPublication,
  publishSnapshot,
  registerArtifactFile,
  recentHyphaChatConversation,
} from "./lib/database";
import { HttpError } from "./lib/errors";
import { InvestigationRoom } from "./lib/investigation-room";
import {
  signRoomTicket,
  stableTicketIdentity,
  verifyRoomTicket,
  type RoomTicketPayload,
} from "./lib/room-ticket";
import { bundledTestScientificScope } from "./lib/bundled-science";
import { environmentalContext } from "./lib/environmental-context";
import { currentUfoReports } from "./lib/current-ufo-reports";
import { handleDynamicalRenderManifest } from "./lib/dynamical-render-manifest";
import {
  handleUfosintSidequestApi,
  matchesUfosintSidequestApi,
} from "./lib/ufosint-sidequest-api";
import {
  ROOM_ID_MAX_LENGTH,
  type RoomTicketRequest,
} from "../src/shared/investigation-room";
import {
  artifactResponse,
  errorResponse,
  jsonResponse,
  methodNotAllowed,
} from "./lib/responses";
import {
  parseEnvironment,
  parseFilename,
  parseIdentifier,
  parsePublication,
  parseSnapshot,
} from "./lib/validation";

interface Env {
  ASSETS: AssetBinding;
  PUBLIC_DB: D1Database;
  CHAT_DB: D1Database;
  PUBLIC_ARTIFACTS?: R2Bucket;
  LIVE_ROOMS: DurableObjectNamespace;
  DISCORD_CLIENT_ID?: string;
  DISCORD_CLIENT_SECRET?: string;
  DISCORD_BOT_TOKEN?: string;
  ACTIVITY_ALLOWED_GUILD_ID?: string;
  ACTIVITY_ALLOWED_TEST_CHANNEL_ID?: string;
  ACTIVITY_ALLOWED_LIVE_CHANNEL_ID?: string;
  ACTIVITY_LIVE_PLAYER_ROLE_ID?: string;
  ACTIVITY_ALLOWED_DISCORD_USER_IDS?: string;
  HYPHA_ACTIVITY_SECRET?: string;
  ACTIVITY_IDENTITY_SECRET?: string;
  SESSION_TTL_SECONDS?: string;
  HYPHA_MAX_CLOCK_SKEW_SECONDS?: string;
  ROOM_TICKET_SECRET?: string;
  ROOM_TICKET_TTL_SECONDS?: string;
  ALLOW_TEST_GUESTS?: string;
  ALLOW_LIVE_PUBLISHING?: string;
  ALLOW_LIVE_STATE_PUBLISHING?: string;
  UFOSINT_MIN_QUALITY_SCORE?: string;
  UFOSINT_LOOKBACK_DAYS?: string;
  UFOSINT_CANDIDATE_LIMIT?: string;
  UFOSINT_CACHE_SECONDS?: string;
  V2_TEST_STREAM_ID?: string;
  V2_LIVE_STREAM_ID?: string;
  V2_LIVE_CONTENT_VERSION?: string;
  HYPHA_CHAT_ENABLED?: string;
  HYPHA_LIVE_CHAT_ENABLED?: string;
  APP_ORIGIN?: string;
  RESEND_API_KEY?: string;
  MAGIC_LINK_FROM_EMAIL?: string;
  GAME_API_ORIGIN?: string;
  GAME_API_SECRET?: string;
}

const MAX_STATE_BYTES = 512 * 1024;
const MAX_PUBLICATION_BYTES = 128 * 1024;
const MAX_ARTIFACT_BYTES = 15 * 1024 * 1024;
const DEFAULT_SESSION_TTL_SECONDS = 900;
const DEFAULT_CLOCK_SKEW_SECONDS = 300;
const DEFAULT_ROOM_TICKET_TTL_SECONDS = 60;
const ACTIVITY_PERMISSIONS_POLICY =
  "microphone=(), camera=(), geolocation=()";
const RATE_BUCKETS = new Map<string, { count: number; resetsAt: number }>();
const MAX_RATE_BUCKETS = 2_048;
const ALLOWED_ARTIFACT_TYPES = new Set([
  "application/json",
  "application/octet-stream",
  "image/png",
  "image/svg+xml",
  "text/csv",
  "text/plain",
]);

function numericSetting(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function enforceEdgeRate(
  request: Request,
  scope: string,
  maximum: number,
  windowSeconds = 60,
): void {
  const now = Math.floor(Date.now() / 1000);
  const address =
    request.headers.get("CF-Connecting-IP")?.trim() ||
    (isLoopbackRequest(request) ? "loopback" : "unknown");
  const key = `${scope}:${address}`;
  if (RATE_BUCKETS.size >= MAX_RATE_BUCKETS) {
    for (const [key, bucket] of RATE_BUCKETS) {
      if (bucket.resetsAt <= now) RATE_BUCKETS.delete(key);
    }
    if (RATE_BUCKETS.size >= MAX_RATE_BUCKETS && !RATE_BUCKETS.has(key)) {
      throw new HttpError(
        429,
        "rate_limited",
        "The Activity rate limiter is at capacity; retry after the current window.",
      );
    }
  }
  const current = RATE_BUCKETS.get(key);
  if (!current || current.resetsAt <= now) {
    RATE_BUCKETS.set(key, { count: 1, resetsAt: now + windowSeconds });
    return;
  }
  current.count += 1;
  if (current.count > maximum) {
    throw new HttpError(
      429,
      "rate_limited",
      "This Activity endpoint is receiving requests too quickly.",
    );
  }
}

function isLoopbackRequest(request: Request): boolean {
  const hostname = new URL(request.url).hostname.toLowerCase();
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
}

function requireArtifactStorage(env: Env): R2Bucket {
  if (!env.PUBLIC_ARTIFACTS) {
    throw new HttpError(
      503,
      "dynamic_artifacts_disabled",
      "Dynamic artifact storage is disabled in strict-free mode.",
    );
  }
  return env.PUBLIC_ARTIFACTS;
}

function requirePublishableEnvironment(
  environment: EnvironmentName,
  env: Env,
): void {
  if (environment === "live" && env.ALLOW_LIVE_PUBLISHING !== "true") {
    throw new HttpError(
      403,
      "live_publishing_disabled",
      "Live Activity publication is disabled on this private test deployment.",
    );
  }
}

async function readBody(request: Request, maxBytes: number): Promise<ArrayBuffer> {
  const declaredLength = Number.parseInt(request.headers.get("Content-Length") ?? "0", 10);
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    throw new HttpError(413, "payload_too_large", `Request body exceeds ${maxBytes} bytes.`);
  }
  const body = await request.arrayBuffer();
  if (body.byteLength > maxBytes) {
    throw new HttpError(413, "payload_too_large", `Request body exceeds ${maxBytes} bytes.`);
  }
  return body;
}

function decodeJson(body: ArrayBuffer): unknown {
  try {
    return JSON.parse(new TextDecoder().decode(body)) as unknown;
  } catch {
    throw new HttpError(400, "invalid_json", "Request body is not valid JSON.");
  }
}

function artifactRoute(pathname: string): {
  environment: EnvironmentName;
  artifactId: string;
  filename: string;
} | null {
  const match = /^\/api\/(?:hypha\/)?artifacts\/(live|test)\/([^/]+)\/([^/]+)$/.exec(
    pathname,
  );
  if (!match) {
    return null;
  }
  return {
    environment: parseEnvironment(match[1]),
    artifactId: parseIdentifier(decodeURIComponent(match[2]), "artifactId"),
    filename: parseFilename(decodeURIComponent(match[3])),
  };
}

function artifactListRoute(pathname: string): {
  environment: EnvironmentName;
  artifactId: string;
} | null {
  const match = /^\/api\/artifacts\/(live|test)\/([^/]+)$/.exec(pathname);
  if (!match) {
    return null;
  }
  return {
    environment: parseEnvironment(match[1]),
    artifactId: parseIdentifier(decodeURIComponent(match[2]), "artifactId"),
  };
}

async function handlePublicState(request: Request, env: Env): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowed(["GET", "HEAD"]);
  }
  const url = new URL(request.url);
  const environment = parseEnvironment(url.searchParams.get("environment") ?? "test");
  const snapshot = await getCurrentSnapshot(env.PUBLIC_DB, environment);
  if (!snapshot) {
    if (environment === "test") {
      return jsonResponse({
        ...MOCK_PUBLIC_STATE,
        environment,
      });
    }
    throw new HttpError(404, "state_unavailable", "No public live snapshot has been published.");
  }
  return jsonResponse(snapshot);
}


async function handleLatestPublication(request: Request, env: Env): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowed(["GET", "HEAD"]);
  }
  const url = new URL(request.url);
  const environment = parseEnvironment(url.searchParams.get("environment") ?? "test");
  const publication = await getLatestPublication(env.PUBLIC_DB, environment);
  if (!publication) {
    return jsonResponse(null);
  }
  return jsonResponse({
    environment: publication.environment,
    publicationId: publication.publicationId,
    artifactId: publication.artifactId,
    stateHeadHash: publication.stateHeadHash,
    evidenceStateHeadHash: publication.evidenceStateHeadHash ?? null,
    title: publication.title,
    publicSummary: publication.publicSummary,
    limitation: publication.limitation,
    primaryFilename: publication.primaryFilename,
    manifestFilename: publication.manifestFilename ?? null,
    visualizationFilename: publication.visualizationFilename ?? null,
    dataFilename: publication.dataFilename ?? null,
    publishedAt: publication.publishedAt,
  });
}

async function handleDiscordAuth(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return methodNotAllowed(["POST"]);
  }
  const body = await readBody(request, 16 * 1024);
  const value = decodeJson(body);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_auth_request", "Authorization request must be an object.");
  }
  const code = String((value as Record<string, unknown>).code ?? "");
  const instanceId = String((value as Record<string, unknown>).instanceId ?? "");
  const result = await exchangeDiscordCode(env.PUBLIC_DB, {
    code,
    instanceId,
    clientId: env.DISCORD_CLIENT_ID ?? "",
    clientSecret: env.DISCORD_CLIENT_SECRET ?? "",
    botToken: env.DISCORD_BOT_TOKEN ?? "",
    allowedGuildId: env.ACTIVITY_ALLOWED_GUILD_ID ?? "",
    allowedChannelId: env.ACTIVITY_ALLOWED_TEST_CHANNEL_ID ?? "",
    allowedLiveChannelId: env.ACTIVITY_ALLOWED_LIVE_CHANNEL_ID ?? "",
    livePlayerRoleId: env.ACTIVITY_LIVE_PLAYER_ROLE_ID ?? "",
    allowedDiscordUserIds: env.ACTIVITY_ALLOWED_DISCORD_USER_IDS ?? "",
    identitySecret: env.ACTIVITY_IDENTITY_SECRET ?? "",
    sessionTtlSeconds: numericSetting(
      env.SESSION_TTL_SECONDS,
      DEFAULT_SESSION_TTL_SECONDS,
    ),
  });
  await cleanupExpiredRows(env.PUBLIC_DB, Math.floor(Date.now() / 1000));
  return jsonResponse(result, 201);
}

async function handleSession(request: Request, env: Env): Promise<Response> {
  if (request.method !== "GET") {
    return methodNotAllowed(["GET"]);
  }
  if (!request.headers.has("Authorization")) {
    const webSession = await readWebSession(request, env);
    if (!webSession) {
      throw new HttpError(401, "missing_session", "A valid website session is required.");
    }
    return jsonResponse({
      participant: webSession.participant,
      environment: "live",
      authProvider: "email",
      expiresAt: webSession.expiresAt,
    });
  }
  const session = await requireSession(env.PUBLIC_DB, request);
  return jsonResponse({
    participant: {
      participantId: session.participantId,
      displayName: session.displayName,
      avatarUrl: session.avatarUrl,
    },
  });
}

async function handleLogout(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return methodNotAllowed(["POST"]);
  }
  if (!request.headers.has("Authorization")) {
    return revokeWebSession(request, env);
  }
  await revokeSession(env.PUBLIC_DB, request);
  return jsonResponse({ ok: true });
}


const HYPHA_CHAT_TTL_SECONDS = 600;
const HYPHA_CHAT_MAX_AUDIO_BYTES = 1_500_000;

function hyphaChatAudioRoute(pathname: string): string | null {
  const match = /^\/api\/hypha-chat\/([A-Za-z0-9-]+)\/audio$/u.exec(pathname);
  return match ? match[1] : null;
}

function hyphaChatCompletionRoute(pathname: string): string | null {
  const match = /^\/api\/hypha\/chat\/([A-Za-z0-9-]+)\/complete$/u.exec(pathname);
  return match ? match[1] : null;
}

function decodeBase64Bytes(value: string): Uint8Array {
  let binary: string;
  try {
    binary = atob(value);
  } catch {
    throw new HttpError(400, "invalid_audio", "Hypha audio payload is not valid base64.");
  }
  if (binary.length > HYPHA_CHAT_MAX_AUDIO_BYTES) {
    throw new HttpError(413, "audio_too_large", "Hypha audio reply exceeds the relay limit.");
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  if (bytes.length < 4 || new TextDecoder().decode(bytes.subarray(0, 4)) !== "OggS") {
    throw new HttpError(400, "invalid_audio", "Hypha audio must be an OGG recording.");
  }
  return bytes;
}

async function handleMyDifficulty(request: Request, env: Env): Promise<Response> {
  if (request.method !== "GET") return methodNotAllowed(["GET"]);
  const session = await requireActivityPrincipal(request, env);
  const environment = session.environment;
  const row = await env.PUBLIC_DB.prepare(
    `SELECT level, revision FROM activity_difficulty_preferences
     WHERE environment = ? AND discord_user_id = ?`,
  ).bind(environment, session.subjectKey).first<{ level: string; revision: number }>();
  return jsonResponse({ environment, level: row?.level ?? "standard", revision: row?.revision ?? 0 });
}

async function handleHyphaDifficultySync(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const body = await readBody(request, 16 * 1024);
  const signed = await signedRequestMetadata(request, env, body);
  await consumeSignedNonce(env, request, signed);
  const value = decodeJson(body);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_difficulty_sync", "Difficulty sync must be an object.");
  }
  const record = value as Record<string, unknown>;
  const environment = parseEnvironment(typeof record.environment === "string" ? record.environment : null);
  const configuredChannel = environment === "live"
    ? env.ACTIVITY_ALLOWED_LIVE_CHANNEL_ID : env.ACTIVITY_ALLOWED_TEST_CHANNEL_ID;
  if (!configuredChannel || !Array.isArray(record.choices) || record.choices.length > 100) {
    throw new HttpError(400, "invalid_difficulty_sync", "Difficulty sync scope is invalid.");
  }
  const choices = record.choices as unknown[];
  const statements = choices.map((choice) => {
    if (typeof choice !== "object" || choice === null || Array.isArray(choice)) {
      throw new HttpError(400, "invalid_difficulty_sync", "Difficulty choice is invalid.");
    }
    const entry = choice as Record<string, unknown>;
    if (typeof entry.discordUserId !== "string" ||
        !/^[1-9][0-9]{15,21}$/u.test(entry.discordUserId) ||
        typeof entry.level !== "string" ||
        !["guided", "standard", "expert"].includes(entry.level) ||
        typeof entry.revision !== "number" ||
        !Number.isSafeInteger(entry.revision) || entry.revision < 1) {
      throw new HttpError(400, "invalid_difficulty_sync", "Difficulty choice is invalid.");
    }
    return env.PUBLIC_DB.prepare(
      `INSERT INTO activity_difficulty_preferences
       (environment, discord_user_id, level, revision, updated_at)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(environment, discord_user_id) DO UPDATE SET
         level = excluded.level, revision = excluded.revision, updated_at = excluded.updated_at
       WHERE excluded.revision >= activity_difficulty_preferences.revision`,
    ).bind(environment, entry.discordUserId, entry.level, entry.revision,
      Math.floor(Date.now() / 1000));
  });
  if (statements.length > 0) await env.PUBLIC_DB.batch(statements);
  return jsonResponse({ ok: true, count: statements.length });
}

function chatScope(env: Env, environment: EnvironmentName): { environment: EnvironmentName; streamId: string } {
  const enabled = environment === "test" ? env.HYPHA_CHAT_ENABLED : env.HYPHA_LIVE_CHAT_ENABLED;
  const streamId = (environment === "test" ? env.V2_TEST_STREAM_ID : env.V2_LIVE_STREAM_ID)?.trim() ?? "";
  if (enabled !== "true") {
    throw new HttpError(503, "chat_not_enabled", "Shared Hypha chat is not active in this investigation.");
  }
  if (!/^[A-Za-z0-9._:-]{1,128}$/u.test(streamId)) {
    throw new HttpError(503, "chat_scope_unconfigured", "Shared investigation chat is unavailable.");
  }
  return { environment, streamId };
}

function relayChatScope(env: Env, record: Record<string, unknown>): {
  environment: EnvironmentName; streamId: string;
} {
  const environment = parseEnvironment(typeof record.environment === "string" ? record.environment : null);
  const configured = environment === "test" ? env.V2_TEST_STREAM_ID : env.V2_LIVE_STREAM_ID;
  const enabled = environment === "test" ? env.HYPHA_CHAT_ENABLED : env.HYPHA_LIVE_CHAT_ENABLED;
  const streamId = configured?.trim() ?? "";
  if (enabled !== "true") {
    throw new HttpError(503, "chat_not_enabled", "Shared Hypha chat is not active yet.");
  }
  if (!/^[A-Za-z0-9._:-]{1,128}$/u.test(streamId) || record.streamId !== streamId) {
    throw new HttpError(403, "chat_scope_mismatch", "Relay stream does not match this Activity.");
  }
  return { environment, streamId };
}

function publicParticipantText(value: string): string {
  return value
    .replace(/<@!?[0-9]+>/gu, "[participant]")
    .replace(/<(?:@&|#)[0-9]+>/gu, "[Discord reference]")
    .replace(/<t:[0-9]+(?::[tTdDfFR])?>/gu, "[time]")
    .replace(/\b[0-9]{17,20}\b/gu, "[Discord ID]")
    .replace(/https?:\/\/(?:cdn|media)\.discordapp\.(?:com|net)\/\S+/giu,
      "[Discord attachment]");
}

function requestedAlbuquerqueMode(message: string, buttonEnabled: boolean): boolean {
  // A turn-off instruction wins for this request. Mentioning the city alone
  // does not change presentation.
  if (/\b(?:disable|deactivate|turn\s+off|switch\s+off|stop\s+using)\s+(?:the\s+)?albuquerque\s+mode\b/iu.test(message)) {
    return false;
  }
  if (buttonEnabled) return true;
  if (/\b(?:enable|activate|turn\s+on|switch\s+on|use)\s+(?:the\s+)?albuquerque\s+mode\b/iu.test(message)) {
    return true;
  }
  return /\b(?:transform|convert|rewrite|translate)\b.{0,100}\b(?:in|into|to|as|using|with)\s+(?:the\s+)?albuquerque(?:\s+mode)?\b|\b(?:write|answer|reply|respond|say)\b.{0,100}\b(?:in|using|with)\s+(?:the\s+)?albuquerque\s+mode\b|\balbuquerque\s+mode\b.{0,100}\b(?:transform|convert|rewrite|translate)\b/iu.test(message);
}

function publicChatMessage(row: Awaited<ReturnType<typeof getHyphaChatMessage>>): Record<string, unknown> {
  if (!row) throw new HttpError(404, "chat_message_not_found", "Chat message unavailable.");
  return {
    messageId: row.message_id,
    requestId: row.request_id,
    environment: row.environment,
    streamId: row.stream_id,
    senderType: row.sender_type,
    participantId: row.participant_id,
    workingName: row.working_name,
    text: row.content_text,
    status: row.delivery_status,
    audioUrl: row.audio_available === 1 && row.delivery_status === "complete"
      ? `/api/hypha-chat/${encodeURIComponent(row.message_id)}/audio`
      : null,
    createdAt: row.created_at,
    completedAt: row.completed_at,
  };
}

async function handleHyphaChatList(request: Request, env: Env): Promise<Response> {
  if (request.method !== "GET") return methodNotAllowed(["GET", "POST"]);
  const session = await requireActivityPrincipal(request, env);
  const scope = chatScope(env, session.environment);
  const url = new URL(request.url);
  const before = url.searchParams.get("before");
  const after = url.searchParams.get("after");
  if ((before && after) ||
      (before !== null && !/^[A-Za-z0-9-]{1,128}$/u.test(before)) ||
      (after !== null && !/^[A-Za-z0-9-]{1,128}$/u.test(after))) {
    throw new HttpError(400, "invalid_chat_cursor", "Choose one valid chat cursor.");
  }
  const limitText = url.searchParams.get("limit") ?? "50";
  const limit = Number(limitText);
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new HttpError(400, "invalid_chat_limit", "Chat page limit must be 1 to 50.");
  }
  const page = await listHyphaChatMessages(env.CHAT_DB, scope.environment,
    scope.streamId, limit, before, after);
  return jsonResponse({
    environment: scope.environment,
    streamId: scope.streamId,
    messages: page.messages.map(publicChatMessage),
    hasMore: page.hasMore,
  });
}

async function handleHyphaChatCreate(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const session = await requireActivityPrincipal(request, env);
  const value = decodeJson(await readBody(request, 8 * 1024));
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_chat_request", "Chat request must be an object.");
  }
  const record = value as Record<string, unknown>;
  const message = publicParticipantText(String(record.message ?? "")).trim();
  if (!message || message.length > 4000) {
    throw new HttpError(400, "invalid_chat_message", "Message must contain 1 to 4000 characters.");
  }
  if (record.albuquerqueMode !== undefined && typeof record.albuquerqueMode !== "boolean") {
    throw new HttpError(400, "invalid_albuquerque_mode", "Albuquerque mode must be on or off.");
  }
  const albuquerqueMode = requestedAlbuquerqueMode(message, record.albuquerqueMode === true);
  const requestedWorkingName = typeof record.workingName === "string"
    ? publicParticipantText(record.workingName)
      .replace(/[\u0000-\u001f\u007f]/gu, " ").trim().slice(0, 40).trim()
    : "";
  const scope = chatScope(env, session.environment);
  if (record.environment !== undefined && record.environment !== scope.environment) {
    throw new HttpError(403, "chat_scope_mismatch", "That investigation is unavailable.");
  }
  if (record.streamId !== undefined && record.streamId !== scope.streamId) {
    throw new HttpError(403, "chat_scope_mismatch", "That investigation is unavailable.");
  }
  const now = Math.floor(Date.now() / 1000);
  const requestId = crypto.randomUUID();
  const participantMessageId = crypto.randomUUID();
  const hyphaMessageId = crypto.randomUUID();
  await createHyphaChatRequest(env.CHAT_DB, {
    requestId,
    participantId: session.participantId,
    discordUserId: session.subjectKey,
    privacyAlias: session.displayName,
    environment: scope.environment,
    streamId: scope.streamId,
    workingName: requestedWorkingName ||
      `Investigator ${session.participantId.slice(-8).toUpperCase()}`,
    participantMessageId,
    hyphaMessageId,
    messageText: message,
    createdAt: now,
    expiresAt: now + HYPHA_CHAT_TTL_SECONDS,
    albuquerqueMode,
  });
  const createdMessages = await getHyphaChatMessagesForRequest(env.CHAT_DB,
    requestId, scope.environment, scope.streamId);
  return jsonResponse({ requestId, participantMessageId, hyphaMessageId,
    messages: createdMessages.map(publicChatMessage) }, 202);
}

async function handleHyphaChatAudio(
  request: Request,
  env: Env,
  messageId: string,
): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowed(["GET", "HEAD"]);
  }
  const session = await requireActivityPrincipal(request, env);
  const scope = chatScope(env, session.environment);
  const row = await getHyphaChatMessage(env.CHAT_DB, messageId,
    scope.environment, scope.streamId);
  if (!row || row.sender_type !== "hypha" || row.delivery_status !== "complete" ||
      row.audio_available !== 1) {
    throw new HttpError(404, "chat_audio_not_found", "That Hypha audio is unavailable.");
  }
  const audio = await getHyphaChatAudio(env.CHAT_DB, messageId);
  if (!audio) throw new HttpError(503, "chat_audio_missing", "Hypha audio is missing.");
  return new Response(request.method === "HEAD" ? null : Uint8Array.from(audio.audio_bytes), {
    headers: {
      "Content-Type": "audio/ogg",
      "Cache-Control": "private, no-store",
      "Content-Disposition": 'inline; filename="hypha-sealed-stone.ogg"',
    },
  });
}

async function handleHyphaChatClaim(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const body = await readBody(request, 8 * 1024);
  const signed = await signedRequestMetadata(request, env, body);
  await consumeSignedNonce(env, request, signed);
  const value = decodeJson(body);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_chat_scope", "Chat claim must include a scope.");
  }
  const record = value as Record<string, unknown>;
  const scope = relayChatScope(env, record);
  await cleanupExpiredChatRows(env.CHAT_DB, Math.floor(Date.now() / 1000));
  const row = await claimNextHyphaChatRequest(
    env.CHAT_DB,
    Math.floor(Date.now() / 1000),
    scope.environment,
    scope.streamId,
  );
  if (!row) return jsonResponse(null);
  const history = await recentHyphaChatConversation(env.CHAT_DB,
    row.environment, row.stream_id, row.participant_message_id);
  return jsonResponse({
    requestId: row.request_id,
    participantId: row.participant_id,
    discordUserId: row.discord_user_id,
    privacyAlias: row.privacy_alias,
    environment: row.environment,
    streamId: row.stream_id,
    message: row.message_text,
    albuquerqueMode: row.albuquerque_mode === 1,
    history: history.map((item) => ({
      senderType: item.sender_type,
      text: item.content_text,
    })),
  });
}

async function handleHyphaChatComplete(
  request: Request,
  env: Env,
  requestId: string,
): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const body = await readBody(request, 3 * 1024 * 1024);
  const signed = await signedRequestMetadata(request, env, body);
  await consumeSignedNonce(env, request, signed);
  const value = decodeJson(body);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_chat_completion", "Chat completion must be an object.");
  }
  const record = value as Record<string, unknown>;
  const failed = record.failed === true;
  const scope = relayChatScope(env, record);
  const transcriptText = typeof record.transcriptText === "string"
    ? record.transcriptText.trim() : "";
  if (!transcriptText || transcriptText.length > 4000) {
    throw new HttpError(400, "invalid_chat_transcript",
      "Hypha completion requires a transcript of 1 to 4000 characters.");
  }
  const audioBytes = !failed && typeof record.audioBase64 === "string"
    ? decodeBase64Bytes(record.audioBase64) : null;
  if (!failed && !audioBytes) {
    throw new HttpError(400, "missing_chat_audio", "Successful Hypha chat completion requires sealed-stone audio.");
  }

  await completeHyphaChatRequest(env.CHAT_DB, {
    requestId,
    environment: scope.environment,
    streamId: scope.streamId,
    transcriptText,
    audioBytes,
    completedAt: Math.floor(Date.now() / 1000),
    failed,
  });
  return jsonResponse({ ok: true, requestId });
}

async function signedRequestMetadata(
  request: Request,
  env: Env,
  body: ArrayBuffer,
) {
  return verifyHyphaSignature(
    request,
    body,
    env.HYPHA_ACTIVITY_SECRET ?? "",
    numericSetting(
      env.HYPHA_MAX_CLOCK_SKEW_SECONDS,
      DEFAULT_CLOCK_SKEW_SECONDS,
    ),
  );
}

async function consumeSignedNonce(
  env: Env,
  request: Request,
  signed: Awaited<ReturnType<typeof signedRequestMetadata>>,
): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  try {
    await nonceInsert(env.PUBLIC_DB, {
      nonce: signed.nonce,
      requestPath: new URL(request.url).pathname,
      bodySha256: signed.bodySha256,
      acceptedAt: now,
      expiresAt: now + 86_400,
    }).run();
  } catch {
    throw new HttpError(409, "replayed_request", "The Hypha nonce has already been used.");
  }
}

async function handleHyphaState(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return methodNotAllowed(["POST"]);
  }
  await cleanupExpiredRows(env.PUBLIC_DB, Math.floor(Date.now() / 1000));
  const body = await readBody(request, MAX_STATE_BYTES);
  const signed = await signedRequestMetadata(request, env, body);
  const snapshot = parseSnapshot(decodeJson(body));
  if (snapshot.environment === "live" && env.ALLOW_LIVE_STATE_PUBLISHING !== "true") {
    throw new HttpError(403, "live_state_publishing_disabled",
      "Live Activity state publication is disabled.");
  }
  if (snapshot.environment === "live" && env.V2_LIVE_CONTENT_VERSION &&
      (snapshot.schemaVersion !== "2.4.0" ||
       snapshot.contentVersion !== env.V2_LIVE_CONTENT_VERSION)) {
    throw new HttpError(403, "live_content_version_mismatch",
      "This live state belongs to a different campaign version.");
  }
  const now = Math.floor(Date.now() / 1000);
  await publishSnapshot(
    env.PUBLIC_DB,
    snapshot,
    signed.bodySha256,
    nonceInsert(env.PUBLIC_DB, {
      nonce: signed.nonce,
      requestPath: new URL(request.url).pathname,
      bodySha256: signed.bodySha256,
      acceptedAt: now,
      expiresAt: now + 86_400,
    }),
  );
  return jsonResponse(
    {
      ok: true,
      environment: snapshot.environment,
      revision: snapshot.revision,
      stateHeadHash: snapshot.stateHeadHash,
    },
    201,
  );
}

async function handleHyphaArtifact(
  request: Request,
  env: Env,
  route: NonNullable<ReturnType<typeof artifactRoute>>,
): Promise<Response> {
  if (request.method !== "PUT") {
    return methodNotAllowed(["PUT"]);
  }
  requirePublishableEnvironment(route.environment, env);
  const artifactStorage = requireArtifactStorage(env);
  await cleanupExpiredRows(env.PUBLIC_DB, Math.floor(Date.now() / 1000));
  const body = await readBody(request, MAX_ARTIFACT_BYTES);
  const signed = await signedRequestMetadata(request, env, body);
  const contentType = (request.headers.get("Content-Type") ?? "application/octet-stream")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  if (!ALLOWED_ARTIFACT_TYPES.has(contentType)) {
    throw new HttpError(415, "unsupported_artifact_type", `Unsupported artifact content type: ${contentType}`);
  }

  const existing = await getArtifactFile(
    env.PUBLIC_DB,
    route.environment,
    route.artifactId,
    route.filename,
  );
  if (existing) {
    throw new HttpError(409, "artifact_file_conflict", "That artifact filename is already registered.");
  }

  const objectKey = [
    "v2",
    route.environment,
    "artifacts",
    route.artifactId,
    signed.bodySha256,
    route.filename,
  ].join("/");
  const uploadedAt = new Date().toISOString();
  await artifactStorage.put(objectKey, body, {
    httpMetadata: {
      contentType,
      cacheControl: "public, max-age=31536000, immutable",
      contentDisposition: `inline; filename="${route.filename}"`,
    },
    customMetadata: {
      environment: route.environment,
      artifactId: route.artifactId,
      sha256: signed.bodySha256,
    },
  });

  const now = Math.floor(Date.now() / 1000);
  try {
    await registerArtifactFile(
      env.PUBLIC_DB,
      {
        environment: route.environment,
        artifact_id: route.artifactId,
        filename: route.filename,
        object_key: objectKey,
        content_type: contentType,
        byte_length: body.byteLength,
        content_sha256: signed.bodySha256,
        uploaded_at: uploadedAt,
      },
      nonceInsert(env.PUBLIC_DB, {
        nonce: signed.nonce,
        requestPath: new URL(request.url).pathname,
        bodySha256: signed.bodySha256,
        acceptedAt: now,
        expiresAt: now + 86_400,
      }),
    );
  } catch (error) {
    await artifactStorage.delete(objectKey);
    throw error;
  }

  return jsonResponse(
    {
      ok: true,
      artifactId: route.artifactId,
      filename: route.filename,
      sha256: signed.bodySha256,
      url: `/api/artifacts/${route.environment}/${route.artifactId}/${route.filename}`,
    },
    201,
  );
}

async function handleArtifactDownload(
  request: Request,
  env: Env,
  route: NonNullable<ReturnType<typeof artifactRoute>>,
): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowed(["GET", "HEAD"]);
  }
  const row = await getArtifactFile(
    env.PUBLIC_DB,
    route.environment,
    route.artifactId,
    route.filename,
  );
  if (!row) {
    throw new HttpError(404, "artifact_not_found", "The requested artifact file is not registered.");
  }
  const object = await requireArtifactStorage(env).get(row.object_key);
  if (!object) {
    throw new HttpError(503, "artifact_storage_mismatch", "Artifact metadata exists but the R2 object is missing.");
  }
  return artifactResponse(request.method === "HEAD" ? null : object.body, {
    contentType: row.content_type,
    byteLength: row.byte_length,
    etag: object.etag,
    sha256: row.content_sha256,
    filename: row.filename,
  });
}

async function handleArtifactList(
  request: Request,
  env: Env,
  route: NonNullable<ReturnType<typeof artifactListRoute>>,
): Promise<Response> {
  if (request.method !== "GET") {
    return methodNotAllowed(["GET"]);
  }
  const files = await listArtifactFiles(env.PUBLIC_DB, route.environment, route.artifactId);
  return jsonResponse({
    environment: route.environment,
    artifactId: route.artifactId,
    files: files.map((file) => ({
      filename: file.filename,
      contentType: file.content_type,
      byteLength: file.byte_length,
      sha256: file.content_sha256,
      uploadedAt: file.uploaded_at,
      url: `/api/artifacts/${route.environment}/${route.artifactId}/${file.filename}`,
    })),
  });
}

async function handleHyphaPublication(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return methodNotAllowed(["POST"]);
  }
  await cleanupExpiredRows(env.PUBLIC_DB, Math.floor(Date.now() / 1000));
  const body = await readBody(request, MAX_PUBLICATION_BYTES);
  const signed = await signedRequestMetadata(request, env, body);
  const decoded = new TextDecoder().decode(body);
  const payload = parsePublication(decodeJson(body));
  requirePublishableEnvironment(payload.environment, env);
  const now = Math.floor(Date.now() / 1000);
  await publishPublication(
    env.PUBLIC_DB,
    payload,
    decoded,
    nonceInsert(env.PUBLIC_DB, {
      nonce: signed.nonce,
      requestPath: new URL(request.url).pathname,
      bodySha256: signed.bodySha256,
      acceptedAt: now,
      expiresAt: now + 86_400,
    }),
  );
  return jsonResponse(
    {
      ok: true,
      publicationId: payload.publicationId,
      artifactId: payload.artifactId,
    },
    201,
  );
}


function roomId(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length < 1 ||
    value.length > ROOM_ID_MAX_LENGTH ||
    !/^[A-Za-z0-9][A-Za-z0-9_-]*$/u.test(value)
  ) {
    throw new HttpError(400, "invalid_room_id", "roomId must use letters, numbers, underscores, or hyphens.");
  }
  return value;
}

function finiteNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new HttpError(400, "invalid_room_ticket_request", `${field} must be a finite number.`);
  }
  return value;
}

function stringList(value: unknown, field: string): string[] {
  if (
    !Array.isArray(value) ||
    value.length < 1 ||
    value.length > 16 ||
    !value.every((item) => typeof item === "string" && item.length > 0 && item.length <= 64)
  ) {
    throw new HttpError(400, "invalid_room_ticket_request", `${field} must be a non-empty string array.`);
  }
  return [...new Set(value as string[])];
}

function parseRoomTicketRequest(value: unknown): RoomTicketRequest {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_room_ticket_request", "Room ticket request must be an object.");
  }
  const record = value as Record<string, unknown>;
  const environment = parseEnvironment(String(record.environment ?? "test"));
  const minimumSeconds = finiteNumber(record.minimumSeconds, "minimumSeconds");
  const maximumSeconds = finiteNumber(record.maximumSeconds, "maximumSeconds");
  if (minimumSeconds >= maximumSeconds) {
    throw new HttpError(400, "invalid_room_ticket_request", "minimumSeconds must precede maximumSeconds.");
  }
  const clientInstanceId = String(record.clientInstanceId ?? "");
  if (!/^[A-Za-z0-9-]{16,96}$/u.test(clientInstanceId)) {
    throw new HttpError(400, "invalid_room_ticket_request", "clientInstanceId is invalid.");
  }
  return {
    roomId: roomId(record.roomId),
    environment,
    artifactId: parseIdentifier(String(record.artifactId ?? ""), "artifactId"),
    visualizationId: parseIdentifier(String(record.visualizationId ?? ""), "visualizationId"),
    minimumSeconds,
    maximumSeconds,
    timeBases: stringList(record.timeBases, "timeBases"),
    clientInstanceId,
  };
}

async function validateActiveVisualization(
  env: Env,
  request: RoomTicketRequest,
): Promise<{
  publicationId: string;
  minimumSeconds: number;
  maximumSeconds: number;
  timeBases: string[];
}> {
  const bundled = bundledTestScientificScope(request);
  if (bundled) return { ...bundled, publicationId: "bundled-test" };

  const publication = await getLatestPublication(env.PUBLIC_DB, request.environment);
  if (!publication || publication.artifactId !== request.artifactId || !publication.visualizationFilename) {
    throw new HttpError(409, "room_publication_mismatch", "Room ticket does not match the latest interactive publication.");
  }
  const row = await getArtifactFile(
    env.PUBLIC_DB,
    request.environment,
    request.artifactId,
    publication.visualizationFilename,
  );
  if (!row) {
    throw new HttpError(503, "visualization_unavailable", "Interactive visualization metadata is missing.");
  }
  const artifactStorage = env.PUBLIC_ARTIFACTS;
  if (!artifactStorage) {
    throw new HttpError(
      503,
      "dynamic_artifacts_disabled",
      "Dynamic artifact storage is disabled in strict-free mode.",
    );
  }
  const object = await artifactStorage.get(row.object_key);
  if (!object) {
    throw new HttpError(503, "visualization_unavailable", "Interactive visualization object is missing.");
  }
  let specification: unknown;
  try {
    specification = JSON.parse(await new Response(object.body).text()) as unknown;
  } catch {
    throw new HttpError(503, "visualization_unavailable", "Interactive visualization metadata is invalid.");
  }
  if (typeof specification !== "object" || specification === null || Array.isArray(specification)) {
    throw new HttpError(409, "room_visualization_mismatch", "Room ticket visualization does not match the active publication.");
  }
  const specificationRecord = specification as Record<string, unknown>;
  if (
    specificationRecord.visualizationId !== request.visualizationId ||
    specificationRecord.artifactId !== request.artifactId
  ) {
    throw new HttpError(409, "room_visualization_mismatch", "Room ticket visualization does not match the active publication.");
  }
  const interaction = specificationRecord.interaction;
  const datasetFilename = specificationRecord.datasetFilename;
  const rawTimeBases =
    typeof interaction === "object" && interaction !== null && !Array.isArray(interaction)
      ? (interaction as Record<string, unknown>).timeBases
      : null;
  if (
    !Array.isArray(rawTimeBases) ||
    !rawTimeBases.every(
      (value) => typeof value === "string" && value.length > 0 && value.length <= 64,
    ) ||
    typeof datasetFilename !== "string"
  ) {
    throw new HttpError(503, "visualization_unavailable", "Interactive visualization scope is invalid.");
  }
  const canonicalTimeBases = [
    ...new Set(rawTimeBases as string[]),
  ];
  const datasetRow = await getArtifactFile(
    env.PUBLIC_DB,
    request.environment,
    request.artifactId,
    parseFilename(datasetFilename),
  );
  if (!datasetRow) {
    throw new HttpError(503, "visualization_unavailable", "Interactive scientific dataset metadata is missing.");
  }
  const datasetObject = await artifactStorage.get(datasetRow.object_key);
  if (!datasetObject) {
    throw new HttpError(503, "visualization_unavailable", "Interactive scientific dataset is missing.");
  }
  let dataset: unknown;
  try {
    dataset = JSON.parse(await new Response(datasetObject.body).text()) as unknown;
  } catch {
    throw new HttpError(503, "visualization_unavailable", "Interactive scientific dataset is invalid.");
  }
  if (typeof dataset !== "object" || dataset === null || Array.isArray(dataset)) {
    throw new HttpError(503, "visualization_unavailable", "Interactive scientific dataset scope is invalid.");
  }
  const datasetRecord = dataset as Record<string, unknown>;
  const waveform = datasetRecord.waveform;
  if (
    datasetRecord.artifactId !== request.artifactId ||
    datasetRecord.visualizationId !== request.visualizationId ||
    typeof waveform !== "object" ||
    waveform === null ||
    Array.isArray(waveform)
  ) {
    throw new HttpError(503, "visualization_unavailable", "Interactive scientific dataset does not match its visualization.");
  }
  const minimumSeconds = (waveform as Record<string, unknown>).startSeconds;
  const maximumSeconds = (waveform as Record<string, unknown>).endSeconds;
  if (
    typeof minimumSeconds !== "number" ||
    !Number.isFinite(minimumSeconds) ||
    typeof maximumSeconds !== "number" ||
    !Number.isFinite(maximumSeconds) ||
    minimumSeconds >= maximumSeconds
  ) {
    throw new HttpError(503, "visualization_unavailable", "Interactive scientific dataset bounds are invalid.");
  }
  if (
    request.minimumSeconds !== minimumSeconds ||
    request.maximumSeconds !== maximumSeconds ||
    request.timeBases.length !== canonicalTimeBases.length ||
    request.timeBases.some((basis, index) => basis !== canonicalTimeBases[index])
  ) {
    throw new HttpError(
      409,
      "room_visualization_scope_mismatch",
      "Room ticket bounds and time bases do not match the active scientific publication.",
    );
  }
  return {
    publicationId: publication.publicationId,
    minimumSeconds,
    maximumSeconds,
    timeBases: canonicalTimeBases,
  };
}

async function handleRoomTicket(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const payload = parseRoomTicketRequest(decodeJson(await readBody(request, 32 * 1024)));
  const authenticated = hasActivityCredential(request);
  if (!authenticated) {
    if (payload.environment !== "test") {
      throw new HttpError(401, "session_required", "Live investigation rooms require an Activity session.");
    }
    if (env.ALLOW_TEST_GUESTS !== "true" || !isLoopbackRequest(request)) {
      throw new HttpError(
        401,
        "session_required",
        "Test investigation rooms require a validated Activity session outside loopback development.",
      );
    }
  }

  const secret = env.ROOM_TICKET_SECRET ?? "";
  let participantId: string;
  let displayName: string;
  let principal: ActivityPrincipal | null = null;
  if (authenticated) {
    principal = await requireActivityPrincipal(request, env);
    if (payload.environment !== principal.environment) {
      throw new HttpError(
        403,
        "room_environment_mismatch",
        "Activity session and room environment must match.",
      );
    }
    participantId = principal.participantId;
    displayName = principal.displayName;
  } else {
    participantId = await stableTicketIdentity(
      secret,
      `test:${payload.clientInstanceId}`,
    );
    displayName = `Local investigator ${payload.clientInstanceId.slice(0, 6)}`;
  }
  const scientificScope = await validateActiveVisualization(env, payload);
  const effectiveRoomId = principal
    ? await stableTicketIdentity(
      secret,
      principal.authProvider === "discord"
        ? `discord-instance:${principal.discordInstanceId}`
        : JSON.stringify({
          kind: "web-room",
          environment: principal.environment,
          publicationId: scientificScope.publicationId,
          artifactId: payload.artifactId,
          visualizationId: payload.visualizationId,
          roomId: payload.roomId,
        }),
      "room",
    )
    : payload.roomId;
  const now = Math.floor(Date.now() / 1000);
  const expiresAt = now + numericSetting(env.ROOM_TICKET_TTL_SECONDS, DEFAULT_ROOM_TICKET_TTL_SECONDS);
  const ticketPayload: RoomTicketPayload = {
    version: 1,
    nonce: crypto.randomUUID(),
    roomId: effectiveRoomId,
    environment: payload.environment,
    artifactId: payload.artifactId,
    visualizationId: payload.visualizationId,
    participantId,
    displayName,
    minimumSeconds: scientificScope.minimumSeconds,
    maximumSeconds: scientificScope.maximumSeconds,
    timeBases: scientificScope.timeBases,
    issuedAt: now,
    expiresAt,
  };
  const ticket = await signRoomTicket(ticketPayload, secret);
  return jsonResponse(
    {
      ticket,
      expiresAt: new Date(expiresAt * 1000).toISOString(),
      participantId,
      displayName,
      websocketPath: `/api/rooms/${encodeURIComponent(effectiveRoomId)}/connect`,
    },
    201,
  );
}

function roomConnectRoute(pathname: string): string | null {
  const match = /^\/api\/rooms\/([^/]+)\/connect$/u.exec(pathname);
  return match ? roomId(decodeURIComponent(match[1])) : null;
}

async function handleRoomConnect(
  request: Request,
  env: Env,
  requestedRoomId: string,
): Promise<Response> {
  if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
    throw new HttpError(426, "websocket_required", "Investigation rooms require a WebSocket upgrade.");
  }
  const url = new URL(request.url);
  const ticket = await verifyRoomTicket(url.searchParams.get("ticket") ?? "", env.ROOM_TICKET_SECRET ?? "");
  if (ticket.roomId !== requestedRoomId) {
    throw new HttpError(401, "room_ticket_mismatch", "Room ticket is not valid for this room.");
  }
  const roomObject = env.LIVE_ROOMS.get(
    env.LIVE_ROOMS.idFromName(`${ticket.environment}:${ticket.roomId}`),
  );
  const forwarded = new Request(request.url, request);
  forwarded.headers.set(
    "X-Investigation-Room-Ticket",
    encodeURIComponent(JSON.stringify(ticket)),
  );
  return roomObject.fetch(forwarded);
}

async function routeRequest(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);

  if (url.pathname === "/api/health") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(["GET", "HEAD"]);
    }
    return jsonResponse({
      ok: true,
      service: "missing-interior-activity",
      phase: 4,
      costMode: env.PUBLIC_ARTIFACTS ? "r2-enabled" : "strict-free",
    });
  }

  if (matchesUfosintSidequestApi(url.pathname)) {
    enforceEdgeRate(
      request,
      url.pathname.startsWith("/api/hypha/")
        ? "ufosint-sidequest-worker"
        : "ufosint-sidequest",
      url.pathname.startsWith("/api/hypha/") ? 30 : 90,
    );
    return handleUfosintSidequestApi(request, env);
  }

  if (url.pathname === "/api/rooms/tickets") {
    enforceEdgeRate(request, "room-ticket", 20);
    return handleRoomTicket(request, env);
  }
  const requestedRoomId = roomConnectRoute(url.pathname);
  if (requestedRoomId) {
    enforceEdgeRate(request, "room-connect", 30);
    return handleRoomConnect(request, env, requestedRoomId);
  }

  if (url.pathname === "/api/public-state") {
    enforceEdgeRate(request, "public-state", 240);
    return handlePublicState(request, env);
  }
  if (url.pathname === "/api/ufo-reports") {
    enforceEdgeRate(request, "ufo-reports", 60);
    return currentUfoReports(request, env);
  }
  if (url.pathname === "/api/map/dynamical/manifest") {
    enforceEdgeRate(request, "dynamical-map-manifest", 120);
    return handleDynamicalRenderManifest(request, env);
  }
  if (url.pathname === "/api/publications/latest") {
    enforceEdgeRate(request, "latest-publication", 240);
    return handleLatestPublication(request, env);
  }
  if (url.pathname === "/api/auth/discord") {
    enforceEdgeRate(request, "discord-auth", 10);
    return handleDiscordAuth(request, env);
  }
  if (url.pathname === "/api/auth/magic-link/request") {
    enforceEdgeRate(request, "magic-link-request", 5);
    return handleMagicLinkRequest(request, env);
  }
  if (url.pathname === "/api/auth/magic-link/verify") {
    enforceEdgeRate(request, "magic-link-verify", 30);
    return handleMagicLinkVerify(request, env);
  }
  if (url.pathname === "/api/game/status") {
    enforceEdgeRate(request, "game-status", 60);
    return handleGameProxy(request, env, "status");
  }
  if (url.pathname === "/api/game/command") {
    enforceEdgeRate(request, "game-command", 30);
    return handleGameProxy(request, env, "command");
  }
  if (url.pathname === "/api/session") {
    enforceEdgeRate(request, "session", 30);
    return handleSession(request, env);
  }
  if (url.pathname === "/api/my-difficulty") {
    enforceEdgeRate(request, "my-difficulty", 30);
    return handleMyDifficulty(request, env);
  }
  if (url.pathname === "/api/hypha/difficulty") {
    enforceEdgeRate(request, "hypha-difficulty", 30);
    return handleHyphaDifficultySync(request, env);
  }
  if (url.pathname === "/api/hypha-chat") {
    enforceEdgeRate(request, "hypha-chat", 120);
    return request.method === "GET"
      ? handleHyphaChatList(request, env)
      : handleHyphaChatCreate(request, env);
  }
  const requestedHyphaChat = hyphaChatAudioRoute(url.pathname);
  if (requestedHyphaChat) {
    enforceEdgeRate(request, "hypha-chat-audio", 120);
    return handleHyphaChatAudio(request, env, requestedHyphaChat);
  }
  if (url.pathname === "/api/hypha/chat/claim") {
    enforceEdgeRate(request, "hypha-chat-claim", 120);
    return handleHyphaChatClaim(request, env);
  }
  const hyphaChatCompletion = hyphaChatCompletionRoute(url.pathname);
  if (hyphaChatCompletion) {
    enforceEdgeRate(request, "hypha-chat-complete", 120);
    return handleHyphaChatComplete(request, env, hyphaChatCompletion);
  }

  if (url.pathname === "/api/environmental-context") {
    if (request.method !== "GET") {
      return methodNotAllowed(["GET"]);
    }
    enforceEdgeRate(request, "environmental-context", 12);
    await requireActivityPrincipal(request, env);
    return jsonResponse(
      await environmentalContext(url.searchParams.get("facility") ?? ""),
    );
  }
  if (url.pathname === "/api/auth/logout") {
    enforceEdgeRate(request, "logout", 10);
    return handleLogout(request, env);
  }
  if (url.pathname === "/api/hypha/state") {
    enforceEdgeRate(request, "hypha-state", 120);
    return handleHyphaState(request, env);
  }
  if (url.pathname === "/api/hypha/publications") {
    enforceEdgeRate(request, "hypha-publication", 60);
    return handleHyphaPublication(request, env);
  }

  const hyphaArtifact = url.pathname.startsWith("/api/hypha/artifacts/")
    ? artifactRoute(url.pathname)
    : null;
  if (hyphaArtifact) {
    enforceEdgeRate(request, "hypha-artifact", 60);
    return handleHyphaArtifact(request, env, hyphaArtifact);
  }

  const publicArtifact = url.pathname.startsWith("/api/artifacts/")
    ? artifactRoute(url.pathname)
    : null;
  if (publicArtifact) {
    if (!env.PUBLIC_ARTIFACTS) {
      throw new HttpError(404, "not_found", "Dynamic artifacts are disabled.");
    }
    enforceEdgeRate(request, "artifact-download", 240);
    return handleArtifactDownload(request, env, publicArtifact);
  }

  const artifactList = artifactListRoute(url.pathname);
  if (artifactList) {
    if (!env.PUBLIC_ARTIFACTS) {
      throw new HttpError(404, "not_found", "Dynamic artifacts are disabled.");
    }
    enforceEdgeRate(request, "artifact-list", 240);
    return handleArtifactList(request, env, artifactList);
  }

  if (url.pathname.startsWith("/api/")) {
    throw new HttpError(404, "not_found", "The requested Activity API route does not exist.");
  }

  const assetResponse = await env.ASSETS.fetch(request);
  const assetHeaders = new Headers(assetResponse.headers);
  assetHeaders.set("Permissions-Policy", ACTIVITY_PERMISSIONS_POLICY);
  return new Response(assetResponse.body, {
    status: assetResponse.status,
    statusText: assetResponse.statusText,
    headers: assetHeaders,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await routeRequest(request, env);
    } catch (error) {
      return errorResponse(error);
    }
  },
};

export { InvestigationRoom };
