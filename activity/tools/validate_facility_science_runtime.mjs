import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const activityRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FACILITIES = [
  "boundary_array",
  "aeronautical_incident_center",
  "aerial_phenomena_archive",
  "holography_laboratory",
  "subsurface_resonance_station",
  "quantum_state_institute",
];

const MAX_ARRAY_LENGTH = 8_192;
const MAX_OBJECT_KEYS = 128;
const MAX_DEPTH = 16;
const MAX_TOTAL_NODES = 250_000;
const MAX_ABSOLUTE_NUMBER = 1_000_000_000_000;
const MAX_STRING_LENGTH = 8_192;
const MAX_MAP_LAYERS = 16;
const MAX_MAP_FEATURES = 2_048;
const MAX_EARTH_RADIUS_KM = 20_100;

const failures = [];

function fail(scope, detail) {
  failures.push(`${scope}: ${detail}`);
}

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function unique(values) {
  return new Set(values).size === values.length;
}

function validateBoundedValue(value, path, state, depth = 0) {
  state.nodes += 1;
  if (state.nodes > MAX_TOTAL_NODES) {
    if (!state.nodeLimitReported) {
      fail(path, `payload exceeds ${MAX_TOTAL_NODES} total nodes`);
      state.nodeLimitReported = true;
    }
    return;
  }
  if (depth > MAX_DEPTH) {
    fail(path, `payload exceeds maximum depth ${MAX_DEPTH}`);
    return;
  }
  if (typeof value === "number") {
    state.numbers += 1;
    if (!Number.isFinite(value)) {
      fail(path, `number is not finite (${String(value)})`);
    } else if (Math.abs(value) > MAX_ABSOLUTE_NUMBER) {
      fail(path, `number exceeds absolute bound ${MAX_ABSOLUTE_NUMBER}`);
    }
    return;
  }
  if (typeof value === "string") {
    if (value.length > MAX_STRING_LENGTH) {
      fail(path, `string exceeds ${MAX_STRING_LENGTH} characters`);
    }
    return;
  }
  if (
    value === null ||
    typeof value === "boolean"
  ) {
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > MAX_ARRAY_LENGTH) {
      fail(path, `array has ${value.length} items; limit is ${MAX_ARRAY_LENGTH}`);
      return;
    }
    value.forEach((item, index) =>
      validateBoundedValue(item, `${path}[${index}]`, state, depth + 1),
    );
    return;
  }
  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length > MAX_OBJECT_KEYS) {
      fail(path, `object has ${entries.length} keys; limit is ${MAX_OBJECT_KEYS}`);
      return;
    }
    for (const [key, item] of entries) {
      validateBoundedValue(item, `${path}.${key}`, state, depth + 1);
    }
    return;
  }
  fail(path, `unsupported runtime value type ${typeof value}`);
}

