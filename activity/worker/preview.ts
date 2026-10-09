/** Separate public-case preview with a public Hypha log and email-only posting. */
import type { AssetBinding, D1Database } from "./lib/cloudflare";
import { hmacSha256Hex, verifyHyphaSignature } from "./lib/crypto";
import { getCurrentSnapshot, nonceInsert, publishSnapshot } from "./lib/database";
import { HttpError } from "./lib/errors";
import { handleGameProxy } from "./lib/game-proxy";
import {
  handleMagicLinkRequest,
  handleMagicLinkVerify,
  normalizedEmail,
  readWebSession,
  requireSameOriginMutation,
  revokeWebSession,
} from "./lib/magic-link-auth";
import { handlePreviewChat } from "./lib/preview-chat";
import { guestDemoConfigured, handleGuestDemo } from "./lib/preview-guest-demo";
import { jsonResponse, methodNotAllowed } from "./lib/responses";
import { parseEnvironment, parseSnapshot } from "./lib/validation";
import { readPublicRecord, readPublicRecordRevision } from "./lib/preview-public-record";

interface PreviewEnv {
  ASSETS: AssetBinding;
  PUBLIC_DB: D1Database;
  CHAT_DB: D1Database;
  APP_ORIGIN?: string;
  SESSION_TTL_SECONDS?: string;
  RESEND_API_KEY?: string;
  MAGIC_LINK_FROM_EMAIL?: string;
  ACTIVITY_IDENTITY_SECRET?: string;
  GEMINI_API_KEY?: string;
  GEMINI_CHAT_MODEL?: string;
  DEMO_CHAT_ENABLED?: string;
  HYPHA_ACTIVITY_SECRET?: string;
  HYPHA_MAX_CLOCK_SKEW_SECONDS?: string;
  GAME_API_ORIGIN?: string;
  GAME_API_SECRET?: string;
  DEMO_IP_RATE_LIMIT?: { limit(options: { key: string }): Promise<{ success: boolean }> };
  DEMO_GLOBAL_RATE_LIMIT?: { limit(options: { key: string }): Promise<{ success: boolean }> };
}

const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "public, max-age=60",
  "X-Content-Type-Options": "nosniff",
};

function jsonError(status: number, error: string, request: Request, message?: string): Response {
  return new Response(request.method === "HEAD" ? null : JSON.stringify({ error, message }), {
    status,
    headers: { ...JSON_HEADERS, "Cache-Control": "no-store" },
  });
}

const PUBLIC_TABLES = [
  "activity_sessions", "web_magic_links", "web_magic_link_cooldowns", "preview_magic_link_quota",
] as const;
const CHAT_READ_TABLES = ["hypha_chat_messages"] as const;
const CHAT_TABLES = [
  "hypha_chat_requests", "hypha_chat_messages", "preview_chat_quota",
] as const;
const LIVE_STATE_READ_TABLES = ["current_public_state"] as const;
const LIVE_STATE_WRITE_TABLES = [
  "current_public_state", "public_state_revisions", "hypha_request_nonces",
] as const;
const PUBLIC_RECORD_TABLES = ["public_state_revisions"] as const;
const MAX_STATE_BYTES = 512 * 1024;
const STATIC_ROLES_CONTENT_VERSION = "2.1.0-static-roles";

function emailConfigured(env: PreviewEnv): boolean {
  return Boolean(env.PUBLIC_DB && env.APP_ORIGIN && env.RESEND_API_KEY?.trim() &&
    env.MAGIC_LINK_FROM_EMAIL?.trim() &&
    (env.ACTIVITY_IDENTITY_SECRET?.length ?? 0) >= 32);
}

function gameConfigured(env: PreviewEnv): boolean {
  if (!env.GAME_API_ORIGIN || (env.GAME_API_SECRET?.length ?? 0) < 32 ||
      (env.HYPHA_ACTIVITY_SECRET?.length ?? 0) < 32) return false;
  try {
    const origin = new URL(env.GAME_API_ORIGIN);
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname.toLowerCase());
    return (origin.protocol === "https:" || loopback && origin.protocol === "http:") &&
      origin.pathname === "/" && !origin.search && !origin.hash &&
      !origin.username && !origin.password;
  } catch {
    return false;
  }
}

async function hasTables(db: D1Database | undefined, names: readonly string[]): Promise<boolean> {
  if (!db) return false;
  try {
    const placeholders = names.map(() => "?").join(", ");
    const result = await db.prepare(
      `SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (${placeholders})`,
    ).bind(...names).all<{ name: string }>();
    const found = new Set((result.results ?? []).map((row) => row.name));
    return names.every((name) => found.has(name));
  } catch {
    return false;
  }
}

