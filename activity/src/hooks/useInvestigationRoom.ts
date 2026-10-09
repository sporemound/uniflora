import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  currentRoomId,
  newOperationId,
  openRoomSocket,
  RoomTicketRequestError,
  requestRoomTicket,
  sendRoomMessage,
  stableClientInstanceId,
} from "../lib/investigation-room";
import {
  INVESTIGATION_ROOM_PROTOCOL_VERSION,
  type FindingRevisionContent,
  type InvestigationRoomSnapshot,
  type InvestigationRoomReviewState,
  type RoomClientMessage,
  type RoomConnectionStatus,
  type RoomFinding,
  type RoomLayerState,
  type RoomOperationErrorDetails,
  type RoomScientificSelection,
  type RoomServerMessage,
  isRoomServerMessage,
} from "../shared/investigation-room";
import type {
  FindingAnalysisArtifactReference,
  FindingEvidenceReference,
  FindingRelationshipType,
  FindingReviewDisposition,
  FindingReviewRubric,
} from "../shared/finding-review";
import type { EnvironmentName } from "../shared/public-state";

const DEFAULT_LAYERS: RoomLayerState = {
  rawVoltageV: true,
  calibratedVoltageV: true,
  residualVoltageV: false,
  uncertainty: true,
};

interface UseInvestigationRoomOptions {
  enabled?: boolean;
  environment: EnvironmentName;
  artifactId: string;
  visualizationId: string;
  minimumSeconds: number;
  maximumSeconds: number;
  timeBases: string[];
  sessionToken: string | null;
  discordInstanceId: string | null;
}

interface FindingDraft {
  title: string;
  observation: string;
  selection: RoomScientificSelection;
  layers: RoomLayerState;
  interpretation?: string | null;
  limitations?: string[];
  evidenceReferences?: FindingEvidenceReference[];
  analysisArtifactReferences?: FindingAnalysisArtifactReference[];
}

export interface RoomOperationFeedback {
  operationId: string | null;
  outcome: "pending" | "accepted" | "duplicate" | "error";
  message: string;
  code: string | null;
  details: RoomOperationErrorDetails | null;
}

export interface InvestigationRoomController {
  roomId: string | null;
  status: RoomConnectionStatus;
  detail: string;
  selfParticipantId: string | null;
  snapshot: InvestigationRoomSnapshot | null;
  findings: RoomFinding[];
  canControlSharedState: boolean;
  isPresenter: boolean;
  pendingOperationIds: string[];
  operationFeedback: RoomOperationFeedback | null;
  sendSelection(selection: RoomScientificSelection): boolean;
  sendLayers(layers: RoomLayerState): boolean;
  claimPresenter(): void;
  releasePresenter(): void;
  createFinding(draft: FindingDraft): string | null;
  updateFinding(findingId: string, title: string, observation: string): string | null;
  deleteFinding(findingId: string): string | null;
  reviseFinding(
    findingId: string,
    findingRevision: number,
    revision: FindingRevisionContent & {
      revisionReason: string;
      addressedReviewIds: string[];
    },
  ): string | null;
  startFindingReview(findingId: string, findingRevision: number): string | null;
  submitFindingReview(
    findingId: string,
    findingRevision: number,
    disposition: FindingReviewDisposition,
    rationale: string,
    rubric: FindingReviewRubric,
  ): string | null;
  resolveFindingReview(
    findingId: string,
    findingRevision: number,
    reviewId: string,
    resolutionAction: "resolve" | "withdraw",
    rationale: string,
  ): string | null;
  createFindingRelationship(
    sourceFindingId: string,
    sourceRevision: number,
    targetFindingId: string,
    targetRevision: number,
    relationshipType: FindingRelationshipType,
    rationale: string | null,
  ): string | null;
  promoteFinding(findingId: string, findingRevision: number): string | null;
  withdrawFinding(
    findingId: string,
    findingRevision: number,
    rationale: string,
  ): string | null;
  openFinding(findingId: string): boolean;
  clearError(): void;
  clearOperationFeedback(): void;
}

