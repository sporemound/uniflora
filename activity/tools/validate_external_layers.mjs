import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { transformWithOxc } from "vite";

const ROOT = process.cwd();
const snapshot = JSON.parse(
  await readFile(path.join(ROOT, "public", "science", "uap-public-reports.json"), "utf8"),
);
const registry = await readFile(
  path.join(ROOT, "src", "shared", "external-map-layers.ts"),
  "utf8",
);
const dynamicalRegistry = await readFile(
  path.join(ROOT, "src", "shared", "dynamical-data.ts"),
  "utf8",
);
const dynamicalRenderContract = await readFile(
  path.join(ROOT, "src", "shared", "dynamical-map-render.ts"),
  "utf8",
);
const geographicMap = await readFile(
  path.join(ROOT, "src", "components", "GeographicFieldMap.tsx"),
  "utf8",
);
const headers = await readFile(path.join(ROOT, "public", "_headers"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(snapshot.schemaVersion === "1.0.0", "unexpected public-report schema");
assert(snapshot.source?.license === "CC BY 4.0", "public-report license missing");
assert(Array.isArray(snapshot.reports), "public reports must be an array");
assert(snapshot.reports.length <= 6_000, "public-report display budget exceeded");

const ids = new Set();
let previousTime = Number.NEGATIVE_INFINITY;
for (const report of snapshot.reports) {
  assert(typeof report.reportId === "string" && report.reportId.length <= 256, "bad report id");
  assert(!ids.has(report.reportId), `duplicate report id: ${report.reportId}`);
  ids.add(report.reportId);
  assert(
    Number.isFinite(report.latitude) &&
      report.latitude >= snapshot.selection.bounds.south &&
      report.latitude <= snapshot.selection.bounds.north,
    `latitude outside published bounds: ${report.reportId}`,
  );
  assert(
    Number.isFinite(report.longitude) &&
      report.longitude >= snapshot.selection.bounds.west &&
      report.longitude <= snapshot.selection.bounds.east,
    `longitude outside published bounds: ${report.reportId}`,
  );
  const observed = Date.parse(report.observedAt);
  assert(Number.isFinite(observed), `bad observation time: ${report.reportId}`);
  assert(observed >= previousTime, "public reports are not chronologically sorted");
  previousTime = observed;
  assert(!("summary" in report) && !("media" in report), "narrative or media leaked into snapshot");
  if (report.sourceUrl !== null) {
    const sourceUrl = new URL(report.sourceUrl);
    assert(
      sourceUrl.protocol === "https:" &&
        (sourceUrl.hostname === "catalog.archives.gov" ||
          sourceUrl.hostname === "www.archives.gov"),
      `unsafe source URL: ${report.reportId}`,
    );
  }
}

for (const layerId of [
  "nasa-true-color",
  "noaa-radar",
  "nws-alerts",
  "uap-public-reports",
]) {
  assert(registry.includes(`id: "${layerId}"`), `closed registry missing ${layerId}`);
}
for (const layerId of [
  "dynamical-asos",
  "dynamical-gfs-analysis",
  "dynamical-hrrr-analysis",
  "dynamical-mrms-analysis",
  "dynamical-imerg-late",
]) {
  assert(
    dynamicalRegistry.includes(`id: "${layerId}"`),
    `Dynamical registry missing ${layerId}`,
  );
}
assert(
  registry.includes("...DYNAMICAL_DATASETS.map"),
  "external layer registry does not include Dynamical datasets",
);
assert(
  dynamicalRegistry.includes('license: "Not stated on experimental catalog page"'),
  "experimental ASOS license must remain explicitly unstated",
);
assert(
  (dynamicalRegistry.match(/^    license: "CC BY 4\.0",$/gm) ?? []).length === 4,
  "expected four CC BY 4.0 Dynamical datasets",
);
assert(!registry.includes("nuforc.org/"), "NUFORC must not be an ingest endpoint");

const dynamicalJavaScript = (
  await transformWithOxc(
    dynamicalRegistry,
    path.join(ROOT, "src", "shared", "dynamical-data.ts"),
  )
).code;
const { dynamicalReportContextCollection } = await import(
  `data:text/javascript;base64,${Buffer.from(dynamicalJavaScript).toString("base64")}`
);
const dynamicalRenderJavaScript = (
  await transformWithOxc(
    dynamicalRenderContract,
    path.join(ROOT, "src", "shared", "dynamical-map-render.ts"),
  )
).code;
const { dynamicalRenderManifestUrl, parseDynamicalRenderManifest } = await import(
  `data:text/javascript;base64,${Buffer.from(dynamicalRenderJavaScript).toString("base64")}`
);
const contextReports = [
  {
    reportId: "ufosint:1",
    observedAt: "2026-07-01T00:00:00Z",
    latitude: 40,
    longitude: -100,
    title: "CONUS recent",
    locationName: "Test",
  },
  {
    reportId: "archive:1",
    observedAt: "1950-07-01T00:00:00Z",
    latitude: 40,
    longitude: -100,
    title: "CONUS historical",
    locationName: "Test",
  },
  {
    reportId: "ufosint:2",
    observedAt: "2026-07-01T00:00:00Z",
    latitude: 48,
    longitude: 2,
    title: "Global recent",
    locationName: "Test",
  },
];
const context = dynamicalReportContextCollection(contextReports);
assert(context.features.length === 3, "Dynamical report context dropped valid reports");
assert(
  context.features[0].properties.datasetCount === 5,
  "recent CONUS reports must expose five query-compatible datasets",
);
assert(
  context.features[1].properties.datasetIds === "dynamical-asos",
  "pre-1998 reports must expose only ASOS context",
);
assert(
  context.features[2].properties.datasetCount === 3,
  "recent non-CONUS reports must expose the three global datasets",
);
for (const marker of [
  "DYNAMICAL_CONTEXT_SOURCE",
  "DYNAMICAL_CONTEXT_LAYER",
  "dynamicalReportContextCollection(filteredPublicReports)",
  "reportDataNeeded = reportsVisible || dynamicalContextVisible",
  'visible: dataset.id === "dynamical-gfs-analysis"',
  "dynamicalRenderManifestUrl({",
  "parseDynamicalRenderManifest(",
  "addDynamicalRender(",
  'map.on("moveend", scheduleViewportRender)',
  "HoloViews raster is visible on the basemap.",
]) {
  assert(geographicMap.includes(marker), `map is missing visible Dynamical context: ${marker}`);
}

const renderUrl = dynamicalRenderManifestUrl({
  datasetId: "dynamical-gfs-analysis",
  bbox: [-123.123456, 34.5, -117.2, 39.4],
  width: 5_000,
  height: 40,
  time: "2026-07-01T00:00:00Z",
});
assert(
  renderUrl.startsWith("/api/map/dynamical/manifest?"),
  "Dynamical render request must remain same-origin",
);
const renderParameters = new URL(renderUrl, "https://activity.example").searchParams;
assert(renderParameters.get("width") === "1280", "render width was not capped");
assert(renderParameters.get("height") === "192", "render height was not bounded");
const parsedRender = parseDynamicalRenderManifest({
  datasetId: "dynamical-gfs-analysis",
  kind: "image",
  url: "/api/map/dynamical/image/test.png",
  coordinates: [[-123, 40], [-117, 40], [-117, 34], [-123, 34]],
  generatedAt: "2026-07-01T01:00:00Z",
  validTime: "2026-07-01T00:00:00Z",
  variable: "total_cloud_cover",
  units: "%",
  attribution: "NOAA GFS via Dynamical",
  status: "ready",
}, "dynamical-gfs-analysis", "https://activity.example");
assert(parsedRender.kind === "image", "valid image render was rejected");
assert(
  parsedRender.url === "https://activity.example/api/map/dynamical/image/test.png",
  "same-origin render image URL was not resolved",
);
let rejectedUnsafeRender = false;
try {
  parseDynamicalRenderManifest({
    ...parsedRender,
    url: "javascript:alert(1)",
  }, "dynamical-gfs-analysis", "https://activity.example");
} catch {
  rejectedUnsafeRender = true;
}
assert(rejectedUnsafeRender, "unsafe render image URL was accepted");
let rejectedCrossOriginRender = false;
try {
  parseDynamicalRenderManifest({
    ...parsedRender,
    url: "https://untrusted.example/render.png",
  }, "dynamical-gfs-analysis", "https://activity.example");
} catch {
  rejectedCrossOriginRender = true;
}
assert(rejectedCrossOriginRender, "cross-origin render image URL was accepted");

for (const host of [
  "gibs.earthdata.nasa.gov",
  "mapservices.weather.noaa.gov",
  "api.weather.gov",
]) {
  assert(headers.includes(`https://${host}`), `CSP missing ${host}`);
}

console.log(JSON.stringify({
  ok: true,
  validator: "external-map-layers",
  registeredLayers: 9,
  dynamicalContextCases: context.features.length,
  dynamicalRenderContractCases: 5,
  publicReports: snapshot.reports.length,
  timeExtent: snapshot.timeExtent,
  narrativeFieldsPublished: false,
  mediaFieldsPublished: false,
}, null, 2));
