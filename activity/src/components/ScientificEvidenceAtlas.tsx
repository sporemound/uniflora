import { useId, useMemo, type CSSProperties } from "react";
import type {
  ActivityEventMarker,
  ActivityScientificDataset,
  ScientificBundle,
} from "../shared/scientific-visualization";
import "./ScientificEvidenceAtlas.css";

interface ScientificEvidenceAtlasProps {
  bundle: ScientificBundle;
  compact?: boolean;
}

interface SpectrumPoint {
  frequencyHz: number;
  averagePowerDb: number;
  linearPower: number;
}

interface QualityShare {
  quality: string;
  count: number;
  fraction: number;
}

const SPECTRUM_WIDTH = 620;
const SPECTRUM_HEIGHT = 250;
const SPECTRUM_LEFT = 54;
const SPECTRUM_RIGHT = 604;
const SPECTRUM_TOP = 18;
const SPECTRUM_BOTTOM = 214;
const EVENT_WIDTH = 620;
const EVENT_LEFT = 26;
const EVENT_RIGHT = 594;

const QUALITY_COLORS: Record<string, string> = {
  valid: "#55c8b5",
  degraded: "#e0ad64",
  excluded: "#d36f69",
  invalid: "#d36f69",
  missing: "#8b82aa",
};

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function scale(
  value: number,
  domainMinimum: number,
  domainMaximum: number,
  outputMinimum: number,
  outputMaximum: number,
): number {
  if (domainMaximum === domainMinimum) {
    return (outputMinimum + outputMaximum) / 2;
  }
  const fraction = (value - domainMinimum) / (domainMaximum - domainMinimum);
  return outputMinimum + fraction * (outputMaximum - outputMinimum);
}

function averageSpectrum(dataset: ActivityScientificDataset): SpectrumPoint[] {
  return dataset.spectrogram.frequencyHz.flatMap((frequencyHz, frequencyIndex) => {
    const row = dataset.spectrogram.powerDb[frequencyIndex] ?? [];
    if (row.length === 0) return [];
    const linearPower =
      row.reduce((sum, powerDb) => sum + 10 ** (powerDb / 10), 0) / row.length;
    return [{
      frequencyHz,
      linearPower,
      averagePowerDb: 10 * Math.log10(Math.max(linearPower, Number.MIN_VALUE)),
    }];
  });
}

function qualityShares(dataset: ActivityScientificDataset): QualityShare[] {
  const counts = new Map<string, number>();
  for (const sample of dataset.waveform.samples) {
    counts.set(sample.quality, (counts.get(sample.quality) ?? 0) + 1);
  }
  const total = Math.max(1, dataset.waveform.samples.length);
  return [...counts.entries()]
    .map(([quality, count]) => ({ quality, count, fraction: count / total }))
    .sort((left, right) => {
      if (left.quality === "valid") return -1;
      if (right.quality === "valid") return 1;
      return right.count - left.count || left.quality.localeCompare(right.quality);
    });
}

function eventPosition(
  event: ActivityEventMarker,
  startSeconds: number,
  endSeconds: number,
): number {
  return scale(
    event.timeSeconds,
    startSeconds,
    endSeconds,
    EVENT_LEFT,
    EVENT_RIGHT,
  );
}

function spectralSummary(points: SpectrumPoint[]) {
  if (points.length === 0) {
    return {
      minimumDb: 0,
      maximumDb: 0,
      dominantFrequencyHz: 0,
      centroidHz: 0,
      bandwidthHz: 0,
    };
  }

  const minimumDb = Math.min(...points.map(({ averagePowerDb }) => averagePowerDb));
  const maximumDb = Math.max(...points.map(({ averagePowerDb }) => averagePowerDb));
  const dominant = points.reduce((best, point) =>
    point.linearPower > best.linearPower ? point : best,
  );
  const totalPower = points.reduce((sum, point) => sum + point.linearPower, 0);
  const centroidHz =
    totalPower === 0
      ? 0
      : points.reduce(
        (sum, point) => sum + point.frequencyHz * point.linearPower,
        0,
      ) / totalPower;
  const variance =
    totalPower === 0
      ? 0
      : points.reduce(
        (sum, point) =>
          sum + (point.frequencyHz - centroidHz) ** 2 * point.linearPower,
        0,
      ) / totalPower;

  return {
    minimumDb,
    maximumDb,
    dominantFrequencyHz: dominant.frequencyHz,
    centroidHz,
    bandwidthHz: Math.sqrt(Math.max(0, variance)),
  };
}

