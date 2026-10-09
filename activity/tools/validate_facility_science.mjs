import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const activityRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sciencePath = resolve(activityRoot, "src/shared/facility-science.ts");
const busPath = resolve(activityRoot, "src/lib/analysis-layer-bus.ts");
const labPath = resolve(activityRoot, "src/components/FacilityScienceLab.tsx");
const infoPopoverPath = resolve(
  activityRoot,
  "src/components/ViewportInfoPopover.tsx",
);
const metricCardPath = resolve(activityRoot, "src/components/MetricCard.tsx");
const appPath = resolve(activityRoot, "src/App.tsx");
const mapPath = resolve(activityRoot, "src/components/GeographicFieldMap.tsx");
const stylesPath = resolve(activityRoot, "src/styles.css");

const FACILITIES = [
  "boundary_array",
  "aeronautical_incident_center",
  "aerial_phenomena_archive",
  "holography_laboratory",
  "subsurface_resonance_station",
  "quantum_state_institute",
];

const FRAME_FUNCTIONS = {
  boundary_array: "boundaryFrame",
  aeronautical_incident_center: "aeronauticalFrame",
  aerial_phenomena_archive: "archiveFrame",
  holography_laboratory: "holographyFrame",
  subsurface_resonance_station: "subsurfaceFrame",
  quantum_state_institute: "quantumFrame",
};

const errors = [];

function check(condition, message) {
  if (!condition) errors.push(message);
}

function scanClosing(source, openingIndex, opening, closing) {
  let depth = 0;
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;

  for (let index = openingIndex; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];

    if (lineComment) {
      if (character === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (character === "*" && next === "/") {
        blockComment = false;
        index += 1;
      }
      continue;
    }
    if (quote !== null) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === quote) {
        quote = null;
      }
      continue;
    }
    if (character === "/" && next === "/") {
      lineComment = true;
      index += 1;
      continue;
    }
    if (character === "/" && next === "*") {
      blockComment = true;
      index += 1;
      continue;
    }
    if (character === '"' || character === "'" || character === "`") {
      quote = character;
      continue;
    }
    if (character === opening) depth += 1;
    if (character === closing) {
      depth -= 1;
      if (depth === 0) return index;
    }
  }

  throw new Error(`Unclosed ${opening} at source offset ${openingIndex}.`);
}

function segmentAfter(source, marker, opening, closing, label = marker) {
  const markerIndex = source.indexOf(marker);
  if (markerIndex < 0) {
    throw new Error(`Missing ${label}.`);
  }
  const openingIndex = source.indexOf(opening, markerIndex + marker.length);
  if (openingIndex < 0) {
    throw new Error(`Missing ${opening} after ${label}.`);
  }
  const closingIndex = scanClosing(source, openingIndex, opening, closing);
  return source.slice(openingIndex, closingIndex + 1);
}

function topLevelCssRule(source, selector) {
  const escaped = selector.replaceAll(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const match = new RegExp(`^${escaped}\\s*\\{`, "mu").exec(source);
  if (!match) {
    throw new Error(`Missing top-level ${selector} CSS rule.`);
  }
  const openingIndex = source.indexOf("{", match.index);
  const closingIndex = scanClosing(source, openingIndex, "{", "}");
  return source.slice(openingIndex + 1, closingIndex);
}

function topLevelObjects(arraySource) {
  const objects = [];
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;

  for (let index = 1; index < arraySource.length - 1; index += 1) {
    const character = arraySource[index];
    const next = arraySource[index + 1];

    if (lineComment) {
      if (character === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (character === "*" && next === "/") {
        blockComment = false;
        index += 1;
      }
      continue;
    }
    if (quote !== null) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === quote) {
        quote = null;
      }
      continue;
    }
    if (character === "/" && next === "/") {
      lineComment = true;
      index += 1;
      continue;
    }
    if (character === "/" && next === "*") {
      blockComment = true;
      index += 1;
      continue;
    }
    if (character === '"' || character === "'" || character === "`") {
      quote = character;
      continue;
    }
    if (character === "{") {
      const closingIndex = scanClosing(arraySource, index, "{", "}");
      objects.push(arraySource.slice(index, closingIndex + 1));
      index = closingIndex;
    }
  }

  return objects;
}

