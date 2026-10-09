import { OscilloscopeRefreshController } from "./OscilloscopeRefreshController";
import { useEffect, useMemo, useRef, useState } from "react";
import { ScientificEvidenceAtlas } from "./ScientificEvidenceAtlas";
import { SharedFindingsPanel } from "./SharedFindingsPanel";
import { LiveCaseStatePanel } from "./LiveCaseStatePanel";
import { DEFAULT_LAYERS, useInvestigationRoom } from "../hooks/useInvestigationRoom";
import type {
  RoomFinding,
  RoomLayerState,
  RoomScientificSelection,
  ScientificSourceView,
} from "../shared/investigation-room";
import type { PublicActivitySnapshot } from "../shared/public-state";
import type {
  ActivityScientificDataset,
  ActivityWaveformSample,
  ScientificBundle,
} from "../shared/scientific-visualization";

const SVG_WIDTH = 1000;
const SVG_HEIGHT = 330;
const PLOT_LEFT = 70;
const PLOT_RIGHT = 980;
const PLOT_TOP = 28;
const PLOT_BOTTOM = 285;

// Sixteen evenly spaced samples from the producer's colorcet.CET_L17 map.
// Keeping the reduced browser projection on this LUT makes its spectral
// encoding agree with the HoloViews/Matplotlib publication render.
const CET_L17_RGB = [
  [254, 255, 255],
  [246, 241, 207],
  [242, 225, 172],
  [242, 207, 146],
  [244, 187, 125],
  [245, 167, 113],
  [244, 145, 105],
  [242, 122, 103],
  [236, 100, 106],
  [226, 77, 113],
  [212, 56, 121],
  [194, 36, 131],
  [169, 26, 143],
  [137, 28, 153],
  [94, 35, 161],
  [0, 42, 167],
] as const;

type TimeRange = readonly [number, number];
type SeriesKey = "rawVoltageV" | "calibratedVoltageV" | "residualVoltageV";

interface ScientificWorkspaceProps {
  bundle: ScientificBundle;
  snapshot: PublicActivitySnapshot;
  sessionToken: string | null;
  discordInstanceId: string | null;
  previewOnly?: boolean;
  archived?: boolean;
}

const SERIES: Array<{ key: SeriesKey; label: string }> = [
  { key: "rawVoltageV", label: "Raw" },
  { key: "calibratedVoltageV", label: "Calibrated" },
  { key: "residualVoltageV", label: "Residual" },
];

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function scale(value: number, domain: TimeRange, output: TimeRange): number {
  const span = domain[1] - domain[0];
  if (span === 0) return (output[0] + output[1]) / 2;
  return output[0] + ((value - domain[0]) / span) * (output[1] - output[0]);
}

function spectralColor(normalized: number): string {
  const position = clamp(normalized, 0, 1) * (CET_L17_RGB.length - 1);
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.min(CET_L17_RGB.length - 1, lowerIndex + 1);
  const fraction = position - lowerIndex;
  const lower = CET_L17_RGB[lowerIndex];
  const upper = CET_L17_RGB[upperIndex];
  const channel = (index: 0 | 1 | 2) =>
    Math.round(lower[index] + (upper[index] - lower[index]) * fraction);
  return `rgb(${channel(0)} ${channel(1)} ${channel(2)})`;
}

