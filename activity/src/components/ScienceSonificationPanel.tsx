import { useEffect, useId, useState } from "react";
import {
  audioController,
  type AudioSchedule,
  useAudioState,
} from "../lib/audio";
import type {
  ScienceSonificationLegend,
  ScienceSonificationSchedule,
} from "../lib/science-sonification";
import "./ScienceSonificationPanel.css";

interface ScienceSonificationPanelProps {
  schedule: ScienceSonificationSchedule;
  frameNumber: number;
}

function rangeText(
  range: ScienceSonificationLegend["sourceDomain"],
  unit: string,
): string {
  if (range === null) return `No finite ${unit} range`;
  const format = (value: number) =>
    Math.abs(value) >= 100
      ? value.toFixed(0)
      : Math.abs(value) >= 10
        ? value.toFixed(1)
        : value.toFixed(3);
  return `${format(range.minimum)}–${format(range.maximum)} ${unit}`;
}

function playableSchedule(
  schedule: ScienceSonificationSchedule,
  frameNumber: number,
): AudioSchedule {
  const visibleSummary = schedule.legends
    .map((legend) => legend.plainLanguage)
    .join(" ");
  return {
    label: `${schedule.title} · frame ${String(frameNumber).padStart(5, "0")}`,
    textAlternative: `${schedule.accessibility.textEquivalent} Captured frame ${frameNumber}. ${visibleSummary}`,
    tones: schedule.events
      .filter(
        (
          candidate,
        ): candidate is typeof candidate & {
          kind: "tone";
          frequencyHz: number;
          waveform: NonNullable<typeof candidate.waveform>;
        } =>
          candidate.kind === "tone" &&
          candidate.frequencyHz !== null &&
          candidate.waveform !== null,
      )
      .map((candidate) => ({
        startSeconds: candidate.startSeconds,
        durationSeconds: candidate.durationSeconds,
        frequencyHz: candidate.frequencyHz,
        level: candidate.gain,
        waveform: candidate.waveform,
      })),
  };
}

export function ScienceSonificationPanel({
  schedule,
  frameNumber,
}: ScienceSonificationPanelProps) {
  const audioState = useAudioState();
  const titleId = useId();
  const descriptionId = useId();
  const [busy, setBusy] = useState(false);
  const [lastPlayedFrame, setLastPlayedFrame] = useState<number | null>(null);

  useEffect(
    () => () => {
      audioController.stopAnalysis(undefined, false);
    },
    [schedule.facilityId, schedule.toolId],
  );

  const start = async () => {
    if (schedule.status !== "available") return;
    setBusy(true);
    try {
      let ready = false;
      if (!audioState.enabled) {
        ready = await audioController.enable();
      } else if (audioState.muted) {
        ready = await audioController.setMuted(false);
      } else if (audioState.contextState !== "running") {
        ready = await audioController.resume();
      } else {
        ready = true;
      }
      if (!ready) return;

      const played = audioController.playSchedule(
        playableSchedule(schedule, frameNumber),
      );
      if (played) {
        setLastPlayedFrame(frameNumber);
      }
    } finally {
      setBusy(false);
    }
  };

  const toneCount = schedule.events.filter(
    (candidate) => candidate.kind === "tone",
  ).length;
  const gapCount = schedule.events.length - toneCount;
  const playLabel =
    !audioState.enabled
      ? "Enable and play sonification"
      : audioState.analysisPlaying
        ? "Restart sonification"
        : "Play sonification";

  return (
    <section
      className="science-sonification"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <header>
        <div>
          <p className="eyebrow">Optional analytical audio</p>
          <h4 id={titleId}>{schedule.title}</h4>
        </div>
        <span className="science-sonification__availability">
          {schedule.status === "available"
            ? `${schedule.durationSeconds.toFixed(1)} s · ${toneCount} tones`
            : "No playable values"}
        </span>
      </header>

      <p id={descriptionId} className="science-sonification__boundary">
        The plot, values, units, and explanations are complete without sound.
        Listening never submits evidence, changes a result, or advances the game.
        Playback captures the displayed frame when selected.
      </p>

      {schedule.status === "available" ? (
        <div className="science-sonification__actions">
          <button type="button" onClick={() => void start()} disabled={busy}>
            {busy ? "Preparing audio…" : playLabel}
          </button>
          <button
            type="button"
            onClick={() => audioController.stopAnalysis()}
            disabled={!audioState.analysisPlaying}
          >
            Stop sonification
          </button>
          <span aria-live="polite">
            {lastPlayedFrame === null
              ? "Nothing has been played."
              : `Last audible snapshot: frame ${String(lastPlayedFrame).padStart(5, "0")}.`}
          </span>
        </div>
      ) : (
        <p className="science-sonification__unavailable" role="status">
          {schedule.unavailableReason}
        </p>
      )}

      <div className="science-sonification__status-key" aria-label="Sonification status key">
        {schedule.statusLegend.map((item) => (
          <span key={item.status} data-status={item.status}>
            <i aria-hidden="true" />
            <strong>{item.visibleLabel}</strong>
            <small>{item.scheduleTreatment}</small>
          </span>
        ))}
      </div>

      <details className="science-sonification__legend">
        <summary>
          Mapping and reproducibility record
          <span>
            {schedule.events.length} scheduled values
            {gapCount > 0 ? ` · ${gapCount} labeled gaps` : ""}
          </span>
        </summary>
        <div>
          {schedule.legends.map((legend) => (
            <article key={legend.id}>
              <header>
                <strong>{legend.label}</strong>
                <span>{legend.sourceStatus}</span>
              </header>
              <p>{legend.plainLanguage}</p>
              <dl>
                <div>
                  <dt>Source</dt>
                  <dd><code>{legend.sourceSeries}</code></dd>
                </div>
                <div>
                  <dt>Input range</dt>
                  <dd>{rangeText(legend.sourceDomain, legend.sourceUnit)}</dd>
                </div>
                <div>
                  <dt>Pitch</dt>
                  <dd>{legend.pitchMapping}</dd>
                </div>
                <div>
                  <dt>Time</dt>
                  <dd>{legend.timeMapping}</dd>
                </div>
                <div>
                  <dt>Gain</dt>
                  <dd>{legend.gainMapping}</dd>
                </div>
                <div>
                  <dt>Normalization</dt>
                  <dd>{legend.normalization}</dd>
                </div>
                <div>
                  <dt>Compression</dt>
                  <dd>{legend.timeCompression}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </details>
    </section>
  );
}
