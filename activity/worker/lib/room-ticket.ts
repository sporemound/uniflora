import type { EnvironmentName } from "../../src/shared/public-state";
import { HttpError } from "./errors";

export interface RoomTicketPayload {
  version: 1;
  nonce: string;
  roomId: string;
  environment: EnvironmentName;
  artifactId: string;
  visualizationId: string;
  participantId: string;
  displayName: string;
  minimumSeconds: number;
  maximumSeconds: number;
  timeBases: string[];
  issuedAt: number;
  expiresAt: number;
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function base64UrlToBytes(value: string): Uint8Array {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  try {
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    throw new HttpError(401, "invalid_room_ticket", "Room ticket encoding is invalid.");
  }
}

async function hmac(
  secret: string,
  message: Uint8Array,
): Promise<Uint8Array> {
  if (secret.length < 32) {
    throw new HttpError(
      503,
      "room_ticket_secret_missing",
      "ROOM_TICKET_SECRET is not configured.",
    );
  }

  const keyMaterial = new TextEncoder().encode(secret);
  const keyBuffer = new ArrayBuffer(keyMaterial.byteLength);
  new Uint8Array(keyBuffer).set(keyMaterial);

  const key = await crypto.subtle.importKey(
    "raw",
    keyBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );

  const messageBuffer = new ArrayBuffer(message.byteLength);
  new Uint8Array(messageBuffer).set(message);

  return new Uint8Array(
    await crypto.subtle.sign("HMAC", key, messageBuffer),
  );
}

function constantTimeEqual(
  left: Uint8Array,
  right: Uint8Array,
): boolean {
  if (left.length !== right.length) {
    return false;
  }

  let difference = 0;

  for (let index = 0; index < left.length; index += 1) {
    difference |= left[index] ^ right[index];
  }

  return difference === 0;
}

export async function signRoomTicket(
  payload: RoomTicketPayload,
  secret: string,
): Promise<string> {
  const encodedPayload = bytesToBase64Url(
    new TextEncoder().encode(JSON.stringify(payload)),
  );
  const signature = await hmac(secret, new TextEncoder().encode(encodedPayload));
  return `${encodedPayload}.${bytesToBase64Url(signature)}`;
}

export async function verifyRoomTicket(
  ticket: string,
  secret: string,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<RoomTicketPayload> {
  const [encodedPayload, encodedSignature, extra] = ticket.split(".");
  if (!encodedPayload || !encodedSignature || extra !== undefined) {
    throw new HttpError(401, "invalid_room_ticket", "Room ticket structure is invalid.");
  }
  const expected = await hmac(secret, new TextEncoder().encode(encodedPayload));
  const actual = base64UrlToBytes(encodedSignature);
  if (!constantTimeEqual(expected, actual)) {
    throw new HttpError(401, "invalid_room_ticket", "Room ticket signature is invalid.");
  }
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder().decode(base64UrlToBytes(encodedPayload))) as unknown;
  } catch {
    throw new HttpError(401, "invalid_room_ticket", "Room ticket payload is invalid.");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(401, "invalid_room_ticket", "Room ticket payload must be an object.");
  }
  const payload = value as Partial<RoomTicketPayload>;
  if (
    payload.version !== 1 ||
    typeof payload.nonce !== "string" ||
    typeof payload.roomId !== "string" ||
    (payload.environment !== "live" && payload.environment !== "test") ||
    typeof payload.artifactId !== "string" ||
    typeof payload.visualizationId !== "string" ||
    typeof payload.participantId !== "string" ||
    typeof payload.displayName !== "string" ||
    typeof payload.minimumSeconds !== "number" ||
    typeof payload.maximumSeconds !== "number" ||
    !Array.isArray(payload.timeBases) ||
    !payload.timeBases.every((item) => typeof item === "string") ||
    typeof payload.issuedAt !== "number" ||
    typeof payload.expiresAt !== "number"
  ) {
    throw new HttpError(401, "invalid_room_ticket", "Room ticket fields are invalid.");
  }
  if (payload.expiresAt <= nowSeconds || payload.issuedAt > nowSeconds + 30) {
    throw new HttpError(401, "expired_room_ticket", "Room ticket has expired.");
  }
  return payload as RoomTicketPayload;
}

export async function stableTicketIdentity(
  secret: string,
  material: string,
  prefix = "participant",
): Promise<string> {
  const digest = await hmac(secret, new TextEncoder().encode(material));
  return `${prefix}_${bytesToBase64Url(digest).slice(0, 22)}`;
}

