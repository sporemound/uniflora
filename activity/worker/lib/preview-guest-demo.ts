/** Public, unsigned Hypha trial on the separate web preview. */
import type { D1Database } from "./cloudflare";
import { hmacSha256Hex } from "./crypto";
import { HttpError } from "./errors";
import { requireSameOriginMutation } from "./magic-link-auth";
import { transformAlbuquerqueMarkdown } from "./preview-albuquerque";
import {
  geminiGuestDemoReply,
  requestedAlbuquerqueMode,
  type PreviewChatEnv,
} from "./preview-chat";
import { jsonResponse } from "./responses";

const MAX_BODY_BYTES = 4096;
const MAX_MESSAGE_CHARS = 500;
const MAX_REPLY_CHARS = 1000;

interface RateLimitBinding {
  limit(options: { key: string }): Promise<{ success: boolean }>;
}

export interface PreviewGuestDemoEnv extends PreviewChatEnv {
  ACTIVITY_IDENTITY_SECRET?: string;
  DEMO_CHAT_ENABLED?: string;
  DEMO_IP_RATE_LIMIT?: RateLimitBinding;
  DEMO_GLOBAL_RATE_LIMIT?: RateLimitBinding;
}

export function guestDemoConfigured(env: PreviewGuestDemoEnv): boolean {
  return Boolean(env.DEMO_CHAT_ENABLED === "true" && env.ASSETS && env.CHAT_DB && env.APP_ORIGIN &&
    env.GEMINI_API_KEY?.trim() &&
    (env.ACTIVITY_IDENTITY_SECRET?.length ?? 0) >= 32 &&
    env.DEMO_IP_RATE_LIMIT?.limit && env.DEMO_GLOBAL_RATE_LIMIT?.limit);
}

async function requireGuestLogSchema(db: D1Database): Promise<void> {
  try {
    const table = await db.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'hypha_chat_messages'",
    ).first<{ name: string }>();
    if (table?.name !== "hypha_chat_messages") {
      throw new HttpError(503, "demo_log_unavailable", "The public Hypha log is still being prepared.");
    }
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(503, "demo_log_unavailable", "The public Hypha log is temporarily unavailable.");
  }
}

async function publishGuestExchange(
  db: D1Database,
  question: string,
  reply: string,
  askedAt: number,
): Promise<void> {
  // The identity changes for each question and cannot identify a visitor across
  // visits. Both complete rows commit together, so the public log never shows a
  // question without its generated reply.
  const requestId = crypto.randomUUID();
  const participantId = `guest:${crypto.randomUUID()}`;
  const questionId = crypto.randomUUID();
  const replyId = crypto.randomUUID();
  const answeredAt = Math.floor(Date.now() / 1000);
  try {
    const results = await db.batch([
      db.prepare(
        `INSERT INTO hypha_chat_messages (
          message_id, request_id, environment, stream_id, sender_type,
          participant_id, working_name, content_text, delivery_status,
          created_at, completed_at
        ) VALUES (?, ?, 'live', 'web-preview', 'participant', ?, 'Guest', ?, 'complete', ?, ?)`,
      ).bind(questionId, requestId, participantId, question, askedAt, askedAt),
      db.prepare(
        `INSERT INTO hypha_chat_messages (
          message_id, request_id, environment, stream_id, sender_type,
          content_text, delivery_status, created_at, completed_at
        ) VALUES (?, ?, 'live', 'web-preview', 'hypha', ?, 'complete', ?, ?)`,
      ).bind(replyId, requestId, reply, answeredAt, answeredAt),
    ]);
    if (results.length !== 2 || results.some((result) =>
      !result.success || (result.meta?.changes ?? 0) !== 1)) {
      throw new Error("Guest exchange did not commit two messages.");
    }
  } catch {
    throw new HttpError(503, "demo_log_unavailable",
      "Hypha could not save this exchange to the public log. Please try again later.");
  }
}

