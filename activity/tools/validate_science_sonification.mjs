import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const activityRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(
  activityRoot,
  "src/lib/science-sonification.ts",
);
const source = await readFile(sourcePath, "utf8");
const sonification = await import(pathToFileURL(sourcePath));

const {
  SCIENCE_SONIFICATION_LIMITS,
  SUPPORTED_SCIENCE_SONIFICATION_TOOLS,
  buildScienceSonification,
  isScienceSonificationSupported,
} = sonification;

function frame(overrides = {}) {
  return {
    metrics: [],
    records: [],
    series: {},
    matrix: [],
    points: [],
    bars: [],
    method: "",
    observation: "",
    mapLayers: [],
    ...overrides,
  };
}

const boundaryFrame = frame({
  metrics: [
    {
      label: "Nyquist frequency",
      value: "32.0 Hz",
      detail: "",
      readingId: "sampling",
    },
  ],
  records: [
    { channel: "Optical photometry", reading: "8 samples", retained: true },
    { channel: "Radio return", reading: "40 ms delay", retained: true },
  ],
  series: {
    optical: [-1, -0.5, 0, 0.5, 1, Number.NaN, 0.25, -0.25],
    radio: [-0.8, -0.4, 0, 0.4, 0.8, 0.2, 0.1, -0.1],
    spectrum: [0, 0.1, 0.9, Number.NaN, 0.25],
    lag: [-0.4, 0, 0.75, 0.3, -0.1],
    residual: [-0.1, 0, 0.2, Number.NaN, -0.05],
  },
});

const stationRecords = [0, 1, 2, 3, 4].map((index) => ({
  channel: `Station ${String(index + 1).padStart(2, "0")}`,
  reading: "",
  retained: index !== 3,
}));
const subsurfaceFrame = frame({
  metrics: [
    {
      label: "Modeled depth span",
      value: "18.0 km",
      detail: "",
      readingId: "depth",
    },
  ],
  records: stationRecords,
  series: {
    depthResponse: [0.1, 0, 0.8, Number.NaN, 0.45],
    spectrum: [0, 0.15, 0.9, 0.3, Number.NaN],
    stations: [0.91, 0.84, 0, 0.72],
  },
  matrix: [
    [0, 0.1, 0.25, 0.4],
    [0.05, Number.NaN, 0.8, 0.3],
    [0.1, 0.2, 0.45, 0.2],
  ],
});

assert.deepEqual(
  SUPPORTED_SCIENCE_SONIFICATION_TOOLS.boundary_array,
  ["oscilloscope", "spectrum", "correlation"],
);
assert.deepEqual(
  SUPPORTED_SCIENCE_SONIFICATION_TOOLS.subsurface_resonance_station,
  ["depthFrequency", "spectrum", "stations"],
);
assert.equal(
  isScienceSonificationSupported("boundary_array", "oscilloscope"),
  true,
);
assert.equal(
  isScienceSonificationSupported("subsurface_resonance_station", "stations"),
  true,
);
assert.equal(
  isScienceSonificationSupported("quantum_state_institute", "spectrum"),
  false,
);

const schedules = [
  buildScienceSonification("boundary_array", "oscilloscope", boundaryFrame),
  buildScienceSonification("boundary_array", "spectrum", boundaryFrame),
  buildScienceSonification("boundary_array", "correlation", boundaryFrame),
  buildScienceSonification(
    "subsurface_resonance_station",
    "depthFrequency",
    subsurfaceFrame,
  ),
  buildScienceSonification(
    "subsurface_resonance_station",
    "spectrum",
    subsurfaceFrame,
  ),
  buildScienceSonification(
    "subsurface_resonance_station",
    "stations",
    subsurfaceFrame,
  ),
];

for (const schedule of schedules) {
  assert.equal(schedule.status, "available");
  assert.equal(schedule.unavailableReason, null);
  assert.equal(schedule.accessibility.optional, true);
  assert.equal(schedule.accessibility.audioRequiredForProgression, false);
  assert.equal(schedule.accessibility.visibleLegendRequired, true);
  assert.match(schedule.accessibility.textEquivalent, /No task.+requires hearing/);
  assert.ok(schedule.events.length > 0);
  assert.ok(
    schedule.events.length <= SCIENCE_SONIFICATION_LIMITS.maximumEvents,
  );
  assert.ok(schedule.durationSeconds <= 12);
  assert.ok(schedule.legends.length > 0);

  for (const legend of schedule.legends) {
    assert.ok(legend.sourceSeries.length > 0);
    assert.ok(legend.sourceUnit.length > 0);
    assert.ok(legend.pitchMapping.length > 0);
    assert.ok(legend.timeMapping.length > 0);
    assert.ok(legend.gainMapping.length > 0);
    assert.ok(legend.normalization.length > 0);
    assert.ok(legend.timeCompression.length > 0);
    assert.ok(legend.plainLanguage.length > 0);
    assert.ok(legend.outputPitchHz.minimum >= 110);
    assert.ok(legend.outputPitchHz.maximum <= 1_760);
    assert.ok(legend.outputGain.maximum <= 0.18);
  }

  for (const scheduledEvent of schedule.events) {
    assert.ok(scheduledEvent.startSeconds >= 0);
    assert.ok(
      scheduledEvent.startSeconds + scheduledEvent.durationSeconds <=
        schedule.durationSeconds + 0.000001,
    );
    assert.ok(scheduledEvent.gain >= 0);
    assert.ok(scheduledEvent.gain <= 0.18);
    if (scheduledEvent.kind === "tone") {
      assert.ok(scheduledEvent.frequencyHz >= 110);
      assert.ok(scheduledEvent.frequencyHz <= 1_760);
      assert.ok(["observed", "zero"].includes(scheduledEvent.status));
      assert.notEqual(scheduledEvent.waveform, null);
    } else {
      assert.equal(scheduledEvent.frequencyHz, null);
      assert.equal(scheduledEvent.gain, 0);
      assert.equal(scheduledEvent.waveform, null);
      assert.ok(["missing", "withheld"].includes(scheduledEvent.status));
    }
  }
}

