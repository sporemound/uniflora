import { useEffect, useMemo, useState } from "react";
import {
  FINDING_OBSERVATION_MAX_LENGTH,
  FINDING_TITLE_MAX_LENGTH,
  type RoomFinding,
  type RoomLayerState,
  type RoomScientificSelection,
} from "../shared/investigation-room";
import type { InvestigationRoomController } from "../hooks/useInvestigationRoom";
import { FindingReviewPanel } from "./FindingReviewPanel";

interface SharedFindingsPanelProps {
  room: InvestigationRoomController;
  selection: RoomScientificSelection | null;
  layers: RoomLayerState;
  selectedFindingId: string | null;
  onOpenFinding(finding: RoomFinding): void;
  onSelectedFindingChange(findingId: string | null): void;
  readOnly?: boolean;
}

function rangeLabel(selection: RoomScientificSelection): string {
  return `${selection.startSeconds.toFixed(3)}–${selection.endSeconds.toFixed(3)} s`;
}

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function SharedFindingsPanel({
  room,
  selection,
  layers,
  selectedFindingId,
  onOpenFinding,
  onSelectedFindingChange,
  readOnly = false,
}: SharedFindingsPanelProps) {
  const [title, setTitle] = useState("");
  const [observation, setObservation] = useState("");
  const [createOperationId, setCreateOperationId] = useState<string | null>(null);

  const localRoomHref = useMemo(() => {
    if (window.location.hostname !== "127.0.0.1" && window.location.hostname !== "localhost") {
      return null;
    }
    const url = new URL(window.location.href);
    url.searchParams.set("room", "phase4-lab");
    url.hash = "findings";
    return `${url.pathname}${url.search}${url.hash}`;
  }, []);

  const selectedFinding = useMemo(
    () => room.findings.find((finding) => finding.findingId === selectedFindingId) ?? null,
    [room.findings, selectedFindingId],
  );

  useEffect(() => {
    if (
      !createOperationId ||
      room.operationFeedback?.operationId !== createOperationId ||
      (room.operationFeedback.outcome !== "accepted" &&
        room.operationFeedback.outcome !== "duplicate")
    ) {
      return;
    }
    setCreateOperationId(null);
    setTitle("");
    setObservation("");
  }, [createOperationId, room.operationFeedback]);

  useEffect(() => {
    if (selectedFindingId && !selectedFinding) {
      onSelectedFindingChange(null);
    }
  }, [onSelectedFindingChange, selectedFinding, selectedFindingId]);

  const save = () => {
    if (readOnly) return;
    const cleanTitle = title.trim();
    const cleanObservation = observation.trim();
    if ((!cleanTitle && !cleanObservation) || !selection) return;
    const operationId = room.createFinding({
      title: cleanTitle,
      observation: cleanObservation,
      selection,
      layers,
    });
    if (operationId) setCreateOperationId(operationId);
  };

  return (
    <section
      className="shared-findings-panel"
      id="findings"
      tabIndex={-1}
      aria-labelledby="shared-findings-heading"
    >
      <div className="section-heading-row findings-heading">
        <div>
          <p className="eyebrow">Phase 4C persistent collaborative review</p>
          <h3 id="shared-findings-heading">Shared findings</h3>
        </div>
        <span className={`room-status ${room.status}`}>{readOnly ? "preview" : room.status}</span>
      </div>

      {readOnly || !room.roomId ? (
        <div className="findings-empty findings-room-entry">
          <h4>{readOnly ? "Review room participation pending" : "Enter a review room"}</h4>
          <p>
            {readOnly
              ? "Explore the evidence and scientific controls. Sign-in and a review room will be required to save, discuss, and promote shared findings."
              : "You can inspect the evidence without a room. A review room is required to save, discuss, and promote shared findings."}
          </p>
          {!readOnly && localRoomHref ? (
            <a className="findings-room-link" href={localRoomHref}>
              Enter local review room
            </a>
          ) : !readOnly ? (
            <p>Open a valid shared room link and sign in to join the discussion.</p>
          ) : null}
        </div>
      ) : (
        <>
          <div className="room-summary">
            <div>
              <span>Room</span>
              <strong>{room.roomId}</strong>
            </div>
            <div>
              <span>Participants</span>
              <strong>{room.snapshot?.participants.length ?? 0}</strong>
            </div>
            <div>
              <span>Room revision</span>
              <strong>{room.snapshot?.roomRevision ?? 0}</strong>
            </div>
          </div>

          <div className="presenter-controls">
            {room.isPresenter ? (
              <button type="button" onClick={room.releasePresenter}>Release presenter control</button>
            ) : (
              <button
                type="button"
                onClick={room.claimPresenter}
                disabled={room.status !== "connected" || room.snapshot?.presenterParticipantId !== null}
              >
                Claim presenter control
              </button>
            )}
            <span aria-live="polite">{room.detail}</span>
          </div>

          {room.operationFeedback ? (
            <div
              className={`room-operation-feedback ${room.operationFeedback.outcome}`}
              role={room.operationFeedback.outcome === "error" ? "alert" : "status"}
              aria-live={room.operationFeedback.outcome === "error" ? "assertive" : "polite"}
            >
              <span>{room.operationFeedback.message}</span>
              {room.operationFeedback.details?.currentFindingRevision !== undefined ? (
                <small>
                  Current finding revision:{" "}
                  {room.operationFeedback.details.currentFindingRevision}
                </small>
              ) : null}
              <button type="button" onClick={room.clearOperationFeedback}>
                Dismiss status
              </button>
            </div>
          ) : null}

          <form
            className="finding-editor"
            onSubmit={(event) => {
              event.preventDefault();
              save();
            }}
          >
            <div className="finding-editor-heading">
              <strong>Save current selection as an initial draft revision</strong>
              {(title || observation) && !createOperationId ? (
                <button
                  type="button"
                  onClick={() => {
                    setTitle("");
                    setObservation("");
                  }}
                >
                  Clear
                </button>
              ) : null}
            </div>
            <label>
              <span>Title</span>
              <input
                value={title}
                maxLength={FINDING_TITLE_MAX_LENGTH}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Observed timing discontinuity"
              />
            </label>
            <label>
              <span>Observation</span>
              <textarea
                value={observation}
                maxLength={FINDING_OBSERVATION_MAX_LENGTH}
                onChange={(event) => setObservation(event.target.value)}
                placeholder="Describe what the selected interval appears to show."
                rows={4}
              />
            </label>
            <div className="finding-editor-footer">
              <span>
                {selection
                  ? `${selection.sourceView} · ${rangeLabel(selection)} · ${selection.timeBasis}`
                  : "Select a waveform or spectrogram interval first"}
              </span>
              <button
                type="submit"
                disabled={
                  room.status !== "connected" ||
                  room.pendingOperationIds.length > 0 ||
                  !selection ||
                  (!title.trim() && !observation.trim())
                }
              >
                {createOperationId && room.pendingOperationIds.includes(createOperationId)
                  ? "Saving finding…"
                  : "Create finding"}
              </button>
            </div>
          </form>

          <p className="phase4b-compatibility-note">
            The compatible Phase 4B protocol labels <q>Edit shared finding</q> and{" "}
            <q>Delete</q> now create an immutable revision or a visible withdrawal. Phase 4C never
            overwrites or erases revision history.
          </p>

          {room.findings.length === 0 ? (
            <p className="findings-empty">No findings have been saved in this room.</p>
          ) : (
            <div className="finding-review-layout">
              <ul className="findings-list" aria-label="Shared finding records">
                {room.findings.map((finding) => (
                  <li
                    key={finding.findingId}
                    className={[
                      selectedFindingId === finding.findingId ? "selected" : "",
                      `lifecycle-${finding.lifecycleState}`,
                    ].filter(Boolean).join(" ")}
                  >
                    <button
                      type="button"
                      className="finding-open"
                      aria-pressed={selectedFindingId === finding.findingId}
                      aria-label={`Inspect ${finding.title || "untitled finding"}, current revision ${finding.currentRevision}, ${finding.lifecycleState.replaceAll("_", " ")}`}
                      onClick={() => onSelectedFindingChange(finding.findingId)}
                    >
                      <strong>{finding.title || "Untitled finding"}</strong>
                      <span>{finding.observation || "No observation text."}</span>
                      <small>
                        {finding.creatorDisplayName} · {finding.selection.sourceView} ·{" "}
                        {rangeLabel(finding.selection)}
                      </small>
                      <small>
                        revision {finding.currentRevision} ·{" "}
                        {finding.lifecycleState.replaceAll("_", " ")} · updated{" "}
                        {dateLabel(finding.updatedAt)}
                      </small>
                    </button>
                  </li>
                ))}
              </ul>
              {selectedFinding ? (
                <FindingReviewPanel
                  room={room}
                  finding={selectedFinding}
                  onOpenFinding={onOpenFinding}
                />
              ) : (
                <section className="finding-review-placeholder" aria-live="polite">
                  <h4>Inspect a finding</h4>
                  <p>
                    Choose a finding to view immutable revisions, exact-revision reviews,
                    relationships, promotion blockers, and sanitized conclusions.
                  </p>
                </section>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