function sortFindings(findings: RoomFinding[]): RoomFinding[] {
  return [...findings].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

function mergeReviewState(
  current: InvestigationRoomSnapshot,
  reviewState: InvestigationRoomReviewState,
  roomRevision: number,
): InvestigationRoomSnapshot {
  if (roomRevision < current.roomRevision) return current;
  return {
    ...current,
    ...reviewState,
    roomRevision,
    findings: sortFindings(reviewState.findings),
  };
}

export function useInvestigationRoom(
  options: UseInvestigationRoomOptions,
): InvestigationRoomController {
  const roomId = useMemo(
    () => options.enabled === false ? null : currentRoomId(options.discordInstanceId),
    [options.discordInstanceId, options.enabled],
  );
  const [status, setStatus] = useState<RoomConnectionStatus>(roomId ? "ticketing" : "disabled");
  const [detail, setDetail] = useState(
    roomId ? "Requesting a short-lived room ticket." : "Add ?room=<name> to join a shared investigation room.",
  );
  const [selfParticipantId, setSelfParticipantId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<InvestigationRoomSnapshot | null>(null);
  const [pendingOperationIds, setPendingOperationIds] = useState<string[]>([]);
  const [operationFeedback, setOperationFeedback] = useState<RoomOperationFeedback | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const stoppedRef = useRef(false);
  const revisionRef = useRef(0);
  const receivedSnapshotRef = useRef(false);
  const pendingOperationIdsRef = useRef(new Set<string>());

  const markOperationComplete = useCallback((operationId: string) => {
    pendingOperationIdsRef.current.delete(operationId);
    setPendingOperationIds([...pendingOperationIdsRef.current]);
  }, []);

  const isPendingOperation = useCallback(
    (operationId: string) => pendingOperationIdsRef.current.has(operationId),
    [],
  );

  const applyServerMessage = useCallback((message: RoomServerMessage) => {
    if (message.type === "room:snapshot") {
      const isReconnectSnapshot = receivedSnapshotRef.current;
      receivedSnapshotRef.current = true;
      const interruptedOperationCount = pendingOperationIdsRef.current.size;
      if (isReconnectSnapshot && interruptedOperationCount > 0) {
        pendingOperationIdsRef.current.clear();
        setPendingOperationIds([]);
        setOperationFeedback({
          operationId: null,
          outcome: "error",
          message:
            "The room reconnected before an operation acknowledgement arrived. Review state is synchronized; your form values remain available to confirm or retry.",
          code: "acknowledgement_interrupted",
          details: null,
        });
      }
      revisionRef.current = Math.max(revisionRef.current, message.snapshot.roomRevision);
      setSelfParticipantId(message.selfParticipantId);
      setSnapshot((current) =>
        current && message.snapshot.roomRevision < current.roomRevision
          ? current
          : {
              ...message.snapshot,
              findings: sortFindings(message.snapshot.findings),
            },
      );
      setDetail(`Connected to ${message.snapshot.roomId}.`);
      return;
    }

    revisionRef.current = Math.max(revisionRef.current, message.roomRevision);

    if (message.type === "room:error") {
      if (message.operationId) markOperationComplete(message.operationId);
      setSnapshot((current) =>
        current
          ? mergeReviewState(current, message.reviewState, message.roomRevision)
          : current,
      );
      setDetail(`${message.code}: ${message.message}`);
      setOperationFeedback({
        operationId: message.operationId,
        outcome: "error",
        message: message.message,
        code: message.code,
        details: message.details,
      });
      return;
    }

    if (message.type === "room:review-state") {
      const operationWasPending = isPendingOperation(message.operationId);
      markOperationComplete(message.operationId);
      setSnapshot((current) =>
        current
          ? mergeReviewState(current, message.reviewState, message.roomRevision)
          : current,
      );
      if (operationWasPending) {
        setDetail("Collaborative finding operation accepted.");
        setOperationFeedback({
          operationId: message.operationId,
          outcome: "accepted",
          message: "Operation accepted. The review state is synchronized.",
          code: null,
          details: null,
        });
      }
      return;
    }

    if (message.type === "operation:duplicate") {
      markOperationComplete(message.operationId);
      setSnapshot((current) =>
        current && message.roomRevision >= current.roomRevision
          ? { ...current, roomRevision: message.roomRevision }
          : current,
      );
      setDetail("The repeated operation was already applied.");
      setOperationFeedback({
        operationId: message.operationId,
        outcome: "duplicate",
        message: "This operation was already applied; no duplicate record was created.",
        code: null,
        details: null,
      });
      return;
    }

    if (message.type === "room:state") {
      setSnapshot((current) =>
        current && message.roomRevision >= current.roomRevision
          ? {
              ...current,
              roomRevision: message.roomRevision,
              participants: message.participants,
              presenterParticipantId: message.presenterParticipantId,
              selection: message.selection,
              layers: message.layers,
            }
          : current,
      );
      return;
    }

    if (message.type === "finding:created" || message.type === "finding:updated") {
      const operationWasPending = isPendingOperation(message.operationId);
      markOperationComplete(message.operationId);
      setSnapshot((current) => {
        if (!current || message.roomRevision < current.roomRevision) return current;
        const without = current.findings.filter(
          (finding) => finding.findingId !== message.finding.findingId,
        );
        return {
          ...current,
          roomRevision: message.roomRevision,
          findings: sortFindings([...without, message.finding]),
        };
      });
      setDetail(message.type === "finding:created" ? "Shared finding saved." : "Shared finding updated.");
      if (operationWasPending) {
        setOperationFeedback({
          operationId: message.operationId,
          outcome: "accepted",
          message: message.type === "finding:created"
            ? "Shared finding saved."
            : "A compatible immutable revision was created.",
          code: null,
          details: null,
        });
      }
      return;
    }

    if (message.type === "finding:deleted") {
      const operationWasPending = isPendingOperation(message.operationId);
      markOperationComplete(message.operationId);
      setSnapshot((current) =>
        current && message.roomRevision >= current.roomRevision
          ? {
              ...current,
              roomRevision: message.roomRevision,
              findings: current.findings.filter(
                (finding) => finding.findingId !== message.findingId,
              ),
            }
          : current,
      );
      setDetail("Shared finding removed by a compatible legacy operation.");
      if (operationWasPending) {
        setOperationFeedback({
          operationId: message.operationId,
          outcome: "accepted",
          message: "The compatible finding operation was accepted.",
          code: null,
          details: null,
        });
      }
      return;
    }

    if (message.type === "operation:accepted") {
      const operationWasPending = isPendingOperation(message.operationId);
      markOperationComplete(message.operationId);
      setSnapshot((current) =>
        current && message.roomRevision >= current.roomRevision
          ? { ...current, roomRevision: message.roomRevision }
          : current,
      );
      if (operationWasPending) {
        setOperationFeedback({
          operationId: message.operationId,
          outcome: "accepted",
          message: "Room operation accepted.",
          code: null,
          details: null,
        });
      }
      return;
    }

    return;
  }, [isPendingOperation, markOperationComplete]);

  useEffect(() => {
    if (!roomId) return undefined;
    stoppedRef.current = false;
    receivedSnapshotRef.current = false;
    reconnectAttemptRef.current = 0;

    function scheduleReconnect(connect: () => Promise<void>): void {
      const attempt = reconnectAttemptRef.current;
      reconnectAttemptRef.current += 1;
      const delay = Math.min(30_000, 1_500 * 2 ** Math.min(attempt, 5));
      const jitter = Math.floor(Math.random() * 500);
      reconnectTimerRef.current = window.setTimeout(() => {
        void connect();
      }, delay + jitter);
    }

    const connect = async (isReconnect: boolean) => {
      setStatus(isReconnect ? "reconnecting" : "ticketing");
      setDetail(isReconnect ? "Reconnecting to the investigation room." : "Requesting a short-lived room ticket.");
      try {
        const ticket = await requestRoomTicket(
          {
            roomId,
            environment: options.environment,
            artifactId: options.artifactId,
            visualizationId: options.visualizationId,
            minimumSeconds: options.minimumSeconds,
            maximumSeconds: options.maximumSeconds,
            timeBases: options.timeBases,
            clientInstanceId: stableClientInstanceId(),
          },
          options.sessionToken,
        );
        if (stoppedRef.current) return;
        setStatus("connecting");
        const socket = openRoomSocket(ticket.websocketPath, ticket.ticket);
        socketRef.current = socket;
        socket.addEventListener("open", () => {
          reconnectAttemptRef.current = 0;
          setStatus("connected");
          setDetail(`Connected as ${ticket.displayName}.`);
        });
        socket.addEventListener("message", (event) => {
          try {
            const value = JSON.parse(String(event.data)) as unknown;
            if (!isRoomServerMessage(value)) {
              throw new Error("Malformed room server message.");
            }
            applyServerMessage(value);
          } catch (error) {
            setStatus("error");
            setDetail(error instanceof Error ? error.message : "Malformed room server message.");
          }
        });
        socket.addEventListener("close", () => {
          if (socketRef.current === socket) socketRef.current = null;
          if (stoppedRef.current) return;
          setStatus("disconnected");
          setDetail("Room connection closed; retrying.");
          scheduleReconnect(() => connect(true));
        });
        socket.addEventListener("error", () => {
          setStatus("error");
          setDetail("The investigation room WebSocket failed.");
        });
      } catch (error) {
        if (stoppedRef.current) return;
        setStatus("error");
        setDetail(error instanceof Error ? error.message : "Unable to connect to the room.");
        if (
          error instanceof RoomTicketRequestError &&
          [400, 401, 403, 404].includes(error.status)
        ) {
          return;
        }
        scheduleReconnect(() => connect(true));
      }
    };

    void connect(false);
    return () => {
      stoppedRef.current = true;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      socketRef.current?.close(1000, "Workspace changed");
      socketRef.current = null;
    };
  }, [
    applyServerMessage,
    options.artifactId,
    options.environment,
    options.maximumSeconds,
    options.minimumSeconds,
    options.sessionToken,
    options.timeBases,
    options.visualizationId,
    roomId,
  ]);

  const send = useCallback((message: RoomClientMessage) => {
    try {
      sendRoomMessage(socketRef.current, message);
      return true;
    } catch (error) {
      setDetail(error instanceof Error ? error.message : "Unable to send the room operation.");
      return false;
    }
  }, []);

  const sendTracked = useCallback((
    createMessage: (operationId: string, expectedRevision: number) => RoomClientMessage,
    pendingMessage: string,
  ): string | null => {
    const operationId = newOperationId();
    const message = createMessage(operationId, revisionRef.current);
    if (!send(message)) {
      setOperationFeedback({
        operationId,
        outcome: "error",
        message: "The operation was not sent. Your form values have been preserved.",
        code: "client_send_failed",
        details: null,
      });
      return null;
    }
    pendingOperationIdsRef.current.add(operationId);
    setPendingOperationIds([...pendingOperationIdsRef.current]);
    setOperationFeedback({
      operationId,
      outcome: "pending",
      message: pendingMessage,
      code: null,
      details: null,
    });
    return operationId;
  }, [send]);

  const presenterParticipantId = snapshot?.presenterParticipantId ?? null;
  const isPresenter = selfParticipantId !== null && presenterParticipantId === selfParticipantId;
  const canControlSharedState =
    status === "connected" &&
    (presenterParticipantId === null || presenterParticipantId === selfParticipantId);

  const baseMessage = () => ({
    protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
    operationId: newOperationId(),
    expectedRevision: revisionRef.current,
  });

  return {
    roomId,
    status,
    detail,
    selfParticipantId,
    snapshot,
    findings: snapshot?.findings ?? [],
    canControlSharedState,
    isPresenter,
    pendingOperationIds,
    operationFeedback,
    sendSelection(selection) {
      if (!canControlSharedState) {
        setDetail("Shared controls are locked by the current presenter.");
        return false;
      }
      return send({ ...baseMessage(), type: "selection:set", selection });
    },
    sendLayers(layers) {
      if (!canControlSharedState) {
        setDetail("Shared controls are locked by the current presenter.");
        return false;
      }
      return send({ ...baseMessage(), type: "layers:set", layers });
    },
    claimPresenter() {
      void send({ ...baseMessage(), type: "presenter:claim" });
    },
    releasePresenter() {
      void send({ ...baseMessage(), type: "presenter:release" });
    },
    createFinding(draft) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:create",
          finding: draft,
        }),
        "Saving the initial immutable finding revision.",
      );
    },
    updateFinding(findingId, title, observation) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:update",
          findingId,
          title,
          observation,
        }),
        "Creating a compatible immutable finding revision.",
      );
    },
    deleteFinding(findingId) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:delete",
          findingId,
        }),
        "Applying the compatible finding withdrawal.",
      );
    },
    reviseFinding(findingId, findingRevision, revision) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:revise",
          findingId,
          findingRevision,
          revision,
        }),
        `Creating revision ${findingRevision + 1}.`,
      );
    },
    startFindingReview(findingId, findingRevision) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:review:start",
          findingId,
          findingRevision,
        }),
        `Starting peer review for revision ${findingRevision}.`,
      );
    },
    submitFindingReview(findingId, findingRevision, disposition, rationale, rubric) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:review:submit",
          findingId,
          findingRevision,
          disposition,
          rationale,
          rubric,
        }),
        `Submitting ${disposition.replaceAll("_", " ")} for revision ${findingRevision}.`,
      );
    },
    resolveFindingReview(
      findingId,
      findingRevision,
      reviewId,
      resolutionAction,
      rationale,
    ) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:review:resolve",
          findingId,
          findingRevision,
          reviewId,
          resolutionAction,
          rationale,
        }),
        `${resolutionAction === "withdraw" ? "Withdrawing" : "Resolving"} the review blocker.`,
      );
    },
    createFindingRelationship(
      sourceFindingId,
      sourceRevision,
      targetFindingId,
      targetRevision,
      relationshipType,
      rationale,
    ) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:relationship:create",
          sourceFindingId,
          sourceRevision,
          targetFindingId,
          targetRevision,
          relationshipType,
          rationale,
        }),
        `Creating ${relationshipType.replaceAll("_", " ")} relationship.`,
      );
    },
    promoteFinding(findingId, findingRevision) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:promote",
          findingId,
          findingRevision,
        }),
        `Promoting eligible revision ${findingRevision}.`,
      );
    },
    withdrawFinding(findingId, findingRevision, rationale) {
      return sendTracked(
        (operationId, expectedRevision) => ({
          protocolVersion: INVESTIGATION_ROOM_PROTOCOL_VERSION,
          operationId,
          expectedRevision,
          type: "finding:withdraw",
          findingId,
          findingRevision,
          rationale,
        }),
        `Withdrawing revision ${findingRevision} while preserving its history.`,
      );
    },
    openFinding(findingId) {
      if (!canControlSharedState) {
        setDetail("Shared controls are locked by the current presenter.");
        return false;
      }
      return send({ ...baseMessage(), type: "finding:open", findingId });
    },
    clearError() {
      setDetail(status === "connected" ? "Connected." : detail);
    },
    clearOperationFeedback() {
      setOperationFeedback(null);
    },
  };
}

export { DEFAULT_LAYERS };