async function requirePublicSchema(env: PreviewEnv): Promise<void> {
  if (!await hasTables(env.PUBLIC_DB, PUBLIC_TABLES)) {
    throw new HttpError(503, "web_auth_schema_unavailable", "Email sign-in is waiting for database setup.");
  }
}

async function requireChatSchema(env: PreviewEnv): Promise<void> {
  if (!await hasTables(env.CHAT_DB, CHAT_TABLES)) {
    throw new HttpError(503, "preview_chat_schema_unavailable", "Hypha chat is waiting for database setup.");
  }
}

async function requireChatReadSchema(env: PreviewEnv): Promise<void> {
  if (!await hasTables(env.CHAT_DB, CHAT_READ_TABLES)) {
    throw new HttpError(503, "preview_chat_schema_unavailable", "Hypha chat history is waiting for database setup.");
  }
}

async function allowMagicLinkSend(request: Request, env: PreviewEnv): Promise<boolean> {
  const now = Math.floor(Date.now() / 1000);
  const hour = Math.floor(now / 3600) * 3600;
  const day = Math.floor(now / 86_400) * 86_400;
  // Cloudflare supplies this header to Workers. Hash it with a rotating hour
  // scope so the database never stores a raw address or persistent IP key.
  const ip = request.headers.get("CF-Connecting-IP")?.trim() || "unknown";
  const ipKey = `ip:${await hmacSha256Hex(
    env.ACTIVITY_IDENTITY_SECRET!, `preview-email-ip:${hour}:${ip}`,
  )}`;
  for (const [subject, windowStart, limit] of [
    [ipKey, hour, 5],
    ["global", day, 100],
  ] as const) {
    const result = await env.PUBLIC_DB.prepare(
      `INSERT INTO preview_magic_link_quota (subject_key, window_start, request_count)
       VALUES (?, ?, 1)
       ON CONFLICT(subject_key, window_start)
       DO UPDATE SET request_count = preview_magic_link_quota.request_count + 1
       WHERE preview_magic_link_quota.request_count < ?`,
    ).bind(subject, windowStart, limit).run();
    if ((result.meta?.changes ?? 0) !== 1) return false;
  }
  return true;
}

async function validMagicLinkAddress(request: Request): Promise<boolean> {
  const declared = Number(request.headers.get("Content-Length") ?? 0);
  if (declared > 4096) return false;
  const body = await request.clone().arrayBuffer();
  if (body.byteLength > 4096) return false;
  let value: unknown;
  try { value = JSON.parse(new TextDecoder().decode(body)); }
  catch { return false; }
  return Boolean(value && typeof value === "object" && !Array.isArray(value) &&
    normalizedEmail((value as Record<string, unknown>).email));
}

async function staticJson(request: Request, env: PreviewEnv, path: string): Promise<Response> {
  const assetUrl = new URL(path, request.url);
  const response = await env.ASSETS.fetch(new Request(assetUrl, { method: request.method }));
  if (!response.ok) return jsonError(503, "preview_snapshot_unavailable", request);
  return new Response(request.method === "HEAD" ? null : response.body, {
    status: 200,
    headers: { ...JSON_HEADERS, "Cache-Control": "no-store",
      "X-Preview-Source": "captured-public-projection" },
  });
}

async function liveSnapshot(request: Request, env: PreviewEnv, environment: "live" | "test"): Promise<Response> {
  // The archived asset is deliberately excluded from this endpoint. The Python
  // publisher reads it before its first write and must see an empty revision
  // chain, not the archived campaign's revision number and state head.
  if (!await hasTables(env.PUBLIC_DB, LIVE_STATE_READ_TABLES)) {
    return jsonError(404, "state_unavailable", request, "No live public state has been published.");
  }
  const snapshot = await getCurrentSnapshot(env.PUBLIC_DB, environment);
  if (!snapshot) {
    return jsonError(404, "state_unavailable", request, "No live public state has been published.");
  }
  return new Response(request.method === "HEAD" ? null : JSON.stringify(snapshot), {
    headers: { ...JSON_HEADERS, "Cache-Control": "no-store",
      "X-Public-Source": "live-projection" },
  });
}

