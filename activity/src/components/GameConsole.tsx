import { useCallback, useEffect, useState, type FormEvent } from "react";
import { CampaignEmblem } from "./CampaignEmblem";

interface GameResponse {
  accepted: boolean;
  code: string;
  summary: string;
  details: string[];
  sequence: number | null;
  projectionCurrent: boolean;
  suggestions: { command: string; label: string }[];
  player: {
    roleId: string | null;
    positionId: string;
    locationId: string | null;
  };
}

const ROLES = [
  {
    id: "evidence_investigator",
    title: "Evidence Investigator",
    description: "Collect records, inspect sources, and operate the instruments.",
  },
  {
    id: "systems_analyst",
    title: "Systems Analyst",
    description: "Connect evidence, test models, and reconstruct what happened.",
  },
  {
    id: "independent_reviewer",
    title: "Independent Reviewer",
    description: "Challenge assumptions, check provenance, and review conclusions.",
  },
] as const;

async function gameRequest(path: string, body?: Record<string, unknown>): Promise<GameResponse> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body ?? {}),
    cache: "no-store",
  });
  const value = await response.json().catch(() => null) as Partial<GameResponse> & { message?: string } | null;
  if (!response.ok || !value || typeof value.summary !== "string" ||
      !Array.isArray(value.details) || !value.player) {
    throw new Error(value?.message ?? `Game API returned ${response.status}.`);
  }
  value.suggestions = Array.isArray(value.suggestions) ? value.suggestions : [];
  return value as GameResponse;
}

export function GameConsole({ onProgress }: { onProgress: () => void | Promise<void> }) {
  const [state, setState] = useState<GameResponse | null>(null);
  const [command, setCommand] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setPending(true);
    try {
      setState(await gameRequest("/api/game/status"));
      setError(null);
      void onProgress();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load the game.");
    } finally {
      setPending(false);
    }
  }, [onProgress]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function run(text: string) {
    if (pending) return;
    setPending(true);
    try {
      const next = await gameRequest("/api/game/command", { text });
      setState(next);
      setError(next.accepted ? null : next.summary);
      if (next.accepted) {
        setCommand("");
        void onProgress();
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The command could not be sent.");
    } finally {
      setPending(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = command.trim();
    if (text) void run(text);
  }

  const role = ROLES.find((item) => item.id === state?.player.roleId);
  return (
    <section className="game-console" aria-labelledby="game-console-heading">
      <CampaignEmblem />
      <header className="game-console__header">
        <div>
          <p className="eyebrow">Authoritative campaign</p>
          <h2 id="game-console-heading">Your investigation</h2>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={pending}>Refresh game state</button>
      </header>
      {error ? <p className="warning" role="alert">{error}</p> : null}
      {state ? (
        <>
          <div className="game-console__status">
            <span>Position: <strong>{state.player.positionId.replaceAll("_", " ")}</strong></span>
            <span>Role: <strong>{role?.title ?? state.player.roleId ?? "Choose below"}</strong></span>
            <span>Event: <strong>{state.sequence ?? "—"}</strong></span>
          </div>
          {!state.player.roleId ? (
            <div className="game-console__roles">
              <p>Choose one role. It stays with you throughout the campaign.</p>
              <div className="game-console__role-list">
                {ROLES.map((item) => (
                  <button key={item.id} type="button" disabled={pending}
                    onClick={() => void run(`assign-role ${item.id}`)}>
                    <strong>{item.title}</strong><span>{item.description}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="game-console__result" aria-live="polite">
            <strong>{state.summary}</strong>
            {state.details.length ? <ul>{state.details.map((detail, index) => (
              <li key={`${index}-${detail}`}>{detail}</li>
            ))}</ul> : null}
            {!state.projectionCurrent ? <p>The public display is catching up with this game event.</p> : null}
          </div>
          {state.player.roleId && state.suggestions.length ? (
            <div className="game-console__suggestions">
              <strong>Available next steps</strong>
              <div>
                {state.suggestions.slice(0, 8).map((item) => (
                  <button key={item.command} type="button" disabled={pending}
                    onClick={() => void run(item.command)} title={item.command}>
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <form onSubmit={submit} className="game-console__command">
            <label htmlFor="game-command">Investigation command</label>
            <div>
              <input id="game-command" type="text" value={command} maxLength={1000}
                onChange={(event) => setCommand(event.target.value)}
                placeholder="Enter a command from the current position guide"
                disabled={pending} />
              <button type="submit" disabled={pending || !command.trim()}>Submit</button>
            </div>
          </form>
        </>
      ) : !error ? <p role="status">Loading your investigation…</p> : null}
    </section>
  );
}
