import { useEffect, useRef, useState } from "react";
import {
  loadPublicRecordPage,
  loadPublicRevisionSnapshot,
  PublicRecordError,
  type PublicRecordEntry,
  type SnapshotOrigin,
} from "../lib/api";
import type { PublicActivitySnapshot } from "../shared/public-state";
import "./PublicRecordTimeline.css";

type RecordStatus = "checking" | "ready" | "pending" | "error";

function displayTimestamp(value: string): string {
  const time = Date.parse(value);
  return Number.isFinite(time) ? new Date(time).toLocaleString() : value;
}

function RevisionSnapshot({
  entry,
  cache,
}: {
  entry: PublicRecordEntry;
  cache: Map<number, PublicActivitySnapshot>;
}) {
  const [snapshot, setSnapshot] = useState<PublicActivitySnapshot | null>(
    () => cache.get(entry.revision) ?? null,
  );
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const saved = cache.get(entry.revision);
    if (saved) {
      setSnapshot(saved);
      return;
    }
    const controller = new AbortController();
    setError("");
    void loadPublicRevisionSnapshot(entry, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        cache.set(entry.revision, result);
        setSnapshot(result);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not load this published revision.");
        }
      });
    return () => controller.abort();
  }, [cache, entry, retry]);

  if (error) {
    return (
      <div className="public-record-timeline__detail" role="alert">
        <p>{error}</p>
        <button type="button" onClick={() => setRetry((current) => current + 1)}>Retry revision</button>
      </div>
    );
  }
  if (!snapshot) {
    return <p className="public-record-timeline__detail" role="status">Loading complete public state at revision {entry.revision}…</p>;
  }

  const caseState = snapshot.schemaVersion === "2.3.0" || snapshot.schemaVersion === "2.4.0"
    ? snapshot : null;
  return (
    <div className="public-record-timeline__detail">
      <h3>Public state at revision {snapshot.revision}</h3>
      <p><strong>Position:</strong> {snapshot.positionTitle} · <strong>Next requirement:</strong> {snapshot.nextRequirement}</p>
      <dl className="public-record-timeline__metrics">
        <div><dt>Active assignments</dt><dd>{snapshot.metrics.activeAssignments}</dd></div>
        <div><dt>Completed artifacts</dt><dd>{snapshot.metrics.completedArtifacts}</dd></div>
        <div><dt>Contradictions</dt><dd>{snapshot.metrics.unresolvedContradictions}</dd></div>
        <div><dt>Awaiting verification</dt><dd>{snapshot.metrics.awaitingVerification}</dd></div>
      </dl>
      <div className="public-record-timeline__detail-grid">
        <section>
          <h4>Roster at this revision</h4>
          {snapshot.assignments.length ? <ul>{snapshot.assignments.map((assignment) => (
            <li key={assignment.assignmentId}>
              {assignment.workingName} · {assignment.roleTitle} · {assignment.status}
            </li>
          ))}</ul> : <p>No assignments recorded.</p>}
        </section>
        <section>
          <h4>Facility state</h4>
          {snapshot.locations.length ? <ul>{snapshot.locations.map((location) => (
            <li key={location.id}>{location.name} · {location.status}</li>
          ))}</ul> : <p>No facilities recorded.</p>}
        </section>
        {caseState ? (
          <>
            <section>
              <h4>Evidence register</h4>
              {caseState.evidence.length ? <ul>{caseState.evidence.map((evidence) => (
                <li key={evidence.id}>{evidence.name} · {evidence.status}</li>
              ))}</ul> : <p>No evidence recorded.</p>}
            </section>
            <section>
              <h4>Actions</h4>
              {caseState.actions.length ? <ul>{caseState.actions.map((action) => (
                <li key={action.id}>{action.title} · {action.status}</li>
              ))}</ul> : <p>No actions recorded.</p>}
            </section>
            <section>
              <h4>Observations</h4>
              {caseState.recentObservations.length ? <ol>{caseState.recentObservations.map((observation) => (
                <li key={`${observation.processId}:${observation.sequence}`}>
                  Sequence {observation.sequence}: {observation.summary}
                </li>
              ))}</ol> : <p>No observations recorded.</p>}
            </section>
          </>
        ) : null}
        {snapshot.latestPublication ? (
          <section>
            <h4>Publication</h4>
            <p><strong>{snapshot.latestPublication.title}.</strong> {snapshot.latestPublication.finding}</p>
            <p><strong>Limitation:</strong> {snapshot.latestPublication.limitation}</p>
          </section>
        ) : null}
      </div>
      <details className="public-record-timeline__full-data">
        <summary>View the complete published state data</summary>
        <pre>{JSON.stringify(snapshot, null, 2)}</pre>
      </details>
    </div>
  );
}