async function boundedBody(request: Request): Promise<ArrayBuffer> {
  const declared = request.headers.get("Content-Length");
  if (declared !== null && /^\d+$/u.test(declared) && Number(declared) > MAX_STATE_BYTES) {
    throw new HttpError(413, "payload_too_large", "Public state exceeds 512 KiB.");
  }
  const reader = request.body?.getReader();
  if (!reader) return new ArrayBuffer(0);
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_STATE_BYTES) {
        await reader.cancel();
        throw new HttpError(413, "payload_too_large", "Public state exceeds 512 KiB.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes.buffer;
}

async function publishLiveState(request: Request, env: PreviewEnv): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const body = await boundedBody(request);
  const configuredSkew = Number.parseInt(env.HYPHA_MAX_CLOCK_SKEW_SECONDS ?? "", 10);
  const skew = Number.isSafeInteger(configuredSkew) && configuredSkew > 0 ? configuredSkew : 300;
  const signed = await verifyHyphaSignature(request, body, env.HYPHA_ACTIVITY_SECRET ?? "", skew);
  let decoded: unknown;
  try { decoded = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body)); }
  catch { throw new HttpError(400, "invalid_json", "Public state must be valid UTF-8 JSON."); }
  const snapshot = parseSnapshot(decoded);
  if (snapshot.environment !== "live" || snapshot.schemaVersion !== "2.4.0" ||
      snapshot.contentVersion !== STATIC_ROLES_CONTENT_VERSION) {
    throw new HttpError(403, "live_content_version_mismatch",
      "The preview accepts only the live static-role campaign.");
  }
  if (!await hasTables(env.PUBLIC_DB, LIVE_STATE_WRITE_TABLES)) {
    throw new HttpError(503, "live_state_schema_unavailable", "Live public state is waiting for database setup.");
  }
  const now = Math.floor(Date.now() / 1000);
  await publishSnapshot(env.PUBLIC_DB, snapshot, signed.bodySha256,
    nonceInsert(env.PUBLIC_DB, {
      nonce: signed.nonce,
      requestPath: new URL(request.url).pathname,
      bodySha256: signed.bodySha256,
      acceptedAt: now,
      expiresAt: now + 86_400,
    }));
  return jsonResponse({ ok: true, environment: "live", revision: snapshot.revision,
    stateHeadHash: snapshot.stateHeadHash }, 201);
}