function spectrumPath(
  points: SpectrumPoint[],
  minimumDb: number,
  maximumDb: number,
): string {
  const maximumFrequency = Math.max(1, ...points.map(({ frequencyHz }) => frequencyHz));
  return points
    .map((point, index) => {
      const x = scale(
        point.averagePowerDb,
        minimumDb,
        maximumDb,
        SPECTRUM_LEFT,
        SPECTRUM_RIGHT,
      );
      const y = scale(
        point.frequencyHz,
        0,
        maximumFrequency,
        SPECTRUM_BOTTOM,
        SPECTRUM_TOP,
      );
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function percent(value: number): string {
  const percentage = value * 100;
  const needsDecimal =
    (percentage > 0 && percentage < 1) ||
    (percentage > 99 && percentage < 100);
  return `${percentage.toFixed(needsDecimal ? 1 : 0)}%`;
}

export function ScientificEvidenceAtlas({
  bundle,
  compact = false,
}: ScientificEvidenceAtlasProps) {
  const titleId = useId();
  const descriptionId = useId();
  const { dataset, publication } = bundle;
  const spectrum = useMemo(() => averageSpectrum(dataset), [dataset]);
  const summary = useMemo(() => spectralSummary(spectrum), [spectrum]);
  const qualities = useMemo(() => qualityShares(dataset), [dataset]);
  const spectrumLine = useMemo(
    () => spectrumPath(spectrum, summary.minimumDb, summary.maximumDb),
    [spectrum, summary.maximumDb, summary.minimumDb],
  );
  const projectionFraction =
    dataset.waveform.fullSampleCount === 0
      ? 0
      : dataset.waveform.publishedSampleCount / dataset.waveform.fullSampleCount;
  const degradedFraction = qualities
    .filter(({ quality }) => quality !== "valid")
    .reduce((sum, item) => sum + item.fraction, 0);
  const validFraction = qualities.length === 0 ? 0 : 1 - degradedFraction;
  const maximumFrequency = Math.max(
    0,
    ...dataset.spectrogram.frequencyHz,
  );
  const receiptInRange =
    dataset.waveform.startSeconds <= 0 && dataset.waveform.endSeconds >= 0;
  const receiptX = scale(
    0,
    dataset.waveform.startSeconds,
    dataset.waveform.endSeconds,
    EVENT_LEFT,
    EVENT_RIGHT,
  );
  const gridValues = Array.from({ length: 5 }, (_, index) =>
    summary.minimumDb +
    ((summary.maximumDb - summary.minimumDb) * index) / 4,
  );

  return (
    <section
      className={`scientific-atlas${compact ? " scientific-atlas--compact" : ""}`}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <header className="scientific-atlas__heading">
        <div>
          <p className="scientific-atlas__eyebrow">Published evidence atlas</p>
          <h3 id={titleId}>Signal structure at a glance</h3>
          <p id={descriptionId}>
            Deterministic browser summaries of the sanitized publication for{" "}
            <strong>{dataset.institutionId}</strong>. Values below are derived only
            from the public projection, not from private or authoritative records.
          </p>
        </div>
        <span className="scientific-atlas__stamp">
          {dataset.spectrogram.frequencyHz.length} ×{" "}
          {dataset.spectrogram.timeSeconds.length} spectral cells
        </span>
      </header>

      <dl className="scientific-atlas__metrics">
        <div>
          <dt>Dominant bin</dt>
          <dd>{summary.dominantFrequencyHz.toFixed(1)} Hz</dd>
        </div>
        <div>
          <dt>Spectral centroid</dt>
          <dd>{summary.centroidHz.toFixed(1)} Hz</dd>
        </div>
        <div>
          <dt>RMS bandwidth</dt>
          <dd>{summary.bandwidthHz.toFixed(1)} Hz</dd>
        </div>
        <div>
          <dt>Projection density</dt>
          <dd>{percent(projectionFraction)}</dd>
        </div>
      </dl>

      <div className="scientific-atlas__grid">
        <article className="scientific-atlas__card scientific-atlas__spectrum">
          <div className="scientific-atlas__card-heading">
            <div>
              <span>Frequency-domain profile</span>
              <h4>Time-averaged power density</h4>
            </div>
            <small>linear mean → dB/Hz</small>
          </div>
          <svg
            viewBox={`0 0 ${SPECTRUM_WIDTH} ${SPECTRUM_HEIGHT}`}
            role="img"
            aria-label={`Average spectral power from 0 to ${maximumFrequency.toFixed(
              1,
            )} hertz; strongest published bin ${summary.dominantFrequencyHz.toFixed(
              1,
            )} hertz`}
          >
            <rect
              x={SPECTRUM_LEFT}
              y={SPECTRUM_TOP}
              width={SPECTRUM_RIGHT - SPECTRUM_LEFT}
              height={SPECTRUM_BOTTOM - SPECTRUM_TOP}
              className="scientific-atlas__plot-background"
            />
            {gridValues.map((value, index) => {
              const x = scale(
                value,
                summary.minimumDb,
                summary.maximumDb,
                SPECTRUM_LEFT,
                SPECTRUM_RIGHT,
              );
              return (
                <g key={`${index}-${value}`}>
                  <line
                    x1={x}
                    x2={x}
                    y1={SPECTRUM_TOP}
                    y2={SPECTRUM_BOTTOM}
                    className="scientific-atlas__grid-line"
                  />
                  <text
                    x={x}
                    y={SPECTRUM_BOTTOM + 22}
                    textAnchor="middle"
                    className="scientific-atlas__axis-label"
                  >
                    {value.toFixed(0)}
                  </text>
                </g>
              );
            })}
            {[0, maximumFrequency / 2, maximumFrequency].map((frequency, index) => {
              const y = scale(
                frequency,
                0,
                Math.max(1, maximumFrequency),
                SPECTRUM_BOTTOM,
                SPECTRUM_TOP,
              );
              return (
                <g key={`${index}-${frequency}`}>
                  <line
                    x1={SPECTRUM_LEFT}
                    x2={SPECTRUM_RIGHT}
                    y1={y}
                    y2={y}
                    className="scientific-atlas__grid-line"
                  />
                  <text
                    x={SPECTRUM_LEFT - 9}
                    y={y + 4}
                    textAnchor="end"
                    className="scientific-atlas__axis-label"
                  >
                    {frequency.toFixed(0)}
                  </text>
                </g>
              );
            })}
            {spectrum.length > 0 ? (
              <>
                <path d={spectrumLine} className="scientific-atlas__spectrum-glow" />
                <path d={spectrumLine} className="scientific-atlas__spectrum-line" />
              </>
            ) : (
              <text
                x={(SPECTRUM_LEFT + SPECTRUM_RIGHT) / 2}
                y={(SPECTRUM_TOP + SPECTRUM_BOTTOM) / 2}
                textAnchor="middle"
                className="scientific-atlas__axis-title"
              >
                No spectral bins published
              </text>
            )}
            <text
              x={(SPECTRUM_LEFT + SPECTRUM_RIGHT) / 2}
              y={SPECTRUM_HEIGHT - 3}
              textAnchor="middle"
              className="scientific-atlas__axis-title"
            >
              Average power (dB/Hz)
            </text>
            <text
              x={13}
              y={(SPECTRUM_TOP + SPECTRUM_BOTTOM) / 2}
              textAnchor="middle"
              className="scientific-atlas__axis-title scientific-atlas__axis-title--vertical"
            >
              Hz
            </text>
          </svg>
        </article>

        <article className="scientific-atlas__card scientific-atlas__quality">
          <div className="scientific-atlas__card-heading">
            <div>
              <span>Projection health</span>
              <h4>Published sample quality</h4>
            </div>
            <small>
              {dataset.waveform.publishedSampleCount.toLocaleString()} retained
            </small>
          </div>

          <div
            className="scientific-atlas__quality-ring"
            style={{
              "--quality-valid": `${validFraction * 360}deg`,
            } as CSSProperties}
            role="img"
            aria-label={`${percent(validFraction)} of retained projection samples are marked valid`}
          >
            <div>
              <strong>{percent(validFraction)}</strong>
              <span>valid</span>
            </div>
          </div>

          <div
            className="scientific-atlas__quality-bar"
            role="img"
            aria-label={qualities
              .map(({ quality, fraction }) => `${quality} ${percent(fraction)}`)
              .join(", ")}
          >
            {qualities.map(({ quality, fraction }) => (
              <span
                key={quality}
                style={{
                  width: `${fraction * 100}%`,
                  background: QUALITY_COLORS[quality] ?? "#78909c",
                }}
              />
            ))}
          </div>
          <ul className="scientific-atlas__legend">
            {qualities.map(({ quality, count, fraction }) => (
              <li key={quality}>
                <i
                  style={{
                    background: QUALITY_COLORS[quality] ?? "#78909c",
                  }}
                />
                <span>{quality}</span>
                <strong>{count.toLocaleString()}</strong>
                <small>{percent(fraction)}</small>
              </li>
            ))}
          </ul>
          <p>
            Projection density reflects extrema-preserving public reduction:{" "}
            {dataset.waveform.publishedSampleCount.toLocaleString()} of{" "}
            {dataset.waveform.fullSampleCount.toLocaleString()} source samples.
          </p>
        </article>
      </div>

      <article className="scientific-atlas__card scientific-atlas__events">
        <div className="scientific-atlas__card-heading">
          <div>
            <span>Temporal structure</span>
            <h4>Event chronology with uncertainty</h4>
          </div>
          <small>relative to verified receipt</small>
        </div>
        <svg
          viewBox={`0 0 ${EVENT_WIDTH} 118`}
          role="img"
          aria-label={`${dataset.events.length} publication events from ${dataset.waveform.startSeconds.toFixed(
            1,
          )} to ${dataset.waveform.endSeconds.toFixed(1)} seconds`}
        >
          <line
            x1={EVENT_LEFT}
            x2={EVENT_RIGHT}
            y1={56}
            y2={56}
            className="scientific-atlas__event-axis"
          />
          {receiptInRange ? (
            <line
              x1={receiptX}
              x2={receiptX}
              y1={18}
              y2={94}
              className="scientific-atlas__receipt-line"
            />
          ) : null}
          {dataset.events.map((event, index) => {
            const x = eventPosition(
              event,
              dataset.waveform.startSeconds,
              dataset.waveform.endSeconds,
            );
            const uncertaintyStart = eventPosition(
              { ...event, timeSeconds: event.timeSeconds - event.uncertaintySeconds },
              dataset.waveform.startSeconds,
              dataset.waveform.endSeconds,
            );
            const uncertaintyEnd = eventPosition(
              { ...event, timeSeconds: event.timeSeconds + event.uncertaintySeconds },
              dataset.waveform.startSeconds,
              dataset.waveform.endSeconds,
            );
            const labelY = index % 2 === 0 ? 22 : 104;
            return (
              <g key={event.eventId}>
                <line
                  x1={clamp(uncertaintyStart, EVENT_LEFT, EVENT_RIGHT)}
                  x2={clamp(uncertaintyEnd, EVENT_LEFT, EVENT_RIGHT)}
                  y1={56}
                  y2={56}
                  className="scientific-atlas__uncertainty-line"
                />
                <line
                  x1={clamp(uncertaintyStart, EVENT_LEFT, EVENT_RIGHT)}
                  x2={clamp(uncertaintyStart, EVENT_LEFT, EVENT_RIGHT)}
                  y1={50}
                  y2={62}
                  className="scientific-atlas__uncertainty-cap"
                />
                <line
                  x1={clamp(uncertaintyEnd, EVENT_LEFT, EVENT_RIGHT)}
                  x2={clamp(uncertaintyEnd, EVENT_LEFT, EVENT_RIGHT)}
                  y1={50}
                  y2={62}
                  className="scientific-atlas__uncertainty-cap"
                />
                <line
                  x1={x}
                  x2={x}
                  y1={index % 2 === 0 ? 28 : 62}
                  y2={index % 2 === 0 ? 50 : 88}
                  className="scientific-atlas__event-stem"
                />
                <circle
                  cx={x}
                  cy={56}
                  r={6}
                  className="scientific-atlas__event-point"
                />
                <text
                  x={x}
                  y={labelY}
                  textAnchor="middle"
                  className="scientific-atlas__event-label"
                >
                  {event.timeSeconds >= 0 ? "+" : ""}
                  {event.timeSeconds.toFixed(2)} s
                </text>
              </g>
            );
          })}
        </svg>
        <ol className="scientific-atlas__event-list">
          {dataset.events
            .slice()
            .sort((left, right) => left.timeSeconds - right.timeSeconds)
            .map((event) => (
              <li key={event.eventId}>
                <span>
                  {event.timeSeconds >= 0 ? "+" : ""}
                  {event.timeSeconds.toFixed(3)} s
                </span>
                <div>
                  <strong>{event.label}</strong>
                  <small>{event.source}</small>
                </div>
                <em>±{event.uncertaintySeconds.toFixed(3)} s</em>
              </li>
            ))}
        </ol>
      </article>

      <footer className="scientific-atlas__footer">
        <span>
          Projection {dataset.visualizationId} · {publication.publicationId}
        </span>
        <span>Evidence state {publication.evidenceStateHeadHash ?? dataset.stateHeadHash}</span>
      </footer>
    </section>
  );
}