export function PublicRecordTimeline({
  origin,
  archiveUpdatedAt,
}: {
  origin: SnapshotOrigin | "checking";
  archiveUpdatedAt: string;
}) {
  const [entries, setEntries] = useState<PublicRecordEntry[]>([]);
  const [status, setStatus] = useState<RecordStatus>("checking");
  const [detail, setDetail] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [lastChecked, setLastChecked] = useState<string | null>(null);
  const [expandedRevision, setExpandedRevision] = useState<number | null>(null);
  const refreshRef = useRef<() => void>(() => undefined);
  const revisionCacheRef = useRef(new Map<number, PublicActivitySnapshot>());

  useEffect(() => {
    let active = true;
    let busy = false;
    let cursor = 0;
    let controller: AbortController | null = null;
    setEntries([]);
    setExpandedRevision(null);
    revisionCacheRef.current.clear();
    setStatus("checking");
    setHasMore(false);
    setLastChecked(null);

    const refresh = async () => {
      if (!active || busy || document.hidden) return;
      busy = true;
      controller = new AbortController();
      try {
        let more = false;
        // A page is at most 100 entries. Continue through the backlog in
        // bounded batches; the next poll or the button resumes at the cursor.
        for (let pageCount = 0; pageCount < 8; pageCount += 1) {
          const page = await loadPublicRecordPage(cursor, controller.signal);
          if (!active || controller.signal.aborted) return;
          if (page.entries.length > 0) {
            cursor = page.entries[page.entries.length - 1].revision;
            setEntries((current) => [...current, ...page.entries]);
          }
          more = page.hasMore;
          if (!more) break;
        }
        setHasMore(more);
        setStatus("ready");
        setDetail("");
        setLastChecked(new Date().toISOString());
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        if (error instanceof PublicRecordError && (error.status === 503 || error.status === 404)) {
          setStatus("pending");
          setDetail("The live public record is being connected.");
        } else {
          setStatus("error");
          setDetail(error instanceof Error ? error.message : "Could not refresh the public record.");
        }
      } finally {
        busy = false;
        controller = null;
      }
    };

    refreshRef.current = () => { void refresh(); };
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 10_000);
    const refreshWhenVisible = () => {
      if (!document.hidden) void refresh();
    };
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      refreshRef.current = () => undefined;
    };
  }, []);

  const newestFirst = [...entries].reverse();
  const label = origin === "published"
    ? "Live published state"
    : origin === "archived"
      ? "Captured case archive"
      : origin === "checking"
        ? "Checking public state"
        : "Live state unavailable";

  return (
    <section className="public-record-timeline" aria-labelledby="public-record-heading">
      <header className="public-record-timeline__header">
        <div>
          <p className="eyebrow">Shared campaign history</p>
          <h2 id="public-record-heading">Public record</h2>
        </div>
        <span className={`public-record-timeline__source ${origin}`}>{label}</span>
      </header>
      <p className="public-record-timeline__intro">
        Published game revisions are readable by everyone with this link. This record checks
        for new entries every 10 seconds and when you return to the page. Open a revision to
        inspect the complete public state at that point. Guest questions and Hypha replies
        appear in the <a href="#hypha-chat">public Hypha chat</a> when that log is available.
      </p>
      {origin === "archived" ? (
        <p className="public-record-timeline__archive" role="status">
          The case shown elsewhere on this page is a captured archive
          {archiveUpdatedAt ? ` from ${displayTimestamp(archiveUpdatedAt)}` : ""}.
          Its entries do not represent new live activity.
        </p>
      ) : null}
      {status === "pending" || status === "error" ? (
        <p className="public-record-timeline__status" role={status === "error" ? "alert" : "status"}>
          {detail}
        </p>
      ) : null}
      {status === "checking" ? <p role="status">Checking the live record…</p> : null}
      {newestFirst.length > 0 ? (
        <ol className="public-record-timeline__entries" aria-label="Published revisions, newest first">
          {newestFirst.map((entry) => (
            <li key={entry.revision}>
              <div className="public-record-timeline__entry-head">
                <strong>Revision {entry.revision} · {entry.positionTitle}</strong>
                <time dateTime={entry.updatedAt}>{displayTimestamp(entry.updatedAt)}</time>
              </div>
              {entry.observationSummary ? <p>{entry.observationSummary}</p> : null}
              <small>
                {entry.sequence === null ? "Sequence not recorded" : `Sequence ${entry.sequence}`}
                {" · "}{entry.positionId}{" · "}State {entry.stateHeadHash}
              </small>
              <button
                className="public-record-timeline__expand"
                type="button"
                aria-expanded={expandedRevision === entry.revision}
                onClick={() => setExpandedRevision((current) =>
                  current === entry.revision ? null : entry.revision)}
              >
                {expandedRevision === entry.revision ? "Hide complete state" : "View complete state"}
              </button>
              {expandedRevision === entry.revision ? (
                <RevisionSnapshot entry={entry} cache={revisionCacheRef.current} />
              ) : null}
            </li>
          ))}
        </ol>
      ) : status === "ready" ? (
        <p className="public-record-timeline__empty">No live revisions have been published yet.</p>
      ) : null}
      <div className="public-record-timeline__footer">
        <span>{entries.length} published {entries.length === 1 ? "revision" : "revisions"} loaded
          {lastChecked ? ` · Last checked ${displayTimestamp(lastChecked)}` : ""}
          {hasMore ? " · Catching up with the record" : ""}
        </span>
        <button type="button" onClick={() => refreshRef.current()} disabled={status === "checking"}>
          {hasMore ? "Load more entries" : "Check now"}
        </button>
      </div>
    </section>
  );
}
