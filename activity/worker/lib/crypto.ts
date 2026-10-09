import { HttpError } from "./errors";

const encoder = new TextEncoder();

export function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(value: ArrayBuffer | Uint8Array | string): Promise<string> {
  const source =
    typeof value === "string"
      ? encoder.encode(value)
      : value instanceof Uint8Array
        ? value
        : new Uint8Array(value);

  const bytes = new Uint8Array(source.byteLength);
  bytes.set(source);
  const digest = await crypto.subtle.digest("SHA-256", bytes.buffer);
  return bytesToHex(new Uint8Array(digest));
}

export async function hmacSha256Hex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return bytesToHex(new Uint8Array(signature));
}

export function timingSafeEqualHex(left: string, right: string): boolean {
  const normalizedLeft = left.toLowerCase();
  const normalizedRight = right.toLowerCase();
  const maxLength = Math.max(normalizedLeft.length, normalizedRight.length);
  let difference = normalizedLeft.length ^ normalizedRight.length;

  for (let index = 0; index < maxLength; index += 1) {
    difference |=
      (normalizedLeft.charCodeAt(index) || 0) ^
      (normalizedRight.charCodeAt(index) || 0);
  }

  return difference === 0;
}

export function randomToken(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return bytesToHex(bytes);
}

export interface SignedRequestMetadata {
  timestamp: number;
  nonce: string;
  bodySha256: string;
}

export async function verifyHyphaSignature(
  request: Request,
  body: ArrayBuffer,
  secret: string,
  maxClockSkewSeconds: number,
): Promise<SignedRequestMetadata> {
  if (!secret) {
    throw new HttpError(503, "hypha_sync_unconfigured", "Hypha publication is not configured.");
  }

  const timestampText = request.headers.get("X-Hypha-Timestamp")?.trim() ?? "";
  const nonce = request.headers.get("X-Hypha-Nonce")?.trim() ?? "";
  const declaredHash = request.headers.get("X-Hypha-Content-SHA256")?.trim().toLowerCase() ?? "";
  const signatureHeader = request.headers.get("X-Hypha-Signature")?.trim() ?? "";
  const timestamp = Number.parseInt(timestampText, 10);

  if (!Number.isSafeInteger(timestamp)) {
    throw new HttpError(401, "invalid_timestamp", "X-Hypha-Timestamp must be Unix seconds.");
  }
  if (!/^[A-Za-z0-9._:-]{16,160}$/.test(nonce)) {
    throw new HttpError(401, "invalid_nonce", "X-Hypha-Nonce has an invalid format.");
  }
  if (!/^[a-f0-9]{64}$/.test(declaredHash)) {
    throw new HttpError(401, "invalid_content_hash", "X-Hypha-Content-SHA256 must be lowercase SHA-256 hex.");
  }

  const nowSeconds = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSeconds - timestamp) > maxClockSkewSeconds) {
    throw new HttpError(401, "stale_request", "The signed request timestamp is outside the allowed window.");
  }

  const actualHash = await sha256Hex(body);
  if (!timingSafeEqualHex(actualHash, declaredHash)) {
    throw new HttpError(401, "content_hash_mismatch", "The request body does not match its declared hash.");
  }

  const signature = signatureHeader.startsWith("v1=")
    ? signatureHeader.slice(3).toLowerCase()
    : "";
  if (!/^[a-f0-9]{64}$/.test(signature)) {
    throw new HttpError(401, "invalid_signature", "X-Hypha-Signature must use the v1=<hex> format.");
  }

  const url = new URL(request.url);
  const canonical = [
    request.method.toUpperCase(),
    url.pathname,
    timestampText,
    nonce,
    actualHash,
  ].join("\n");
  const expected = await hmacSha256Hex(secret, canonical);
  if (!timingSafeEqualHex(signature, expected)) {
    throw new HttpError(401, "signature_mismatch", "The Hypha request signature is invalid.");
  }

  return {
    timestamp,
    nonce,
    bodySha256: actualHash,
  };
}
