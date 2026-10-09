import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  DISPLAY_REFRESH_RATES,
  readSignalLaboratoryDisplayFps,
  SignalLaboratoryOscilloscope,
  storeSignalLaboratoryDisplayFps,
  type DisplayRefreshRate,
} from "./SignalLaboratoryOscilloscope";
import { publishAnalysisMapLayers } from "../lib/analysis-layer-bus";
import { loadEnvironmentalContext } from "../lib/environmental-context";
import {
  buildScienceSonification,
  isScienceSonificationSupported,
} from "../lib/science-sonification";
import {
  analyzeFacilityScience,
  FACILITY_SCIENCE,
  initialScienceControls,
  type FacilityScienceFrame,
  type ScienceReading,
  type ScienceControlValues,
} from "../shared/facility-science";
import {
  type EnvironmentalContextSnapshot,
  type EnvironmentalFacilityId,
} from "../shared/environmental-context";
import { ScienceSonificationPanel } from "./ScienceSonificationPanel";
import { ViewportInfoPopover } from "./ViewportInfoPopover";

interface FacilityScienceLabProps {
  facilityId: EnvironmentalFacilityId;
  sessionToken: string | null;
}

const CONTEXT_REFRESH_MILLISECONDS = 2 * 60 * 1_000;

function readingById(
  readings: readonly ScienceReading[],
  readingId: string,
): ScienceReading {
  const reading = readings.find((candidate) => candidate.id === readingId);
  if (!reading) {
    throw new Error(`Unknown facility-science reading ID: ${readingId}`);
  }
  return reading;
}