const deterministicA = buildScienceSonification(
  "boundary_array",
  "oscilloscope",
  boundaryFrame,
);
const deterministicB = buildScienceSonification(
  "boundary_array",
  "oscilloscope",
  structuredClone(boundaryFrame),
);
assert.deepEqual(deterministicA, deterministicB);

const missingAndZero = buildScienceSonification(
  "boundary_array",
  "spectrum",
  boundaryFrame,
);
assert.ok(missingAndZero.events.some((candidate) => candidate.status === "zero"));
assert.ok(
  missingAndZero.events.some((candidate) => candidate.status === "missing"),
);
assert.ok(
  missingAndZero.events
    .filter((candidate) => candidate.status === "missing")
    .every(
      (candidate) =>
        candidate.kind === "silence" && candidate.sourceValue === null,
    ),
);

const withheldBoundaryFrame = frame({
  ...boundaryFrame,
  records: [
    { channel: "Optical photometry", reading: "8 samples", retained: true },
    { channel: "Radio return", reading: "40 ms delay", retained: false },
  ],
  series: {
    ...boundaryFrame.series,
    radio: [],
    lag: [],
    residual: [],
  },
});
const withheldCorrelation = buildScienceSonification(
  "boundary_array",
  "correlation",
  withheldBoundaryFrame,
);
assert.equal(withheldCorrelation.status, "unavailable");
assert.match(withheldCorrelation.unavailableReason, /withheld/i);
assert.equal(
  withheldCorrelation.events.every(
    (candidate) =>
      candidate.kind === "silence" && candidate.status === "withheld",
  ),
  true,
);
assert.equal(
  withheldCorrelation.legends.every(
    (candidate) => candidate.sourceStatus === "withheld",
  ),
  true,
);

const withheldWaveform = buildScienceSonification(
  "boundary_array",
  "oscilloscope",
  withheldBoundaryFrame,
);
assert.equal(withheldWaveform.status, "available");
assert.ok(
  withheldWaveform.events.some(
    (candidate) =>
      candidate.sourceSeries === "series.radio" &&
      candidate.status === "withheld" &&
      candidate.kind === "silence",
  ),
);
assert.equal(
  withheldWaveform.legends.find(
    (candidate) => candidate.sourceSeries === "series.radio",
  )?.sourceStatus,
  "withheld",
);

const missingOpticalFrame = frame({
  ...boundaryFrame,
  series: {
    ...boundaryFrame.series,
    optical: [],
  },
});
const missingOptical = buildScienceSonification(
  "boundary_array",
  "oscilloscope",
  missingOpticalFrame,
);
assert.ok(
  missingOptical.events.some(
    (candidate) =>
      candidate.sourceSeries === "series.optical" &&
      candidate.status === "missing" &&
      candidate.kind === "silence",
  ),
);

const stations = buildScienceSonification(
  "subsurface_resonance_station",
  "stations",
  subsurfaceFrame,
);
assert.deepEqual(
  stations.events.map((candidate) => candidate.sourceValue),
  [0.91, 0.84, 0, null, 0.72],
);
assert.deepEqual(
  stations.events.map((candidate) => candidate.status),
  ["observed", "observed", "zero", "withheld", "observed"],
);
assert.match(stations.legends[0].plainLanguage, /Station 04 is withheld/);

const depthFrequency = buildScienceSonification(
  "subsurface_resonance_station",
  "depthFrequency",
  subsurfaceFrame,
  { maxEvents: 7, durationSeconds: 99 },
);
assert.equal(depthFrequency.durationSeconds, 12);
assert.ok(depthFrequency.events.length <= 7);
const originalFieldValues = subsurfaceFrame.matrix.flat();
for (const scheduledEvent of depthFrequency.events.filter(
  (candidate) => candidate.sourceSeries === "matrix",
)) {
  if (scheduledEvent.sourceValue !== null) {
    assert.ok(originalFieldValues.includes(scheduledEvent.sourceValue));
  }
}

const unsupported = buildScienceSonification(
  "quantum_state_institute",
  "spectrum",
  frame(),
);
assert.equal(unsupported.status, "unavailable");
assert.match(unsupported.unavailableReason, /not yet mapped/i);
assert.deepEqual(unsupported.events, []);

assert.doesNotMatch(source, /Math\.random|Date\.now|new Date/u);
assert.match(source, /No value is interpolated/u);
assert.match(source, /audioRequiredForProgression:\s*false/u);

console.log(
  `Science sonification validation passed (${schedules.length} mapped schedules; deterministic, bounded, optional, and gap-preserving).`,
);
