import type { D1Database } from "./cloudflare";
import { hmacSha256Hex, randomToken, sha256Hex } from "./crypto";
import { HttpError } from "./errors";
import { jsonResponse, methodNotAllowed } from "./responses";

const LINK_TTL_SECONDS = 15 * 60;
const SEND_COOLDOWN_SECONDS = 60;
const DEFAULT_SESSION_TTL_SECONDS = 15 * 60;
const PRODUCTION_COOKIE = "__Host-mi_session";
const DEVELOPMENT_COOKIE = "mi_dev_session";
const GENERIC_SEND_MESSAGE = "If that address can receive mail, a sign-in link is on its way.";

export interface MagicLinkEnv {
  PUBLIC_DB: D1Database;
  APP_ORIGIN?: string;
  RESEND_API_KEY?: string;
  MAGIC_LINK_FROM_EMAIL?: string;
  ACTIVITY_IDENTITY_SECRET?: string;
  SESSION_TTL_SECONDS?: string;
}

export interface WebParticipant {
  participantId: string;
  displayName: string;
  avatarUrl: null;
}

export interface WebSession {
  participant: WebParticipant;
  expiresAt: number;
}

interface MagicLinkRow {
  email: string;
  email_hash: string;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function appOrigin(env: MagicLinkEnv): URL {
  let origin: URL;
  try {
    origin = new URL(env.APP_ORIGIN ?? "");
  } catch {
    throw new HttpError(503, "web_auth_unconfigured", "Website authentication is not configured.");
  }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname.toLowerCase());
  if (
    (origin.protocol !== "https:" && !(loopback && origin.protocol === "http:")) ||
    origin.pathname !== "/" || origin.search || origin.hash || origin.username || origin.password
  ) {
    throw new HttpError(503, "web_auth_unconfigured", "APP_ORIGIN must be an HTTPS origin.");
  }
  return origin;
}

function requireRequestHost(request: Request, origin: URL): void {
  if (new URL(request.url).origin !== origin.origin) {
    throw new HttpError(403, "origin_mismatch", "The sign-in link must open on this website.");
  }
}

/** Apply to every state-changing route that accepts a website session cookie. */
export function requireSameOriginMutation(request: Request, env: MagicLinkEnv): void {
  const origin = appOrigin(env);
  requireRequestHost(request, origin);
  if (request.headers.get("Origin") !== origin.origin) {
    throw new HttpError(403, "origin_mismatch", "This request must come from the website.");
  }
}

export function normalizedEmail(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const email = value.trim().toLowerCase();
  if (
    email.length < 3 || email.length > 254 ||
    !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/u.test(email) ||
    email.includes("..")
  ) return null;
  return email;
}

function identitySecret(env: MagicLinkEnv): string {
  const value = env.ACTIVITY_IDENTITY_SECRET ?? "";
  if (value.length < 32) {
    throw new HttpError(503, "web_auth_unconfigured", "Website identity is not configured.");
  }
  return value;
}

function sessionTtl(env: MagicLinkEnv): number {
  const configured = Number.parseInt(env.SESSION_TTL_SECONDS ?? "", 10);
  return Number.isSafeInteger(configured)
    ? Math.max(300, Math.min(configured, 86_400))
    : DEFAULT_SESSION_TTL_SECONDS;
}

function cookieName(origin: URL): string {
  return origin.protocol === "https:" ? PRODUCTION_COOKIE : DEVELOPMENT_COOKIE;
}

function sessionCookie(origin: URL, token: string, maxAge: number): string {
  const secure = origin.protocol === "https:" ? "; Secure" : "";
  return `${cookieName(origin)}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure}`;
}

function cookieValue(request: Request, name: string): string | null {
  const entry = (request.headers.get("Cookie") ?? "")
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  return entry ? entry.slice(name.length + 1) : null;
}

function htmlResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
      "Content-Type": "text/html; charset=utf-8",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