async function api(request: Request, env: PreviewEnv): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname === "/api/health") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(["GET", "HEAD"]);
    }
    const [emailSchemaReady, chatReadReady, chatSchemaReady, liveStateSchemaReady] = await Promise.all([
      hasTables(env.PUBLIC_DB, PUBLIC_TABLES),
      hasTables(env.CHAT_DB, CHAT_READ_TABLES),
      hasTables(env.CHAT_DB, CHAT_TABLES),
      hasTables(env.PUBLIC_DB, LIVE_STATE_WRITE_TABLES),
    ]);
    const emailReady = emailConfigured(env) && emailSchemaReady;
    return new Response(request.method === "HEAD" ? null : JSON.stringify({
      status: "preview",
      emailReady,
      chatReady: Boolean(emailReady && chatSchemaReady && env.GEMINI_API_KEY?.trim()),
      chatReadReady,
      demoReady: Boolean(chatReadReady && guestDemoConfigured(env)),
      emailSchemaReady,
      chatSchemaReady,
      gameActionsReady: Boolean(emailReady && liveStateSchemaReady && gameConfigured(env)),
    }), { headers: { ...JSON_HEADERS, "Cache-Control": "no-store" } });
  }

  if (url.pathname === "/api/auth/magic-link/request") {
    if (request.method !== "POST") return methodNotAllowed(["POST"]);
    if (!emailConfigured(env)) {
      throw new HttpError(503, "web_auth_unconfigured", "Email sign-in is not configured yet.");
    }
    requireSameOriginMutation(request, env);
    await requirePublicSchema(env);
    if (!await validMagicLinkAddress(request)) {
      return handleMagicLinkRequest(request, env);
    }
    if (!await allowMagicLinkSend(request, env)) {
      return jsonResponse({ ok: true,
        message: "If that address can receive mail, a sign-in link is on its way." }, 202);
    }
    return handleMagicLinkRequest(request, env);
  }
  if (url.pathname === "/api/auth/magic-link/verify") {
    if (!env.PUBLIC_DB) {
      throw new HttpError(503, "web_auth_unconfigured", "Email sign-in is not configured yet.");
    }
    await requirePublicSchema(env);
    return handleMagicLinkVerify(request, env);
  }
  if (url.pathname === "/api/auth/logout") {
    if (request.method !== "POST") return methodNotAllowed(["POST"]);
    if (!env.PUBLIC_DB) throw new HttpError(503, "web_auth_unconfigured", "Email sign-in is unavailable.");
    await requirePublicSchema(env);
    return revokeWebSession(request, env);
  }
  if (url.pathname === "/api/session") {
    if (request.method !== "GET") return methodNotAllowed(["GET"]);
    if (!env.PUBLIC_DB) throw new HttpError(503, "web_auth_unconfigured", "Email sign-in is unavailable.");
    await requirePublicSchema(env);
    const session = await readWebSession(request, env);
    if (!session) throw new HttpError(401, "missing_session", "Sign in by email to join the investigation.");
    return jsonResponse({ participant: session.participant, environment: "live",
      authProvider: "email", expiresAt: session.expiresAt });
  }
  if (url.pathname === "/api/hypha-chat") {
    if (request.method === "GET") {
      await requireChatReadSchema(env);
      return handlePreviewChat(request, env);
    }
    if (request.method !== "POST") return methodNotAllowed(["GET", "POST"]);
    if (!/(?:^|;)\s*(?:__Host-mi_session|mi_dev_session)=/u.test(request.headers.get("Cookie") ?? "")) {
      throw new HttpError(401, "missing_session", "Sign in by email to speak with Hypha.");
    }
    await requirePublicSchema(env);
    await requireChatSchema(env);
    return handlePreviewChat(request, env);
  }
  if (url.pathname === "/api/hypha-demo") {
    if (request.method !== "POST") return methodNotAllowed(["POST"]);
    return handleGuestDemo(request, env);
  }
  if (url.pathname === "/api/hypha/state") {
    return publishLiveState(request, env);
  }
  if (url.pathname === "/api/game/status" || url.pathname === "/api/game/command") {
    if (request.method !== "POST") return methodNotAllowed(["POST"]);
    if (request.headers.has("Authorization")) {
      throw new HttpError(403, "web_session_required", "Website email sign-in is required for game actions.");
    }
    if (!/(?:^|;)\s*(?:__Host-mi_session|mi_dev_session)=/u.test(request.headers.get("Cookie") ?? "")) {
      throw new HttpError(401, "missing_session", "Sign in by email to join the investigation.");
    }
    await requirePublicSchema(env);
    if (!gameConfigured(env)) {
      throw new HttpError(503, "game_api_unconfigured", "Live game actions are waiting for service setup.");
    }
    return handleGameProxy(request, env,
      url.pathname === "/api/game/status" ? "status" : "command");
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    return jsonError(405, "read_only_preview", request);
  }
  if (url.pathname === "/api/ufo-reports") {
    return staticJson(request, env, "/preview-ufo-reports.json");
  }
  if (url.pathname === "/api/preview-capture") {
    const environment = parseEnvironment(url.searchParams.get("environment"));
    return staticJson(request, env, environment === "live"
      ? "/preview-live-state.json" : "/preview-test-state.json");
  }
  if (url.pathname.startsWith("/api/public-record/")) {
    const environment = url.searchParams.get("environment");
    if (environment !== null && environment !== "live") {
      return jsonError(400, "invalid_environment", request, "The live public record is required.");
    }
    if (!await hasTables(env.PUBLIC_DB, PUBLIC_RECORD_TABLES)) {
      return jsonError(503, "public_record_schema_unavailable", request,
        "The public record is waiting for database setup.");
    }
    return readPublicRecordRevision(request, env.PUBLIC_DB,
      url.pathname.slice("/api/public-record/".length));
  }
  if (url.pathname === "/api/public-record") {
    if (url.searchParams.get("environment") !== "live") {
      return jsonError(400, "invalid_environment", request, "The live public record is required.");
    }
    if (!await hasTables(env.PUBLIC_DB, PUBLIC_RECORD_TABLES)) {
      return jsonError(503, "public_record_schema_unavailable", request,
        "The public record is waiting for database setup.");
    }
    return readPublicRecord(request, env.PUBLIC_DB);
  }
  if (url.pathname === "/api/public-state" || url.pathname === "/api/publications/latest") {
    const environment = parseEnvironment(url.searchParams.get("environment"));
    if (url.pathname === "/api/publications/latest") {
      return new Response(request.method === "HEAD" ? null : "null", {
        headers: { ...JSON_HEADERS, "Cache-Control": "no-store" },
      });
    }
    return liveSnapshot(request, env, environment);
  }
  return jsonError(404, "preview_api_unavailable", request);
}

export default {
  async fetch(request: Request, env: PreviewEnv): Promise<Response> {
    if (!new URL(request.url).pathname.startsWith("/api/")) {
      return env.ASSETS.fetch(request);
    }
    try { return await api(request, env); }
    catch (error) {
      if (error instanceof HttpError) return jsonError(error.status, error.code, request, error.message);
      console.error("Preview API request failed", error instanceof Error ? error.name : "unknown");
      return jsonError(500, "internal_error", request);
    }
  },
};