function validateMapLayers(layers, scope, requireLayer) {
  if (!Array.isArray(layers)) {
    fail(scope, "mapLayers must be an array");
    return;
  }
  if (requireLayer && layers.length === 0) {
    fail(scope, "normal analysis path must publish at least one map layer");
  }
  if (layers.length > MAX_MAP_LAYERS) {
    fail(scope, `publishes ${layers.length} layers; limit is ${MAX_MAP_LAYERS}`);
  }

  const layerIds = [];
  for (const [layerIndex, layer] of layers.entries()) {
    const layerScope = `${scope}.mapLayers[${layerIndex}]`;
    if (!isRecord(layer)) {
      fail(layerScope, "layer must be an object");
      continue;
    }
    if (typeof layer.layerId !== "string" || layer.layerId.length === 0) {
      fail(layerScope, "layerId must be a nonempty string");
    } else {
      layerIds.push(layer.layerId);
    }
    if (typeof layer.label !== "string" || layer.label.length === 0) {
      fail(layerScope, "label must be a nonempty string");
    }

    if (layer.kind === "trajectory") {
      if (!Array.isArray(layer.samples)) {
        fail(layerScope, "trajectory samples must be an array");
        continue;
      }
      if (layer.samples.length > MAX_MAP_FEATURES) {
        fail(
          layerScope,
          `trajectory has ${layer.samples.length} samples; limit is ${MAX_MAP_FEATURES}`,
        );
      }
      const sampleIds = [];
      for (const [sampleIndex, sample] of layer.samples.entries()) {
        const sampleScope = `${layerScope}.samples[${sampleIndex}]`;
        if (!isRecord(sample)) {
          fail(sampleScope, "sample must be an object");
          continue;
        }
        if (typeof sample.sampleId !== "string" || sample.sampleId.length === 0) {
          fail(sampleScope, "sampleId must be a nonempty string");
        } else {
          sampleIds.push(sample.sampleId);
        }
        if (
          !Number.isFinite(sample.latitude) ||
          sample.latitude < -90 ||
          sample.latitude > 90
        ) {
          fail(sampleScope, `latitude is outside [-90, 90] (${String(sample.latitude)})`);
        }
        if (
          !Number.isFinite(sample.longitude) ||
          sample.longitude < -180 ||
          sample.longitude > 180
        ) {
          fail(sampleScope, `longitude is outside [-180, 180] (${String(sample.longitude)})`);
        }
        if (
          !Number.isFinite(sample.uncertaintyKm) ||
          sample.uncertaintyKm < 0 ||
          sample.uncertaintyKm > MAX_EARTH_RADIUS_KM
        ) {
          fail(
            sampleScope,
            `uncertaintyKm must be within [0, ${MAX_EARTH_RADIUS_KM}]`,
          );
        }
        if (
          typeof sample.observedAt !== "string" ||
          !Number.isFinite(Date.parse(sample.observedAt))
        ) {
          fail(sampleScope, "observedAt must be a valid timestamp");
        }
      }
      if (!unique(sampleIds)) {
        fail(layerScope, "trajectory sample IDs must be unique");
      }
      continue;
    }

    if (layer.kind === "heatmap") {
      if (!Array.isArray(layer.cells)) {
        fail(layerScope, "heatmap cells must be an array");
        continue;
      }
      if (layer.cells.length > MAX_MAP_FEATURES) {
        fail(
          layerScope,
          `heatmap has ${layer.cells.length} cells; limit is ${MAX_MAP_FEATURES}`,
        );
      }
      const cellIds = [];
      for (const [cellIndex, cell] of layer.cells.entries()) {
        const cellScope = `${layerScope}.cells[${cellIndex}]`;
        if (!isRecord(cell)) {
          fail(cellScope, "cell must be an object");
          continue;
        }
        if (typeof cell.cellId !== "string" || cell.cellId.length === 0) {
          fail(cellScope, "cellId must be a nonempty string");
        } else {
          cellIds.push(cell.cellId);
        }
        if (
          !Number.isFinite(cell.latitude) ||
          cell.latitude < -90 ||
          cell.latitude > 90
        ) {
          fail(cellScope, `latitude is outside [-90, 90] (${String(cell.latitude)})`);
        }
        if (
          !Number.isFinite(cell.longitude) ||
          cell.longitude < -180 ||
          cell.longitude > 180
        ) {
          fail(cellScope, `longitude is outside [-180, 180] (${String(cell.longitude)})`);
        }
        if (
          !Number.isFinite(cell.intensity) ||
          cell.intensity < 0 ||
          cell.intensity > 1
        ) {
          fail(cellScope, `intensity must be within [0, 1] (${String(cell.intensity)})`);
        }
        if (
          !Number.isFinite(cell.radiusKm) ||
          cell.radiusKm <= 0 ||
          cell.radiusKm > MAX_EARTH_RADIUS_KM
        ) {
          fail(
            cellScope,
            `radiusKm must be within (0, ${MAX_EARTH_RADIUS_KM}]`,
          );
        }
        if (
          !Array.isArray(cell.sourceReferences) ||
          cell.sourceReferences.length === 0 ||
          cell.sourceReferences.length > 32
        ) {
          fail(cellScope, "sourceReferences must contain between 1 and 32 entries");
        }
      }
      if (!unique(cellIds)) {
        fail(layerScope, "heatmap cell IDs must be unique");
      }
      continue;
    }

    fail(layerScope, `unsupported map-layer kind ${String(layer.kind)}`);
  }

  if (!unique(layerIds)) {
    fail(scope, "map-layer IDs must be unique within a frame");
  }
}