function pathFor(
  samples: ActivityWaveformSample[],
  key: SeriesKey,
  timeRange: TimeRange,
  valueRange: TimeRange,
): string {
  return samples
    .map((sample, index) => {
      const x = scale(sample.timeSeconds, timeRange, [PLOT_LEFT, PLOT_RIGHT]);
      const y = scale(sample[key], valueRange, [PLOT_BOTTOM, PLOT_TOP]);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function uncertaintyPath(
  samples: ActivityWaveformSample[],
  timeRange: TimeRange,
  valueRange: TimeRange,
): string {
  if (samples.length === 0) return "";
  const upper = samples.map((sample) => {
    const x = scale(sample.timeSeconds, timeRange, [PLOT_LEFT, PLOT_RIGHT]);
    const y = scale(
      sample.calibratedVoltageV + sample.uncertaintyV,
      valueRange,
      [PLOT_BOTTOM, PLOT_TOP],
    );
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const lower = [...samples].reverse().map((sample) => {
    const x = scale(sample.timeSeconds, timeRange, [PLOT_LEFT, PLOT_RIGHT]);
    const y = scale(
      sample.calibratedVoltageV - sample.uncertaintyV,
      valueRange,
      [PLOT_BOTTOM, PLOT_TOP],
    );
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return `M${upper.join(" L")} L${lower.join(" L")} Z`;
}

function nearestSample(
  samples: ActivityWaveformSample[],
  timeSeconds: number,
): ActivityWaveformSample | null {
  let nearest: ActivityWaveformSample | null = null;
  let distance = Number.POSITIVE_INFINITY;
  for (const sample of samples) {
    const candidate = Math.abs(sample.timeSeconds - timeSeconds);
    if (candidate < distance) {
      nearest = sample;
      distance = candidate;
    }
  }
  return nearest;
}

function timestamp(
  dataset: ActivityScientificDataset,
  offsetSeconds: number,
  timeBasis: string,
): string {
  const zone =
    timeBasis === "Facility local"
      ? dataset.timeZones.facility
      : timeBasis === "Source original"
        ? dataset.timeZones.source
        : dataset.timeZones.named[timeBasis] ?? "UTC";
  const date = new Date(
    new Date(dataset.referenceTimeUtc).getTime() + offsetSeconds * 1000,
  );
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZoneName: "short",
    }).format(date);
  } catch {
    return date.toISOString();
  }
}

function SpectrogramCanvas({
  dataset,
  range,
  onSelect,
}: {
  dataset: ActivityScientificDataset;
  range: TimeRange;
  onSelect(range: TimeRange): void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [selectionStart, setSelectionStart] = useState<number | null>(null);
  const [canvasSizeRevision, setCanvasSizeRevision] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      setCanvasSizeRevision((revision) => revision + 1);
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(bounds.width * ratio));
    const height = Math.max(1, Math.round(bounds.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }

    context.clearRect(0, 0, width, height);
    context.fillStyle = "#101519";
    context.fillRect(0, 0, width, height);

    const { timeSeconds, frequencyHz, powerDb, minimumDb, maximumDb } =
      dataset.spectrogram;
    const visibleTimeIndices = timeSeconds
      .map((value, index) => ({ value, index }))
      .filter(({ value }) => value >= range[0] && value <= range[1]);
    if (visibleTimeIndices.length === 0 || frequencyHz.length === 0) return;

    const denominator = Math.max(0.000001, maximumDb - minimumDb);
    const cellWidth = width / visibleTimeIndices.length;
    const cellHeight = height / frequencyHz.length;

    for (let frequencyIndex = 0; frequencyIndex < frequencyHz.length; frequencyIndex += 1) {
      for (let visibleIndex = 0; visibleIndex < visibleTimeIndices.length; visibleIndex += 1) {
        const timeIndex = visibleTimeIndices[visibleIndex].index;
        const value = powerDb[frequencyIndex]?.[timeIndex] ?? minimumDb;
        const normalized = clamp((value - minimumDb) / denominator, 0, 1);
        context.fillStyle = spectralColor(normalized);
        context.fillRect(
          visibleIndex * cellWidth,
          height - (frequencyIndex + 1) * cellHeight,
          Math.ceil(cellWidth + 0.5),
          Math.ceil(cellHeight + 0.5),
        );
      }
    }
  }, [canvasSizeRevision, dataset, range]);

  const pointerTime = (clientX: number, element: HTMLDivElement): number => {
    const bounds = element.getBoundingClientRect();
    const fraction = clamp((clientX - bounds.left) / Math.max(1, bounds.width), 0, 1);
    return range[0] + fraction * (range[1] - range[0]);
  };

  return (
    <div
      className="spectrogram-shell"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        setSelectionStart(pointerTime(event.clientX, event.currentTarget));
      }}
      onPointerUp={(event) => {
        const end = pointerTime(event.clientX, event.currentTarget);
        if (selectionStart !== null) {
          const next: TimeRange = [Math.min(selectionStart, end), Math.max(selectionStart, end)];
          if (next[1] > next[0]) onSelect(next);
        }
        setSelectionStart(null);
      }}
    >
      <canvas
        ref={canvasRef}
        className="spectrogram-canvas"
        role="img"
        aria-label={`Spectrogram from ${range[0].toFixed(3)} to ${range[1].toFixed(3)} seconds`}
      />
      <span className="spectrogram-y-label">Frequency (Hz)</span>
      <span className="spectrogram-x-label">
        Drag or use linked window controls
      </span>
      <div
        className="spectrogram-colorbar"
        role="img"
        aria-label={`Color scale from ${dataset.spectrogram.minimumDb.toFixed(1)} to ${dataset.spectrogram.maximumDb.toFixed(1)} decibels per hertz using Colorcet CET L17`}
      >
        <span>{dataset.spectrogram.maximumDb.toFixed(0)}</span>
        <i aria-hidden="true" />
        <span>{dataset.spectrogram.minimumDb.toFixed(0)}</span>
        <small>dB/Hz</small>
      </div>
    </div>
  );
}

export function ScientificWorkspace({
  bundle,
  snapshot,
  sessionToken,
  discordInstanceId,
  previewOnly = false,
  archived = false,
}: ScientificWorkspaceProps) {
  const { dataset, spec, publication } = bundle;
  const defaultTimeBasis = spec.interaction.timeBases[0] ?? "UTC";
  const fullRange = useMemo<TimeRange>(
    () => [dataset.waveform.startSeconds, dataset.waveform.endSeconds],
    [dataset],
  );
  const [range, setRange] = useState<TimeRange>(fullRange);
  const [selectionStart, setSelectionStart] = useState<number | null>(null);
  const [activeSelection, setActiveSelection] = useState<RoomScientificSelection | null>(null);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [hovered, setHovered] = useState<ActivityWaveformSample | null>(null);
  const [timeBasis, setTimeBasis] = useState(defaultTimeBasis);
  const [visibleSeries, setVisibleSeries] = useState<Record<SeriesKey, boolean>>({
    rawVoltageV: DEFAULT_LAYERS.rawVoltageV,
    calibratedVoltageV: DEFAULT_LAYERS.calibratedVoltageV,
    residualVoltageV: DEFAULT_LAYERS.residualVoltageV,
  });
  const [showUncertainty, setShowUncertainty] = useState(DEFAULT_LAYERS.uncertainty);

  const layers = useMemo<RoomLayerState>(
    () => ({
      rawVoltageV: visibleSeries.rawVoltageV,
      calibratedVoltageV: visibleSeries.calibratedVoltageV,
      residualVoltageV: visibleSeries.residualVoltageV,
      uncertainty: showUncertainty,
    }),
    [showUncertainty, visibleSeries],
  );

  const room = useInvestigationRoom({
    enabled: !previewOnly,
    environment: dataset.environment,
    artifactId: dataset.artifactId,
    visualizationId: dataset.visualizationId,
    minimumSeconds: fullRange[0],
    maximumSeconds: fullRange[1],
    timeBases: spec.interaction.timeBases,
    sessionToken,
    discordInstanceId,
  });

  const setLayersLocally = (next: RoomLayerState) => {
    setVisibleSeries({
      rawVoltageV: next.rawVoltageV,
      calibratedVoltageV: next.calibratedVoltageV,
      residualVoltageV: next.residualVoltageV,
    });
    setShowUncertainty(next.uncertainty);
  };

  useEffect(() => {
    setRange(fullRange);
    setActiveSelection(null);
    setSelectedFindingId(null);
    setHovered(null);
    setTimeBasis(defaultTimeBasis);
  }, [defaultTimeBasis, fullRange, dataset.visualizationId]);

  useEffect(() => {
    const shared = room.snapshot;
    if (!shared) return;
    if (shared.selection) {
      setRange([shared.selection.startSeconds, shared.selection.endSeconds]);
      setTimeBasis(shared.selection.timeBasis);
      setActiveSelection(shared.selection);
    }
    setLayersLocally(shared.layers);
  }, [room.snapshot?.selection, room.snapshot?.layers]);

  const visibleSamples = useMemo(
    () =>
      dataset.waveform.samples.filter(
        (sample) => sample.timeSeconds >= range[0] && sample.timeSeconds <= range[1],
      ),
    [dataset, range],
  );

  const valueRange = useMemo<TimeRange>(() => {
    const values: number[] = [];
    for (const sample of visibleSamples) {
      for (const { key } of SERIES) {
        if (visibleSeries[key]) values.push(sample[key]);
      }
      if (showUncertainty && visibleSeries.calibratedVoltageV) {
        values.push(
          sample.calibratedVoltageV - sample.uncertaintyV,
          sample.calibratedVoltageV + sample.uncertaintyV,
        );
      }
    }
    if (values.length === 0) return [-1, 1];
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    const padding = Math.max(0.001, (maximum - minimum) * 0.08);
    return [minimum - padding, maximum + padding];
  }, [showUncertainty, visibleSamples, visibleSeries]);

  const stats = useMemo(() => {
    const values = visibleSamples.map((sample) => sample.calibratedVoltageV);
    if (values.length === 0) {
      return { minimum: 0, maximum: 0, rms: 0 };
    }
    return {
      minimum: Math.min(...values),
      maximum: Math.max(...values),
      rms: Math.sqrt(values.reduce((sum, value) => sum + value ** 2, 0) / values.length),
    };
  }, [visibleSamples]);

  const pointerTime = (clientX: number, element: SVGSVGElement): number => {
    const bounds = element.getBoundingClientRect();
    const plotLeft = bounds.left + (PLOT_LEFT / SVG_WIDTH) * bounds.width;
    const plotRight = bounds.left + (PLOT_RIGHT / SVG_WIDTH) * bounds.width;
    const fraction = clamp((clientX - plotLeft) / (plotRight - plotLeft), 0, 1);
    return range[0] + fraction * (range[1] - range[0]);
  };

  const commitSelection = (
    next: TimeRange,
    sourceView: ScientificSourceView,
    basis = timeBasis,
  ) => {
    const normalized: RoomScientificSelection = {
      startSeconds: clamp(Math.min(next[0], next[1]), fullRange[0], fullRange[1]),
      endSeconds: clamp(Math.max(next[0], next[1]), fullRange[0], fullRange[1]),
      timeBasis: basis,
      sourceView,
    };
    if (room.roomId && !room.sendSelection(normalized)) return;
    setRange([normalized.startSeconds, normalized.endSeconds]);
    setActiveSelection(normalized);
    setSelectedFindingId(null);
  };

  const commitLayers = (next: RoomLayerState) => {
    if (room.roomId && !room.sendLayers(next)) return;
    setLayersLocally(next);
  };

  const zoom = (factor: number) => {
    const center = (range[0] + range[1]) / 2;
    const half = ((range[1] - range[0]) * factor) / 2;
    let start = center - half;
    let end = center + half;
    if (start < fullRange[0]) {
      end += fullRange[0] - start;
      start = fullRange[0];
    }
    if (end > fullRange[1]) {
      start -= end - fullRange[1];
      end = fullRange[1];
    }
    commitSelection(
      [Math.max(fullRange[0], start), Math.min(fullRange[1], end)],
      activeSelection?.sourceView ?? "waveform",
    );
  };

  const rangeStep = Math.max(
    1 / dataset.sampleRateHz,
    (fullRange[1] - fullRange[0]) / 10_000,
  );

  const openFinding = (finding: RoomFinding) => {
    if (room.roomId && !room.openFinding(finding.findingId)) return;
    setRange([finding.selection.startSeconds, finding.selection.endSeconds]);
    setTimeBasis(finding.selection.timeBasis);
    setActiveSelection(finding.selection);
    setLayersLocally(finding.layers);
    setSelectedFindingId(finding.findingId);
  };

  return (
    <section className="science-workspace" aria-labelledby="science-workspace-heading">
      <div className="section-heading-row science-heading">
        <div>
          <p className="eyebrow">Phase 4C collaborative scientific projection</p>
          <h2 id="science-workspace-heading">{dataset.title}</h2>
          <p className="science-summary">{dataset.publicSummary}</p>
        </div>
        <span className="publication-status published">interactive</span>
      </div>

      <LiveCaseStatePanel snapshot={snapshot} archived={archived} />

      {bundle.fallbackUrl ? (
        <article className="holoviz-publication-card" aria-labelledby="holoviz-publication-heading">
          <div className="science-card-heading">
            <div>
              <p className="eyebrow">Producer render · HoloViews / Matplotlib / Resvg</p>
              <h3 id="holoviz-publication-heading">HoloViz scientific publication plate</h3>
            </div>
            <span>Full retained dataset · immutable publication asset</span>
          </div>
          <figure>
            <img
              src={bundle.fallbackUrl}
              alt="HoloViz publication plate plotting the retained line-voltage waveform, time-frequency spectrogram, applied calibration correction, and calibrated-voltage versus slew-rate phase map."
            />
            <figcaption>
              This is the scientific producer&apos;s HoloViews render of the published
              full dataset. The linked plots below are the reduced interactive browser
              projection; they are not presented as HoloViz output.
            </figcaption>
          </figure>
        </article>
      ) : null}

      <div className="science-toolbar" aria-label="Scientific visualization controls">
        <OscilloscopeRefreshController />
        <label>
          <span>Time basis</span>
          <select
            value={timeBasis}
            onChange={(event) => {
              const basis = event.target.value;
              setTimeBasis(basis);
              if (activeSelection) {
                commitSelection(
                  [activeSelection.startSeconds, activeSelection.endSeconds],
                  activeSelection.sourceView,
                  basis,
                );
              }
            }}
          >
            {spec.interaction.timeBases.map((basis) => (
              <option value={basis} key={basis}>{basis}</option>
            ))}
          </select>
        </label>
        <div className="series-controls" role="group" aria-label="Visible waveform series">
          {SERIES.map(({ key, label }) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={visibleSeries[key]}
                onChange={(event) =>
                  commitLayers({ ...layers, [key]: event.target.checked })
                }
              />
              <span>{label}</span>
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={showUncertainty}
              onChange={(event) =>
                commitLayers({ ...layers, uncertainty: event.target.checked })
              }
            />
            <span>Uncertainty</span>
          </label>
        </div>
        <fieldset
          className="science-window-controls"
          aria-describedby="science-window-help"
        >
          <legend>Linked time window</legend>
          <label>
            <span>Start</span>
            <input
              type="range"
              min={fullRange[0]}
              max={Math.max(fullRange[0], range[1] - rangeStep)}
              step={rangeStep}
              value={range[0]}
              onChange={(event) =>
                commitSelection(
                  [Number(event.target.value), range[1]],
                  activeSelection?.sourceView ?? "waveform",
                )
              }
            />
            <output>{range[0].toFixed(3)} s</output>
          </label>
          <label>
            <span>End</span>
            <input
              type="range"
              min={Math.min(fullRange[1], range[0] + rangeStep)}
              max={fullRange[1]}
              step={rangeStep}
              value={range[1]}
              onChange={(event) =>
                commitSelection(
                  [range[0], Number(event.target.value)],
                  activeSelection?.sourceView ?? "waveform",
                )
              }
            />
            <output>{range[1].toFixed(3)} s</output>
          </label>
          <span className="sr-only" id="science-window-help">
            Use the arrow keys on either slider to select the same linked time
            window as dragging the waveform or spectrogram.
          </span>
        </fieldset>
        <div className="range-controls">
          <button type="button" onClick={() => zoom(0.5)}>Zoom in</button>
          <button type="button" onClick={() => zoom(2)}>Zoom out</button>
          <button
            type="button"
            onClick={() => commitSelection(fullRange, activeSelection?.sourceView ?? "waveform")}
          >
            Reset
          </button>
        </div>
      </div>

      <div className="science-grid">
        <article className="waveform-card">
          <div className="science-card-heading">
            <div>
              <p className="eyebrow">Linked waveform</p>
              <h3>Retained voltage record</h3>
            </div>
            <span>{visibleSamples.length} published samples in view</span>
          </div>
          <svg
            className="waveform-svg"
            viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
            role="img"
            aria-label="Interactive raw, calibrated, and residual waveform"
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              setSelectionStart(pointerTime(event.clientX, event.currentTarget));
            }}
            onPointerMove={(event) => {
              const time = pointerTime(event.clientX, event.currentTarget);
              setHovered(nearestSample(visibleSamples, time));
            }}
            onPointerUp={(event) => {
              const end = pointerTime(event.clientX, event.currentTarget);
              if (selectionStart !== null) {
                const next: TimeRange = [
                  Math.min(selectionStart, end),
                  Math.max(selectionStart, end),
                ];
                if (next[1] - next[0] > (fullRange[1] - fullRange[0]) / 500) {
                  commitSelection(next, "waveform");
                }
              }
              setSelectionStart(null);
            }}
            onPointerLeave={() => setHovered(null)}
            onWheel={(event) => {
              event.preventDefault();
              zoom(event.deltaY < 0 ? 0.8 : 1.25);
            }}
          >
            <rect x="0" y="0" width={SVG_WIDTH} height={SVG_HEIGHT} className="waveform-background" />
            {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
              const y = PLOT_TOP + fraction * (PLOT_BOTTOM - PLOT_TOP);
              const value = valueRange[1] - fraction * (valueRange[1] - valueRange[0]);
              return (
                <g key={fraction}>
                  <line x1={PLOT_LEFT} x2={PLOT_RIGHT} y1={y} y2={y} className="plot-grid-line" />
                  <text x={PLOT_LEFT - 12} y={y + 4} textAnchor="end" className="plot-axis-label">
                    {value.toFixed(3)}
                  </text>
                </g>
              );
            })}
            {dataset.waveform.qualityIntervals
              .filter(
                (interval) =>
                  interval.quality !== "valid" &&
                  interval.endSeconds >= range[0] &&
                  interval.startSeconds <= range[1],
              )
              .map((interval) => {
                const start = scale(
                  clamp(interval.startSeconds, range[0], range[1]),
                  range,
                  [PLOT_LEFT, PLOT_RIGHT],
                );
                const end = scale(
                  clamp(interval.endSeconds, range[0], range[1]),
                  range,
                  [PLOT_LEFT, PLOT_RIGHT],
                );
                return (
                  <rect
                    key={`${interval.startSeconds}-${interval.endSeconds}-${interval.quality}`}
                    x={Math.min(start, end)}
                    y={PLOT_TOP}
                    width={Math.abs(end - start)}
                    height={PLOT_BOTTOM - PLOT_TOP}
                    className="quality-region"
                  />
                );
              })}
            {showUncertainty && visibleSeries.calibratedVoltageV ? (
              <path
                d={uncertaintyPath(visibleSamples, range, valueRange)}
                className="uncertainty-band"
              />
            ) : null}
            {SERIES.map(({ key }) =>
              visibleSeries[key] ? (
                <path
                  key={key}
                  d={pathFor(visibleSamples, key, range, valueRange)}
                  className={`waveform-line ${key}`}
                />
              ) : null,
            )}
            {dataset.events
              .filter((event) => event.timeSeconds >= range[0] && event.timeSeconds <= range[1])
              .map((event) => {
                const x = scale(event.timeSeconds, range, [PLOT_LEFT, PLOT_RIGHT]);
                return (
                  <g key={event.eventId}>
                    <line x1={x} x2={x} y1={PLOT_TOP} y2={PLOT_BOTTOM} className="event-line" />
                    <text x={x + 5} y={PLOT_TOP + 14} className="event-label">{event.label}</text>
                  </g>
                );
              })}
            {hovered ? (
              <g>
                <line
                  x1={scale(hovered.timeSeconds, range, [PLOT_LEFT, PLOT_RIGHT])}
                  x2={scale(hovered.timeSeconds, range, [PLOT_LEFT, PLOT_RIGHT])}
                  y1={PLOT_TOP}
                  y2={PLOT_BOTTOM}
                  className="hover-line"
                />
                <circle
                  cx={scale(hovered.timeSeconds, range, [PLOT_LEFT, PLOT_RIGHT])}
                  cy={scale(hovered.calibratedVoltageV, valueRange, [PLOT_BOTTOM, PLOT_TOP])}
                  r="5"
                  className="hover-point"
                />
              </g>
            ) : null}
            <line x1={PLOT_LEFT} x2={PLOT_RIGHT} y1={PLOT_BOTTOM} y2={PLOT_BOTTOM} className="plot-axis" />
            <text x={(PLOT_LEFT + PLOT_RIGHT) / 2} y={318} textAnchor="middle" className="plot-axis-title">
              Seconds relative to verified receipt · drag or use window controls · wheel or buttons to zoom
            </text>
          </svg>

          <div className="science-readout" aria-live="polite">
            <dl>
              <div><dt>Window</dt><dd>{range[0].toFixed(3)}–{range[1].toFixed(3)} s</dd></div>
              <div><dt>Minimum</dt><dd>{stats.minimum.toFixed(5)} V</dd></div>
              <div><dt>Maximum</dt><dd>{stats.maximum.toFixed(5)} V</dd></div>
              <div><dt>RMS</dt><dd>{stats.rms.toFixed(5)} V</dd></div>
            </dl>
            {hovered ? (
              <div className="hover-readout">
                <strong>{timestamp(dataset, hovered.timeSeconds, timeBasis)}</strong>
                <span>t {hovered.timeSeconds.toFixed(6)} s</span>
                <span>cal {hovered.calibratedVoltageV.toFixed(6)} V</span>
                <span>± {hovered.uncertaintyV.toFixed(6)} V</span>
                <span>{hovered.quality}</span>
              </div>
            ) : (
              <p>Move across the waveform to inspect the nearest retained sample.</p>
            )}
          </div>
        </article>

        <article className="spectrogram-card">
          <div className="science-card-heading">
            <div>
              <p className="eyebrow">Linked spectral view</p>
              <h3>Power spectral density</h3>
            </div>
            <span>{dataset.spectrogram.minimumDb.toFixed(1)} to {dataset.spectrogram.maximumDb.toFixed(1)} dB/Hz</span>
          </div>
          <SpectrogramCanvas
            dataset={dataset}
            range={range}
            onSelect={(next) => commitSelection(next, "spectrogram")}
          />
          <div className="derived-grid">
            {dataset.derivedValues.map((value) => (
              <div key={value.valueId}>
                <span>{value.label}</span>
                <strong>{value.value.toLocaleString()} {value.unit}</strong>
                <small>± {value.uncertainty.toLocaleString()} {value.unit}</small>
              </div>
            ))}
          </div>
        </article>
      </div>

      <ScientificEvidenceAtlas bundle={bundle} />

      <SharedFindingsPanel
        room={room}
        selection={activeSelection}
        layers={layers}
        selectedFindingId={selectedFindingId}
        onOpenFinding={openFinding}
        onSelectedFindingChange={setSelectedFindingId}
        readOnly={previewOnly}
      />

      <div className="science-provenance">
        <div>
          <span>Publication</span>
          <strong>{publication.publicationId}</strong>
        </div>
        <div>
          <span>Evidence state</span>
          <strong>{publication.evidenceStateHeadHash ?? dataset.stateHeadHash}</strong>
        </div>
        <div>
          <span>Input dataset</span>
          <strong>{dataset.inputDatasetHash}</strong>
        </div>
        <div>
          <span>Projection</span>
          <strong>{dataset.waveform.publishedSampleCount}/{dataset.waveform.fullSampleCount} waveform samples</strong>
        </div>
      </div>
      <p className="science-limitation"><strong>Limitation.</strong> {publication.limitation}</p>
    </section>
  );
}
