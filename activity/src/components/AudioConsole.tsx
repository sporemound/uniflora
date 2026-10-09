import { useEffect, useId, useState } from "react";
import { useAudioState } from "../hooks/useAudioState";
import { audioController } from "../lib/audio-controller";
import "./AudioConsole.css";

export interface AudioConsoleProps {
  /**
   * Pass the current route or workspace identifier to stop active sounds when
   * navigation changes. The audio preference and mixer settings remain intact.
   */
  routeKey?: string;
  className?: string;
  hyphaTextOnly?: boolean;
}

function percent(volume: number): number {
  return Math.round(volume * 100);
}

export function AudioConsole({
  routeKey,
  className = "",
  hyphaTextOnly = false,
}: AudioConsoleProps) {
  const state = useAudioState();
  const [busy, setBusy] = useState(false);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(
    () => () => {
      audioController.stopForRouteChange();
    },
    [routeKey],
  );

  const activationLabel =
    state.enabled && state.contextState !== "running"
      ? "Resume audio"
      : "Enable optional audio";
  const stateLabel = !state.supported
    ? "Unavailable"
    : !state.enabled
      ? "Off"
      : state.contextState !== "running"
        ? "Paused"
        : state.muted
          ? "Muted"
          : "On";

  const activate = async () => {
    setBusy(true);
    try {
      if (state.enabled) {
        await audioController.resume();
      } else {
        await audioController.enable();
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className={`audio-console${className ? ` ${className}` : ""}`}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      data-audio-state={stateLabel.toLowerCase()}
    >
      <div className="audio-console__heading">
        <div>
          <span className="audio-console__eyebrow">Optional sound</span>
          <h2 id={titleId}>Audio console</h2>
        </div>
        <span className="audio-console__state" aria-label={`Audio ${stateLabel}`}>
          {stateLabel}
        </span>
      </div>

      <p id={descriptionId} className="audio-console__description">
        Every value, event, and instruction remains available visually and in
        text. Audio never changes scoring or access. No microphone is used.
        {hyphaTextOnly
          ? " Hypha chat replies appear as text in this preview."
          : " Hypha replies play here when the website conversation service is available."}
      </p>

      {!state.supported ? null : (
        <div className="audio-console__actions" aria-label="Audio controls">
          {!state.enabled || state.contextState !== "running" ? (
            <button type="button" onClick={activate} disabled={busy}>
              {busy ? "Starting…" : activationLabel}
            </button>
          ) : null}
          {state.enabled && state.contextState === "running" ? (
            <button
              type="button"
              onClick={() => {
                void audioController.setMuted(!state.muted);
              }}
            >
              {state.muted ? "Unmute" : "Mute"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => audioController.stopAll()}
            disabled={!state.analysisPlaying && !state.presentationPlaying}
          >
            Stop sound
          </button>
          {state.enabled ? (
            <button
              type="button"
              className="audio-console__quiet-action"
              onClick={() => {
                void audioController.disable();
              }}
            >
              Turn audio off
            </button>
          ) : null}
        </div>
      )}

      <details className="audio-console__mixer">
        <summary>Mixer levels</summary>
        <div className="audio-console__sliders">
          <VolumeControl
            id={`${titleId}-master`}
            label="Master"
            value={state.masterVolume}
            onChange={(value) => audioController.setMasterVolume(value)}
          />
          <VolumeControl
            id={`${titleId}-analysis`}
            label="Data sonification"
            value={state.analysisVolume}
            onChange={(value) => audioController.setAnalysisVolume(value)}
          />
          <VolumeControl
            id={`${titleId}-presentation`}
            label="Narration and cues"
            value={state.presentationVolume}
            onChange={(value) => audioController.setPresentationVolume(value)}
          />
        </div>
      </details>

      <p className="audio-console__status" role="status" aria-live="polite">
        {state.statusMessage}
      </p>
    </section>
  );
}

interface VolumeControlProps {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
}

function VolumeControl({
  id,
  label,
  value,
  onChange,
}: VolumeControlProps) {
  const valuePercent = percent(value);
  return (
    <label className="audio-console__slider" htmlFor={id}>
      <span>
        {label}
        <output htmlFor={id}>{valuePercent}%</output>
      </span>
      <input
        id={id}
        type="range"
        min="0"
        max="100"
        step="1"
        value={valuePercent}
        aria-valuetext={`${valuePercent} percent`}
        onChange={(event) => onChange(Number(event.currentTarget.value) / 100)}
      />
    </label>
  );
}