function validateFrame(frame, scope, { requireMapLayer }) {
  if (!isRecord(frame)) {
    fail(scope, "analysis result must be an object");
    return;
  }

  const state = { nodes: 0, numbers: 0, nodeLimitReported: false };
  validateBoundedValue(frame, scope, state);
  if (state.numbers === 0) {
    fail(scope, "analysis result contains no numeric data");
  }

  if (!Array.isArray(frame.metrics) || frame.metrics.length < 3 || frame.metrics.length > 32) {
    fail(scope, "metrics must contain between 3 and 32 entries");
  }
  if (!Array.isArray(frame.records) || frame.records.length < 1 || frame.records.length > 512) {
    fail(scope, "records must contain between 1 and 512 entries");
  }
  if (!isRecord(frame.series)) {
    fail(scope, "series must be an object");
  } else {
    const seriesEntries = Object.entries(frame.series);
    if (seriesEntries.length === 0 || seriesEntries.length > 32) {
      fail(scope, "series must contain between 1 and 32 named arrays");
    }
    for (const [seriesId, values] of seriesEntries) {
      if (!Array.isArray(values) || values.length > MAX_ARRAY_LENGTH) {
        fail(`${scope}.series.${seriesId}`, "series must be a bounded array");
      }
    }
  }
  if (!Array.isArray(frame.matrix) || frame.matrix.length > 256) {
    fail(scope, "matrix must have at most 256 rows");
  } else if (
    frame.matrix.some((row) => !Array.isArray(row) || row.length > 256)
  ) {
    fail(scope, "each matrix row must have at most 256 columns");
  }
  if (!Array.isArray(frame.points) || frame.points.length > 4_096) {
    fail(scope, "points must be an array of at most 4096 entries");
  }
  if (!Array.isArray(frame.bars) || frame.bars.length > 4_096) {
    fail(scope, "bars must be an array of at most 4096 entries");
  }
  if (
    (!isRecord(frame.series) || Object.keys(frame.series).length === 0) &&
    (!Array.isArray(frame.matrix) || frame.matrix.length === 0) &&
    (!Array.isArray(frame.points) || frame.points.length === 0) &&
    (!Array.isArray(frame.bars) || frame.bars.length === 0)
  ) {
    fail(scope, "frame must contain at least one plot payload");
  }
  if (typeof frame.method !== "string" || frame.method.length === 0) {
    fail(scope, "method must be a nonempty string");
  }
  if (typeof frame.observation !== "string" || frame.observation.length === 0) {
    fail(scope, "observation must be a nonempty string");
  }

  validateMapLayers(frame.mapLayers, scope, requireMapLayer);
}

function withoutObservedAt(value) {
  if (Array.isArray(value)) return value.map(withoutObservedAt);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => key !== "observedAt")
      .map(([key, item]) => [key, withoutObservedAt(item)]),
  );
}

function stableJson(value) {
  return JSON.stringify(withoutObservedAt(value));
}

function calculationPayload(frame) {
  return {
    metricValues: Array.isArray(frame.metrics)
      ? frame.metrics.map((metric) => metric?.value)
      : [],
    series: frame.series,
    matrix: frame.matrix,
    points: frame.points,
    bars: frame.bars,
    mapLayers: frame.mapLayers,
  };
}

