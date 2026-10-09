import type { PublicActivitySnapshotV24 } from "../shared/public-state";

interface StrategicBoardProps {
  snapshot: PublicActivitySnapshotV24;
}

function ratio(value: number, minimum: number, maximum: number): number {
  if (maximum <= minimum) return 0;
  return ((value - minimum) / (maximum - minimum)) * 100;
}

export function StrategicBoard({ snapshot }: StrategicBoardProps) {
  const board = snapshot.strategicBoard;

  return (
    <section className="strategic-board" aria-labelledby="strategic-board-heading">
      <div className="live-case-card-heading">
        <div>
          <p className="eyebrow">Shared operation board</p>
          <h4 id="strategic-board-heading">Strategic state</h4>
        </div>
        {board ? (
          <span>
            Round {board.roundIndex}/{board.maxRounds}
          </span>
        ) : (
          <span>Not active</span>
        )}
      </div>

      <div className="strategic-track-grid">
        {snapshot.campaignTracks.map((track) => (
          <article key={track.id} className="strategic-track">
            <div>
              <strong>{track.label}</strong>
              <span>
                {track.value}/{track.maximum}
              </span>
            </div>
            <progress
              max={100}
              value={ratio(track.value, track.minimum, track.maximum)}
            >
              {track.value}
            </progress>
          </article>
        ))}
      </div>

      {board ? (
        <>
          <dl className="strategic-position-grid">
            <div>
              <dt>Capacity</dt>
              <dd>
                {board.capacityRemaining}/{board.capacityPerRound}
              </dd>
            </div>
            <div>
              <dt>Coordination</dt>
              <dd>
                {board.coordination}/{board.coordinationMaximum}
              </dd>
            </div>
            <div>
              <dt>Escalation</dt>
              <dd>
                {board.escalation}/{board.escalationMaximum}
              </dd>
            </div>
            <div>
              <dt>{board.localResource.title}</dt>
              <dd>
                {board.localResource.value}/{board.localResource.maximum}
              </dd>
            </div>
          </dl>

          {board.forcedReview ? (
            <p className="strategic-warning">
              Final operation round closed. The position is now in fail-forward review.
            </p>
          ) : null}

          <div className="strategic-board-columns">
            <section>
              <h5>Active conditions</h5>
              {board.conditions.length ? (
                <ul className="strategic-token-list">
                  {board.conditions.map((condition) => (
                    <li key={condition.id}>
                      <strong>{condition.label}</strong>
                      <span>{condition.duration.replaceAll("_", " ")}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No preparation condition is active.</p>
              )}
            </section>

            <section>
              <h5>Major-operation proposals</h5>
              {board.proposals.length ? (
                <ul className="strategic-proposal-list">
                  {board.proposals.map((proposal) => (
                    <li key={proposal.proposalId}>
                      <strong>{proposal.actionId.replaceAll("_", " ")}</strong>
                      <span>
                        Support {proposal.currentSupporterCount}/
                        {proposal.requiredSupporterCount}
                      </span>
                      <code>/v2 command · {proposal.command}</code>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No major operation is awaiting support.</p>
              )}
            </section>
          </div>
        </>
      ) : (
        <p>The operation board opens with the first strategic capability.</p>
      )}

      {snapshot.campaignModifiers.length ? (
        <div className="strategic-carryover">
          <h5>Campaign carryover</h5>
          <ul className="strategic-token-list">
            {snapshot.campaignModifiers.map((modifier) => (
              <li key={modifier.id}>
                <strong>{modifier.label}</strong>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {snapshot.strategicOutcomes.length ? (
        <details className="strategic-outcome-history">
          <summary>Position outcome history</summary>
          <ol>
            {snapshot.strategicOutcomes.map((outcome) => (
              <li key={outcome.positionId} data-grade={outcome.grade}>
                <strong>{outcome.positionId.replaceAll("_", " ")}</strong>
                <span>{outcome.grade}</span>
                <small>
                  integrity {outcome.caseIntegrity} · trust {outcome.institutionalTrust} ·
                  escalation {outcome.escalation}
                </small>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}