function confirmationPage(token: string): Response {
  return htmlResponse(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Confirm sign in</title></head>
<body><main><h1>Sign in to The Missing Interior</h1>
<p>Continue only if you requested this sign-in link.</p>
<form method="post" action="/api/auth/magic-link/verify">
<input type="hidden" name="token" value="${token}">
<button type="submit">Continue to the investigation</button></form></main></body></html>`);
}

async function readSmallBody(request: Request, maxBytes: number): Promise<string> {
  const stated = Number.parseInt(request.headers.get("Content-Length") ?? "0", 10);
  if (Number.isFinite(stated) && stated > maxBytes) {
    throw new HttpError(413, "payload_too_large", "The sign-in request is too large.");
  }
  const body = await request.arrayBuffer();
  if (body.byteLength > maxBytes) {
    throw new HttpError(413, "payload_too_large", "The sign-in request is too large.");
  }
  return new TextDecoder().decode(body);
}

async function sendSignInEmail(
  env: MagicLinkEnv,
  email: string,
  link: string,
  idempotencyKey: string,
): Promise<void> {
  const apiKey = env.RESEND_API_KEY?.trim() ?? "";
  const from = env.MAGIC_LINK_FROM_EMAIL?.trim() ?? "";
  if (!apiKey || !normalizedEmail(from)) {
    throw new HttpError(503, "web_auth_unconfigured", "Sign-in email delivery is not configured.");
  }
  let response: Response;
  try {
    response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({
        from,
        to: [email],
        subject: "Sign in to The Missing Interior",
        text: `Open this link to sign in to The Missing Interior:\n\n${link}\n\nThe link expires in 15 minutes. If you did not request it, ignore this message.`,
      }),
    });
  } catch {
    throw new HttpError(503, "email_delivery_unavailable", "Sign-in email is temporarily unavailable.");
  }
  if (!response.ok) {
    throw new HttpError(503, "email_delivery_unavailable", "Sign-in email is temporarily unavailable.");
  }
}

export async function handleMagicLinkRequest(request: Request, env: MagicLinkEnv): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  requireSameOriginMutation(request, env);
  const origin = appOrigin(env);
  const body = await readSmallBody(request, 4096);
  let value: unknown;
  try {
    value = JSON.parse(body) as unknown;
  } catch {
    value = null;
  }
  const email = normalizedEmail(
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>).email : null,
  );
  const generic = () => jsonResponse({ ok: true, message: GENERIC_SEND_MESSAGE }, 202);
  if (!email) return generic();

  const secret = identitySecret(env);
  const emailHash = await hmacSha256Hex(secret, `web-email:${email}`);
  const now = nowSeconds();
  const cooldown = await env.PUBLIC_DB.prepare(
    `INSERT INTO web_magic_link_cooldowns (email_hash, next_allowed_at)
     VALUES (?, ?)
     ON CONFLICT(email_hash) DO UPDATE SET next_allowed_at = excluded.next_allowed_at
     WHERE web_magic_link_cooldowns.next_allowed_at <= ?`,
  ).bind(emailHash, now + SEND_COOLDOWN_SECONDS, now).run();
  if ((cooldown.meta?.changes ?? 0) !== 1) return generic();

  const token = randomToken();
  const tokenHash = await sha256Hex(token);
  await env.PUBLIC_DB.prepare(
    `INSERT INTO web_magic_links (token_hash, email, email_hash, issued_at, expires_at)
     VALUES (?, ?, ?, ?, ?)`,
  ).bind(tokenHash, email, emailHash, now, now + LINK_TTL_SECONDS).run();
  const link = new URL("/api/auth/magic-link/verify", origin);
  link.searchParams.set("token", token);
  try {
    await sendSignInEmail(env, email, link.toString(), tokenHash);
  } catch (error) {
    await env.PUBLIC_DB.prepare("DELETE FROM web_magic_links WHERE token_hash = ?")
      .bind(tokenHash).run();
    throw error;
  }
  await env.PUBLIC_DB.prepare("DELETE FROM web_magic_links WHERE expires_at < ?")
    .bind(now).run();
  await env.PUBLIC_DB.prepare("DELETE FROM web_magic_link_cooldowns WHERE next_allowed_at < ?")
    .bind(now - 86_400).run();
  return generic();
}

export async function handleMagicLinkVerify(request: Request, env: MagicLinkEnv): Promise<Response> {
  const origin = appOrigin(env);
  requireRequestHost(request, origin);
  if (request.method === "GET") {
    const token = new URL(request.url).searchParams.get("token") ?? "";
    if (!/^[a-f0-9]{64}$/u.test(token)) {
      return htmlResponse("<!doctype html><html lang=\"en\"><title>Invalid link</title><h1>This sign-in link is invalid.</h1></html>", 400);
    }
    return confirmationPage(token);
  }
  if (request.method !== "POST") return methodNotAllowed(["GET", "POST"]);
  requireSameOriginMutation(request, env);
  const contentType = request.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().startsWith("application/x-www-form-urlencoded")) {
    throw new HttpError(415, "unsupported_media_type", "Sign-in confirmation requires a form submission.");
  }
  const form = new URLSearchParams(await readSmallBody(request, 1024));
  const token = form.get("token") ?? "";
  if (!/^[a-f0-9]{64}$/u.test(token)) {
    return htmlResponse("<!doctype html><html lang=\"en\"><title>Invalid link</title><h1>This sign-in link is invalid.</h1></html>", 400);
  }
  const tokenHash = await sha256Hex(token);
  const now = nowSeconds();
  const consumed = await env.PUBLIC_DB.prepare(
    `UPDATE web_magic_links SET consumed_at = ?
     WHERE token_hash = ? AND consumed_at IS NULL AND expires_at >= ?`,
  ).bind(now, tokenHash, now).run();
  if ((consumed.meta?.changes ?? 0) !== 1) {
    return htmlResponse("<!doctype html><html lang=\"en\"><title>Expired link</title><h1>This sign-in link has expired or was already used.</h1></html>", 400);
  }
  const row = await env.PUBLIC_DB.prepare(
    "SELECT email, email_hash FROM web_magic_links WHERE token_hash = ?",
  ).bind(tokenHash).first<MagicLinkRow>();
  if (!row) {
    throw new HttpError(500, "sign_in_failed", "Sign-in could not be completed.");
  }
  const participantId = `participant_${row.email_hash.slice(0, 24)}`;
  const displayName = `Investigator ${row.email_hash.slice(0, 6).toUpperCase()}`;
  const sessionToken = randomToken();
  const sessionHash = await sha256Hex(sessionToken);
  const expiresAt = now + sessionTtl(env);
  await env.PUBLIC_DB.prepare(
    `INSERT INTO activity_sessions (
       session_hash, participant_id, display_name, avatar_url,
       discord_user_id, instance_id, guild_id, channel_id,
       issued_at, expires_at, last_seen_at, auth_provider, email_hash
     ) VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, 'email', ?)`,
  ).bind(sessionHash, participantId, displayName, now, expiresAt, now, row.email_hash).run();
  // Keep the email address only in the short-lived, consumed challenge row.
  await env.PUBLIC_DB.prepare("DELETE FROM web_magic_links WHERE token_hash = ?")
    .bind(tokenHash).run();
  const response = new Response(null, {
    status: 303,
    headers: {
      Location: new URL("/", origin).toString(),
      "Cache-Control": "no-store",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
  });
  response.headers.set("Set-Cookie", sessionCookie(origin, sessionToken, expiresAt - now));
  return response;
}

export async function readWebSession(request: Request, env: MagicLinkEnv): Promise<WebSession | null> {
  const cookies = request.headers.get("Cookie") ?? "";
  if (!/(?:^|;)\s*(?:__Host-mi_session|mi_dev_session)=/u.test(cookies)) return null;
  const origin = appOrigin(env);
  const token = cookieValue(request, cookieName(origin));
  if (!token || !/^[a-f0-9]{64}$/u.test(token)) return null;
  const now = nowSeconds();
  const sessionHash = await sha256Hex(token);
  const row = await env.PUBLIC_DB.prepare(
    `SELECT participant_id, display_name, expires_at
     FROM activity_sessions
     WHERE session_hash = ? AND auth_provider = 'email' AND expires_at >= ?`,
  ).bind(sessionHash, now).first<{
    participant_id: string;
    display_name: string;
    expires_at: number;
  }>();
  if (!row) return null;
  // Email sessions have a fixed expiry; reads do not refresh them. Avoid a D1
  // row write on every five-second chat poll.
  return {
    participant: {
      participantId: row.participant_id,
      displayName: row.display_name,
      avatarUrl: null,
    },
    expiresAt: row.expires_at,
  };
}

export async function revokeWebSession(request: Request, env: MagicLinkEnv): Promise<Response> {
  requireSameOriginMutation(request, env);
  const origin = appOrigin(env);
  const token = cookieValue(request, cookieName(origin));
  if (token && /^[a-f0-9]{64}$/u.test(token)) {
    await env.PUBLIC_DB.prepare("DELETE FROM activity_sessions WHERE session_hash = ? AND auth_provider = 'email'")
      .bind(await sha256Hex(token)).run();
  }
  const response = jsonResponse({ ok: true });
  response.headers.set("Set-Cookie", sessionCookie(origin, "", 0));
  return response;
}