let vite;
try {
  vite = await createServer({
    root: activityRoot,
    configFile: false,
    appType: "custom",
    logLevel: "silent",
    server: {
      middlewareMode: true,
      hmr: false,
      watch: null,
    },
  });

  const science = await vite.ssrLoadModule("/src/shared/facility-science.ts");
  const definitions = science.FACILITY_SCIENCE;
  const initialControls = science.initialScienceControls;
  const analyze = science.analyzeFacilityScience;

  if (!isRecord(definitions)) {
    fail("module", "FACILITY_SCIENCE export is missing");
  }
  if (typeof initialControls !== "function") {
    fail("module", "initialScienceControls export is missing");
  }
  if (typeof analyze !== "function") {
    fail("module", "analyzeFacilityScience export is missing");
  }

  if (
    isRecord(definitions) &&
    typeof initialControls === "function" &&
    typeof analyze === "function"
  ) {
    const runtimeIds = Object.keys(definitions);
    if (
      runtimeIds.length !== FACILITIES.length ||
      !FACILITIES.every((facilityId) => runtimeIds.includes(facilityId))
    ) {
      fail("module", `runtime definitions do not contain exactly ${FACILITIES.join(", ")}`);
    }

    for (const facilityId of FACILITIES) {
      const definition = definitions[facilityId];
      const scope = facilityId;
      if (!isRecord(definition)) {
        fail(scope, "runtime definition is missing");
        continue;
      }
      if (!Array.isArray(definition.controls) || definition.controls.length !== 5) {
        fail(scope, `must expose exactly five controls at runtime`);
        continue;
      }

      const defaults = initialControls(facilityId);
      if (!isRecord(defaults)) {
        fail(scope, "initial controls must be an object");
        continue;
      }
      const controlIds = definition.controls.map((control) => control?.id);
      if (
        !controlIds.every(
          (controlId) =>
            typeof controlId === "string" &&
            Number.isFinite(defaults[controlId]),
        )
      ) {
        fail(scope, "initial controls must provide a finite value for every control");
        continue;
      }

      for (const withheld of [false, true]) {
        const variant = withheld ? "withheld" : "default";
        const first = analyze(facilityId, { ...defaults }, withheld, 17);
        const second = analyze(facilityId, { ...defaults }, withheld, 17);
        validateFrame(first, `${scope}.${variant}`, {
          requireMapLayer: !withheld,
        });
        if (stableJson(first) !== stableJson(second)) {
          fail(
            `${scope}.${variant}`,
            "same controls and tick produce nondeterministic output after observedAt removal",
          );
        }
      }

      for (const control of definition.controls) {
        const controlScope = `${scope}.${String(control?.id)}`;
        if (
          !isRecord(control) ||
          typeof control.id !== "string" ||
          !Number.isFinite(control.minimum) ||
          !Number.isFinite(control.maximum) ||
          control.minimum >= control.maximum
        ) {
          fail(controlScope, "control must provide finite ordered minimum and maximum values");
          continue;
        }

        const minimumFrame = analyze(
          facilityId,
          { ...defaults, [control.id]: control.minimum },
          false,
          23,
        );
        const maximumFrame = analyze(
          facilityId,
          { ...defaults, [control.id]: control.maximum },
          false,
          23,
        );
        validateFrame(minimumFrame, `${controlScope}.minimum`, {
          requireMapLayer: true,
        });
        validateFrame(maximumFrame, `${controlScope}.maximum`, {
          requireMapLayer: true,
        });

        const minimumPayload = stableJson(calculationPayload(minimumFrame));
        const maximumPayload = stableJson(calculationPayload(maximumFrame));
        if (minimumPayload === maximumPayload) {
          fail(
            controlScope,
            "minimum and maximum change only prose/records or have no effect on calculated, plotted, or mapped output",
          );
        }
      }
    }
  }
} catch (error) {
  fail(
    "runtime loader",
    error instanceof Error ? error.stack ?? error.message : String(error),
  );
} finally {
  await vite?.close();
}

if (failures.length > 0) {
  console.error(
    `Facility science runtime validation failed (${failures.length} issue${failures.length === 1 ? "" : "s"}):`,
  );
  for (const failure of failures) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log(
    "Facility science runtime validation passed: " +
      "6 facilities, 12 deterministic default/withheld frames, " +
      "30 independently effective controls, bounded scientific payloads and map layers.",
  );
}
