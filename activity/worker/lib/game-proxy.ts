import { hmacSha256Hex, sha256Hex } from "./crypto";
import { HttpError } from "./errors";
import { requireActivityPrincipal, type PrincipalEnv } from "./principal";
import { jsonResponse, methodNotAllowed } from "./responses";

export interface GameProxyEnv extends PrincipalEnv {
  GAME_API_ORIGIN?: string;
  GAME_API_SECRET?: string;
}

function gameApiOrigin(env: GameProxyEnv): URL {
  let origin: URL;
  try {
    origin = new URL(env.GAME_API_ORIGIN ?? "");
  } catch {
    throw new HttpError(503, "game_api_unconfigured", "Game service is not configured.");
  }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname.toLowerCase());
  if (
    (origin.protocol !== "https:" && !(loopback && origin.protocol === "http:")) ||
    origin.pathname !== "/" || origin.search || origin.hash ||
    origin.username || origin.password
  ) {
    throw new HttpError(503, "game_api_unconfigured", "GAME_API_ORIGIN must be an HTTPS origin.");
  }
  return origin;
}

async function commandText(request: Request): Promise<string> {
  const declared = Number.parseInt(request.headers.get("Content-Length") ?? "0", 10);
  if (Number.isFinite(declared) && declared > 4096) {
    throw new HttpError(413, "payload_too_large", "Game command is too large.");
  }
  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > 4096) {
    throw new HttpError(413, "payload_too_large", "Game command is too large.");
  }
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
  } catch {
    throw new HttpError(400, "invalid_json", "Game command must be JSON.");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_game_command", "Game command must be an object.");
  }
  const record = value as Record<string, unknown>;
  const text = typeof record.text === "string" ? record.text.trim() : "";
  if (!text || text.length > 1000) {
    throw new HttpError(400, "invalid_game_command", "Command text must contain 1 to 1000 characters.");
  }
  if (Object.keys(record).some((key) => key !== "text")) {
    throw new HttpError(400, "invalid_game_command", "Only command text may be supplied.");
  }
  return text;
}

export async function handleGameProxy(
  request: Request,
  env: GameProxyEnv,
  action: "status" | "command",
): Promise<Response> {
  if (request.method !== "POST") return methodNotAllowed(["POST"]);
  const principal = await requireActivityPrincipal(request, env);
  if (principal.authProvider !== "email" || principal.environment !== "live") {
    throw new HttpError(403, "web_session_required", "A website session is required for game actions.");
  }
  const text = action === "command" ? await commandText(request) : undefined;
  const apiOrigin = gameApiOrigin(env);
  const secret = env.GAME_API_SECRET ?? "";
  if (secret.length < 32) {
    throw new HttpError(503, "game_api_unconfigured", "Game service signing is not configured.");
  }
  const body = JSON.stringify({
    playerId: principal.subjectKey,
    environment: "live",
    ...(text === undefined ? {} : { text }),
  });
  const path = `/internal/game/${action}`;
  const timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const bodyHash = await sha256Hex(body);
  const canonical = ["POST", path, timestamp, nonce, bodyHash].join("\n");
  const signature = await hmacSha256Hex(secret, canonical);
  let upstream: Response;
  try {
    upstream = await fetch(new URL(path, apiOrigin), {
      method: "POST",
      redirect: "manual",
      signal: AbortSignal.timeout(20_000),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Game-Timestamp": timestamp,
        "X-Game-Nonce": nonce,
        "X-Game-Content-SHA256": bodyHash,
        "X-Game-Signature": `v1=${signature}`,
      },
      body,
    });
  } catch {
    throw new HttpError(503, "game_api_unavailable", "Game service is temporarily unavailable.");
  }
  const declaredLength = Number.parseInt(upstream.headers.get("Content-Length") ?? "0", 10);
  if (Number.isFinite(declaredLength) && declaredLength > 256 * 1024) {
    throw new HttpError(502, "game_api_invalid_response", "Game service response was too large.");
  }
  const responseBody = await upstream.arrayBuffer();
  if (responseBody.byteLength > 256 * 1024 ||
      !upstream.headers.get("Content-Type")?.toLowerCase().includes("application/json")) {
    throw new HttpError(502, "game_api_invalid_response", "Game service returned an invalid response.");
  }
  let result: unknown;
  try {
    result = JSON.parse(new TextDecoder().decode(responseBody)) as unknown;
  } catch {
    throw new HttpError(502, "game_api_invalid_response", "Game service returned invalid JSON.");
  }
  if (upstream.status < 200 || upstream.status > 599) {
    throw new HttpError(502, "game_api_invalid_response", "Game service returned an invalid status.");
  }
  return jsonResponse(result, upstream.status);
}