function stringProperty(source, property) {
  const escaped = property.replaceAll(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  return source.match(new RegExp(`\\b${escaped}\\s*:\\s*"([^"]+)"`, "u"))?.[1] ?? null;
}

function numberProperty(source, property) {
  const escaped = property.replaceAll(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const raw = source.match(
    new RegExp(
      `\\b${escaped}\\s*:\\s*(-?(?:(?:\\d(?:_?\\d)*)(?:\\.(?:\\d(?:_?\\d)*))?|\\.(?:\\d(?:_?\\d)*)))`,
      "u",
    ),
  )?.[1];
  return raw === undefined ? null : Number(raw.replaceAll("_", ""));
}

function unique(values) {
  return new Set(values).size === values.length;
}

function stripStringsAndComments(source) {
  let result = "";
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];

    if (lineComment) {
      if (character === "\n") {
        lineComment = false;
        result += "\n";
      } else {
        result += " ";
      }
      continue;
    }
    if (blockComment) {
      if (character === "*" && next === "/") {
        result += "  ";
        blockComment = false;
        index += 1;
      } else {
        result += character === "\n" ? "\n" : " ";
      }
      continue;
    }
    if (quote !== null) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === quote) {
        quote = null;
      }
      result += character === "\n" ? "\n" : " ";
      continue;
    }
    if (character === "/" && next === "/") {
      result += "  ";
      lineComment = true;
      index += 1;
      continue;
    }
    if (character === "/" && next === "*") {
      result += "  ";
      blockComment = true;
      index += 1;
      continue;
    }
    if (character === '"' || character === "'" || character === "`") {
      quote = character;
      result += " ";
      continue;
    }
    result += character;
  }

  return result;
}

function functionParts(source, functionName) {
  const marker = `function ${functionName}`;
  const markerIndex = source.indexOf(marker);
  if (markerIndex < 0) throw new Error(`Missing ${functionName}().`);
  const parameters = segmentAfter(
    source.slice(markerIndex),
    marker,
    "(",
    ")",
    `${functionName} parameters`,
  );
  const bodySearchStart = markerIndex + marker.length + parameters.length;
  const bodyOpening = source.indexOf("{", bodySearchStart);
  if (bodyOpening < 0) throw new Error(`Missing ${functionName}() body.`);
  const bodyClosing = scanClosing(source, bodyOpening, "{", "}");
  return {
    parameters,
    body: source.slice(bodyOpening, bodyClosing + 1),
  };
}