function ReadingMarker({
  reading,
  meaning,
}: {
  reading: ScienceReading;
  meaning: string;
}) {
  return (
    <ViewportInfoPopover
      title={reading.title}
      ariaLabel={`Explain this value and open ${reading.title}`}
    >
      <small>{meaning}</small>
      <em>{reading.source} · {reading.access}</em>
      <a
        href={reading.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        Open reading <span aria-hidden="true">↗</span>
      </a>
    </ViewportInfoPopover>
  );
}

function extent(values: readonly number[]): [number, number] {
  if (values.length === 0) return [0, 1];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  if (minimum === maximum) return [minimum - 0.5, maximum + 0.5];
  return [minimum, maximum];
}

function linePath(
  values: readonly number[],
  width = 600,
  height = 240,
  padding = 24,
  domain = extent(values),
): string {
  if (values.length === 0) return "";
  const [minimum, maximum] = domain;
  return values
    .map((candidate, index) => {
      const x =
        padding +
        (index / Math.max(1, values.length - 1)) * (width - padding * 2);
      const y =
        height -
        padding -
        ((candidate - minimum) / Math.max(0.000001, maximum - minimum)) *
          (height - padding * 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function gridLines(width = 640, height = 280) {
  return (
    <g className="science-plot-grid" aria-hidden="true">
      {Array.from({ length: 9 }, (_, index) => (
        <path
          key={`vertical-${index}`}
          d={`M${20 + index * ((width - 40) / 8)} 16V${height - 22}`}
        />
      ))}
      {Array.from({ length: 6 }, (_, index) => (
        <path
          key={`horizontal-${index}`}
          d={`M20 ${18 + index * ((height - 42) / 5)}H${width - 20}`}
        />
      ))}
    </g>
  );
}

function MatrixPlot({
  matrix,
  label,
}: {
  matrix: readonly (readonly number[])[];
  label: string;
}) {
  const rows = matrix.length;
  const columns = Math.max(0, ...matrix.map((row) => row.length));
  const flat = matrix.flat();
  const measuredExtent = extent(flat);
  const [minimum, maximum] =
    measuredExtent[0] >= 0 && measuredExtent[1] <= 1
      ? [0, 1]
      : measuredExtent;
  if (rows === 0 || columns === 0) {
    return <p className="science-plot-empty">No matrix values are available.</p>;
  }
  const cellWidth = 580 / columns;
  const cellHeight = 230 / rows;
  return (
    <svg viewBox="0 0 640 280" role="img" aria-label={label}>
      <rect x="0" y="0" width="640" height="280" className="science-plot-field" />
      <g transform="translate(30 20)">
        {matrix.flatMap((row, rowIndex) =>
          row.map((candidate, columnIndex) => {
            const normalized =
              (candidate - minimum) / Math.max(0.000001, maximum - minimum);
            return (
              <rect
                key={`${rowIndex}-${columnIndex}`}
                x={columnIndex * cellWidth}
                y={rowIndex * cellHeight}
                width={Math.max(0.8, cellWidth - 0.7)}
                height={Math.max(0.8, cellHeight - 0.7)}
                className="science-matrix-cell"
                style={{
                  opacity: 0.12 + normalized * 0.88,
                  fill: `hsl(${198 - normalized * 152} 58% ${42 + normalized * 24}%)`,
                }}
              />
            );
          }),
        )}
      </g>
      <text x="30" y="270">min {minimum.toFixed(3)}</text>
      <text x="610" y="270" textAnchor="end">max {maximum.toFixed(3)}</text>
    </svg>
  );
}

function BarsPlot({
  values,
  label,
}: {
  values: readonly number[];
  label: string;
}) {
  const measuredMaximum = Math.max(0.000001, ...values);
  const maximum = measuredMaximum <= 1 ? 1 : measuredMaximum;
  const width = 590 / Math.max(1, values.length);
  return (
    <svg viewBox="0 0 640 280" role="img" aria-label={label}>
      <rect x="0" y="0" width="640" height="280" className="science-plot-field" />
      {gridLines()}
      <g transform="translate(25 15)">
        {values.map((candidate, index) => {
          const height = (candidate / maximum) * 220;
          return (
            <rect
              key={index}
              x={index * width + 1}
              y={230 - height}
              width={Math.max(1, width - 2)}
              height={height}
              className="science-spectrum-bar"
            />
          );
        })}
      </g>
      <text x="610" y="270" textAnchor="end">
        scale max {maximum.toFixed(maximum <= 1 ? 2 : 1)}
      </text>
    </svg>
  );
}

function LinesPlot({
  series,
  label,
  markers,
}: {
  series: readonly { values: readonly number[]; className: string }[];
  label: string;
  markers?: readonly { x: number; label: string }[];
}) {
  const domain = extent(series.flatMap((candidate) => candidate.values));
  return (
    <svg viewBox="0 0 640 280" role="img" aria-label={label}>
      <rect x="0" y="0" width="640" height="280" className="science-plot-field" />
      {gridLines()}
      {series.map((candidate, index) =>
        candidate.values.length > 0 ? (
          <path
            key={index}
            d={linePath(candidate.values, 640, 280, 25, domain)}
            className={`science-line ${candidate.className}`}
          />
        ) : null,
      )}
      {markers?.map((marker) => (
        <g key={marker.label} transform={`translate(${25 + marker.x * 590} 0)`}>
          <path d="M0 18V254" className="science-marker" />
          <text x="5" y="32">{marker.label}</text>
        </g>
      ))}
    </svg>
  );
}

function TrackPlot({
  frame,
  covariance,
}: {
  frame: FacilityScienceFrame;
  covariance: boolean;
}) {
  const groups = [0, 1, 2, 3];
  const points = frame.points;
  const xExtent = extent(points.map((point) => point.x));
  const yExtent = extent(points.map((point) => point.y));
  const transform = (x: number, y: number) => ({
    x:
      35 +
      ((x - xExtent[0]) / Math.max(0.000001, xExtent[1] - xExtent[0])) *
        560,
    y:
      248 -
      ((y - yExtent[0]) / Math.max(0.000001, yExtent[1] - yExtent[0])) *
        215,
  });
  return (
    <svg viewBox="0 0 640 280" role="img" aria-label={covariance ? "Track uncertainty envelopes" : "Independent and fused tracks"}>
      <rect x="0" y="0" width="640" height="280" className="science-plot-field" />
      {gridLines()}
      {groups.map((group) => {
        const groupPoints = points.filter((point) => point.group === group);
        const path = groupPoints
          .map((point, index) => {
            const projected = transform(point.x, point.y);
            return `${index === 0 ? "M" : "L"}${projected.x.toFixed(2)} ${projected.y.toFixed(2)}`;
          })
          .join(" ");
        return (
          <g key={group} className={`science-track-group science-track-${group}`}>
            {!covariance ? <path d={path} className="science-line" /> : null}
            {groupPoints
              .filter((_, index) => index % 4 === 0)
              .map((point, index) => {
                const projected = transform(point.x, point.y);
                return covariance ? (
                  <ellipse
                    key={index}
                    cx={projected.x}
                    cy={projected.y}
                    rx={Math.max(3, (point.uncertainty ?? 1) * 2.2)}
                    ry={Math.max(2, (point.uncertainty ?? 1) * 1.25)}
                    className="science-covariance"
                  />
                ) : (
                  <circle
                    key={index}
                    cx={projected.x}
                    cy={projected.y}
                    r="2.7"
                    className="science-track-point"
                  />
                );
              })}
          </g>
        );
      })}
    </svg>
  );
}

function NetworkPlot({ frame }: { frame: FacilityScienceFrame }) {
  const points = frame.points;
  return (
    <svg viewBox="0 0 640 280" role="img" aria-label="Archive dependency and recurrence network">
      <rect x="0" y="0" width="640" height="280" className="science-plot-field" />
      {gridLines()}
      <g transform="translate(22 18)">
        {points.slice(1).map((point, index) => {
          const previous = points[Math.max(0, index - (index % 3))];
          return (
            <path
              key={`link-${index}`}
              d={`M${previous.x * 5.8} ${225 - previous.y * 2.5}L${point.x * 5.8} ${225 - point.y * 2.5}`}
              className={point.group === 1 ? "science-network-copy" : "science-network-link"}
            />
          );
        })}
        {points.map((point, index) => (
          <g key={index} transform={`translate(${point.x * 5.8} ${225 - point.y * 2.5})`}>
            <circle r={point.group === 0 ? 5 : 3.5} className={`science-network-node group-${point.group}`} />
            <text x="7" y="-5">{String(index + 1).padStart(2, "0")}</text>
          </g>
        ))}
      </g>
    </svg>
  );
}

function BlochPlot({ frame }: { frame: FacilityScienceFrame }) {
  const point = frame.points[0] ?? { x: 0, y: 0, uncertainty: 0 };
  const x = 190 + point.x * 112;
  const y = 140 - point.y * 112;
  return (
    <svg viewBox="0 0 640 280" role="img" aria-label="Two-state manifold and basis vector">
      <rect x="0" y="0" width="640" height="280" className="science-plot-field" />
      <g className="science-bloch">
        <circle cx="190" cy="140" r="112" />
        <ellipse cx="190" cy="140" rx="112" ry="34" />
        <ellipse cx="190" cy="140" rx="34" ry="112" />
        <path d={`M190 140L${x} ${y}`} />
        <circle cx={x} cy={y} r="6" />
        <circle
          cx={x}
          cy={y}
          r={8 + (point.uncertainty ?? 0) * 38}
          className="science-bloch-uncertainty"
        />
      </g>
      <g className="science-bloch-guide">
        <text x="350" y="68">Vector length</text>
        <strong />
        <text x="350" y="92">{Math.hypot(point.x, point.y).toFixed(3)}</text>
        <text x="350" y="142">Dephasing radius</text>
        <text x="350" y="166">{(point.uncertainty ?? 0).toFixed(3)}</text>
        <text x="350" y="216">Changing basis rotates the measurement axes.</text>
      </g>
    </svg>
  );
}

function FacilityToolPlot({
  facilityId,
  toolId,
  frame,
  nextFrame,
  controls,
  streaming,
  analysisRateHz,
  displayFps,
}: {
  facilityId: EnvironmentalFacilityId;
  toolId: string;
  frame: FacilityScienceFrame;
  nextFrame: FacilityScienceFrame;
  controls: ScienceControlValues;
  streaming: boolean;
  analysisRateHz: number;
  displayFps: DisplayRefreshRate;
}) {
  if (facilityId === "boundary_array") {
    if (toolId === "spectrum") {
      return (
        <BarsPlot
          values={frame.series.spectrum ?? []}
          label="Discrete Fourier amplitude spectrum"
        />
      );
    }
    if (toolId === "correlation") {
      return (
        <LinesPlot
          series={[
            { values: frame.series.lag ?? [], className: "primary" },
            { values: frame.series.residual ?? [], className: "secondary" },
          ]}
          label="Lag correlation and alignment residual"
          markers={[{ x: 0.5, label: "zero lag" }]}
        />
      );
    }
    return (
      <SignalLaboratoryOscilloscope
        primary={frame.series.optical ?? []}
        nextPrimary={nextFrame.series.optical ?? []}
        secondary={frame.series.radio ?? []}
        nextSecondary={nextFrame.series.radio ?? []}
        label="Streaming optical and corrected radio waveforms"
        streaming={streaming}
        analysisRateHz={analysisRateHz}
        displayFps={displayFps}
      />
    );
  }

  if (facilityId === "aeronautical_incident_center") {
    if (toolId === "residuals") {
      return (
        <LinesPlot
          series={[
            { values: frame.series.residual ?? [], className: "primary" },
            { values: frame.series.fusionResidual ?? [], className: "secondary" },
          ]}
          label="Feed and fusion residuals over time"
        />
      );
    }
    return <TrackPlot frame={frame} covariance={toolId === "covariance"} />;
  }

  if (facilityId === "aerial_phenomena_archive") {
    if (toolId === "chronology") {
      return <BarsPlot values={frame.bars} label="Archive chronology histogram" />;
    }
    if (toolId === "similarity") {
      return <MatrixPlot matrix={frame.matrix} label="Pairwise feature similarity matrix" />;
    }
    return <NetworkPlot frame={frame} />;
  }

  if (facilityId === "holography_laboratory") {
    if (toolId === "residual") {
      return (
        <LinesPlot
          series={[{ values: frame.series.residual ?? [], className: "primary" }]}
          label="Withheld projection residual by angle"
        />
      );
    }
    if (toolId === "sinogram") {
      const rows = 16;
      const columns = 24;
      const matrix = Array.from({ length: rows }, (_, row) =>
        Array.from(
          { length: columns },
          (_, column) =>
            frame.points[row * columns + column]?.uncertainty ?? 0,
        ),
      );
      return <MatrixPlot matrix={matrix} label="Projection sinogram" />;
    }
    return <MatrixPlot matrix={frame.matrix} label="Limited-angle reconstructed slice" />;
  }

  if (facilityId === "subsurface_resonance_station") {
    if (toolId === "depthFrequency") {
      return <MatrixPlot matrix={frame.matrix} label="Depth-frequency modal response field" />;
    }
    if (toolId === "stations") {
      return <BarsPlot values={frame.bars} label="Cross-station coherence" />;
    }
    return (
      <LinesPlot
        series={[
          { values: frame.series.spectrum ?? [], className: "primary" },
          { values: frame.series.depthResponse ?? [], className: "secondary" },
        ]}
        label="Mode spectrum and selected depth response"
        markers={[
          {
            x: Math.min(1, Math.max(0, ((controls.trialFrequency ?? 1) - 1) / 23)),
            label: "trial",
          },
        ]}
      />
    );
  }

  if (toolId === "density") {
    return <MatrixPlot matrix={frame.matrix} label="Density matrix magnitude" />;
  }
  if (toolId === "sensitivity") {
    return (
      <LinesPlot
        series={[
          { values: frame.series.sensitivity ?? [], className: "primary" },
        ]}
        label="Predicted outcome probability across measurement bases"
      />
    );
  }
  return <BlochPlot frame={frame} />;
}

function formatReading(value: number | null, unit: string): string {
  if (value === null) return "missing";
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${unit}`.trim();
}

function exportRun(
  facilityId: EnvironmentalFacilityId,
  controls: ScienceControlValues,
  frame: FacilityScienceFrame,
  prediction: string | null,
  note: string,
  context: EnvironmentalContextSnapshot | null,
) {
  const payload = {
    schemaVersion: "1.0.0",
    exportedAt: new Date().toISOString(),
    facilityId,
    dataset: "sealed-orientation-record-v1",
    controls,
    prediction,
    quantitativeObservation: frame.observation,
    explanationNote: note,
    method: frame.method,
    metrics: frame.metrics,
    records: frame.records,
    currentContext:
      context === null
        ? null
        : {
            retrievedAt: context.retrievedAt,
            sources: context.sources,
            readings: context.readings,
          },
    limitation:
      "Current context is recorded separately and did not enter the sealed-record calculation.",
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${facilityId}-science-run-${Date.now()}.json`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function FacilityScienceLab({
  facilityId,
  sessionToken,
}: FacilityScienceLabProps) {
  const definition = FACILITY_SCIENCE[facilityId];
  const [controls, setControls] = useState<ScienceControlValues>(() =>
    initialScienceControls(facilityId),
  );
  const [toolId, setToolId] = useState(definition.tools[0].id);
  const [withheld, setWithheld] = useState(false);
  const [streaming, setStreaming] = useState(true);
  const [streamRate, setStreamRate] = useState(2);
  const [displayFps, setDisplayFps] =
    useState<DisplayRefreshRate>(
      readSignalLaboratoryDisplayFps,
    );
  const [tick, setTick] = useState(0);
  const [context, setContext] =
    useState<EnvironmentalContextSnapshot | null>(null);
  const [contextHistory, setContextHistory] = useState<
    EnvironmentalContextSnapshot[]
  >([]);
  const [contextStatus, setContextStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [contextError, setContextError] = useState<string | null>(null);
  const [contextFrozen, setContextFrozen] = useState(false);
  const [nextRefreshAt, setNextRefreshAt] = useState(
    Date.now() + CONTEXT_REFRESH_MILLISECONDS,
  );
  const [secondsToRefresh, setSecondsToRefresh] = useState(120);
  const [prediction, setPrediction] = useState<string | null>(null);
  const [misconceptionOpen, setMisconceptionOpen] = useState(false);
  const noteKey = `missing-interior:science-note:${facilityId}`;
  const [note, setNote] = useState(
    () => window.localStorage.getItem(noteKey) ?? "",
  );
  const refreshRevision = useRef(0);
  const mapPublishRevision = useRef({
    lastPublishedAt: 0,
    timer: 0,
  });

  useEffect(() => {
    setControls(initialScienceControls(facilityId));
    setToolId(FACILITY_SCIENCE[facilityId].tools[0].id);
    setWithheld(false);
    setPrediction(null);
    setNote(window.localStorage.getItem(noteKey) ?? "");
  }, [facilityId, noteKey]);

  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        setTick((current) => current + 1);
      }
    }, 1_000 / streamRate);
    return () => window.clearInterval(timer);
  }, [streamRate, streaming]);

  const refreshContext = useCallback(async () => {
    if (!sessionToken || contextFrozen) return;
    const revision = ++refreshRevision.current;
    setContextStatus("loading");
    setContextError(null);
    try {
      const snapshot = await loadEnvironmentalContext(facilityId, sessionToken);
      if (revision !== refreshRevision.current) return;
      setContext(snapshot);
      setContextHistory((current) => [...current, snapshot].slice(-24));
      setContextStatus("ready");
      setNextRefreshAt(Date.now() + CONTEXT_REFRESH_MILLISECONDS);
    } catch (reason) {
      if (revision !== refreshRevision.current) return;
      setContextStatus("error");
      setContextError(
        reason instanceof Error
          ? reason.message
          : "Current context could not be loaded.",
      );
      setNextRefreshAt(Date.now() + CONTEXT_REFRESH_MILLISECONDS * 2);
    }
  }, [contextFrozen, facilityId, sessionToken]);

  useEffect(() => {
    void refreshContext();
  }, [refreshContext]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const remaining = Math.max(
        0,
        Math.ceil((nextRefreshAt - Date.now()) / 1_000),
      );
      setSecondsToRefresh(remaining);
      if (
        remaining === 0 &&
        !contextFrozen &&
        document.visibilityState === "visible"
      ) {
        void refreshContext();
      }
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [contextFrozen, nextRefreshAt, refreshContext]);

  const frame = useMemo(
    () =>
      analyzeFacilityScience(
        facilityId,
        controls,
        withheld,
        tick,
      ),
    [controls, facilityId, tick, withheld],
  );
  const nextFrame = useMemo(
    () =>
      facilityId === "boundary_array" &&
      toolId === "oscilloscope"
        ? analyzeFacilityScience(
            facilityId,
            controls,
            withheld,
            tick + 1,
          )
        : frame,
    [
      controls,
      facilityId,
      frame,
      tick,
      toolId,
      withheld,
    ],
  );
  const sonificationSchedule = useMemo(
    () => buildScienceSonification(facilityId, toolId, frame),
    [facilityId, frame, toolId],
  );

  useEffect(() => {
    const revision = mapPublishRevision.current;
    window.clearTimeout(revision.timer);
    const publish = () => {
      publishAnalysisMapLayers(facilityId, frame.mapLayers);
      revision.lastPublishedAt = performance.now();
      revision.timer = 0;
    };
    const wait = Math.max(0, 250 - (performance.now() - revision.lastPublishedAt));
    if (wait === 0) {
      publish();
    } else {
      revision.timer = window.setTimeout(publish, wait);
    }
    return () => window.clearTimeout(revision.timer);
  }, [facilityId, frame.mapLayers]);

  const selectedTool =
    definition.tools.find((tool) => tool.id === toolId) ?? definition.tools[0];
  const oscilloscopeActive =
    facilityId === "boundary_array" &&
    toolId === "oscilloscope";
  const contextSeries = contextHistory.map(
    (snapshot) =>
      snapshot.indicators.find(
        (indicator) => indicator.id === "atmospheric-obscuration",
      )?.value ?? 0,
  );

  return (
    <section
      className={`facility-science-lab facility-science-lab-${facilityId}`}
      aria-labelledby="facility-science-lab-title"
    >
      <header className="science-lab-header">
        <div>
          <p className="eyebrow">{definition.code} · teaching instrument bank</p>
          <h2 id="facility-science-lab-title">{definition.title}</h2>
          <p>{definition.discipline}</p>
        </div>
        <div className="science-stream-status">
          <i className={streaming ? "running" : "frozen"} aria-hidden="true" />
          <strong>
            {streaming
              ? oscilloscopeActive
                ? `${streamRate} Hz analysis \u00b7 ${displayFps} FPS display cap`
                : `${streamRate} Hz analysis playback`
              : "Analysis frozen"}
          </strong>
          <small>sealed orientation record · frame {String(tick).padStart(5, "0")}</small>
        </div>
      </header>

      <section className="science-learning-objectives" aria-labelledby="science-concepts-title">
        <div>
          <p className="eyebrow">What this laboratory teaches</p>
          <h3 id="science-concepts-title">Concepts in this position</h3>
        </div>
        <div className="science-concept-grid">
          {definition.concepts.map((concept) => (
            <article key={concept.title}>
              <strong>
                {concept.title}
                <ReadingMarker
                  reading={readingById(
                    definition.readings,
                    concept.readingId,
                  )}
                  meaning={concept.explanation}
                />
              </strong>
              <p>{concept.explanation}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="science-prediction-panel">
        <div className="science-step-index">01</div>
        <div>
          <p className="eyebrow">Predict before manipulating</p>
          <h3>{definition.predictionPrompt}</h3>
          <div className="science-prediction-options">
            {definition.predictionOptions.map((option) => (
              <button
                key={option}
                type="button"
                className={prediction === option ? "selected" : ""}
                aria-pressed={prediction === option}
                onClick={() => setPrediction(option)}
              >
                {option}
              </button>
            ))}
          </div>
          <small>
            {prediction
              ? `Prediction recorded: ${prediction}. Change the controls and compare it with the measurement.`
              : "This is a laboratory note, not a score or progression gate."}
          </small>
        </div>
      </section>

      <div className="science-tool-tabs" role="tablist" aria-label="Analysis tools">
        {definition.tools.map((tool, index) => (
          <button
            key={tool.id}
            id={`science-tab-${facilityId}-${tool.id}`}
            type="button"
            role="tab"
            aria-selected={tool.id === toolId}
            aria-controls={`science-panel-${facilityId}-${tool.id}`}
            tabIndex={tool.id === toolId ? 0 : -1}
            onClick={() => setToolId(tool.id)}
            onKeyDown={(event) => {
              let nextIndex = index;
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                nextIndex = (index + 1) % definition.tools.length;
              } else if (
                event.key === "ArrowLeft" ||
                event.key === "ArrowUp"
              ) {
                nextIndex =
                  (index - 1 + definition.tools.length) %
                  definition.tools.length;
              } else if (event.key === "Home") {
                nextIndex = 0;
              } else if (event.key === "End") {
                nextIndex = definition.tools.length - 1;
              } else {
                return;
              }
              event.preventDefault();
              const nextTool = definition.tools[nextIndex];
              setToolId(nextTool.id);
              window.requestAnimationFrame(() => {
                document
                  .getElementById(
                    `science-tab-${facilityId}-${nextTool.id}`,
                  )
                  ?.focus();
              });
            }}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{tool.label}</strong>
            <small>{tool.focus}</small>
          </button>
        ))}
      </div>

      <div
        id={`science-panel-${facilityId}-${selectedTool.id}`}
        className="science-analysis-stage"
        role="tabpanel"
        aria-labelledby={`science-tab-${facilityId}-${selectedTool.id}`}
        tabIndex={0}
      >
        <header>
          <div>
            <p className="eyebrow">02 · Manipulate and observe</p>
            <h3>{selectedTool.label}</h3>
          </div>
          <div className="science-playback-controls">
            <button type="button" onClick={() => setStreaming((current) => !current)}>
              {streaming ? "Freeze playback" : "Resume playback"}
            </button>
            <label>
              <span>Analysis</span>
              <select
                value={streamRate}
                onChange={(event) =>
                  setStreamRate(Number(event.target.value))
                }
              >
                <option value="1">1 Hz</option>
                <option value="2">2 Hz</option>
                <option value="4">4 Hz</option>
              </select>
            </label>

            {oscilloscopeActive ? (
              <label>
                <span>Display</span>
                <select
                  value={displayFps}
                  aria-label={
                    "Signal oscilloscope maximum display " +
                    "frames per second"
                  }
                  onChange={(event) => {
                    const candidate = Number(
                      event.target.value,
                    ) as DisplayRefreshRate;

                    if (
                      !DISPLAY_REFRESH_RATES.includes(
                        candidate,
                      )
                    ) {
                      return;
                    }

                    setDisplayFps(candidate);
                    storeSignalLaboratoryDisplayFps(
                      candidate,
                    );
                  }}
                >
                  {DISPLAY_REFRESH_RATES.map((rate) => (
                    <option key={rate} value={rate}>
                      {rate} FPS
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
        </header>
        <FacilityToolPlot
          facilityId={facilityId}
          toolId={toolId}
          frame={frame}
          nextFrame={nextFrame}
          controls={controls}
          streaming={streaming}
          analysisRateHz={streamRate}
          displayFps={displayFps}
        />
        <div className="science-plot-legend">
          <span><i className="primary" /> primary / measured</span>
          <span><i className="secondary" /> comparison / modeled</span>
          <strong>{frame.method}</strong>
        </div>
        {isScienceSonificationSupported(facilityId, toolId) ? (
          <ScienceSonificationPanel
            schedule={sonificationSchedule}
            frameNumber={tick}
          />
        ) : null}
      </div>

      <div className="science-workbench">
        <section className="science-parameter-panel">
          <p className="eyebrow">Analysis parameters</p>
          {definition.controls.map((control) => {
            const inputId = `science-control-${facilityId}-${control.id}`;
            const descriptionId = `${inputId}-description`;
            return (
            <div className="science-parameter-control" key={control.id}>
              <div className="science-parameter-heading">
                <span>
                  <label htmlFor={inputId}>{control.label}</label>
                  <ReadingMarker
                    reading={readingById(
                      definition.readings,
                      control.readingId,
                    )}
                    meaning={control.teaches}
                  />
                </span>
                <output htmlFor={inputId}>
                  {(controls[control.id] ?? control.initial).toFixed(
                    control.step < 1 ? 1 : 0,
                  )}
                  {control.unit}
                </output>
              </div>
              <input
                id={inputId}
                type="range"
                min={control.minimum}
                max={control.maximum}
                step={control.step}
                value={controls[control.id] ?? control.initial}
                aria-describedby={descriptionId}
                onChange={(event) =>
                  setControls((current) => ({
                    ...current,
                    [control.id]: Number(event.target.value),
                  }))
                }
              />
              <small id={descriptionId}>{control.teaches}</small>
            </div>
            );
          })}
          <label className="science-withholding-control">
            <input
              type="checkbox"
              checked={withheld}
              onChange={(event) => setWithheld(event.target.checked)}
            />
            <span>
              <strong>{definition.withholdingLabel}</strong>
              <small>Recompute without this dependency and compare the result.</small>
            </span>
          </label>
          <button
            type="button"
            onClick={() => {
              setControls(initialScienceControls(facilityId));
              setWithheld(false);
              setTick(0);
            }}
          >
            Restore laboratory baseline
          </button>
        </section>

        <section className="science-results-panel">
          <p className="eyebrow">Quantitative result</p>
          <div className="science-metric-grid">
            {frame.metrics.map((metric) => (
              <article key={metric.label}>
                <span>
                  {metric.label}
                  <ReadingMarker
                    reading={readingById(
                      definition.readings,
                      metric.readingId,
                    )}
                    meaning={metric.detail}
                  />
                </span>
                <strong>{metric.value}</strong>
                <small>{metric.detail}</small>
              </article>
            ))}
          </div>
          <div className="science-observation">
            <strong>Measured observation</strong>
            <p>{frame.observation}</p>
          </div>
          <div className="science-equation">
            <code>
              {definition.equation}
              <ReadingMarker
                reading={readingById(
                  definition.readings,
                  definition.equationReadingId,
                )}
                meaning={definition.equationGuide}
              />
            </code>
            <p>{definition.equationGuide}</p>
          </div>
        </section>
      </div>

      <section className="science-context-bus">
        <header>
          <div>
            <p className="eyebrow">Current reference context</p>
            <h3>Official-source layer bus</h3>
          </div>
          <div className={`science-context-state ${contextStatus}`}>
            <strong>
              {contextFrozen
                ? "Snapshot frozen"
                : contextStatus === "ready"
                  ? "Auto-refresh active"
                  : contextStatus === "loading"
                    ? "Refreshing"
                    : contextStatus === "error"
                      ? "Partial context"
                      : "Sign-in required"}
            </strong>
            <small>
              {contextFrozen
                ? "reproducible local comparison"
                : `next request in ${secondsToRefresh}s`}
            </small>
          </div>
        </header>
        <p className="science-context-boundary">
          These readings are displayed beside the sealed record. They do not
          enter its calculations, evidence, review quality, completion, or outcomes.
        </p>
        {context ? (
          <>
            <div className="science-current-readings">
              {context.readings.map((reading) => (
                <article key={reading.id}>
                  <span>{reading.label}</span>
                  <strong>{formatReading(reading.value, reading.unit)}</strong>
                  <small>{reading.source.toUpperCase()}</small>
                </article>
              ))}
            </div>
            {contextSeries.length > 1 ? (
              <div className="science-context-history">
                <span>Retrieved-context history</span>
                <LinesPlot
                  series={[{ values: contextSeries, className: "context" }]}
                  label="History of retrieved atmospheric context values"
                />
              </div>
            ) : null}
            <ul className="science-source-list">
              {context.sources.map((source) => (
                <li key={source.id} className={source.status}>
                  <i aria-hidden="true" />
                  <span>
                    <strong>{source.label}</strong>
                    <small>
                      observed {source.observedAt ? new Date(source.observedAt).toLocaleString() : "time unavailable"}
                      {" · "}retrieved {new Date(context.retrievedAt).toLocaleString()}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="science-context-message">
            Sign in to retrieve current NWS, USGS, and NOAA SWPC readings.
            The sealed teaching dataset remains fully usable without them.
          </p>
        )}
        {contextError ? <p className="science-context-message" role="status">{contextError}</p> : null}
        <div className="science-context-actions">
          <button
            type="button"
            onClick={() => setContextFrozen((current) => !current)}
            disabled={!context}
          >
            {contextFrozen ? "Unfreeze context" : "Freeze context snapshot"}
          </button>
          <button
            type="button"
            onClick={() => void refreshContext()}
            disabled={!sessionToken || contextStatus === "loading" || contextFrozen}
          >
            Refresh now
          </button>
          <a href="/#network-heading">Open analysis layers on map</a>
        </div>
      </section>

      <section className="science-explanation-panel">
        <div className="science-step-index">03</div>
        <div>
          <p className="eyebrow">Explain and preserve uncertainty</p>
          <h3>Laboratory notebook</h3>
          <label>
            <span>
              Explain the quantitative change, name the assumption that produced it,
              and preserve one ordinary alternative.
            </span>
            <textarea
              value={note}
              rows={5}
              placeholder="The result changed from… because… This supports… It does not rule out…"
              onChange={(event) => {
                const next = event.target.value.slice(0, 2_000);
                setNote(next);
                window.localStorage.setItem(noteKey, next);
              }}
            />
          </label>
          <button
            type="button"
            className="science-misconception-toggle"
            aria-expanded={misconceptionOpen}
            onClick={() => setMisconceptionOpen((current) => !current)}
          >
            Test a common misconception
          </button>
          {misconceptionOpen ? (
            <div className="science-misconception">
              <strong>{definition.misconception}</strong>
              <p>{definition.correction}</p>
            </div>
          ) : null}
          <button
            type="button"
            onClick={() =>
              exportRun(
                facilityId,
                controls,
                frame,
                prediction,
                note,
                context,
              )
            }
          >
            Export reproducible run
          </button>
        </div>
      </section>

      <section className="science-input-record">
        <p className="eyebrow">Retained input record</p>
        <div role="table" aria-label={`${definition.title} retained inputs`}>
          <div role="row" className="science-record-heading">
            <span role="columnheader">Channel</span>
            <span role="columnheader">Reading</span>
            <span role="columnheader">Use</span>
          </div>
          {frame.records.map((record) => (
            <div
              key={record.channel}
              role="row"
              className={record.retained ? "" : "withheld"}
            >
              <strong role="cell">{record.channel}</strong>
              <span role="cell">{record.reading}</span>
              <span role="cell">{record.retained ? "retained" : "withheld"}</span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
