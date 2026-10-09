import type {
  RoomClientMessage,
  RoomTicketRequest,
  RoomTicketResponse,
} from "../shared/investigation-room";
import { ROOM_ID_MAX_LENGTH } from "../shared/investigation-room";
import { siteAuthHeaders } from "./site-auth";

function responseDetail(value: unknown): string {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (typeof record.message === "string") return record.message;
    if (typeof record.error === "string") return record.error;
  }
  return "The investigation room request failed.";
}

export function discordInstanceRoomId(instanceId: string | null): string | null {
  const normalized = instanceId?.trim() ?? "";
  if (!normalized) return null;
  const prefix = "discord-";
  const safeInstanceId = normalized
    .replace(/[^A-Za-z0-9_-]+/gu, "-")
    .replace(/^-+|-+$/gu, "")
    .slice(0, ROOM_ID_MAX_LENGTH - prefix.length);
  return safeInstanceId ? `${prefix}${safeInstanceId}` : null;
}

export class RoomTicketRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "RoomTicketRequestError";
  }
}

export function currentRoomId(discordInstanceId: string | null = null): string | null {
  const discordRoomId = discordInstanceRoomId(discordInstanceId);
  if (discordRoomId) return discordRoomId;
  const url = new URL(window.location.href);
  const requested = url.searchParams.get("room")?.trim() || "campaign";
  return /^[A-Za-z0-9_-]{1,96}$/u.test(requested) ? requested : null;
}

export function stableClientInstanceId(): string {
  const key = "missing-interior-phase4-client-instance";
  const existing = window.sessionStorage.getItem(key);
  if (existing) return existing;
  const created = globalThis.crypto.randomUUID();
  window.sessionStorage.setItem(key, created);
  return created;
}

export function newOperationId(): string {
  return globalThis.crypto.randomUUID();
}

export async function requestRoomTicket(
  request: RoomTicketRequest,
  sessionToken: string | null,
): Promise<RoomTicketResponse> {
  const response = await fetch("/api/rooms/tickets", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...siteAuthHeaders(sessionToken),
    },
    body: JSON.stringify(request),
  });
  const value = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    throw new RoomTicketRequestError(response.status, responseDetail(value));
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Room ticket response was malformed.");
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.ticket !== "string" ||
    typeof record.expiresAt !== "string" ||
    typeof record.participantId !== "string" ||
    typeof record.displayName !== "string" ||
    typeof record.websocketPath !== "string"
  ) {
    throw new Error("Room ticket response failed validation.");
  }
  return record as unknown as RoomTicketResponse;
}

export function openRoomSocket(path: string, ticket: string): WebSocket {
  const url = new URL(path, window.location.href);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("ticket", ticket);
  return new WebSocket(url);
}

export function sendRoomMessage(socket: WebSocket | null, message: RoomClientMessage): void {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("The investigation room is disconnected.");
  }
  socket.send(JSON.stringify(message));
}
