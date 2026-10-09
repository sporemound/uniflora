import type {
  PublicActivitySnapshot,
  PublicActivitySnapshotV23,
  PublicActivitySnapshotV24,
  PublicStochasticMeasurement,
} from "../shared/public-state";
import { StrategicBoard } from "./StrategicBoard";

interface LiveCaseStatePanelProps {
  snapshot: PublicActivitySnapshot;
  archived?: boolean;
}

function measurementText(measurement: PublicStochasticMeasurement): string {
  const unit = measurement.unit ? ` ${measurement.unit}` : "";
  const uncertainty = measurement.uncertainty
    ? ` · ${measurement.uncertainty}`
    : "";
  return `${measurement.value}${unit}${uncertainty}`;
}

function LiveState({
  snapshot,
  archived,
}: {
  snapshot: PublicActivitySnapshotV23 | PublicActivitySnapshotV24;
  archived: boolean;
}) {
  const resolvedActions = snapshot.actions.filter(
    (action) => action.status === "completed",
  ).length;
  const examinedEvidence = snapshot.evidence.filter(
    (evidence) => evidence.status === "examined",
  ).length;

  return (
    <section
      className="live-case-state"
      aria-labelledby="live-case-state-heading"
      aria-live="polite"
    >
      <header className="live-case-state-header">
        <div>
          <p className="eyebrow">{archived ? "Captured investigation record" : "Authoritative investigation stream"}</p>
          <h3 id="live-case-state-heading">
            Sequence {snapshot.sequence} · {snapshot.casePhase}
          </h3>
          <p>{snapshot.nextRequirement}</p>
        </div>
        <dl className="live-case-state-summary">
          <div>
            <dt>Evidence</dt>
            <dd>
              {examinedEvidence}/{snapshot.evidence.length}
            </dd>
          </div>
          <div>
            <dt>Capabilities</dt>
            <dd>
              {resolvedActions}/{snapshot.actions.length}
            </dd>
          </div>
          <div>
            <dt>Routes</dt>
            <dd>
              {snapshot.completionRoutes.filter((route) => route.status === "complete").length}/
              {snapshot.completionRoutes.length}
            </dd>
          </div>
        </dl>
      </header>

      {snapshot.schemaVersion === "2.4.0" ? (
        <StrategicBoard snapshot={snapshot} />
      ) : null}

      <div className="live-case-state-grid">
        <section className="live-case-card" aria-labelledby="live-routes-heading">
          <div className="live-case-card-heading">
            <h4 id="live-routes-heading">Investigation routes</h4>
            <span>Complete any one</span>
          </div>
          <ul className="live-route-list">
            {snapshot.completionRoutes.map((route) => (
              <li key={route.id} data-status={route.status}>
                <div>
                  <strong>{route.title}</strong>
                  <span>{route.description}</span>
                  <small>{route.progress}</small>
                </div>
                <span className="live-status-label">{route.status}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="live-case-card" aria-labelledby="live-evidence-heading">
          <div className="live-case-card-heading">
            <h4 id="live-evidence-heading">Evidence register</h4>
            <span>Sequence-bound access</span>
          </div>
          <ul className="live-evidence-list">
            {snapshot.evidence.map((evidence) => (
              <li key={evidence.id} data-status={evidence.status}>
                <div>
                  <strong>{evidence.name}</strong>
                  <span>
                    {evidence.sourceClass.replaceAll("_", " ")} · {evidence.recordType}
                  </span>
                  {evidence.instrumentName ? <small>{evidence.instrumentName}</small> : null}
                </div>
                <span className="live-status-label">{evidence.status}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="live-case-card live-capability-card" aria-labelledby="live-capabilities-heading">
          <div className="live-case-card-heading">
            <h4 id="live-capabilities-heading">Current capabilities</h4>
            <span>Current investigation actions</span>
          </div>
          <ul className="live-capability-list">
            {snapshot.actions.map((action) => (
              <li key={action.id} data-status={action.status}>
                <div>
                  <strong>{action.title}</strong>
                  <span>{action.description}</span>
                  {action.strategicClass ? (
                    <small>
                      {action.strategicClass.replaceAll("_", " ")} · capacity {action.capacityCost}
                      {action.coordinationCost ? ` · coordination ${action.coordinationCost}` : ""}
                      {action.supporterCount ? ` · ${action.supporterCount} independent supporter` : ""}
                      {action.irreversible ? " · irreversible" : ""}
                    </small>
                  ) : null}
                  {action.variableOutcome ? (
                    <small>Variable observation · recorded after resolution</small>
                  ) : null}
                  {action.command ? (
                    <code>/v2 command · {action.command}</code>
                  ) : action.blockers.length ? (
                    <small>
                      Waiting on {action.blockers.map((item) => item.replace(":", " ")).join(", ")}
                    </small>
                  ) : null}
                </div>
                <span className="live-status-label">{action.status}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="live-case-card live-model-card" aria-labelledby="live-model-heading">
          <div className="live-case-card-heading">
            <h4 id="live-model-heading">Working model support</h4>
            <span>Evidence-weighted, not a conclusion</span>
          </div>
          {snapshot.stochasticProcesses.map((process) => (
            <article className="live-process" key={process.id}>
              <header>
                <div>
                  <strong>{process.title}</strong>
                  <span>{process.description}</span>
                </div>
                <span>
                  {process.observationCount} observation
                  {process.observationCount === 1 ? "" : "s"}
                </span>
              </header>
              {process.observedState ? (
                <p className="live-observed-state">Observed regime: {process.observedState}</p>
              ) : null}
              <ol className="live-model-support">
                {process.modelSupport.map((model) => (
                  <li key={model.modelId}>
                    <div>
                      <span>{model.label}</span>
                      <strong>{model.percent.toFixed(2)}%</strong>
                    </div>
                    <progress max={100} value={model.percent}>
                      {model.percent.toFixed(2)}%
                    </progress>
                  </li>
                ))}
              </ol>
            </article>
          ))}
          {snapshot.stochasticProcesses.length === 0 ? (
            <p>No variable process is active for this position.</p>
          ) : null}
        </section>
      </div>

      <section className="live-observation-ledger" aria-labelledby="live-observation-heading">
        <div className="live-case-card-heading">
          <h4 id="live-observation-heading">Observed sequence record</h4>
          <span>Latent states remain private unless explicitly disclosed</span>
        </div>
        {snapshot.recentObservations.length ? (
          <ol>
            {[...snapshot.recentObservations].reverse().map((observation) => (
              <li key={`${observation.sequence}-${observation.processId}-${observation.channelId}`}>
                <span className="live-sequence-token">{observation.sequence}</span>
                <div>
                  <strong>{observation.summary}</strong>
                  <span>
                    {observation.actionId.replaceAll("_", " ")} · {observation.channelId.replaceAll("_", " ")}
                  </span>
                  {observation.measurements.length ? (
                    <dl>
                      {observation.measurements.map((measurement) => (
                        <div key={measurement.key}>
                          <dt>{measurement.key.replaceAll("_", " ")}</dt>
                          <dd>{measurementText(measurement)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p>
            No stochastic observation has been committed in this position yet. The
            scientific publication below remains source context rather than a newly
            resolved instrument result.
          </p>
        )}
      </section>
    </section>
  );
}

export function LiveCaseStatePanel({ snapshot, archived = false }: LiveCaseStatePanelProps) {
  if (
    snapshot.schemaVersion !== "2.3.0" &&
    snapshot.schemaVersion !== "2.4.0"
  ) {
    return (
      <section className="live-case-state live-case-state-legacy" aria-live="polite">
        <p className="eyebrow">Authoritative investigation stream</p>
        <h3>Live case-state catalogue unavailable</h3>
        <p>
          This site is reading a legacy public projection. Position and network
          state remain visible, but evidence, routes, and variable observations require
          public schema 2.3 or 2.4.
        </p>
      </section>
    );
  }
  return <LiveState snapshot={snapshot} archived={archived} />;
}