async function readGuestQuestion(request: Request): Promise<{ message: string; mode: boolean }> {
  if (!/^application\/json(?:\s*;|\s*$)/iu.test(request.headers.get("Content-Type") ?? "")) {
    throw new HttpError(415, "unsupported_media_type", "Demo questions must be JSON.");
  }
  const declared = request.headers.get("Content-Length");
  if (declared !== null && /^\d+$/u.test(declared) && Number(declared) > MAX_BODY_BYTES) {
    throw new HttpError(413, "payload_too_large", "Demo question is too large.");
  }
  const reader = request.body?.getReader();
  if (!reader) throw new HttpError(400, "invalid_json", "Demo question must be JSON.");
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY_BYTES) {
        await reader.cancel();
        throw new HttpError(413, "payload_too_large", "Demo question is too large.");
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
  let parsed: unknown;
  try { parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new HttpError(400, "invalid_json", "Demo question must be JSON."); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new HttpError(400, "invalid_demo_question", "Demo question must be an object.");
  }
  const record = parsed as Record<string, unknown>;
  if (Object.keys(record).some((key) => key !== "message" && key !== "albuquerqueMode")) {
    throw new HttpError(400, "invalid_demo_question", "Demo question contains unsupported fields.");
  }
  const message = typeof record.message === "string" ? record.message.trim() : "";
  if (!message || message.length > MAX_MESSAGE_CHARS) {
    throw new HttpError(400, "invalid_demo_question", "Demo question must contain 1 to 500 characters.");
  }
  if (record.albuquerqueMode !== undefined && typeof record.albuquerqueMode !== "boolean") {
    throw new HttpError(400, "invalid_albuquerque_mode", "Albuquerque mode must be on or off.");
  }
  return { message, mode: requestedAlbuquerqueMode(message, record.albuquerqueMode === true) };
}

async function reserveGuestQuota(request: Request, env: PreviewGuestDemoEnv): Promise<void> {
  const ip = request.headers.get("CF-Connecting-IP")?.trim() ?? "";
  if (!/^[0-9a-fA-F:.]{3,45}$/u.test(ip)) {
    throw new HttpError(503, "demo_unavailable", "The guest demo is temporarily unavailable.");
  }
  const key = await hmacSha256Hex(env.ACTIVITY_IDENTITY_SECRET!, `hypha-demo-ip:${ip}`);
  let ipAllowed: boolean;
  let globalAllowed: boolean;
  try {
    ipAllowed = (await env.DEMO_IP_RATE_LIMIT!.limit({ key })).success;
    if (!ipAllowed) throw new HttpError(429, "demo_rate_limited", "Hypha's demo limit has been reached. Try again in a minute.");
    globalAllowed = (await env.DEMO_GLOBAL_RATE_LIMIT!.limit({ key: "hypha-demo" })).success;
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(503, "demo_unavailable", "The guest demo is temporarily unavailable.");
  }
  if (!globalAllowed) {
    throw new HttpError(429, "demo_rate_limited", "Hypha's demo limit has been reached. Try again in a minute.");
  }
}

function boundedGuestReply(text: string, mode: boolean): string {
  const source = text.trim();
  if (!source) throw new HttpError(502, "gemini_empty_reply", "Hypha could not prepare a reply.");
  if (!mode) return source.length <= MAX_REPLY_CHARS
    ? source : `${source.slice(0, MAX_REPLY_CHARS - 1).trimEnd()}…`;
  let shortened = source;
  let rendered = transformAlbuquerqueMarkdown(shortened);
  while (rendered.length > MAX_REPLY_CHARS && shortened.length > 1) {
    shortened = shortened.slice(0, Math.floor(shortened.length * 0.8)).trimEnd();
    rendered = transformAlbuquerqueMarkdown(`${shortened}…`);
  }
  return rendered;
}

export async function handleGuestDemo(request: Request, env: PreviewGuestDemoEnv): Promise<Response> {
  requireSameOriginMutation(request, env);
  if (!guestDemoConfigured(env)) {
    throw new HttpError(503, "demo_unavailable", "The guest demo is temporarily unavailable.");
  }
  const { message, mode } = await readGuestQuestion(request);
  await reserveGuestQuota(request, env);
  await requireGuestLogSchema(env.CHAT_DB);
  const askedAt = Math.floor(Date.now() / 1000);
  const reply = boundedGuestReply(await geminiGuestDemoReply(request, env, message), mode);
  await publishGuestExchange(env.CHAT_DB, message, reply, askedAt);
  return jsonResponse({ reply, albuquerqueMode: mode });
}
