import type { CollaborationRoomState } from "../lib/room";

function participantLabel(
  participantId: string | null,
  room: CollaborationRoomState,
): string {
  if (!participantId) return "Open control";
  return (
    room.snapshot?.participants.find(
      (participant) => participant.participantId === participantId,
    )?.displayName ?? "Disconnected presenter"
  );
}

export function CollaborationPanel({ room }: { room: CollaborationRoomState }) {
  const presenterName = participantLabel(
    room.snapshot?.presenterParticipantId ?? null,
    room,
  );

  return (
    <section className="collaboration-panel" aria-labelledby="collaboration-heading">
      <div className="section-heading-row collaboration-heading">
        <div>
          <p className="eyebrow">Phase 4 shared investigation room</p>
          <h2 id="collaboration-heading">Synchronized analysis session</h2>
        </div>
        <span className={`room-status ${room.status}`}>{room.status}</span>
      </div>

      <div className="room-summary">
        <dl>
          <div>
            <dt>Room</dt>
            <dd>{room.roomId}</dd>
          </div>
          <div>
            <dt>Presenter</dt>
            <dd>{presenterName}</dd>
          </div>
          <div>
            <dt>Connections</dt>
            <dd>{room.snapshot?.connectionCount ?? 0}</dd>
          </div>
          <div>
            <dt>Shared revision</dt>
            <dd>{room.snapshot?.view.revision ?? 0}</dd>
          </div>
        </dl>
        <p aria-live="polite">{room.detail}</p>
      </div>

      <div className="room-actions">
        {room.isPresenter ? (
          <button type="button" onClick={room.releasePresenter}>
            Release presenter control
          </button>
        ) : (
          <button
            type="button"
            onClick={room.claimPresenter}
            disabled={
              room.status !== "connected" ||
              room.snapshot?.presenterParticipantId !== null
            }
          >
            Present shared view
          </button>
        )}
        <button type="button" onClick={room.reconnect} disabled={room.status === "connecting"}>
          Reconnect
        </button>
      </div>

      <ul className="presence-list" aria-label="Connected participants">
        {(room.snapshot?.participants ?? []).map((participant) => {
          const isSelf = participant.participantId === room.participant?.participantId;
          const isPresenter =
            participant.participantId === room.snapshot?.presenterParticipantId;
          return (
            <li key={participant.participantId}>
              {participant.avatarUrl ? (
                <img src={participant.avatarUrl} alt="" />
              ) : (
                <span className="presence-avatar" aria-hidden="true">
                  {participant.displayName.slice(0, 1).toUpperCase()}
                </span>
              )}
              <div>
                <strong>{participant.displayName}</strong>
                <small>
                  {isSelf ? "this view" : "participant"}
                  {isPresenter ? " · presenter" : ""}
                </small>
              </div>
            </li>
          );
        })}
      </ul>

      {room.snapshot?.presenterParticipantId && !room.canControl ? (
        <p className="room-lock-note">
          The presenter currently controls the linked time range, layers, and time basis.
        </p>
      ) : null}
    </section>
  );
}