const [
  scienceSource,
  busSource,
  labSource,
  infoPopoverSource,
  metricCardSource,
  appSource,
  mapSource,
  stylesSource,
] =
  await Promise.all([
    readFile(sciencePath, "utf8"),
    readFile(busPath, "utf8"),
    readFile(labPath, "utf8"),
    readFile(infoPopoverPath, "utf8"),
    readFile(metricCardPath, "utf8"),
    readFile(appPath, "utf8"),
    readFile(mapPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

let definitionsSource;
try {
  definitionsSource = segmentAfter(
    scienceSource,
    "export const FACILITY_SCIENCE",
    "{",
    "}",
    "FACILITY_SCIENCE definition",
  );
} catch (error) {
  errors.push(error instanceof Error ? error.message : String(error));
  definitionsSource = "{}";
}

const discoveredFacilities = [
  ...definitionsSource.matchAll(/^  ([a-z][a-z0-9_]*): \{/gmu),
].map((match) => match[1]);
check(
  discoveredFacilities.length === FACILITIES.length &&
    FACILITIES.every((facilityId) => discoveredFacilities.includes(facilityId)),
  `FACILITY_SCIENCE must define exactly these six facilities: ${FACILITIES.join(", ")}.`,
);
check(unique(discoveredFacilities), "Facility IDs must be unique.");

const facilityCodes = [];
const facilityTitles = [];
const qualifiedIds = [];
const allReadingIds = [];
const allReadingUrls = [];

for (const facilityId of FACILITIES) {
  let definition;
  try {
    definition = segmentAfter(
      definitionsSource,
      `${facilityId}:`,
      "{",
      "}",
      `${facilityId} definition`,
    );
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
    continue;
  }

  const code = stringProperty(definition, "code");
  const title = stringProperty(definition, "title");
  check(Boolean(code), `${facilityId} must have a code.`);
  check(Boolean(title), `${facilityId} must have a title.`);
  if (code) facilityCodes.push(code);
  if (title) facilityTitles.push(title);

  let controls = [];
  let tools = [];
  let concepts = [];
  let readings = [];
  try {
    controls = topLevelObjects(
      segmentAfter(definition, "controls:", "[", "]", `${facilityId} controls`),
    );
    tools = topLevelObjects(
      segmentAfter(definition, "tools:", "[", "]", `${facilityId} tools`),
    );
    concepts = topLevelObjects(
      segmentAfter(definition, "concepts:", "[", "]", `${facilityId} concepts`),
    );
    readings = topLevelObjects(
      segmentAfter(definition, "readings:", "[", "]", `${facilityId} readings`),
    );
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
    continue;
  }

  check(controls.length >= 5, `${facilityId} must define at least five parameters.`);
  check(tools.length >= 3, `${facilityId} must define at least three tools.`);
  check(concepts.length >= 4, `${facilityId} must define at least four concepts.`);
  check(readings.length >= 4, `${facilityId} must define at least four readings.`);

  const controlIds = controls.map((control) => stringProperty(control, "id"));
  const toolIds = tools.map((tool) => stringProperty(tool, "id"));
  const readingIds = readings.map((reading) => stringProperty(reading, "id"));
  const readingIdSet = new Set(readingIds.filter(Boolean));
  const localIds = [...controlIds, ...toolIds];
  check(
    localIds.every((id) => typeof id === "string" && /^[a-z][A-Za-z0-9]*$/u.test(id)),
    `${facilityId} parameter and tool IDs must be nonempty lower-camel identifiers.`,
  );
  check(unique(localIds), `${facilityId} parameter and tool IDs must be unique.`);
  check(
    readingIds.every(
      (id) => typeof id === "string" && /^[a-z][a-z0-9_]*$/u.test(id),
    ),
    `${facilityId} reading IDs must be nonempty lower-snake identifiers.`,
  );
  check(unique(readingIds), `${facilityId} reading IDs must be unique.`);
  for (const id of localIds) {
    if (id) qualifiedIds.push(`${facilityId}:${id}`);
  }
  for (const id of readingIds) {
    if (id) allReadingIds.push(id);
  }

  for (const control of controls) {
    const id = stringProperty(control, "id") ?? "(missing control ID)";
    const readingId = stringProperty(control, "readingId");
    const minimum = numberProperty(control, "minimum");
    const maximum = numberProperty(control, "maximum");
    const step = numberProperty(control, "step");
    const initial = numberProperty(control, "initial");
    check(Boolean(stringProperty(control, "label")), `${facilityId}:${id} must have a label.`);
    check(Boolean(stringProperty(control, "teaches")), `${facilityId}:${id} must name what it teaches.`);
    check(
      Boolean(readingId),
      `${facilityId}:${id} must declare a readingId.`,
    );
    if (readingId) {
      check(
        readingIdSet.has(readingId),
        `${facilityId}:${id} maps to unknown reading ID ${readingId}.`,
      );
    }
    check(
      minimum !== null &&
        maximum !== null &&
        step !== null &&
        initial !== null &&
        minimum < maximum &&
        step > 0 &&
        initial >= minimum &&
        initial <= maximum,
      `${facilityId}:${id} must have finite ordered bounds, a positive step, and an in-range initial value.`,
    );
  }

  for (const tool of tools) {
    const id = stringProperty(tool, "id") ?? "(missing tool ID)";
    check(Boolean(stringProperty(tool, "label")), `${facilityId}:${id} must have a tool label.`);
    check(Boolean(stringProperty(tool, "focus")), `${facilityId}:${id} must have a scientific focus.`);
  }

  const conceptTitles = concepts.map((concept) => stringProperty(concept, "title"));
  check(
    conceptTitles.every(Boolean) && unique(conceptTitles),
    `${facilityId} concept titles must be present and unique.`,
  );
  for (const concept of concepts) {
    const conceptTitle =
      stringProperty(concept, "title") ?? "(missing concept title)";
    const readingId = stringProperty(concept, "readingId");
    check(
      Boolean(stringProperty(concept, "explanation")),
      `${facilityId}:${conceptTitle} must explain the concept.`,
    );
    check(
      Boolean(readingId),
      `${facilityId}:${conceptTitle} must declare a readingId.`,
    );
    if (readingId) {
      check(
        readingIdSet.has(readingId),
        `${facilityId}:${conceptTitle} maps to unknown reading ID ${readingId}.`,
      );
    }
  }

  for (const reading of readings) {
    const readingId = stringProperty(reading, "id");
    const readingTitle = stringProperty(reading, "title");
    const urlValue = stringProperty(reading, "url");
    const access = stringProperty(reading, "access");
    check(Boolean(readingId), `${facilityId} readings must have stable IDs.`);
    check(Boolean(readingTitle), `${facilityId} readings must have titles.`);
    check(Boolean(stringProperty(reading, "source")), `${facilityId}:${readingTitle ?? "(untitled reading)"} must name its source.`);
    check(
      typeof access === "string" && /(free|open|public|cc by)/iu.test(access),
      `${facilityId}:${readingTitle ?? "(untitled reading)"} must state its open-access basis.`,
    );
    if (!urlValue) {
      errors.push(`${facilityId}:${readingTitle ?? "(untitled reading)"} must have a URL.`);
      continue;
    }
    allReadingUrls.push(urlValue);
    try {
      const url = new URL(urlValue);
      check(
        url.protocol === "https:" &&
          Boolean(url.hostname) &&
          url.username === "" &&
          url.password === "" &&
          !["localhost", "127.0.0.1", "::1"].includes(url.hostname),
        `${facilityId}:${readingTitle ?? "(untitled reading)"} must use a public HTTPS URL without credentials.`,
      );
    } catch {
      errors.push(`${facilityId}:${readingTitle ?? "(untitled reading)"} has an invalid URL.`);
    }
  }

  const equationReadingId = stringProperty(definition, "equationReadingId");
  check(
    Boolean(equationReadingId),
    `${facilityId} must declare an equationReadingId.`,
  );
  if (equationReadingId) {
    check(
      readingIdSet.has(equationReadingId),
      `${facilityId} equation maps to unknown reading ID ${equationReadingId}.`,
    );
  }

  const frameName = FRAME_FUNCTIONS[facilityId];
  try {
    const { parameters, body } = functionParts(scienceSource, frameName);
    const parameterNames = parameters
      .slice(1, -1)
      .split(",")
      .map((parameter) => parameter.trim().match(/^([A-Za-z_$][\w$]*)/u)?.[1])
      .filter(Boolean);
    check(
      parameterNames.join(",") === "controls,withheld,tick",
      `${frameName}() may accept only controls, withheld, and tick.`,
    );

    const executableBody = stripStringsAndComments(body);
    const forbiddenCoreInput =
      /\b(?:context|contextSnapshot|environmentalSnapshot|sessionToken|progression|progressionState|positionState|reviewScore|qualityBand|adaptationBand|difficulty)\b/iu;
    const forbiddenCoreEffect =
      /\b(?:fetch|loadEnvironmentalContext|submitCommand|dispatchCommand|promoteFinding|sealPosition)\s*\(/u;
    check(
      !forbiddenCoreInput.test(executableBody),
      `${frameName}() must not read current context or progression inputs.`,
    );
    check(
      !forbiddenCoreEffect.test(executableBody),
      `${frameName}() must remain a local calculation without context fetches or progression effects.`,
    );

    let metrics = [];
    try {
      metrics = topLevelObjects(
        segmentAfter(body, "metrics:", "[", "]", `${frameName} metrics`),
      );
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
    check(metrics.length > 0, `${frameName}() must return at least one metric.`);
    for (const metric of metrics) {
      const metricLabel =
        stringProperty(metric, "label") ?? "(missing metric label)";
      const readingId = stringProperty(metric, "readingId");
      check(
        Boolean(readingId),
        `${frameName} metric ${metricLabel} must declare a readingId.`,
      );
      if (readingId) {
        check(
          readingIdSet.has(readingId),
          `${frameName} metric ${metricLabel} maps to unknown reading ID ${readingId}.`,
        );
      }
    }

    const mapIndex = executableBody.search(/\bmapLayers\s*:/u);
    check(mapIndex >= 0, `${frameName}() must return mapLayers.`);
    const returnedMapSource =
      mapIndex >= 0 ? executableBody.slice(mapIndex) : "";
    const returnedMapVariables =
      mapIndex < 0
        ? []
        : [
            ...returnedMapSource.matchAll(
              /\bmapLayers\s*:\s*\[\s*([A-Za-z_$][\w$]*)/gu,
            ),
          ].map((match) => match[1]);
    const returnsDeclaredConcreteLayer = returnedMapVariables.some(
      (variableName) => {
        const escaped = variableName.replaceAll(
          /[.*+?^${}()|[\]\\]/gu,
          "\\$&",
        );
        return new RegExp(
          `\\bconst\\s+${escaped}\\s*(?::[^=;]+)?=\\s*\\{[\\s\\S]*?\\blayerId\\s*:`,
          "u",
        ).test(executableBody);
      },
    );
    check(
      mapIndex >= 0 &&
        (/\b(?:layerId|facilityHeatLayer)\b/u.test(returnedMapSource) ||
          returnsDeclaredConcreteLayer),
      `${frameName}() must return at least one concrete or generated map layer in its normal analysis path.`,
    );
    check(
      new RegExp(
        `case\\s+"${facilityId}"\\s*:\\s*return\\s+${frameName}\\s*\\(`,
        "u",
      ).test(scienceSource),
      `analyzeFacilityScience() must dispatch ${facilityId} to ${frameName}().`,
    );
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }
}

check(unique(facilityCodes), "Facility codes must be unique.");
check(unique(facilityTitles), "Facility titles must be unique.");
check(unique(qualifiedIds), "Qualified parameter and tool IDs must be unique.");
check(unique(allReadingIds), "Reading IDs must be globally unique.");
check(unique(allReadingUrls), "Reading URLs must be unique across all facilities.");

const staticMapIds = [
  ...scienceSource.matchAll(/\blayerId\s*:\s*"([^"]+)"/gu),
].map((match) => match[1]);
check(unique(staticMapIds), "Static workstation map-layer IDs must be unique.");

check(
  /export function publishAnalysisMapLayers\s*\(/u.test(busSource),
  "The analysis layer bus must export publishAnalysisMapLayers().",
);
check(
  /publishAnalysisMapLayers\s*\(\s*facilityId\s*,\s*frame\.mapLayers\s*\)/u.test(
    labSource,
  ),
  "FacilityScienceLab must publish the current frame's map layers.",
);
check(
  /readings\.find\s*\(\s*\(candidate\)\s*=>\s*candidate\.id\s*===\s*readingId\s*\)/u.test(
    labSource,
  ),
  "FacilityScienceLab must resolve readings by exact stable ID.",
);
check(
  !/definition\.readings\s*\[/u.test(labSource) &&
    !/definition\.readings\.length/u.test(labSource),
  "FacilityScienceLab must not select readings by array index or modulo fallback.",
);
check(
  /concept\.readingId/u.test(labSource) &&
    /control\.readingId/u.test(labSource) &&
    /metric\.readingId/u.test(labSource) &&
    /definition\.equationReadingId/u.test(labSource),
  "FacilityScienceLab must use explicit reading mappings for concepts, controls, metrics, and equations.",
);
check(
  /<ViewportInfoPopover/u.test(labSource),
  "FacilityScienceLab must retain the shared viewport-safe information controls.",
);
check(
  /createPortal\s*\(/u.test(infoPopoverSource) &&
    /document\.body/u.test(infoPopoverSource) &&
    /maximumRight\s*-\s*width/u.test(infoPopoverSource),
  "Information panels must remain portaled and horizontally clamped to the Activity viewport.",
);
check(
  /triggerText="Info"/u.test(metricCardSource) &&
    /triggerVariant="tab"/u.test(metricCardSource) &&
    /definition:\s*string/u.test(metricCardSource),
  "Overview value cards must retain persistent, descriptive Info tabs.",
);
check(
  (appSource.match(/<MetricCard\b/gu) ?? []).length === 4 &&
    (appSource.match(/\bdefinition=/gu) ?? []).length >= 4,
  "Every overview value card must supply an information definition.",
);
check(
  /subscribeAnalysisMapLayers\s*\(\s*setAnalysisMapLayers\s*\)/u.test(appSource),
  "App must subscribe to workstation analysis map layers.",
);
check(
  /anomalyLayers=\{analysisMapLayers\}/u.test(appSource),
  "App must pass workstation analysis layers to the geographic view.",
);
check(
  mapSource.includes("const visibleAnalysisLayers = useMemo") &&
    mapSource.includes("trajectoryCollection(visibleAnalysisLayers)") &&
    mapSource.includes("heatCollection(visibleAnalysisLayers)"),
  "GeographicFieldMap must render trajectory and heatmap publications through the display filter.",
);
check(
  /cooperativeGestures:\s*true/u.test(mapSource),
  "GeographicFieldMap must preserve page gestures even when an embedded WebView misreports pointer type.",
);
check(
  /\.waveform-svg\s*\{[^}]*touch-action:\s*pan-y pinch-zoom;/u.test(
    stylesSource,
  ) &&
    /\.spectrogram-shell\s*\{[^}]*touch-action:\s*pan-y pinch-zoom;/u.test(
      stylesSource,
    ),
  "Interactive science plots must preserve vertical page scrolling and pinch zoom regardless of pointer media-query reporting.",
);

try {
  const htmlRule = topLevelCssRule(stylesSource, "html");
  const bodyRule = topLevelCssRule(stylesSource, "body");
  const rootRule = topLevelCssRule(stylesSource, "#root");
  check(
    !/\boverflow-x\s*:\s*hidden\b/iu.test(htmlRule),
    "The viewport HTML rule must not create a horizontal-only scroll container; clip wide content at #root.",
  );
  check(
    !/\boverflow-x\s*:\s*hidden\b/iu.test(bodyRule),
    "The body rule must not become a non-scrolling mobile touch container through overflow-x: hidden.",
  );
  check(
    !/\boverscroll-behavior-y\s*:\s*contain\b/iu.test(bodyRule),
    "The body rule must not terminate touch scrolling before the documentElement viewport.",
  );
  check(
    /\boverflow-x\s*:\s*clip\b/iu.test(rootRule),
    "#root must clip wide plots without becoming a nested scrolling container.",
  );
} catch (error) {
  errors.push(error instanceof Error ? error.message : String(error));
}

if (errors.length > 0) {
  console.error(`Facility science validation failed (${errors.length} issue${errors.length === 1 ? "" : "s"}):`);
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log(
    `Facility science validation passed: ${FACILITIES.length} facilities, ` +
      `${qualifiedIds.length} controls/tools, ${allReadingUrls.length} open HTTPS readings, ` +
      `${staticMapIds.length + FACILITIES.length} static/generated map-layer identities.`,
  );
}
