import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DiscordConnectionState, PublicParticipant } from "./discord";
import {
  isRoomServerMessage,
  sanitizeRoomId,
  type RoomClientMessage,
  type RoomSnapshot,
  type SharedViewPatch,
} from "../shared/collaboration";
import type { EnvironmentName } from "../shared/public-state";
import type { ScientificBundle } from "../shared/scientific-visualization";

interface RoomTicketResponse {
  ticket: string;
  expiresAt: number;
  roomId: string;
  participant: PublicParticipant;
  websocketPath: string;
}

export type RoomConnectionStatus =
  | "disabled"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

export interface CollaborationRoomState {
  status: RoomConnectionStatus;
  detail: string;
  roomId: string;
  participant: PublicParticipant | null;
  snapshot: RoomSnapshot | null;
  canControl: boolean;
  isPresenter: boolean;
  sendViewPatch(patch: SharedViewPatch): void;
  claimPresenter(): void;
  releasePresenter(): void;
  reconnect(): void;
}

function previewIdentity(): string {
  const key = "missing-interior-phase4-preview-identity";
  const existing = window.localStorage.getItem(key);
  if (existing && /^[A-Za-z0-9._:-]{16,128}$/u.test(existing)) return existing;
  const created = `browser-${crypto.randomUUID()}`;
  window.localStorage.setItem(key, created);
  return created;
}

function requestedRoomId(instanceId: string | null): string {
  const parameters = new URLSearchParams(window.location.search);
  const candidate =
    parameters.get("room") ??
    instanceId ??
    parameters.get("instance_id") ??
    parameters.get("channel_id") ??
    "phase4-preview";
  try {
    return sanitizeRoomId(candidate);
  } catch {
    return "phase4-preview";
  }
}

async function requestRoomTicket(input: {
  environment: EnvironmentName;
  roomId: string;
  bundle: ScientificBundle;
  discord: DiscordConnectionState;
}): Promise<RoomTicketResponse> {
  const { dataset } = input.bundle;
  const identity = previewIdentity();
  const response = await fetch("/api/rooms/ticket", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(input.discord.sessionToken
        ? { Authorization: `Bearer ${input.discord.sessionToken}` }
        : {}),
    },
    body: JSON.stringify({
      environment: input.environment,
      roomId: input.roomId,
      artifactId: dataset.artifactId,
      visualizationId: dataset.visualizationId,
      minimumSeconds: dataset.waveform.startSeconds,
      maximumSeconds: dataset.waveform.endSeconds,
      previewIdentity: identity,
      previewName: `Test observer ${identity.slice(-4)}`,
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Room ticket failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as RoomTicketResponse;
}

function webSocketUrl(path: string): string {
  const url = new URL(path, window.location.origin);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function useCollaborationRoom(input: {
  environment: EnvironmentName;
  bundle: ScientificBundle | null;
  discord: DiscordConnectionState;
}): CollaborationRoomState {
  const roomId = useMemo(
    () => requestedRoomId(input.discord.instanceId),
    [input.discord.instanceId],
  );
  const [status, setStatus] = useState<RoomConnectionStatus>(
    input.bundle ? "connecting" : "disabled",
  );
  const [detail, setDetail] = useState(
    input.bundle ? "Preparing the shared investigation room." : "No scientific projection is available.",
  );
  const [participant, setParticipant] = useState<PublicParticipant | null>(null);
  const [snapshot, setSnapshot] = useState<RoomSnapshot | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const snapshotRef = useRef<RoomSnapshot | null>(null);
  const reconnectRef = useRef<() => void>(() => undefined);
  const generationRef = useRef(0);

  useEffect(() => {
    snapshotRef.current = snapshot;
  }, [snapshot]);

  const send = useCallback((message: RoomClientMessage) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setDetail("The shared room is not connected.");
      return;
    }
    socket.send(JSON.stringify(message));
  }, []);

  const connect = useCallback(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    const bundle = input.bundle;
    if (!bundle) {
      setStatus("disabled");
      setDetail("No scientific projection is available.");
      return;
    }

    socketRef.current?.close(1000, "Room configuration changed.");
    socketRef.current = null;
    setStatus((current) => (current === "connected" ? "reconnecting" : "connecting"));
    setDetail(`Connecting to room ${roomId}.`);

    void requestRoomTicket({
      environment: input.environment,
      roomId,
      bundle,
      discord: input.discord,
    })
      .then((ticket) => {
        if (generationRef.current !== generation) return;
        setParticipant(ticket.participant);
        const socket = new WebSocket(webSocketUrl(ticket.websocketPath));
        socketRef.current = socket;

        socket.addEventListener("open", () => {
          if (generationRef.current !== generation) return;
          setStatus("connected");
          setDetail(`Connected to shared room ${ticket.roomId}.`);
        });
        socket.addEventListener("message", (event) => {
          if (generationRef.current !== generation || typeof event.data !== "string") return;
          if (event.data === "pong") return;
          let value: unknown;
          try {
            value = JSON.parse(event.data) as unknown;
          } catch {
            setDetail("Room sent a non-JSON message.");
            return;
          }
          if (!isRoomServerMessage(value)) {
            setDetail("Room message failed the Phase 4 schema check.");
            return;
          }
          if (value.type === "room-ready" || value.type === "room-snapshot") {
            snapshotRef.current = value.snapshot;
            setSnapshot(value.snapshot);
            setDetail(
              `${value.snapshot.participants.length} participant${value.snapshot.participants.length === 1 ? "" : "s"} connected.`,
            );
          } else if (value.type === "room-error") {
            if (value.snapshot) {
              snapshotRef.current = value.snapshot;
              setSnapshot(value.snapshot);
            }
            setDetail(`${value.code}: ${value.message}`);
          }
        });
        socket.addEventListener("close", (event) => {
          if (generationRef.current !== generation) return;
          socketRef.current = null;
          if (event.code === 1000) return;
          setStatus("reconnecting");
          setDetail("Shared room disconnected; retrying shortly.");
          window.setTimeout(() => {
            if (generationRef.current === generation) reconnectRef.current();
          }, 2_500);
        });
        socket.addEventListener("error", () => {
          if (generationRef.current !== generation) return;
          setStatus("error");
          setDetail("Shared room WebSocket failed.");
        });
      })
      .catch((error: unknown) => {
        if (generationRef.current !== generation) return;
        setStatus("error");
        setDetail(error instanceof Error ? error.message : "Room connection failed.");
      });
  }, [input.bundle, input.discord, input.environment, roomId]);

  reconnectRef.current = connect;

  useEffect(() => {
    connect();
    const pingTimer = window.setInterval(() => {
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
    }, 25_000);
    return () => {
      generationRef.current += 1;
      window.clearInterval(pingTimer);
      socketRef.current?.close(1000, "Activity view closed.");
      socketRef.current = null;
    };
  }, [connect]);

  const participantId = participant?.participantId ?? null;
  const presenterId = snapshot?.presenterParticipantId ?? null;
  const canControl =
    status === "connected" &&
    participantId !== null &&
    (presenterId === null || presenterId === participantId);

  return {
    status,
    detail,
    roomId,
    participant,
    snapshot,
    canControl,
    isPresenter: participantId !== null && presenterId === participantId,
    sendViewPatch(patch) {
      const current = snapshotRef.current;
      if (!current) return;
      send({ type: "view-patch", baseRevision: current.view.revision, patch });
    },
    claimPresenter() {
      send({ type: "claim-presenter" });
    },
    releasePresenter() {
      send({ type: "release-presenter" });
    },
    reconnect: connect,
  };
}
